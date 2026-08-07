#!/usr/bin/env python3
"""RM3100 magnetometer noise-floor calculator.

Processes one or more RM3100 log files that have already been copied from the
Raspberry Pi. The program merges the selected logs, splits them into time
segments, calculates amplitude spectral density (ASD), and saves plots plus a
CSV summary for X, Y, Z, and total field.
"""

import csv
import shutil
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch


ROOT = Path(__file__).resolve().parent

HEADER = ("time", "rtemp", "ltemp", "x", "y", "z", "rx", "ry", "rz", "total")
HUMAN_TIME_FORMAT = "%d %b %Y %H:%M:%S"
SAMPLE_RATE_HZ = 1.0
NOISE_BAND_HZ = (0.10, 0.40)
PSWS_REFERENCE_NT = 10.0
CHANNELS = ("X", "Y", "Z", "TOTAL")
INVALID_LABEL_CHARS = '<>:"/\\|?*'


def parse_timestamp(value):
    """Return a human-readable or epoch timestamp as UTC epoch seconds."""
    value = value.strip().strip('"')

    try:
        return datetime.strptime(value, HUMAN_TIME_FORMAT).replace(
            tzinfo=timezone.utc
        ).timestamp()
    except ValueError:
        return float(value)


def read_log_rows(paths):
    """Read valid data rows from one or more RM3100 log files."""
    rows = []

    for path in sorted(paths):
        with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
            reader = csv.reader(file, skipinitialspace=True)

            for record in reader:
                if len(record) < len(HEADER):
                    continue

                if record[0].strip().lower() == "time":
                    continue

                try:
                    epoch = parse_timestamp(record[0])
                    values = [field.strip() for field in record[1:len(HEADER)]]
                except ValueError:
                    continue

                rows.append((epoch, [f"{epoch:.6f}", *values]))

    if not rows:
        raise ValueError("No valid data rows were found in the selected file(s).")

    rows.sort(key=lambda item: item[0])
    return rows


