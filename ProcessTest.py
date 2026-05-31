#!/usr/bin/env python3
"""
ProcessTest.py
RM3100 Magnetometer -- Noise Floor Processing Tool
--------------------------------------------------

This script processes RM3100 magnetometer log files that were already recorded
on a Raspberry Pi, typically using Dave Witten's rm3100-runMag software:

    https://github.com/wittend/rm3100-runMag

This script DOES NOT talk to the RM3100 directly.
It only processes existing log files copied from the Raspberry Pi.

Main use:
  1. Put the RM3100 at a test location.
  2. Record data on the Raspberry Pi.
  3. Copy the raw .log file(s) to this computer.
  4. Run this script.
  5. Compare the generated noise floor plots/results.
  6. Move the RM3100 to another location and repeat.

Output folder behavior:
  By default, this script saves all output inside the same folder that
  ProcessTest.py is stored in. This makes the script portable for GitHub.

  Example:
      RM3100-Noise-Floor-Tool/
          ProcessTest.py
          Backyard/
              All/
                  Test_1_full.log
              Test_1/
                  2026-05-28_22-00-00.log
                  2026-05-28_22-05-00.log
                  ...
              Test_1 Figures/
                  X_Test_1.png
                  X_Test_1_noisefloor.png
                  Y_Test_1.png
                  Y_Test_1_noisefloor.png
                  Z_Test_1.png
                  Z_Test_1_noisefloor.png
                  TOTAL_Test_1.png
                  TOTAL_Test_1_noisefloor.png
              Test_1_noise_summary.csv

Required Python packages:
  numpy
  matplotlib
  scipy

tkinter is also used for the file-selection window. It is included with most
Windows Python installs. On Linux/Raspberry Pi OS, it may need to be installed
with:

    sudo apt install python3-tk
"""

import csv
import re
import shutil
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib

# Use the non-interactive matplotlib backend.
# This lets the script save PNG files without opening plot windows.
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch


# ─────────────────────────────────────────────────────────────────────────────
# User-facing configuration
# ─────────────────────────────────────────────────────────────────────────────

# ROOT is the base output folder.
#
# This is intentionally set to the folder where ProcessTest.py is located.
# That means if a user downloads this GitHub repository and runs the script,
# all generated site folders will be created inside the repository folder.
#
# Example:
#   If ProcessTest.py is located in:
#       C:/Users/Name/Desktop/RM3100-Noise-Floor-Tool/
#
#   and the user enters the site folder:
#       Backyard
#
#   then output will be saved to:
#       C:/Users/Name/Desktop/RM3100-Noise-Floor-Tool/Backyard/
#
# Users may also browse to an outside folder if they want output saved elsewhere.
ROOT = Path(__file__).resolve().parent

# Human-readable timestamp format used by some rm3100-runMag logs.
# Example timestamp:
#   28 May 2026 22:00:00
#
# The script also accepts epoch timestamps if the file already uses them.
TS_FMT_HUMAN = "%d %b %Y %H:%M:%S"

# Expected header from rm3100-runMag style files.
# Header lines are skipped during sorting/chopping and then written back
# to the merged and segmented output files.
EXPECTED_HEADER = '"time", "rtemp", "ltemp", "x", "y", "z", "rx", "ry", "rz", "total"'

# Frequency band used to estimate the broadband noise floor.
#
# The RM3100 logs are assumed to be sampled at about 1 Hz, so the Nyquist
# frequency is about 0.5 Hz. This band avoids the very low-frequency drift
# region and avoids getting too close to the Nyquist edge.
FLAT_LO = 0.10
FLAT_HI = 0.40

# Quick reference target used for PASS/FAIL messages.
#
# HamSCI PSWS documentation gives a practical RM3100 target level on the order
# of 10 nT for real deployments. This script compares the calculated broadband
# ASD noise floor to 10 nT/rtHz as a simple field-screening reference.
#
# This is mainly useful for quick comparison between test locations.
PSWS_TARGET_NT = 10.0


