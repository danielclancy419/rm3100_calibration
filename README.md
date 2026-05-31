# RM3100 Noise Floor Calculator

This repository contains a Python tool for processing RM3100 magnetometer log files recorded on a Raspberry Pi using Dave Witten's `rm3100-runMag` software.

Dave Witten's RM3100 data collection code can be found here:

https://github.com/wittend/rm3100-runMag

HamSCI RM3100 setup and installation documentation can be found here:

https://hamsci.org/mag_software

https://hamsci.org/mag_install

This tool does not collect data from the RM3100 directly. It only processes existing `.log` files after they have been copied from the Raspberry Pi.

---

## What It Does

`ProcessTest.py` lets the user select RM3100 log files, organize them by site/test name, split the data into time segments, and generate noise-floor plots.

The script automatically:

* merges selected raw log files,
* sorts the data chronologically,
* saves a full merged archive,
* splits the data into fixed-length segments,
* calculates Welch PSD/ASD curves for X, Y, Z, and total field,
* estimates the broadband noise floor from 0.10 Hz to 0.40 Hz,
* saves PSD overlay plots,
* saves noise-floor plots,
* saves a CSV summary of the noise-floor results.

---

## Installation

Install Python 3, then install the required packages:

```bash
pip install numpy matplotlib scipy
```

On Linux or Raspberry Pi OS, install tkinter if needed:

```bash
sudo apt install python3-tk
```

---

## How to Run

From the repository folder, run:

```bash
python ProcessTest.py
```

or on some systems:

```bash
python3 ProcessTest.py
```

A small window will open.

Select:

1. the raw RM3100 log file or files,
2. a site folder name,
3. a test label,
4. the segment length in minutes.

For this method, a 5-minute segment length is recommended.

---

## Output

The script saves results inside the repository folder unless the user chooses another location.

Example output:

```text
SiteName/
├── All/
│   └── TestLabel_full.log
├── TestLabel/
│   ├── 2026-05-28_22-00-00.log
│   ├── 2026-05-28_22-05-00.log
│   └── ...
├── TestLabel Figures/
│   ├── X_TestLabel.png
│   ├── X_TestLabel_noisefloor.png
│   ├── Y_TestLabel.png
│   ├── Y_TestLabel_noisefloor.png
│   ├── Z_TestLabel.png
│   ├── Z_TestLabel_noisefloor.png
│   ├── TOTAL_TestLabel.png
│   └── TOTAL_TestLabel_noisefloor.png
└── TestLabel_noise_summary.csv
```

---

## Basic Workflow

1. Place the RM3100 at a test location.
2. Record data using the Raspberry Pi and `rm3100-runMag`.
3. Copy the `.log` file from the Raspberry Pi.
4. Run `ProcessTest.py`.
5. Review the plots and CSV noise-floor results.
6. Move the RM3100 to another location and repeat.
7. Compare results and choose the best location.

For reliable comparison, about 30 minutes of data per location is recommended.

---

## Input File Format

The script expects RM3100 log files with columns like:

```text
"time", "rtemp", "ltemp", "x", "y", "z", "rx", "ry", "rz", "total"
```

The timestamp can be either human-readable UTC time or epoch time. The script converts human-readable timestamps automatically.

---

## Credits

RM3100 data collection is based on Dave Witten's `rm3100-runMag` repository and HamSCI PSWS RM3100 setup documentation.

This tool is only for post-processing recorded RM3100 log files.
