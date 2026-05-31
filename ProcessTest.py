#!/usr/bin/env python3
"""
ProcessTest.py
RM3100 Magnetometer Noise Floor Calculator

This script processes RM3100 magnetometer log files that were already recorded
on a Raspberry Pi, typically using Dave Witten's rm3100-runMag software:

    https://github.com/wittend/rm3100-runMag

It does not communicate with the RM3100 directly. It only processes existing
.log files after they have been copied from the Raspberry Pi.

Main workflow:
    1. Select one or more raw RM3100 log files.
    2. Choose or create a site folder.
    3. Enter a test label.
    4. Choose a segment length.
    5. Run the processing pipeline.

Outputs are saved inside the repository folder by default:

    SiteName/
        All/
            TestLabel_full.log
        TestLabel/
            chopped segment files
        TestLabel Figures/
            PSD and noise-floor PNG plots
        TestLabel_noise_summary.csv
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

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch


# The default output location is the folder containing this script.
# This keeps the script portable for GitHub users.
ROOT = Path(__file__).resolve().parent

# Human-readable timestamp format used by rm3100-runMag logs.
# Epoch timestamps are also accepted.
TS_FMT_HUMAN = "%d %b %Y %H:%M:%S"

EXPECTED_HEADER = '"time", "rtemp", "ltemp", "x", "y", "z", "rx", "ry", "rz", "total"'

# Frequency band used for the broadband noise-floor estimate.
# For 1 Hz data, Nyquist is 0.5 Hz, so this avoids both low-frequency drift
# and the upper edge of the spectrum.
FLAT_LO = 0.10
FLAT_HI = 0.40

# Quick reference line for the plots and console PASS/FAIL messages.
PSWS_TARGET_NT = 10.0


def _to_epoch(ts: str) -> float:
    """
    Convert a timestamp to epoch seconds.

    Accepted inputs:
        - "28 May 2026 22:00:00"
        - "1780005600.0"
    """
    ts = ts.strip().strip('"')

    try:
        return datetime.strptime(ts, TS_FMT_HUMAN).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return float(ts)


def _line_to_epoch(line: str) -> str:
    """
    Convert the first column of a log line to epoch time when possible.
    Header lines and invalid lines are returned unchanged.
    """
    s = line.rstrip("\n")

    if not s or s.strip() == EXPECTED_HEADER:
        return s + "\n"

    match = re.match(r'^"([^"]+)"\s*,\s*(.*)$', s)

    if match:
        try:
            return str(_to_epoch(match.group(1))) + ", " + match.group(2) + "\n"
        except ValueError:
            pass

    return line


def chop_files(raw_paths, out_dir, segment_minutes, full_archive_path=None):
    """
    Merge selected raw logs, sort them by time, save one full archive,
    and split the data into fixed-length segment files.

    Returns:
        Number of segment files written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    segment_seconds = segment_minutes * 60
    header_line = EXPECTED_HEADER + "\n"
    rows = []

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
                    continue

    if not rows:
        raise ValueError("No valid data rows found in the selected file(s).")

    rows.sort(key=lambda r: r[0])

    # Save one complete merged file before chopping.
    if full_archive_path is not None:
        full_archive_path.parent.mkdir(parents=True, exist_ok=True)

        with full_archive_path.open("w", encoding="utf-8") as archive:
            archive.write(header_line)
            for _, line in rows:
                archive.write(line)

    segment_start = rows[0][0]
    current_fp = None
    segment_count = 0

    def open_segment(ts):
        nonlocal current_fp, segment_count

        if current_fp:
            current_fp.close()

        filename = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d_%H-%M-%S") + ".log"
        current_fp = (out_dir / filename).open("w", encoding="utf-8")
        current_fp.write(header_line)
        segment_count += 1

    open_segment(segment_start)

    for epoch, line in rows:
        if epoch - segment_start >= segment_seconds:
            segment_start = epoch
            open_segment(epoch)

        current_fp.write(line)

    if current_fp:
        current_fp.close()

    return segment_count


