#!/usr/bin/env python3
"""
audit_mp3.py - Pre-gig MP3 integrity, loudness, and transcode auditor.

Scans MP3 libraries using `mp3val` and `ffmpeg` to catch corrupt frames,
true-peak clipping, extreme loudness, low bitrates, and suspected "fake 320"
transcodes, sorting results by fix priority and Date Modified (newest first).
Automatically saves a timestamped report in the target directory by default.

License: MIT
"""

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

__version__ = "1.1.0"

# ==============================================================================
# CONFIGURABLE THRESHOLDS
# Adjust these values to match your mastering or DJ software standards.
# ==============================================================================
MIN_BITRATE_KBPS = 320       # Flag MP3s below 320 kbps
HIGH_FREQ_CUTOFF_HZ = 16500  # 128 kbps MP3s brickwall around 16 kHz
MIN_HF_RMS_DBFS = -75.0      # Energy below this above cutoff suggests a transcode

MAX_TRUE_PEAK_DBFS = -1.0    # > -1.0 dBFS risks inter-sample clipping; > 0.0 is hard clipping
MAX_LOUDNESS_LUFS = -9.0     # Louder than this is heavily brick-walled
MIN_LOUDNESS_LUFS = -28.0    # Quieter than this may be too faint for normal playback
MIN_LRA_LU = 2.0             # Very low dynamic range (over-compressed)
MAX_LRA_LU = 20.0            # Very wide dynamic range (inconsistent volume)
# ==============================================================================

# Severity Ranks (Lower number = higher priority / printed first)
SEV_CRITICAL = 1  # Corrupt files, structural errors, hard clipping (> 0.0 dBFS)
SEV_HIGH = 2      # Low bitrate, suspected transcodes, structural warnings, low headroom, extreme loudness
SEV_MINOR = 3     # Dynamic range (LRA) outliers
SEV_OK = 4        # No issues


@dataclass
class Issue:
    severity: int
    tag: str
    message: str


@dataclass
class TrackReport:
    path: Path
    mtime: float
    metrics: dict[str, float] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def worst_severity(self) -> int:
        return min((i.severity for i in self.issues), default=SEV_OK)

    @property
    def status_tag(self) -> str:
        return {
            SEV_CRITICAL: "[MUST FIX]",
            SEV_HIGH:     "[WARN]    ",
            SEV_MINOR:    "[MINOR]   ",
            SEV_OK:       "[OK]      ",
        }[self.worst_severity]

    @property
    def formatted_date(self) -> str:
        if self.mtime <= 0:
            return "Unknown Date"
        return datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d %H:%M")


def check_dependencies() -> None:
    """Ensure required external binaries are installed and available in PATH."""
    missing = [tool for tool in ("mp3val", "ffmpeg") if shutil.which(tool) is None]
    if missing:
        sys.exit(
            f"Error: Missing required tool(s) in PATH: {', '.join(missing)}\n"
            "Install them via Homebrew (macOS): brew install mp3val ffmpeg\n"
            "Or apt (Debian/Ubuntu): sudo apt install mp3val ffmpeg"
        )