# ─────────────────────────────────────────────────────────────────────────────
# Timestamp helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_epoch(ts):
    """
    Convert a timestamp string to epoch seconds.

    Accepts either:
      1. Human-readable UTC time, such as:
             28 May 2026 22:00:00

      2. Existing epoch time, such as:
             1780005600.0

    The output is always a float epoch timestamp.
    """
    ts = ts.strip().strip('"')

    try:
        return datetime.strptime(ts, TS_FMT_HUMAN).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return float(ts)


def _line_to_epoch(line):
    """
    Convert the timestamp field of one raw log line to epoch time if possible.

    rm3100-runMag files may have a quoted timestamp in the first column.
    This function keeps the rest of the line unchanged and only replaces
    the timestamp field.

    Header lines and invalid lines are returned unchanged.
    """
    s = line.rstrip("\n")

    if not s or s.strip() == EXPECTED_HEADER:
        return s + "\n"

    # Match a quoted first field:
    #   "28 May 2026 22:00:00", ...
    m = re.match(r'^"([^"]+)"\s*,\s*(.*)$', s)

    if m:
        try:
            return str(_to_epoch(m.group(1))) + ", " + m.group(2) + "\n"
        except ValueError:
            pass

    return line


# ─────────────────────────────────────────────────────────────────────────────
# File merging and chopping
# ─────────────────────────────────────────────────────────────────────────────

