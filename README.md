# mixxx-audit-mp3

A lightweight, zero-dependency Python CLI utility for Mixxx and mobile DJs to audit MP3 libraries before a gig. It wraps `mp3val` and `ffmpeg` to catch corrupt frames, inter-sample clipping, brick-walled loudness, low bitrates, and suspected "fake 320" transcodes—automatically sorting results by **fix priority** and **Date Modified (newest first)** so you only spend time fixing tracks that actually need attention.

---

## Why Use This?

Tracks that sound acceptable on laptop speakers or headphones at low volume can cause serious problems when pushed through a club or mobile PA system at 90–95 dB SPL:

* **Corrupt MP3 frames or bad headers** can cause Mixxx, CDJs, or hardware controllers to display inaccurate track lengths, drift beatgrids mid-song, stutter, or abruptly stop playback.
* **True peaks above $0.0\text{ dBFS}$** trigger harsh digital distortion the moment they hit a mixer's DAC, limiter, or EQ boost.
* **Low-bitrate or re-encoded ("fake 320") files** suffer from smeared drum transients, collapsed stereo imaging, and high-frequency artifacts that cause listener ear fatigue on compression drivers.

---

## Features

* **Two-Pass Diagnostic Engine:** Combines `mp3val` for fast structural frame/header verification with `ffmpeg` (`ebur128` + `astats`) for EBU R128 loudness, true-peak measurement, bitrate detection, and high-frequency spectral cutoff analysis.
* **Actionable Triage Sorting:** Groups tracks into `[MUST FIX]`, `[WARN]`, `[MINOR]`, and `[OK]`, sorting newest files (`Date Modified`) to the top of each category so newly added or freshly edited tracks are checked first.
* **Fake-320 Transcode Detection:** Runs a dual-stage $16.5\text{ kHz}$ high-pass filter check on files claiming $320\text{ kbps}$ to catch low-bitrate rips that were upsampled or re-encoded.
* **Zero Python Dependencies:** Built strictly with the Python 3.9+ standard library—no virtual environments or `pip install` required.
* **Safe Path Handling:** Properly handles filenames with spaces, punctuation, and non-ASCII characters, with timeouts to prevent hung processes on severely damaged files.

---

## Prerequisites

1. **Python 3.9 or newer**
2. **`mp3val`** (MP3 frame and header validator)
3. **`ffmpeg`** (Audio decoder, EBU R128 loudness analyzer, and spectral filter)

### Installing `mp3val` and `ffmpeg`

**macOS (via Homebrew):**
```bash
brew install mp3val ffmpeg
```

**Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install mp3val ffmpeg
```

**Windows (via winget / manual PATH):**
```powershell
winget install Gyan.FFmpeg
# Download mp3val from SourceForge and add its folder to your System PATH
```

Verify both tools are accessible in your terminal:
```bash
mp3val -v && ffmpeg -version
```

---

## Installation

1. Clone or download this repository:
   ```bash
   git clone https://github.com/<your-username>/mixxx-audit-mp3.git
   cd mixxx-audit-mp3
   ```

2. Make the script executable (macOS / Linux):
   ```bash
   chmod +x audit_mp3.py
   ```

3. *(Optional)* Symlink or move `audit_mp3.py` into a directory in your `PATH` (such as `/usr/local/bin/audit_mp3`) to run it from any folder without typing the full path.

---

## Usage

```bash
./audit_mp3.py [target] [options]
```

*(On Windows, run with `python audit_mp3.py [target] [options]`.)*

### CLI Options

| Flag | Description |
| :--- | :--- |
| `target` | Directory or single `.mp3` file to audit (defaults to current directory `.`) |
| `-r`, `--recursive` | Scan all subdirectories recursively |
| `--issues-only` | Hide `[OK]` tracks and display only files with warnings or errors |
| `-p`, `--full-path` | Print full file paths instead of filenames (useful for nested crate folders) |
| `-v`, `--version` | Show script version and exit |
| `-h`, `--help` | Show help message and exit |

### Common Examples

```bash
# Audit all MP3s in the current folder
./audit_mp3.py

# Recursively audit an entire Mixxx music library and show only flagged tracks
./audit_mp3.py /path/to/Music -r --issues-only

# Recursively audit with full paths so you can locate files across subfolders
./audit_mp3.py /path/to/Music -r --issues-only -p

