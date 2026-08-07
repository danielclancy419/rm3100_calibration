# RM3100 Noise Floor Calculator

This repository contains a Python tool for analyzing data recorded by a PNI RM3100 magnetometer.

It was made to help compare possible magnetometer installation locations by looking at the noise present in recordings from each position. The program works with `.log` files produced using Dave Witten's `rm3100-runMag` software.

The calculator does not communicate with the RM3100 or collect data itself. The recordings should already be completed and copied from the Raspberry Pi before using this program.

## References

RM3100 data collection software:

https://github.com/wittend/rm3100-runMag

HamSCI RM3100 documentation:

https://hamsci.org/mag_software

https://hamsci.org/mag_install

## Requirements

Python 3 is required along with NumPy, Matplotlib, and SciPy.

Install the required Python packages with:

```bash
pip install numpy matplotlib scipy
```

The program uses Tkinter for the interface. Tkinter is normally included with Python on Windows.

On Linux or Raspberry Pi OS, it may need to be installed separately:

```bash
sudo apt install python3-tk
```

## Running the Program

Download or clone this repository, then open a terminal in the repository folder.

Run:

```bash
python ProcessTest.py
```

Depending on the system, Python may instead be called with:

```bash
python3 ProcessTest.py
```

A small window will open with four inputs:

1. **Raw log file(s)**
   Select one or more RM3100 `.log` files from the same test.

2. **Site folder**
   Choose an existing site folder or enter a new name. Tests from the same general installation site can be kept together here.

3. **Test label**
   Give the individual test a useful name such as `Backyard_Close`, `Fence_Test`, or `Location_3`.

4. **Segment length**
   This controls how the recording is divided before analysis. Five-minute segments are recommended for the current testing method.

Press **Run** once the information is filled in.

## What the Program Does

The selected log files are first combined and sorted by timestamp. A complete merged copy is saved before the recording is divided into smaller time segments.

Each segment is then analyzed using Welch's method to calculate the amplitude spectral density for:

* X
* Y
* Z
* Total magnetic field

The current program assumes the RM3100 data was recorded at approximately 1 Hz.

A broadband noise-floor estimate is calculated between **0.10 Hz and 0.40 Hz**. The program also uses **10 nT/√Hz** as a reference value when reporting the results.

The reference is useful for quickly comparing tests, but the plots should still be reviewed when choosing a location.

## Output

Results are saved inside the selected site folder.

For a test labeled `Backyard_Far`, the folder will look similar to:

```text
SiteName/
├── All/
│   └── Backyard_Far_full.log
│
├── Backyard_Far/
│   ├── 2026-05-28_22-00-00.log
│   ├── 2026-05-28_22-05-00.log
│   └── ...
│
├── Backyard_Far Figures/
│   ├── X_Backyard_Far.png
│   ├── X_Backyard_Far_noisefloor.png
│   ├── Y_Backyard_Far.png
│   ├── Y_Backyard_Far_noisefloor.png
│   ├── Z_Backyard_Far.png
│   ├── Z_Backyard_Far_noisefloor.png
│   ├── TOTAL_Backyard_Far.png
│   └── TOTAL_Backyard_Far_noisefloor.png
│
└── Backyard_Far_noise_summary.csv
```

### `All`

Contains the complete merged recording before it is divided into segments.

### Test Folder

Contains the individual time segments used for the analysis.

### Figures

Two figures are produced for each magnetic-field channel.

The regular PSD plot shows the individual time segments together. This makes it easier to spot changes in noise during the recording.

The noise-floor plot shows the median spectrum, the spread between segments, the calculated noise floor, and the current reference line.

### Noise Summary

The CSV file contains the calculated noise floor for X, Y, Z, and total field along with the frequency range, reference value, pass/fail result, and number of segments used.

## Testing a Location

For site testing, collect roughly **30 minutes of data at each candidate position**.

Try to keep the recording length, magnetometer settings, and analysis settings the same between locations.

A basic testing cycle is:

1. Choose a possible magnetometer location.
2. Record approximately 30 minutes of data.
3. Copy the resulting `.log` file to the computer.
4. Process the recording with `ProcessTest.py`.
5. Repeat the test at another position.
6. Compare the noise-floor values and plots.

The best position should not be chosen from the pass/fail result alone.

When comparing locations, look for lower noise-floor values, consistent results between segments, and fewer large or repeating peaks in the PSD plots.

After finding the quietest general area, additional measurements can be taken a short distance apart to narrow down the final installation position.

## Expected Log Format

The program expects RM3100 logs containing these columns:

```text
"time", "rtemp", "ltemp", "x", "y", "z", "rx", "ry", "rz", "total"
```

Timestamps may be stored as UTC date/time strings or epoch time. Human-readable timestamps are converted automatically during processing.

Multiple log files from the same test can be selected together. The program sorts their measurements by timestamp before creating the merged file.

## Credits

RM3100 data collection is based on Dave Witten's `rm3100-runMag` project and the HamSCI Personal Space Weather Station RM3100 documentation.

This repository is intended for post-processing and site comparison of previously recorded RM3100 data.