def chop_files(raw_paths, out_dir, segment_minutes, full_archive_path=None):
    """
    Merge raw RM3100 logs, sort them by time, save a full archive, and split
    them into fixed-length segment files.

    Args:
        raw_paths:
            List of Path objects pointing to the raw .log files copied from
            the Raspberry Pi.

        out_dir:
            Folder where chopped segment files will be saved.
            Usually:
                ROOT / site_name / test_label

        segment_minutes:
            Length of each segment in minutes.
            For this site-testing method, 5 minutes is recommended.

        full_archive_path:
            Optional path where the full merged un-chopped file is saved.
            Usually:
                ROOT / site_name / "All" / "test_label_full.log"

    Returns:
        Number of segment files written.

    Output example:
        Backyard/
            All/
                Test_1_full.log
            Test_1/
                2026-05-28_22-00-00.log
                2026-05-28_22-05-00.log
                ...
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    seg_seconds = segment_minutes * 60
    header_line = EXPECTED_HEADER + "\n"
    rows = []

    # Read every selected file, convert timestamps, and collect valid rows.
    for path in sorted(raw_paths):
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                converted = _line_to_epoch(line)
                stripped = converted.strip()

                if not stripped:
                    continue

                if stripped == EXPECTED_HEADER:
                    header_line = converted
                    continue

                try:
                    epoch = float(stripped.split(",", 1)[0].strip())
                    rows.append((epoch, converted))
                except ValueError:
                    # Skip lines that are not valid data rows.
                    continue

    if not rows:
        raise ValueError("No valid data rows found in the selected file(s).")

    # Sort all selected files together chronologically.
    # This makes it safe to select multiple raw logs from the same test.
    rows.sort(key=lambda r: r[0])

    # Save the full merged archive before chopping.
    # This gives the user one clean master file for the test.
    if full_archive_path is not None:
        full_archive_path.parent.mkdir(parents=True, exist_ok=True)

        with full_archive_path.open("w", encoding="utf-8") as fa:
            fa.write(header_line)

            for _, line in rows:
                fa.write(line)

    # Split the merged data into fixed-length time chunks.
    seg_start = rows[0][0]
    current_fp = None
    seg_count = 0

    def open_seg(ts):
        """
        Open a new segment file named by its UTC start time.
        """
        nonlocal current_fp, seg_count

        if current_fp:
            current_fp.close()

        fname = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d_%H-%M-%S") + ".log"
        current_fp = (out_dir / fname).open("w", encoding="utf-8")
        current_fp.write(header_line)
        seg_count += 1

    open_seg(seg_start)

    for epoch, line in rows:
        if epoch - seg_start >= seg_seconds:
            seg_start = epoch
            open_seg(epoch)

        current_fp.write(line)

    if current_fp:
        current_fp.close()

    return seg_count


# ─────────────────────────────────────────────────────────────────────────────
# Segment loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_segment(path):
    """
    Load one chopped segment file and return the magnetic field channels.

    The script expects each line to have at least 10 columns:

        time, rtemp, ltemp, x, y, z, rx, ry, rz, total

    Returns:
        fs, x, y, z, total

    Notes:
        fs is fixed at 1.0 Hz because the RM3100 site-testing workflow is
        built around nominal 1 Hz data.

        Computing the sample rate from timestamps can cause problems if one
        segment has a small timing gap, because then the frequency grid can
        become inconsistent between segments.

        The x1000 scaling is kept from the earlier plotting workflow so that
        the plotted values are in the expected nT scale.
    """
    x, y, z, total = [], [], [], []

    with path.open("r", encoding="utf-8", errors="replace") as f:
        first = f.readline()

        if not first.strip().lower().startswith('"time"'):
            f.seek(0)

        for line in f:
            parts = line.strip().split(",")

            if len(parts) < 10:
                continue

            try:
                x.append(float(parts[3]))
                y.append(float(parts[4]))
                z.append(float(parts[5]))
                total.append(float(parts[9]))
            except ValueError:
                continue

    if len(x) < 2:
        raise ValueError("Not enough data in " + path.name)

    fs = 1.0

    def prep(sig):
        # Remove the DC offset from the segment.
        # The Earth field is large; for PSD/noise floor comparison we only
        # care about variation around the mean.
        return (np.array(sig) - np.mean(sig)) * 1e3

    return fs, prep(x), prep(y), prep(z), prep(total)


# ─────────────────────────────────────────────────────────────────────────────
# PSD analysis and plotting
# ─────────────────────────────────────────────────────────────────────────────

def run_psd_and_save(seg_dir, fig_dir, label, summary_path, status_cb):
    """
    Run PSD/noise-floor analysis on all segment files in one test folder.

    Inputs:
        seg_dir:
            Folder containing chopped .log segment files.
            Usually:
                ROOT / site_name / test_label

        fig_dir:
            Folder where PNG plots will be saved.
            Usually:
                ROOT / site_name / "test_label Figures"

        label:
            Test label used in plot filenames.

        summary_path:
            CSV path where final noise-floor values will be saved.
            Usually:
                ROOT / site_name / "test_label_noise_summary.csv"

        status_cb:
            Function used to print/update status messages in the GUI.

    Output files:
        X_label.png
        Y_label.png
        Z_label.png
        TOTAL_label.png

        X_label_noisefloor.png
        Y_label_noisefloor.png
        Z_label_noisefloor.png
        TOTAL_label_noisefloor.png

        label_noise_summary.csv
    """
    fig_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(seg_dir.glob("*.log"))

    if not files:
        raise ValueError("No .log files found in " + str(seg_dir))

    channels = ("X", "Y", "Z", "TOTAL")
    seg_curves = {ch: [] for ch in channels}

    status_cb("Computing PSD on " + str(len(files)) + " segments...")

    # Compute an ASD curve for every segment and every channel.
    for seg_path in files:
        try:
            fs, x, y, z, total = _load_segment(seg_path)
        except ValueError:
            # Skip empty or invalid segment files.
            continue

        channel_data = {
            "X": x,
            "Y": y,
            "Z": z,
            "TOTAL": total,
        }

        for ch, sig in channel_data.items():
            if len(sig) < 2:
                continue

            # Use a power-of-two window size no larger than the segment length.
            nperseg = min(1024, 2 ** int(np.floor(np.log2(len(sig)))))

            freqs, psd = welch(sig, fs=fs, nperseg=nperseg, window="hann")

            # ASD is the square root of PSD.
            # PSD units are nT^2/Hz, so ASD units are nT/sqrt(Hz).
            asd = np.sqrt(psd)

            seg_curves[ch].append((freqs, asd))

    # Save PSD overlay plots.
    # These show all segments together so the user can see whether one segment
    # had unusually high noise compared with the rest.
    for ch in channels:
        segs = seg_curves[ch]

        if not segs:
            continue

        fig, ax = plt.subplots(figsize=(10, 5))

        for freqs, asd in segs:
            ax.semilogy(freqs, asd, lw=0.6, alpha=0.65, color="#1f77b4")

        ax.set_xlim(0, 0.5)
        ax.set_ylim(1e0, 1e3)
        ax.set_xlabel("Frequency (Hz)", fontsize=11)
        ax.set_ylabel("ASD (nT/rtHz)", fontsize=11)
        ax.set_title(ch + " PSD Overlay -- " + label, fontsize=12)
        ax.grid(True, which="both", linestyle="--", alpha=0.4)

        fig.tight_layout()

        out_path = fig_dir / (ch + "_" + label + ".png")
        fig.savefig(out_path, dpi=150)
        plt.close(fig)

        status_cb("Saved " + out_path.name)

    sep = "=" * 60
    print("")
    print(sep)
    print("  NOISE FLOOR RESULTS -- " + label)
    print("  Flat band: " + str(FLAT_LO) + " - " + str(FLAT_HI) + " Hz")
    print("  PSWS target/reference: " + str(PSWS_TARGET_NT) + " nT/rtHz")
    print(sep)

    summary_rows = []

    # Save noise-floor plots and CSV results.
    for ch in channels:
        segs = seg_curves[ch]

        if not segs:
            continue

        # Interpolate all segment curves onto the same frequency grid.
        common_freqs = segs[0][0]
        asd_matrix = np.zeros((len(segs), len(common_freqs)))

        for i, (freqs, asd) in enumerate(segs):
            asd_matrix[i, :] = np.interp(common_freqs, freqs, asd)

        # Median and percentile curves across all segments.
        median_curve = np.median(asd_matrix, axis=0)
        p10_curve = np.percentile(asd_matrix, 10, axis=0)
        p90_curve = np.percentile(asd_matrix, 90, axis=0)

        # The final broadband noise floor is one number per channel:
        # median of the median ASD curve from FLAT_LO to FLAT_HI.
        flat_mask = (common_freqs >= FLAT_LO) & (common_freqs <= FLAT_HI)
        noise_floor = float(np.median(median_curve[flat_mask])) if flat_mask.any() else float("nan")

        if noise_floor <= PSWS_TARGET_NT:
            status = "PASS"
            quality = "PASS (below " + str(PSWS_TARGET_NT) + " nT/rtHz target)"
        else:
            status = "FAIL"
            ratio = noise_floor / PSWS_TARGET_NT
            quality = "FAIL (" + "{:.1f}".format(ratio) + "x above target)"

        print(
            "  "
            + ch.ljust(6)
            + "  floor = "
            + "{:.3f}".format(noise_floor)
            + " nT/rtHz"
            + "  ["
            + quality
            + "]"
        )

        summary_rows.append({
            "channel": ch,
            "noise_floor_nT_per_rtHz": "{:.6f}".format(noise_floor),
            "flat_band_low_Hz": FLAT_LO,
            "flat_band_high_Hz": FLAT_HI,
            "target_nT_per_rtHz": PSWS_TARGET_NT,
            "status": status,
            "segments_used": len(files),
        })

        # Plot the useful frequency range for quick visual comparison.
        plot_mask = (common_freqs >= FLAT_LO) & (common_freqs <= 0.5)
        pf = common_freqs[plot_mask]
        pm = median_curve[plot_mask]
        pp10 = p10_curve[plot_mask]
        pp90 = p90_curve[plot_mask]

        fig, ax = plt.subplots(figsize=(10, 5))

        ax.fill_between(
            pf,
            pp10,
            pp90,
            alpha=0.25,
            color="#1f77b4",
            label="10th-90th percentile",
        )

        ax.semilogy(
            pf,
            pm,
            lw=1.8,
            color="#1f77b4",
            label="Median ASD",
        )

        ax.axhline(
            noise_floor,
            color="green",
            lw=1.5,
            linestyle="--",
            label="Noise floor: " + "{:.3f}".format(noise_floor) + " nT/rtHz",
        )

        ax.axhline(
            PSWS_TARGET_NT,
            color="red",
            lw=1.2,
            linestyle=":",
            label="Target: " + str(PSWS_TARGET_NT) + " nT/rtHz",
        )

        ax.set_xlim(FLAT_LO, 0.5)
        ax.set_ylim(1e0, 1e3)
        ax.set_xlabel("Frequency (Hz)", fontsize=11)
        ax.set_ylabel("ASD (nT/rtHz)", fontsize=11)
        ax.set_title(
            ch
            + " Noise Floor -- "
            + label
            + "  ["
            + "{:.3f}".format(noise_floor)
            + " nT/rtHz]",
            fontsize=12,
        )
        ax.legend(fontsize=9, loc="upper right")
        ax.grid(True, which="both", linestyle="--", alpha=0.4)

        fig.tight_layout()

        out_path = fig_dir / (ch + "_" + label + "_noisefloor.png")
        fig.savefig(out_path, dpi=150)
        plt.close(fig)

        status_cb("Saved " + out_path.name)

    # Save final numeric results to CSV.
    # This makes it easier to compare tests without copying console output.
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "channel",
            "noise_floor_nT_per_rtHz",
            "flat_band_low_Hz",
            "flat_band_high_Hz",
            "target_nT_per_rtHz",
            "status",
            "segments_used",
        ]

        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    status_cb("Saved " + summary_path.name)

    print("  Segments used: " + str(len(files)))
    print("  Summary CSV: " + str(summary_path))
    print(sep)
    print("")


# ─────────────────────────────────────────────────────────────────────────────
# Graphical user interface
# ─────────────────────────────────────────────────────────────────────────────

class ProcessTestUI(tk.Tk):
    """
    Small tkinter window for selecting files and starting the processing run.

    The GUI is intentionally simple because this tool is meant for field users
    who just need to pick files, label a test, and generate plots.
    """

    def __init__(self):
        super().__init__()

        self.title("ProcessTest -- RM3100 Noise Floor Calculator")
        self.geometry("660x420")
        self.resizable(False, False)

        self._raw_files = []

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        # Raw input logs copied from the Raspberry Pi.
        f0 = ttk.LabelFrame(self, text="1. Raw log file(s)", padding=6)
        f0.pack(fill=tk.X, **pad)

        self._file_label = ttk.Label(f0, text="No files selected", foreground="gray")
        self._file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(f0, text="Browse...", command=self._pick_files).pack(side=tk.RIGHT)

        # Site folder.
        #
        # If the user types "Backyard", output will go to:
        #     ROOT / "Backyard"
        #
        # If the user browses to an absolute folder outside the repo,
        # output will go to that selected folder.
        f1 = ttk.LabelFrame(self, text="2. Site folder  (inside this repository folder)", padding=6)
        f1.pack(fill=tk.X, **pad)

        self._site_var = tk.StringVar()
        ttk.Entry(f1, textvariable=self._site_var, width=30).pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )

        ttk.Button(f1, text="Browse...", command=self._pick_site).pack(side=tk.RIGHT)
        ttk.Label(f1, text="  (type new name to create)", foreground="gray").pack(side=tk.RIGHT)

        # Test label.
        #
        # If the user enters "Test_1", the script creates:
        #     SiteFolder/Test_1/
        #     SiteFolder/Test_1 Figures/
        #     SiteFolder/All/Test_1_full.log
        #     SiteFolder/Test_1_noise_summary.csv
        f2 = ttk.LabelFrame(self, text="3. Test label  (e.g. Test_1, garage_close)", padding=6)
        f2.pack(fill=tk.X, **pad)

        self._label_var = tk.StringVar()
        ttk.Entry(f2, textvariable=self._label_var, width=30).pack(fill=tk.X)

        # Segment length.
        #
        # 5 minutes is recommended for the current site-testing method.
        f3 = ttk.LabelFrame(self, text="4. Segment length (minutes)", padding=6)
        f3.pack(fill=tk.X, **pad)

        self._seg_var = tk.IntVar(value=5)
        ttk.Spinbox(f3, from_=1, to=120, textvariable=self._seg_var, width=8).pack(anchor=tk.W)

        ttk.Button(self, text="Run", command=self._start).pack(pady=12)

        self._status = ttk.Label(self, text="Ready.", anchor=tk.W, foreground="gray")
        self._status.pack(fill=tk.X, padx=10, pady=(0, 8))

    def _pick_files(self):
        """
        Let the user select one or more raw RM3100 .log files.
        """
        paths = filedialog.askopenfilenames(
            title="Select raw log file(s)",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")],
        )

        if paths:
            self._raw_files = [Path(p) for p in paths]
            self._file_label.config(
                text=", ".join(p.name for p in self._raw_files),
                foreground="black",
            )

    def _pick_site(self):
        """
        Let the user browse to an existing output folder.

        If the selected folder is inside ROOT, the GUI stores it as a relative
        path. Otherwise, it stores the full absolute path.
        """
        folder = filedialog.askdirectory(
            title="Select or create site folder",
            initialdir=str(ROOT) if ROOT.exists() else str(Path.home()),
        )

        if folder:
            p = Path(folder)

            try:
                self._site_var.set(str(p.relative_to(ROOT)))
            except ValueError:
                self._site_var.set(str(p))

    def _start(self):
        """
        Validate user input and start processing in a background thread.
        """
        if not self._raw_files:
            messagebox.showwarning("Missing input", "Please select at least one raw log file.")
            return

        if not self._site_var.get().strip():
            messagebox.showwarning("Missing site", "Please enter or select a site folder name.")
            return

        if not self._label_var.get().strip():
            messagebox.showwarning("Missing label", "Please enter a test label.")
            return

        threading.Thread(
            target=self._run,
            args=(self._site_var.get().strip(), self._label_var.get().strip()),
            daemon=True,
        ).start()

    def _set_status(self, msg):
        """
        Update the GUI status line and also print the message to the console.
        """
        self._status.config(text=msg, foreground="black")
        print(msg)

    def _run(self, site, label):
        """
        Main processing sequence.

        Folder outputs for a site called "Backyard" and a label called "Test_1":

            Backyard/
                All/
                    Test_1_full.log

                Test_1/
                    chopped segment files

                Test_1 Figures/
                    generated PNG plots

                Test_1_noise_summary.csv
                    final numeric summary
        """
        try:
            site_path = Path(site) if Path(site).is_absolute() else ROOT / site

            seg_dir = site_path / label
            fig_dir = site_path / (label + " Figures")
            archive_path = site_path / "All" / (label + "_full.log")
            summary_path = site_path / (label + "_noise_summary.csv")

            if seg_dir.exists() and any(seg_dir.iterdir()):
                if not messagebox.askyesno(
                    "Folder exists",
                    seg_dir.name + " already contains files.\n\nOverwrite?",
                ):
                    self._set_status("Cancelled.")
                    return

                shutil.rmtree(seg_dir)

            if fig_dir.exists() and any(fig_dir.iterdir()):
                if messagebox.askyesno(
                    "Figure folder exists",
                    fig_dir.name + " already contains files.\n\nOverwrite figures?",
                ):
                    shutil.rmtree(fig_dir)
                else:
                    self._set_status("Cancelled.")
                    return

            self._set_status("Chopping segments...")

            n_segs = chop_files(
                self._raw_files,
                seg_dir,
                self._seg_var.get(),
                full_archive_path=archive_path,
            )

            self._set_status("Chopped into " + str(n_segs) + " segments. Running PSD...")

            run_psd_and_save(
                seg_dir,
                fig_dir,
                label,
                summary_path,
                self._set_status,
            )

            self._set_status(
                "Done.  "
                + str(n_segs)
                + " segments  |  Figures -> "
                + str(fig_dir)
                + "  |  Archive -> "
                + str(archive_path)
                + "  |  Summary -> "
                + str(summary_path)
            )

        except Exception as e:
            import traceback

            traceback.print_exc()
            messagebox.showerror("Error", str(e))
            self._set_status("Error: " + str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """
    Start the tkinter app.
    """
    app = ProcessTestUI()
    app.mainloop()


if __name__ == "__main__":
    main()