def write_log(path, rows):
    """Write RM3100 rows using the standard ten-column format."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows(record for _, record in rows)


def split_logs(raw_paths, segment_dir, segment_minutes, archive_path):
    """Merge, sort, archive, and split selected logs into fixed time segments."""
    rows = read_log_rows(raw_paths)
    write_log(archive_path, rows)

    segment_dir.mkdir(parents=True, exist_ok=True)
    segment_seconds = segment_minutes * 60
    segment_start = rows[0][0]
    segment_rows = []
    segment_count = 0

    def save_segment(records):
        nonlocal segment_count

        if not records:
            return

        first_timestamp = records[0][0]
        filename = datetime.fromtimestamp(
            first_timestamp, tz=timezone.utc
        ).strftime("%Y-%m-%d_%H-%M-%S.log")
        write_log(segment_dir / filename, records)
        segment_count += 1

    for epoch, record in rows:
        if segment_rows and epoch - segment_start >= segment_seconds:
            save_segment(segment_rows)
            segment_rows = []
            segment_start = epoch

        segment_rows.append((epoch, record))

    save_segment(segment_rows)
    return segment_count


def load_segment(path):
    """Load X, Y, Z, and total field from one segment as nanotesla arrays."""
    values = [[], [], [], []]
    column_indices = (3, 4, 5, 9)

    with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        reader = csv.reader(file, skipinitialspace=True)

        for record in reader:
            if len(record) < len(HEADER) or record[0].strip().lower() == "time":
                continue

            try:
                for output, column in zip(values, column_indices):
                    output.append(float(record[column]))
            except ValueError:
                continue

    if len(values[0]) < 2:
        raise ValueError(f"Not enough valid data in {path.name}")

    signals = np.asarray(values, dtype=float)
    signals -= signals.mean(axis=1, keepdims=True)
    signals *= 1000.0
    return signals


def save_overlay_plot(curves, channel, label, output_path):
    """Save an ASD overlay containing every valid segment for one channel."""
    figure, axis = plt.subplots(figsize=(10, 5))

    for frequencies, asd in curves:
        axis.semilogy(frequencies, asd, lw=0.6, alpha=0.65, color="#1f77b4")

    axis.set_xlim(0, 0.5)
    axis.set_ylim(1e0, 1e3)
    axis.set_xlabel("Frequency (Hz)")
    axis.set_ylabel("ASD (nT/√Hz)")
    axis.set_title(f"{channel} PSD Overlay -- {label}")
    axis.grid(True, which="both", linestyle="--", alpha=0.4)

    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def save_noise_floor_plot(
    frequencies,
    median_curve,
    lower_curve,
    upper_curve,
    noise_floor,
    channel,
    label,
    output_path,
):
    """Save the median ASD, spread, calculated floor, and reference level."""
    plot_mask = frequencies >= NOISE_BAND_HZ[0]
    plot_frequencies = frequencies[plot_mask]

    figure, axis = plt.subplots(figsize=(10, 5))

    axis.fill_between(
        plot_frequencies,
        lower_curve[plot_mask],
        upper_curve[plot_mask],
        alpha=0.25,
        color="#1f77b4",
        label="10th-90th percentile",
    )
    axis.semilogy(
        plot_frequencies,
        median_curve[plot_mask],
        lw=1.8,
        color="#1f77b4",
        label="Median ASD",
    )
    axis.axhline(
        noise_floor,
        color="green",
        lw=1.5,
        linestyle="--",
        label=f"Noise floor: {noise_floor:.3f} nT/√Hz",
    )
    axis.axhline(
        PSWS_REFERENCE_NT,
        color="red",
        lw=1.2,
        linestyle=":",
        label=f"Reference: {PSWS_REFERENCE_NT:g} nT/√Hz",
    )

    axis.set_xlim(NOISE_BAND_HZ[0], 0.5)
    axis.set_ylim(1e0, 1e3)
    axis.set_xlabel("Frequency (Hz)")
    axis.set_ylabel("ASD (nT/√Hz)")
    axis.set_title(f"{channel} Noise Floor -- {label}  [{noise_floor:.3f} nT/√Hz]")
    axis.legend(fontsize=9, loc="upper right")
    axis.grid(True, which="both", linestyle="--", alpha=0.4)

    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def analyze_segments(segment_dir, figure_dir, label, summary_path, status_callback):
    """Calculate ASD and noise-floor results for all segments in one test."""
    files = sorted(segment_dir.glob("*.log"))
    if not files:
        raise ValueError(f"No .log files found in {segment_dir}")

    figure_dir.mkdir(parents=True, exist_ok=True)
    segment_curves = {channel: [] for channel in CHANNELS}
    valid_segments = 0

    status_callback(f"Computing PSD for {len(files)} segments...")

    for path in files:
        try:
            signals = load_segment(path)
        except ValueError:
            continue

        n_samples = signals.shape[1]
        nperseg = min(1024, 2 ** int(np.floor(np.log2(n_samples))))
        frequencies, psd = welch(
            signals,
            fs=SAMPLE_RATE_HZ,
            nperseg=nperseg,
            window="hann",
            axis=1,
        )
        asd = np.sqrt(psd)

        for index, channel in enumerate(CHANNELS):
            segment_curves[channel].append((frequencies, asd[index]))

        valid_segments += 1

    if valid_segments == 0:
        raise ValueError("None of the generated segments contained enough valid data.")

    for channel in CHANNELS:
        output_path = figure_dir / f"{channel}_{label}.png"
        save_overlay_plot(segment_curves[channel], channel, label, output_path)
        status_callback(f"Saved {output_path.name}")

    summary_rows = []
    low_frequency, high_frequency = NOISE_BAND_HZ

    print("\n" + "=" * 60)
    print(f"NOISE FLOOR RESULTS -- {label}")
    print(f"Noise band: {low_frequency:.2f}-{high_frequency:.2f} Hz")
    print(f"Reference: {PSWS_REFERENCE_NT:g} nT/√Hz")
    print("=" * 60)

    for channel in CHANNELS:
        curves = segment_curves[channel]
        common_frequencies = curves[0][0]
        asd_matrix = np.vstack(
            [np.interp(common_frequencies, frequencies, asd) for frequencies, asd in curves]
        )

        median_curve = np.median(asd_matrix, axis=0)
        lower_curve = np.percentile(asd_matrix, 10, axis=0)
        upper_curve = np.percentile(asd_matrix, 90, axis=0)

        band_mask = (
            (common_frequencies >= low_frequency)
            & (common_frequencies <= high_frequency)
        )
        if not np.any(band_mask):
            raise ValueError(
                f"The {channel} data does not contain frequencies in the selected noise band."
            )

        noise_floor = float(np.median(median_curve[band_mask]))
        passed = noise_floor <= PSWS_REFERENCE_NT
        status = "PASS" if passed else "FAIL"

        print(f"{channel:<6} floor = {noise_floor:.3f} nT/√Hz  [{status}]")

        summary_rows.append(
            {
                "channel": channel,
                "noise_floor_nT_per_rtHz": f"{noise_floor:.6f}",
                "flat_band_low_Hz": low_frequency,
                "flat_band_high_Hz": high_frequency,
                "target_nT_per_rtHz": PSWS_REFERENCE_NT,
                "status": status,
                "segments_used": len(curves),
            }
        )

        output_path = figure_dir / f"{channel}_{label}_noisefloor.png"
        save_noise_floor_plot(
            common_frequencies,
            median_curve,
            lower_curve,
            upper_curve,
            noise_floor,
            channel,
            label,
            output_path,
        )
        status_callback(f"Saved {output_path.name}")

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(summary_rows[0])

    with summary_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    status_callback(f"Saved {summary_path.name}")
    print(f"Segments used: {valid_segments}")
    print(f"Summary CSV: {summary_path}")
    print("=" * 60 + "\n")


class ProcessTestUI(tk.Tk):
    """Small desktop interface for the RM3100 processing workflow."""

    def __init__(self):
        super().__init__()

        self.title("RM3100 Noise Floor Calculator")
        self.geometry("660x420")
        self.resizable(False, False)

        self.raw_files = []
        self.site_var = tk.StringVar()
        self.label_var = tk.StringVar()
        self.segment_var = tk.IntVar(value=5)

        self.build_ui()

    def build_ui(self):
        raw_frame = ttk.LabelFrame(self, text="1. Raw log file(s)", padding=6)
        raw_frame.pack(fill=tk.X, padx=10, pady=4)

        self.file_label = ttk.Label(raw_frame, text="No files selected", foreground="gray")
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(raw_frame, text="Browse...", command=self.pick_files).pack(side=tk.RIGHT)

        site_frame = ttk.LabelFrame(
            self,
            text="2. Site folder (inside this repository folder)",
            padding=6,
        )
        site_frame.pack(fill=tk.X, padx=10, pady=4)

        ttk.Entry(site_frame, textvariable=self.site_var, width=30).pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )
        ttk.Button(site_frame, text="Browse...", command=self.pick_site).pack(side=tk.RIGHT)
        ttk.Label(site_frame, text="  (type a new name to create)", foreground="gray").pack(
            side=tk.RIGHT
        )

        label_frame = ttk.LabelFrame(
            self,
            text="3. Test label (e.g. Test_1, garage_close)",
            padding=6,
        )
        label_frame.pack(fill=tk.X, padx=10, pady=4)

        ttk.Entry(label_frame, textvariable=self.label_var, width=30).pack(fill=tk.X)

        segment_frame = ttk.LabelFrame(self, text="4. Segment length (minutes)", padding=6)
        segment_frame.pack(fill=tk.X, padx=10, pady=4)

        ttk.Spinbox(
            segment_frame,
            from_=1,
            to=120,
            textvariable=self.segment_var,
            width=8,
        ).pack(anchor=tk.W)

        self.run_button = ttk.Button(self, text="Run", command=self.start_processing)
        self.run_button.pack(pady=12)

        self.status_label = ttk.Label(self, text="Ready.", anchor=tk.W, foreground="gray")
        self.status_label.pack(fill=tk.X, padx=10, pady=(0, 8))

    def pick_files(self):
        paths = filedialog.askopenfilenames(
            title="Select raw log file(s)",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")],
        )

        if paths:
            self.raw_files = [Path(path) for path in paths]
            self.file_label.config(
                text=", ".join(path.name for path in self.raw_files),
                foreground="black",
            )

    def pick_site(self):
        folder = filedialog.askdirectory(
            title="Select or create site folder",
            initialdir=ROOT,
        )

        if not folder:
            return

        selected = Path(folder)
        try:
            self.site_var.set(str(selected.relative_to(ROOT)))
        except ValueError:
            self.site_var.set(str(selected))

    def validate_inputs(self):
        if not self.raw_files:
            messagebox.showwarning("Missing input", "Select at least one raw log file.")
            return None

        site = self.site_var.get().strip()
        if not site:
            messagebox.showwarning("Missing site", "Enter or select a site folder.")
            return None

        label = self.label_var.get().strip()
        if not label:
            messagebox.showwarning("Missing label", "Enter a test label.")
            return None

        if label in {".", ".."} or any(char in label for char in INVALID_LABEL_CHARS):
            messagebox.showwarning(
                "Invalid label",
                "The test label contains characters that cannot be used in a folder name.",
            )
            return None

        try:
            segment_minutes = self.segment_var.get()
        except tk.TclError:
            messagebox.showwarning("Invalid segment", "Enter a whole number of minutes.")
            return None

        if not 1 <= segment_minutes <= 120:
            messagebox.showwarning("Invalid segment", "Segment length must be 1 to 120 minutes.")
            return None

        return site, label, segment_minutes

    def start_processing(self):
        inputs = self.validate_inputs()
        if inputs is None:
            return

        site, label, segment_minutes = inputs
        site_path = Path(site) if Path(site).is_absolute() else ROOT / site
        segment_dir = site_path / label
        figure_dir = site_path / f"{label} Figures"

        existing_output = (
            (segment_dir.exists() and any(segment_dir.iterdir()))
            or (figure_dir.exists() and any(figure_dir.iterdir()))
        )

        if existing_output and not messagebox.askyesno(
            "Replace existing output",
            f"Output for '{label}' already exists. Replace it?",
        ):
            return

        raw_files = tuple(self.raw_files)
        self.run_button.config(state=tk.DISABLED)
        self.set_status("Starting...")

        try:
            self.process(raw_files, site_path, label, segment_minutes)
        finally:
            self.run_button.config(state=tk.NORMAL)

    def process(self, raw_files, site_path, label, segment_minutes):
        segment_dir = site_path / label
        figure_dir = site_path / f"{label} Figures"
        archive_path = site_path / "All" / f"{label}_full.log"
        summary_path = site_path / f"{label}_noise_summary.csv"

        try:
            if segment_dir.exists():
                shutil.rmtree(segment_dir)
            if figure_dir.exists():
                shutil.rmtree(figure_dir)

            self.set_status("Splitting log into segments...")
            segment_count = split_logs(
                raw_files,
                segment_dir,
                segment_minutes,
                archive_path,
            )

            self.set_status(f"Created {segment_count} segments. Running PSD analysis...")
            analyze_segments(
                segment_dir,
                figure_dir,
                label,
                summary_path,
                self.set_status,
            )

            message = (
                f"Done. {segment_count} segments | "
                f"Figures: {figure_dir} | Summary: {summary_path}"
            )
            self.set_status(message)

        except Exception as error:
            error_message = str(error)
            print(f"Error: {error_message}")
            messagebox.showerror("Error", error_message)
            self.set_status(f"Error: {error_message}")

    def set_status(self, message):
        print(message)
        self.status_label.config(text=message, foreground="black")
        self.update_idletasks()


def main():
    ProcessTestUI().mainloop()


if __name__ == "__main__":
    main()