def _load_segment(path):
    """
    Load one chopped segment file.

    Expected columns:
        time, rtemp, ltemp, x, y, z, rx, ry, rz, total

    Returns:
        fs, x, y, z, total

    The nominal sample rate is fixed at 1 Hz so all segments use the same
    frequency grid. Each channel is mean-subtracted before PSD analysis.
    """
    x_values, y_values, z_values, total_values = [], [], [], []

    with path.open("r", encoding="utf-8", errors="replace") as f:
        first = f.readline()

        if not first.strip().lower().startswith('"time"'):
            f.seek(0)

        for line in f:
            parts = line.strip().split(",")

            if len(parts) < 10:
                continue

            try:
                x_values.append(float(parts[3]))
                y_values.append(float(parts[4]))
                z_values.append(float(parts[5]))
                total_values.append(float(parts[9]))
            except ValueError:
                continue

    if len(x_values) < 2:
        raise ValueError("Not enough data in " + path.name)

    fs = 1.0

    def prep(signal):
        return (np.array(signal) - np.mean(signal)) * 1e3

    return (
        fs,
        prep(x_values),
        prep(y_values),
        prep(z_values),
        prep(total_values),
    )


def run_psd_and_save(seg_dir, fig_dir, label, summary_path, status_cb):
    """
    Run PSD and noise-floor analysis for one test folder.

    Saves:
        - PSD overlay plots
        - noise-floor plots
        - CSV summary of noise-floor values
    """
    fig_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(seg_dir.glob("*.log"))
    if not files:
        raise ValueError("No .log files found in " + str(seg_dir))

    channels = ("X", "Y", "Z", "TOTAL")
    segment_curves = {channel: [] for channel in channels}

    status_cb("Computing PSD on " + str(len(files)) + " segments...")

    for segment_path in files:
        try:
            fs, x, y, z, total = _load_segment(segment_path)
        except ValueError:
            continue

        channel_data = {
            "X": x,
            "Y": y,
            "Z": z,
            "TOTAL": total,
        }

        for channel, signal in channel_data.items():
            if len(signal) < 2:
                continue

            nperseg = min(1024, 2 ** int(np.floor(np.log2(len(signal)))))
            freqs, psd = welch(signal, fs=fs, nperseg=nperseg, window="hann")
            asd = np.sqrt(psd)

            segment_curves[channel].append((freqs, asd))

    # Plot every segment curve together for each channel.
    for channel in channels:
        curves = segment_curves[channel]

        if not curves:
            continue

        fig, ax = plt.subplots(figsize=(10, 5))

        for freqs, asd in curves:
            ax.semilogy(freqs, asd, lw=0.6, alpha=0.65, color="#1f77b4")

        ax.set_xlim(0, 0.5)
        ax.set_ylim(1e0, 1e3)
        ax.set_xlabel("Frequency (Hz)", fontsize=11)
        ax.set_ylabel("ASD (nT/rtHz)", fontsize=11)
        ax.set_title(channel + " PSD Overlay -- " + label, fontsize=12)
        ax.grid(True, which="both", linestyle="--", alpha=0.4)

        fig.tight_layout()

        output_path = fig_dir / (channel + "_" + label + ".png")
        fig.savefig(output_path, dpi=150)
        plt.close(fig)

        status_cb("Saved " + output_path.name)

    sep = "=" * 60
    print("")
    print(sep)
    print("  NOISE FLOOR RESULTS -- " + label)
    print("  Flat band: " + str(FLAT_LO) + " - " + str(FLAT_HI) + " Hz")
    print("  PSWS target/reference: " + str(PSWS_TARGET_NT) + " nT/rtHz")
    print(sep)

    summary_rows = []

    for channel in channels:
        curves = segment_curves[channel]

        if not curves:
            continue

        common_freqs = curves[0][0]
        asd_matrix = np.zeros((len(curves), len(common_freqs)))

        for i, (freqs, asd) in enumerate(curves):
            asd_matrix[i, :] = np.interp(common_freqs, freqs, asd)

        median_curve = np.median(asd_matrix, axis=0)
        p10_curve = np.percentile(asd_matrix, 10, axis=0)
        p90_curve = np.percentile(asd_matrix, 90, axis=0)

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
            + channel.ljust(6)
            + "  floor = "
            + "{:.3f}".format(noise_floor)
            + " nT/rtHz"
            + "  ["
            + quality
            + "]"
        )

        summary_rows.append({
            "channel": channel,
            "noise_floor_nT_per_rtHz": "{:.6f}".format(noise_floor),
            "flat_band_low_Hz": FLAT_LO,
            "flat_band_high_Hz": FLAT_HI,
            "target_nT_per_rtHz": PSWS_TARGET_NT,
            "status": status,
            "segments_used": len(files),
        })

        plot_mask = (common_freqs >= FLAT_LO) & (common_freqs <= 0.5)
        plot_freqs = common_freqs[plot_mask]
        plot_median = median_curve[plot_mask]
        plot_p10 = p10_curve[plot_mask]
        plot_p90 = p90_curve[plot_mask]

        fig, ax = plt.subplots(figsize=(10, 5))

        ax.fill_between(
            plot_freqs,
            plot_p10,
            plot_p90,
            alpha=0.25,
            color="#1f77b4",
            label="10th-90th percentile",
        )

        ax.semilogy(
            plot_freqs,
            plot_median,
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
            channel
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

        output_path = fig_dir / (channel + "_" + label + "_noisefloor.png")
        fig.savefig(output_path, dpi=150)
        plt.close(fig)

        status_cb("Saved " + output_path.name)

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


class ProcessTestUI(tk.Tk):
    """
    Small file-picker interface for running the pipeline.
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

        raw_frame = ttk.LabelFrame(self, text="1. Raw log file(s)", padding=6)
        raw_frame.pack(fill=tk.X, **pad)

        self._file_label = ttk.Label(raw_frame, text="No files selected", foreground="gray")
        self._file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(raw_frame, text="Browse...", command=self._pick_files).pack(side=tk.RIGHT)

        site_frame = ttk.LabelFrame(
            self,
            text="2. Site folder  (inside this repository folder)",
            padding=6,
        )
        site_frame.pack(fill=tk.X, **pad)

        self._site_var = tk.StringVar()
        ttk.Entry(site_frame, textvariable=self._site_var, width=30).pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )

        ttk.Button(site_frame, text="Browse...", command=self._pick_site).pack(side=tk.RIGHT)
        ttk.Label(site_frame, text="  (type new name to create)", foreground="gray").pack(side=tk.RIGHT)

        label_frame = ttk.LabelFrame(
            self,
            text="3. Test label  (e.g. Test_1, garage_close)",
            padding=6,
        )
        label_frame.pack(fill=tk.X, **pad)

        self._label_var = tk.StringVar()
        ttk.Entry(label_frame, textvariable=self._label_var, width=30).pack(fill=tk.X)

        segment_frame = ttk.LabelFrame(self, text="4. Segment length (minutes)", padding=6)
        segment_frame.pack(fill=tk.X, **pad)

        self._seg_var = tk.IntVar(value=5)
        ttk.Spinbox(segment_frame, from_=1, to=120, textvariable=self._seg_var, width=8).pack(anchor=tk.W)

        ttk.Button(self, text="Run", command=self._start).pack(pady=12)

        self._status = ttk.Label(self, text="Ready.", anchor=tk.W, foreground="gray")
        self._status.pack(fill=tk.X, padx=10, pady=(0, 8))

    def _pick_files(self):
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
        folder = filedialog.askdirectory(
            title="Select or create site folder",
            initialdir=str(ROOT) if ROOT.exists() else str(Path.home()),
        )

        if folder:
            selected = Path(folder)

            try:
                self._site_var.set(str(selected.relative_to(ROOT)))
            except ValueError:
                self._site_var.set(str(selected))

    def _start(self):
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
        self._status.config(text=msg, foreground="black")
        print(msg)

    def _run(self, site, label):
        try:
            site_path = Path(site) if Path(site).is_absolute() else ROOT / site

            segment_dir = site_path / label
            figure_dir = site_path / (label + " Figures")
            archive_path = site_path / "All" / (label + "_full.log")
            summary_path = site_path / (label + "_noise_summary.csv")

            if segment_dir.exists() and any(segment_dir.iterdir()):
                if not messagebox.askyesno(
                    "Folder exists",
                    segment_dir.name + " already contains files.\n\nOverwrite?",
                ):
                    self._set_status("Cancelled.")
                    return

                shutil.rmtree(segment_dir)

            if figure_dir.exists() and any(figure_dir.iterdir()):
                if messagebox.askyesno(
                    "Figure folder exists",
                    figure_dir.name + " already contains files.\n\nOverwrite figures?",
                ):
                    shutil.rmtree(figure_dir)
                else:
                    self._set_status("Cancelled.")
                    return

            self._set_status("Chopping segments...")

            segment_count = chop_files(
                self._raw_files,
                segment_dir,
                self._seg_var.get(),
                full_archive_path=archive_path,
            )

            self._set_status("Chopped into " + str(segment_count) + " segments. Running PSD...")

            run_psd_and_save(
                segment_dir,
                figure_dir,
                label,
                summary_path,
                self._set_status,
            )

            self._set_status(
                "Done.  "
                + str(segment_count)
                + " segments  |  Figures -> "
                + str(figure_dir)
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


def main():
    app = ProcessTestUI()
    app.mainloop()


if __name__ == "__main__":
    main()
