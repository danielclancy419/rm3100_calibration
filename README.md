# RM3100 Noise Floor Calculator

This repository contains a small Python tool for processing RM3100 magnetometer log files collected using Dave Witten's `rm3100-runMag` Raspberry Pi software.

The purpose of this tool is simple:

1. Record RM3100 data at a possible magnetometer location.
2. Copy the raw log file from the Raspberry Pi.
3. Run this script.
4. Check the generated noise floor values and plots.
5. Move the magnetometer to another location and repeat until satisfied.

This tool does not collect data from the RM3100 directly. It processes log files that were already recorded by the Raspberry Pi.

---

## Background

The RM3100 Raspberry Pi data collection software used by HamSCI is based on Dave Witten's `rm3100-runMag` repository:

https://github.com/wittend/rm3100-runMag

HamSCI's Raspberry Pi-based RM3100 software manual explains how to set up the Raspberry Pi, set the system time to UTC, clone Dave Witten's repository, compile the software, and run the magnetometer logger:

https://hamsci.org/mag_software

HamSCI's RM3100 installation manual explains the physical PSWS ground magnetometer setup and recommends placing the remote RM3100 sensor outside and away from EMI sources:

https://hamsci.org/mag_install

This repository is meant to come after that setup. Once the Raspberry Pi is already recording RM3100 logs, this tool helps organize and analyze those logs.

---

## Main Script

The main script is:

```text
ProcessTest.py
```

When the script runs, a small window opens with four inputs:

### 1. Raw Log File(s)

Select one or more RM3100 log files copied from the Raspberry Pi.

Multiple files can be selected if the same test was split across more than one file. The script merges them chronologically before processing.

### 2. Site Folder

Enter or choose a site folder name, such as:

```text
Backyard
Nations
JJ
House_Test
```

The script creates this folder if it does not already exist.

### 3. Test Label

Enter a label for the test, such as:

```text
Test_1
center_lawn
near_house
garage_close
```

This label is added to the output filenames.

### 4. Segment Length

Choose how many minutes each segment should be.

The recommended value is:

```text
5 minutes
```

---

## What the Script Does

After pressing **Run**, the script automatically:

* reads the selected raw RM3100 log files,
* converts human-readable timestamps to epoch time when needed,
* sorts all rows chronologically,
* saves one full merged archive file,
* splits the data into fixed-length segments,
* calculates Welch PSD/ASD curves for X, Y, Z, and total field,
* estimates the broadband noise floor from 0.10 Hz to 0.40 Hz,
* saves PSD overlay plots,
* saves noise-floor plots,
* saves a noise summary CSV file,
* prints PASS/FAIL results in the console.

---

## Output Folder Structure

After a run, the output will look like this:

```text
Repository_Folder/
└── SiteName/
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

The `All` folder stores the full merged log file.

The `TestLabel` folder stores the chopped time segments.

The `TestLabel Figures` folder stores the generated plots.

The `TestLabel_noise_summary.csv` file stores the final noise floor values.

---

## What the Plots Mean

For each channel, the script creates two plots.

The channels are:

* X
* Y
* Z
* TOTAL

### PSD Overlay Plot

The PSD overlay plot shows all segment ASD curves on the same graph.

This is useful for seeing whether the test was stable or whether some segments had bursts of noise.

### Noise Floor Plot

The noise-floor plot shows:

* the median ASD curve,
* the 10th to 90th percentile spread,
* the calculated broadband noise floor,
* the PSWS target reference line.

The broadband noise floor is calculated as the median value of the median ASD curve from:

```text
0.10 Hz to 0.40 Hz
```

This band is used because it avoids the low-frequency drift region and stays below the 0.5 Hz Nyquist limit for 1 Hz data.

---

## Basic Use

Use this tool after the RM3100 and Raspberry Pi are already working.

A simple workflow is:

1. Put the RM3100 at a location you want to test.
2. Record data using the Raspberry Pi and `rm3100-runMag`.
3. Copy the log file from the Raspberry Pi.
4. Run `ProcessTest.py`.
5. Look at the generated noise floor plots and values.
6. Move the RM3100 to another location.
7. Repeat until one location is good enough.

A good quick test is about:

```text
30 minutes per location
```

Shorter tests can show whether the system is working, but they are less reliable for comparing locations.

---

## Installation

This script is written in Python.

It uses:

```text
numpy
matplotlib
scipy
tkinter
```

`tkinter` is included with most Windows Python installations. On Linux or Raspberry Pi OS, it may need to be installed separately.

---

## Windows Installation

Install Python 3 from:

```text
https://www.python.org/downloads/
```

During installation, check:

```text
Add Python to PATH
```

Then open Command Prompt in the repository folder and run:

```bash
pip install numpy matplotlib scipy
```

Run the program with:

```bash
python ProcessTest.py
```

---

## macOS Installation

Install Python 3 if needed.

Then open Terminal in the repository folder and run:

```bash
pip3 install numpy matplotlib scipy
```

Run the program with:

```bash
python3 ProcessTest.py
```

---

## Linux / Raspberry Pi Installation

Install Python and tkinter if needed:

```bash
sudo apt update
sudo apt install python3 python3-pip python3-tk
```

Then install the required Python packages:

```bash
pip3 install numpy matplotlib scipy
```

Run the program with:

```bash
python3 ProcessTest.py
```

---

## Optional requirements.txt

A `requirements.txt` file can be used to make installation easier.

Recommended contents:

```text
numpy
matplotlib
scipy
```

Then users can install the dependencies with:

```bash
pip install -r requirements.txt
```

or on Linux/Raspberry Pi:

```bash
pip3 install -r requirements.txt
```

---

## Input File Format

The script expects RM3100 log files with columns like:

```text
"time", "rtemp", "ltemp", "x", "y", "z", "rx", "ry", "rz", "total"
```

The timestamp can be either:

* human-readable UTC time, or
* epoch time.

The script attempts to convert human-readable timestamps to epoch time automatically.

---

## Important Notes

Before transferring data from the Raspberry Pi, make sure the RM3100 logging service is running and the log file is growing.

A useful SSH check is:

```bash
tail -5 /path/to/current/log/file.log
```

If the timestamps are updating once per second, the file is actively recording.

For reliable comparison, collect at least 30 minutes of clean data at each location when possible.

---

## What This Tool Is Not

This tool is not the Raspberry Pi RM3100 data logger.

It does not communicate with the RM3100 directly.

It does not replace Dave Witten's `rm3100-runMag` software.

It does not upload data to the PSWS server.

It does not perform final RM3100 alignment.

It is only meant to process recorded RM3100 log files and help compare noise floor results between test locations.

---

## Credits

RM3100 data collection for the HamSCI PSWS ground magnetometer is based on Dave Witten's `rm3100-runMag` repository:

https://github.com/wittend/rm3100-runMag

HamSCI's RM3100 setup and installation documentation should be used for Raspberry Pi setup, RM3100 installation, and final sensor alignment:

https://hamsci.org/mag_software

https://hamsci.org/mag_install