# Audit a single track after exporting from a DAW
./audit_mp3.py "/path/to/Music/New Track.mp3"
```

---

## Understanding the Output

### Severity Categories

Tracks are sorted in the following order, and ordered **newest to oldest** by `Date Modified` within each tier:

1. **`[MUST FIX]`** — Critical structural errors or hard true-peak clipping ($> 0.0\text{ dBFS}$). Fix or replace before playing live.
2. **`[WARN]`** — Non-fatal header warnings, bitrates below $320\text{ kbps}$, suspected transcodes, low peak headroom, or extreme loudness.
3. **`[MINOR]`** — Informational dynamic range (`LRA`) outliers.
4. **`[OK]`** — Passes all structural, bitrate, spectral, and loudness checks.

### Issue Tags Reference

| Severity | Tag | Trigger Condition | Practical Impact |
| :--- | :--- | :--- | :--- |
| `[MUST FIX]` | `[CORRUPT]` | `mp3val` error/problem or `ffmpeg` decode failure | Deck glitches, beatgrid drift, or playback dropouts |
| `[MUST FIX]` | `[CLIPPING]` | True peak $> 0.0\text{ dBFS}$ | Audible digital distortion on mixers, DACs, and PA speakers |
| `[MUST FIX]` | `[TIMEOUT]` / `[ERROR]` | Analysis timed out or external binary failed | Unreadable or locked file |
| `[WARN]` | `[HEADER]` | `mp3val` warning (e.g., missing VBR/Xing tag, trailing garbage) | Wrong duration display or inaccurate waveform seeking |
| `[WARN]` | `[BITRATE]` | Stream bitrate $< 320\text{ kbps}$ | Smeared percussion transients and high-end compression artifacts |
| `[WARN]` | `[TRANSCODE]` | $320\text{ kbps}$ file with HF RMS $< -75.0\text{ dBFS}$ above $16.5\text{ kHz}$ | Likely re-encoded from a 128/192 kbps source *(note: vintage analog recordings may naturally roll off above 16 kHz)* |
| `[WARN]` | `[HEADROOM]` | True peak between $-1.0\text{ dBFS}$ and $0.0\text{ dBFS}$ | Little headroom left for mixer EQ boosts |
| `[WARN]` | `[LOUDNESS]` | Integrated loudness $> -9.0\text{ LUFS}$ or $< -28.0\text{ LUFS}$ | Heavy brick-wall limiting or unusually quiet master |
| `[MINOR]` | `[DYNAMICS]` | Loudness Range (`LRA`) $< 2.0\text{ LU}$ or $> 20.0\text{ LU}$ | Flat/over-compressed dynamics or wide volume swings |

### Sample Output

```text
Scanning 4 file(s)...
[MUST FIX] [2026-11-24 10:15] Salsa Clasica (Club Edit).mp3
  - [CLIPPING] Hard clipping: True peak is +0.3 dBFS (> 0.0 dBFS)
  - [LOUDNESS] Over-loud/brickwalled: -8.0 LUFS (> -9.0 LUFS)
  - [DYNAMICS] Flat dynamics: 1.9 LU (< 2.0 LU)
[WARN]     [2026-11-22 18:40] Promo Track 04.mp3
  - [TRANSCODE] Suspected fake 320: Negligible energy above 16.5 kHz (HF RMS: -84.2 dBFS)
[WARN]     [2026-11-19 09:12] Old Download.mp3
  - [BITRATE] Low bitrate: 192 kbps (< 320 kbps)
[OK]       [2026-11-20 14:05] Mastered Track.mp3 (320k | I: -18.0 LUFS | Peak: -1.5 dBFS | LRA: 6.4 LU)

Summary: 4 scanned | 1 must-fix | 2 warnings
```

---

## Fixing Flagged Tracks

* **`[CLIPPING]` or `[LOUDNESS]`:** Re-process from your lossless (`WAV`/`FLAC`) source in a DAW (such as REAPER or Audacity). Complete any tempo, pitch, or EQ edits **first**, normalize integrated loudness to your target (e.g., $-18.0\text{ LUFS}$ or $-14.0\text{ LUFS}$), and place a True Peak brickwall limiter set to $-1.5\text{ dBTP}$ (or $-2.0\text{ dBTP}$ when encoding to MP3) as the final plugin on your master bus before rendering to $320\text{ kbps}$ CBR.
* **`[HEADER]`:** Often repairable in-place with `mp3val "filename.mp3" -f -nb` (back up your file first).
* **`[CORRUPT]`, `[BITRATE]`, or `[TRANSCODE]`:** Replace the file from a verified lossless or legitimate $320\text{ kbps}$ distribution source—lost high-frequency data and damaged audio frames cannot be restored by re-encoding.

---

## Customizing Thresholds

Open `audit_mp3.py` and edit the configuration block at the top of the file to match your preferred library standards:

```python
MIN_BITRATE_KBPS = 320       # Flag MP3s below 320 kbps
HIGH_FREQ_CUTOFF_HZ = 16500  # 128 kbps MP3s brickwall around 16 kHz
MIN_HF_RMS_DBFS = -75.0      # Energy below this above cutoff suggests a transcode

MAX_TRUE_PEAK_DBFS = -1.0    # > -1.0 dBFS risks inter-sample clipping; > 0.0 is hard clipping
MAX_LOUDNESS_LUFS = -9.0     # Louder than this is heavily brick-walled
MIN_LOUDNESS_LUFS = -28.0    # Quieter than this may be too faint for normal playback
MIN_LRA_LU = 2.0             # Very low dynamic range (over-compressed)
MAX_LRA_LU = 20.0            # Very wide dynamic range (inconsistent volume)
```

---

## Exit Codes

For shell scripts or batch automation:

* **`0`** — All scanned files passed with `[OK]`.
* **`1`** — One or more files triggered `[MUST FIX]`, `[WARN]`, or `[MINOR]` flags (or a fatal runtime error occurred).

---

## License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom it is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.