def check_structure(file_path: Path) -> list[Issue]:
    """Run mp3val -si to detect corrupt frames, bad headers, or stream errors."""
    try:
        res = subprocess.run(
            ["mp3val", "-si", str(file_path)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return [Issue(SEV_CRITICAL, "TIMEOUT", "Structural check timed out")]
    except OSError as exc:
        return [Issue(SEV_CRITICAL, "ERROR", f"Failed to run mp3val: {exc}")]

    issues: list[Issue] = []
    combined_output = f"{res.stdout}\n{res.stderr}"
    for line in combined_output.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(WARNING|PROBLEM|ERROR):\s*(?:.+?:\s*)?(.*)$", line, re.IGNORECASE)
        if match:
            kind, detail = match.groups()
            if kind.upper() in ("PROBLEM", "ERROR"):
                issues.append(Issue(SEV_CRITICAL, "CORRUPT", f"Structure error: {detail}"))
            else:
                issues.append(Issue(SEV_HIGH, "HEADER", f"Structure warning: {detail}"))
        elif res.returncode != 0 and "Analyzing file" not in line:
            issues.append(Issue(SEV_CRITICAL, "CORRUPT", f"Structure error: {line}"))

    return issues


def check_spectral_cutoff(file_path: Path) -> list[Issue]:
    """Measure high-frequency energy above 16.5 kHz to catch low-bitrate transcodes."""
    try:
        res = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(file_path),
                "-af",
                f"highpass=f={HIGH_FREQ_CUTOFF_HZ},highpass=f={HIGH_FREQ_CUTOFF_HZ},astats=metadata=0:reset=0",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    overall_split = res.stderr.split("Overall")
    if len(overall_split) < 2:
        return []

    rms_match = re.search(r"RMS level dB:\s*([+-]?\d+(?:\.\d+)?|-inf)", overall_split[-1])
    if not rms_match:
        return []

    raw_val = rms_match.group(1)
    if raw_val == "-inf" or float(raw_val) < MIN_HF_RMS_DBFS:
        return [
            Issue(
                SEV_HIGH,
                "TRANSCODE",
                f"Suspected fake 320: Negligible energy above {HIGH_FREQ_CUTOFF_HZ / 1000:.1f} kHz (HF RMS: {raw_val} dBFS)",
            )
        ]
    return []


def check_loudness_and_quality(file_path: Path) -> tuple[dict[str, float], list[Issue]]:
    """Measure integrated loudness (LUFS), LRA, true peak (dBFS), and stream bitrate."""
    try:
        res = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(file_path),
                "-af",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {}, [Issue(SEV_CRITICAL, "TIMEOUT", "Loudness analysis timed out")]
    except OSError as exc:
        return {}, [Issue(SEV_CRITICAL, "ERROR", f"Failed to run ffmpeg: {exc}")]

    issues: list[Issue] = []

    # 1. Stream bitrate check
    bitrate_match = re.search(r"Audio:\s*mp3.*?(\d+)\s*kb/s", res.stderr)
    bitrate = int(bitrate_match.group(1)) if bitrate_match else 0
    if 0 < bitrate < MIN_BITRATE_KBPS:
        issues.append(Issue(SEV_HIGH, "BITRATE", f"Low bitrate: {bitrate} kbps (< {MIN_BITRATE_KBPS} kbps)"))
    elif bitrate >= MIN_BITRATE_KBPS:
        issues.extend(check_spectral_cutoff(file_path))

    # 2. EBU R128 loudness metrics
    summary_split = res.stderr.split("Summary:")
    if len(summary_split) < 2:
        return {}, [Issue(SEV_CRITICAL, "CORRUPT", "Corrupt or unreadable audio stream")]

    summary = summary_split[-1]
    metrics: dict[str, float] = {}
    patterns = {
        "I": r"^\s*I:\s*([+-]?\d+(?:\.\d+)?)\s*LUFS",
        "LRA": r"^\s*LRA:\s*([+-]?\d+(?:\.\d+)?)\s*LU",
        "Peak": r"^\s*Peak:\s*([+-]?\d+(?:\.\d+)?)\s*dBFS",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, summary, re.MULTILINE)
        if match:
            metrics[key] = float(match.group(1))

    if len(metrics) < 3:
        return metrics, [Issue(SEV_CRITICAL, "CORRUPT", "Incomplete loudness metrics returned")]

    if bitrate:
        metrics["Bitrate"] = float(bitrate)

    lufs = metrics["I"]
    lra = metrics["LRA"]
    peak = metrics["Peak"]

    # 3. Clipping & headroom
    if peak > 0.0:
        issues.append(Issue(SEV_CRITICAL, "CLIPPING", f"Hard clipping: True peak is {peak:+.1f} dBFS (> 0.0 dBFS)"))
    elif peak > MAX_TRUE_PEAK_DBFS:
        issues.append(Issue(SEV_HIGH, "HEADROOM", f"Low headroom: True peak is {peak:+.1f} dBFS (> {MAX_TRUE_PEAK_DBFS:+.1f} dBFS)"))

    # 4. Integrated loudness
    if lufs > MAX_LOUDNESS_LUFS:
        issues.append(Issue(SEV_HIGH, "LOUDNESS", f"Over-loud/brickwalled: {lufs:.1f} LUFS (> {MAX_LOUDNESS_LUFS:.1f} LUFS)"))
    elif lufs < MIN_LOUDNESS_LUFS:
        issues.append(Issue(SEV_HIGH, "LOUDNESS", f"Too quiet: {lufs:.1f} LUFS (< {MIN_LOUDNESS_LUFS:.1f} LUFS)"))

    # 5. Dynamic range
    if lra < MIN_LRA_LU:
        issues.append(Issue(SEV_MINOR, "DYNAMICS", f"Flat dynamics: {lra:.1f} LU (< {MIN_LRA_LU:.1f} LU)"))
    elif lra > MAX_LRA_LU:
        issues.append(Issue(SEV_MINOR, "DYNAMICS", f"Wide dynamics: {lra:.1f} LU (> {MAX_LRA_LU:.1f} LU)"))

    return metrics, issues


def get_mtime(file_path: Path) -> float:
    try:
        return file_path.stat().st_mtime
    except OSError:
        return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit MP3 files for structural integrity, clipping, loudness, and transcodes."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Directory or single .mp3 file to scan (default: current directory)",
    )
    parser.add_argument("-r", "--recursive", action="store_true", help="Scan subdirectories recursively")
    parser.add_argument("--issues-only", action="store_true", help="Only display/save tracks with warnings or errors")
    parser.add_argument("-p", "--full-path", action="store_true", help="Display full file paths instead of filenames")
    parser.add_argument(
        "-o",
        "--output",
        help="Custom output file path (default: <target_dir>/audit_report_YYYY-MM-DD_HHMMSS.txt)",
    )
    parser.add_argument("--no-save", action="store_true", help="Print to terminal only without saving a report file")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    check_dependencies()

    target_path = Path(args.target).resolve()
    if not target_path.exists():
        sys.exit(f"Error: Path does not exist: {target_path}")

    if target_path.is_file():
        files = [target_path]
        report_dir = target_path.parent
    else:
        glob_pattern = "**/*.mp3" if args.recursive else "*.mp3"
        files = [p for p in target_path.glob(glob_pattern) if p.is_file() and p.suffix.lower() == ".mp3"]
        report_dir = target_path

    if not files:
        sys.exit(f"No MP3 files found in '{target_path}'.")

    print(f"Scanning {len(files)} file(s)...", file=sys.stderr)

    reports: list[TrackReport] = []
    for file_path in files:
        mtime = get_mtime(file_path)
        struct_issues = check_structure(file_path)
        metrics, loud_issues = check_loudness_and_quality(file_path)
        all_issues = sorted(struct_issues + loud_issues, key=lambda i: i.severity)
        reports.append(TrackReport(path=file_path, mtime=mtime, metrics=metrics, issues=all_issues))

    # Sort by: severity -> newest Date Modified -> filename
    reports.sort(key=lambda r: (r.worst_severity, -r.mtime, r.path.name.lower()))

    must_fix_count = sum(1 for r in reports if r.worst_severity == SEV_CRITICAL)
    warn_count = sum(1 for r in reports if r.worst_severity in (SEV_HIGH, SEV_MINOR))

    lines: list[str] = []
    for report in reports:
        display_name = str(report.path) if args.full_path else report.path.name
        if report.issues:
            lines.append(f"{report.status_tag} [{report.formatted_date}] {display_name}")
            for issue in report.issues:
                lines.append(f"  - [{issue.tag}] {issue.message}")
        elif not args.issues_only:
            br = f"{int(report.metrics['Bitrate'])}k | " if "Bitrate" in report.metrics else ""
            stats = (
                f"{br}I: {report.metrics['I']:.1f} LUFS | Peak: {report.metrics['Peak']:+.1f} dBFS | LRA: {report.metrics['LRA']:.1f} LU"
                if all(k in report.metrics for k in ("I", "Peak", "LRA"))
                else "Metrics unavailable"
            )
            lines.append(f"{report.status_tag} [{report.formatted_date}] {display_name} ({stats})")

    lines.append(f"\nSummary: {len(files)} scanned | {must_fix_count} must-fix | {warn_count} warnings")
    report_text = "\n".join(lines) + "\n"

    print(report_text, end="")

    if not args.no_save:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = Path(args.output) if args.output else report_dir / f"audit_report_{timestamp}.txt"
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            header = (
                f"MP3 Audit Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Target: {target_path}\n"
                f"{'-' * 72}\n"
            )
            output_path.write_text(header + report_text, encoding="utf-8")
            print(f"Report saved to: {output_path}", file=sys.stderr)
        except OSError as exc:
            print(f"Warning: Could not save report to {output_path}: {exc}", file=sys.stderr)

    sys.exit(1 if (must_fix_count + warn_count) > 0 else 0)


if __name__ == "__main__":
    main()