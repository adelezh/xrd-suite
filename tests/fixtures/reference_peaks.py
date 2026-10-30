"""Focused helpers for CHI/XY XRD peak analysis with Pseudo-Voigt fits."""

from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from scipy.optimize import curve_fit
from scipy.signal import find_peaks

try:
    from pybaselines import Baseline
except (ImportError, ModuleNotFoundError):
    Baseline = None


RESULT_COLUMNS = [
    "sequence",
    "file",
    "peak_number",
    "peak_x_guess",
    "center",
    "height",
    "fwhm",
    "area",
    "eta",
    "r_squared",
    "status",
]

_SEQUENCE_RE = re.compile(r"-(\d+)_mean_(?:tth|q)\.chi$", re.IGNORECASE)


def parse_sequence(filename) -> int:
    """Return the integer sequence from a recognized '-N_mean_tth.chi' or '-N_mean_q.chi' suffix."""
    name = Path(filename).name
    match = _SEQUENCE_RE.search(name)
    if not match:
        raise ValueError(f"Cannot parse sequence from filename: {name}")
    return int(match.group(1))


def natural_sort_key(path):
    """Sort embedded filename numbers numerically."""
    return [int(part) if part.isdigit() else part
            for part in re.split(r"(\d+)", Path(path).name.lower())]


def scan_axis_values(files):
    """Use sequence numbers only when every filename has a unique sequence."""
    try:
        values = [parse_sequence(file) for file in files]
    except ValueError:
        return np.arange(len(files), dtype=int)
    return (np.asarray(values, dtype=int) if len(set(values)) == len(values)
            else np.arange(len(files), dtype=int))


def ordered_files(files):
    files = sorted(map(str, files), key=lambda path: (natural_sort_key(path), path))
    indices = scan_axis_values(files)
    return [files[i] for i in np.argsort(indices, kind="stable")]


def as_file_list(path_or_files, search_item="*"):
    """Accept one file, a list of files, or a folder and return sequence-sorted files."""
    if path_or_files is None:
        return []

    if isinstance(path_or_files, (list, tuple)):
        files = [Path(item) for item in path_or_files]
    else:
        path = Path(path_or_files)
        if path.is_file():
            files = [path]
        else:
            pattern = str(path / search_item) if not any(ch in str(path) for ch in "*?[]") else str(path)
            files = [Path(item) for item in glob.glob(pattern)]

    return ordered_files([file for file in files if file.is_file() and
                          (search_item != "*" or file.suffix.lower() in {".chi", ".xy"})])


def _numeric_pair_from_line(line: str):
    parts = line.replace(",", " ").split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def loadxy(filename, xmin=None, xmax=None, skiprows=0, usecols=(0, 1)):
    """Load the first two numeric columns from a CHI/XY text file without fixed skiprows."""
    path = Path(filename)
    rows = []
    if int(skiprows) < 0 or len(usecols) != 2 or min(usecols) < 0:
        raise ValueError("skiprows must be nonnegative and usecols must select two columns.")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if index < int(skiprows) or line.lstrip().startswith(("#", ";", "@")):
                continue
            parts = line.replace(",", " ").split()
            try:
                pair = tuple(float(parts[col]) for col in usecols)
            except (ValueError, IndexError):
                continue
            rows.append(pair)

    if not rows:
        raise ValueError(f"No usable numeric x/intensity data found in file: {path}")

    data = np.asarray(rows, dtype=float)
    x = data[:, 0]
    y = data[:, 1]
    valid = np.isfinite(x) & np.isfinite(y)
    x = x[valid]
    y = y[valid]
    if len(x) == 0:
        raise ValueError(f"No finite numeric x/intensity data found in file: {path}")

    order = np.argsort(x, kind="stable")
    x, y = x[order], y[order]
    if np.any(np.diff(x) == 0):
        raise ValueError(f"Duplicate x values in file: {path}")

    if xmin is not None or xmax is not None:
        left = -np.inf if xmin is None else float(xmin)
        right = np.inf if xmax is None else float(xmax)
        if right <= left:
            raise ValueError("xmax must be greater than xmin.")
        keep = (x >= left) & (x <= right)
        x = x[keep]
        y = y[keep]
        if len(x) == 0:
            raise ValueError(f"No data in requested x range for file: {path}")
    return x, y


def require_baseline(method):
    """Fail explicitly if a requested correction cannot be performed."""
    if method is None or str(method).lower() in {"none", "raw"}:
        return
    if str(method).lower() not in {"arpls", "asls", "asymmetricls"}:
        raise ValueError(f"Unknown baseline_method: {method}")
    if Baseline is None:
        raise ImportError("Baseline correction requires pybaselines. Install it in the active "
                          "Python environment (python -m pip install pybaselines), "
                          "or explicitly select baseline_method='none' for raw data.")


def overlay_plot(path_or_files, search_item="*", xmin=None, xmax=None, yoffset=0, islabel=None):
    """Plot sequence-sorted CHI/XY patterns for quick inspection."""
    filenames = as_file_list(path_or_files, search_item)
    if not filenames:
        raise FileNotFoundError(f"No files found for {path_or_files!r} with {search_item!r}")

    print(f"Total files found: {len(filenames)}")
    fig, ax = plt.subplots(figsize=(10, 4))
    for i, filename in enumerate(filenames):
        x, y = loadxy(filename, xmin=xmin, xmax=xmax)
        label = Path(filename).name if islabel else None
        ax.plot(x, y + i * yoffset, label=label)
    ax.set_title("Overlay Plot")
    ax.set_xlabel("2Theta (deg)")
    ax.set_ylabel("Intensity")
    if islabel:
        ax.legend(fontsize="small", loc="best")
    fig.tight_layout()
    plt.show()
    return fig, ax


def baseline_correct_signal(x, y, method="arpls", lam=5e5):
    """Baseline-correct a signal before peak detection."""
    require_baseline(method)
    if method is None or str(method).lower() in {"none", "raw"}:
        baseline = np.zeros_like(y)
        return y.copy(), baseline

    fitter = Baseline(x_data=x)
    method_name = str(method).lower()
    if method_name == "arpls":
        baseline, _ = fitter.arpls(y, lam=lam)
    elif method_name in {"asls", "asymmetricls"}:
        baseline, _ = fitter.asls(y, lam=lam)
    else:
        raise ValueError(f"Unknown baseline_method: {method}")
    return y - baseline, baseline


def find_xrd_peaks(x, y, height=None, prominence=None, distance=None, width=None):
    """Find peak indices using scipy.signal.find_peaks."""
    peak_indices, properties = find_peaks(
        y,
        height=height,
        prominence=prominence,
        distance=distance,
        width=width,
    )
    return peak_indices, properties


def pseudo_voigt(x, area, center, fwhm, eta):
    """Area-normalized Pseudo-Voigt profile: eta*Lorentzian + (1-eta)*Gaussian."""
    fwhm = np.asarray(fwhm)
    sigma = fwhm / (2 * np.sqrt(2 * np.log(2)))
    gamma = fwhm / 2
    gaussian = np.exp(-0.5 * ((x - center) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))
    lorentzian = (gamma / np.pi) / ((x - center) ** 2 + gamma**2)
    return area * (eta * lorentzian + (1 - eta) * gaussian)


def _pseudo_voigt_with_offset(x, area, center, fwhm, eta, offset):
    return offset + pseudo_voigt(x, area, center, fwhm, eta)


def fit_pseudo_voigt_peak(x, y, peak_index, window=0.3, fwhm_guess=0.05, eta_guess=0.5,
                          center_bounds=None, fit_bounds=None, initial_fit=None):
    """Fit one baseline-corrected peak with an area-normalized Pseudo-Voigt profile."""
    center_guess = float(x[peak_index])
    fit_min = center_guess - window
    fit_max = center_guess + window
    if center_bounds is not None:
        center_min, center_max = center_bounds
        fit_min = max(fit_min, center_min)
        fit_max = min(fit_max, center_max)
    else:
        center_min = fit_min
        center_max = fit_max

    # Tracking can constrain the center independently of the data fitting window.
    if fit_bounds is not None:
        fit_min, fit_max = fit_bounds

    keep = (x >= fit_min) & (x <= fit_max)
    x_fit = x[keep]
    y_fit = y[keep]
    if len(x_fit) < 5:
        raise ValueError("Not enough points in fitting window.")

    diffs = np.diff(x_fit)
    step = float(np.nanmedian(np.abs(diffs))) if len(diffs) else max(window, fit_max - fit_min) / 10
    if not np.isfinite(step) or step <= 0:
        step = max(window, fit_max - fit_min) / 10

    offset_guess = float(np.nanmin(y_fit))
    y_above_offset = y_fit - offset_guess
    peak_height_guess = float(np.nanmax(y_above_offset))
    if not np.isfinite(peak_height_guess) or peak_height_guess <= 0:
        raise ValueError("Peak is not above local minimum.")

    fwhm_guess = float(max(fwhm_guess, step))
    if hasattr(np, "trapezoid"):
        integrate_area = np.trapezoid
    else:
        integrate_area = np.trapz
    area_guess = float(max(peak_height_guess * fwhm_guess, integrate_area(np.maximum(y_above_offset, 0), x_fit)))
    fwhm_upper = max((fit_max - fit_min), fwhm_guess * 5, step * 3)
    lower = [np.finfo(float).eps, center_min, step / 2, 0.0, -np.inf]
    upper = [np.inf, center_max, fwhm_upper, 1.0, np.inf]
    initial = [area_guess, center_guess, fwhm_guess, eta_guess, offset_guess]
    if initial_fit is not None:
        initial = [initial_fit[key] for key in ("area", "center", "fwhm", "eta", "offset")]
        initial = np.clip(initial, np.nextafter(lower, np.inf), np.nextafter(upper, -np.inf))

    popt, pcov = curve_fit(
        _pseudo_voigt_with_offset,
        x_fit,
        y_fit,
        p0=initial,
        bounds=(lower, upper),
        maxfev=20000,
    )

    area, center, fwhm, eta, offset = popt
    fitted_corrected = pseudo_voigt(x_fit, area, center, fwhm, eta)
    fitted = fitted_corrected + offset
    residual = y_fit - fitted
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((y_fit - np.mean(y_fit)) ** 2))
    r_squared = np.nan if ss_tot == 0 else 1 - ss_res / ss_tot

    height = float(np.nanmax(pseudo_voigt(np.asarray([center]), area, center, fwhm, eta)))
    return {
        "center": float(center),
        "height": height,
        "fwhm": float(fwhm),
        "area": float(area),
        "eta": float(eta),
        "offset": float(offset),
        "r_squared": r_squared,
        "x_fit": x_fit,
        "y_fit": y_fit,
        "y_corrected": y_fit - offset,
        "best_fit": fitted,
        "best_fit_corrected": fitted_corrected,
        "covariance": pcov,
        "center_bounds": (float(center_min), float(center_max)),
    }


def _tracking_fit_region(x, y, peaks, candidate, fit_window, xmin, xmax, noise):
    """Isolate a resolved peak at neighboring valleys; return an ambiguity reason."""
    left = max(xmin, x[candidate] - fit_window)
    right = min(xmax, x[candidate] + fit_window)
    region = y[(x >= left) & (x <= right)]
    floor = float(np.min(region))
    before, after = peaks[peaks < candidate], peaks[peaks > candidate]
    neighbors = ([before[-1]] if len(before) else []) + ([after[0]] if len(after) else [])
    for neighbor in neighbors:
        if not left < x[neighbor] < right:
            continue
        low, high = sorted((candidate, int(neighbor)))
        valley = low + int(np.argmin(y[low:high+1]))
        weaker_height = min(y[candidate], y[neighbor]) - floor
        valley_drop = min(y[candidate], y[neighbor]) - y[valley]
        # A shallow saddle is unresolved, whereas a clear valley isolates peaks
        # even when both lie inside the original fitting window.
        if high-low < 4 or valley in (low, high) or valley_drop < max(3*noise, 0.2*weaker_height):
            return None, f"Unresolved overlap with neighbor at {x[neighbor]:.6g}: shallow inter-peak minimum"
        if neighbor < candidate:
            left = float(x[valley])
        else:
            right = float(x[valley])
    if np.count_nonzero((x >= left) & (x < x[candidate])) < 2 or np.count_nonzero((x > x[candidate]) & (x <= right)) < 2:
        return None, "Unresolved overlap or insufficient samples on both sides of target"
    return (left, right), ""


def track_peak_files(files, initial_center, max_shift, xmin, xmax, fit_window=0.3,
                     fwhm_guess=0.05, baseline_method="arpls", skiprows=0,
                     prominence=None, min_r_squared=0.9, start_file=None):
    """Rebuild a conservative single-peak track, retaining only reliable fit state.

    max_shift is measured from the last accepted center and never grows over gaps.
    Ambiguity after an accepted fit latches until explicit reselection. Before
    initialization, each scan is evaluated independently against initial_center.
    Automatic prominence is max(5 * robust noise, 1% signal range).
    """
    require_baseline(baseline_method)
    settings = [initial_center, max_shift, xmin, xmax, fit_window, fwhm_guess, min_r_squared]
    if not np.all(np.isfinite(settings)) or not xmin < initial_center < xmax:
        raise ValueError("Initial center must be inside a finite peak range.")
    if min(max_shift, fit_window, fwhm_guess) <= 0 or not 0 <= min_r_squared <= 1:
        raise ValueError("Shift, fit window and width must be positive; minimum R² must be in [0, 1].")
    if prominence is not None and (not np.isfinite(prominence) or prominence <= 0):
        raise ValueError("Prominence must be positive, or blank for automatic detection.")
    files = ordered_files(files)
    if start_file is not None:
        start_file = str(Path(start_file).resolve())
        if start_file not in [str(Path(file).resolve()) for file in files]:
            raise ValueError("The selected starting scan is not in the active file list.")
    started = start_file is None
    last_fit = None
    center, width = float(initial_center), float(fwhm_guess)
    gap = False
    needs_reselection = False
    pause_reason = ""
    rows = []
    for filename, scan in zip(files, scan_axis_values(files)):
        row = dict(sequence=scan, file=str(filename), center=np.nan, height=np.nan,
                   area=np.nan, fwhm=np.nan, r_squared=np.nan, status="not detected", detail="")
        rows.append(row)
        if not started:
            started = str(Path(filename).resolve()) == start_file
            if not started:
                row["detail"] = "Before selected starting scan"
                continue
        if needs_reselection:
            row.update(status="tracking paused", detail=f"User reselection required after {pause_reason}")
            continue
        try:
            x, y = loadxy(filename, skiprows=skiprows, xmin=xmin, xmax=xmax)
            if len(x) < 5:
                raise ValueError("Not enough points in the peak range")
            y, _ = baseline_correct_signal(x, y, method=baseline_method)
            step = float(np.median(np.diff(x)))
            noise = float(np.median(np.abs(np.diff(y, n=2) - np.median(np.diff(y, n=2)))) / (0.6745*np.sqrt(6)))
            threshold = prominence if prominence is not None else max(5*noise, 0.01*np.ptp(y), np.finfo(float).eps)
            peaks, _ = find_peaks(y, prominence=threshold)
            candidates = peaks[np.abs(x[peaks] - center) <= max_shift]
            if len(candidates) == 0:
                row["detail"] = "No significant local maximum within maximum center shift"
                gap = True
                continue
            candidates = candidates[np.argsort(np.abs(x[candidates]-center), kind="stable")]
            candidate = int(candidates[0])
            if len(candidates) > 1:
                nearest, runner_up = np.abs(x[candidates[:2]]-center)
                separation = abs(x[candidates[1]]-x[candidate])
                if runner_up-nearest <= max(step, 0.25*separation):
                    row.update(status="overlap/ambiguous", detail="Candidates are similarly close to target center; reselect target")
                    needs_reselection = last_fit is not None
                    pause_reason = f"{Path(filename).name}: {row['detail']}"
                    continue
            candidate_center = float(x[candidate])
            fit_bounds, overlap_reason = _tracking_fit_region(
                x, y, peaks, candidate, fit_window, xmin, xmax, noise)
            if fit_bounds is None:
                row.update(status="overlap/ambiguous", detail=overlap_reason)
                needs_reselection = last_fit is not None
                pause_reason = f"{Path(filename).name}: {row['detail']}"
                continue
            recovery_radius = min(max_shift/2, width/2)
            recovering = gap and last_fit is not None
            if recovering and abs(candidate_center - center) > recovery_radius:
                row.update(status="overlap/ambiguous", detail="Returning candidate cannot be matched confidently; reselect target")
                needs_reselection = True
                pause_reason = f"{Path(filename).name}: {row['detail']}"
                continue
            bounds = (max(fit_bounds[0], center-max_shift), min(fit_bounds[1], center+max_shift))
            if x[0] > fit_bounds[0] + step or x[-1] < fit_bounds[1] - step:
                raise ValueError("Insufficient coverage of peak fitting window")
            fit = fit_pseudo_voigt_peak(
                x, y, candidate, window=fit_window, fwhm_guess=width,
                center_bounds=bounds, fit_bounds=fit_bounds, initial_fit=last_fit)
            numeric = [fit[key] for key in ("center", "height", "area", "fwhm", "r_squared")]
            if not np.all(np.isfinite(numeric)) or min(fit["height"], fit["area"], fit["fwhm"]) <= 0:
                raise ValueError("Nonfinite or nonpositive fitted peak")
            if fit["r_squared"] < min_r_squared:
                raise ValueError(f"Unreliable fit: R²={fit['r_squared']:.3g} below {min_r_squared:g}")
            boundary_margin = max(step/2, max_shift*0.01)
            if min(fit["center"]-bounds[0], bounds[1]-fit["center"]) <= boundary_margin:
                row.update(status="overlap/ambiguous", detail="Fit reached center constraint; reselect target")
                needs_reselection = last_fit is not None
                pause_reason = f"{Path(filename).name}: {row['detail']}"
                continue
            ratio = fit["fwhm"] / width
            width_limit = 1.5 if recovering else 2.0
            if last_fit is not None and (not 1/width_limit <= ratio <= width_limit or
                                        (recovering and abs(fit["center"]-center) > recovery_radius)):
                row.update(status="overlap/ambiguous", detail="Width/center change suggests merging or ambiguous recovery; reselect target")
                needs_reselection = True
                pause_reason = f"{Path(filename).name}: {row['detail']}"
                continue
            row.update({key: fit[key] for key in ("center", "height", "area", "fwhm", "r_squared")})
            row.update(status="detected", detail="Confident recovery" if recovering else "")
            last_fit = fit
            center, width = fit["center"], fit["fwhm"]
            gap = False
        except Exception as exc:
            row.update(status="fit failed", detail=str(exc))
            gap = True
    return pd.DataFrame(rows, columns=["sequence", "file", "center", "height", "area", "fwhm", "r_squared", "status", "detail"])


def inspect_tracked_peak(files, selected_file, **tracking_options):
    """Rebuild tracking through one file and return its decision plus plot diagnostics.

    The reported status is produced by :func:`track_peak_files`, so inspection
    follows the same ordering, continuity gates, and reselection behavior.
    """
    files = ordered_files(files)
    target = str(Path(selected_file).resolve())
    resolved = [str(Path(item).resolve()) for item in files]
    if target not in resolved:
        raise ValueError("The selected scan is not in the active file list.")
    index = resolved.index(target)
    results = track_peak_files(files[:index + 1], **tracking_options)
    row = results.iloc[-1].to_dict()
    x, raw = loadxy(target, skiprows=tracking_options.get("skiprows", 0),
                    xmin=tracking_options["xmin"], xmax=tracking_options["xmax"])
    corrected, baseline = baseline_correct_signal(
        x, raw, method=tracking_options.get("baseline_method", "arpls"))
    noise = float(np.median(np.abs(np.diff(corrected, n=2) - np.median(np.diff(corrected, n=2)))) /
                  (0.6745 * np.sqrt(6)))
    prominence = tracking_options.get("prominence")
    threshold = prominence if prominence is not None else max(5 * noise, .01 * np.ptp(corrected), np.finfo(float).eps)
    peaks, _ = find_peaks(corrected, prominence=threshold)
    previous = results.iloc[:-1]
    accepted = previous[previous.status == "detected"]
    predicted = (float(accepted.iloc[-1].center) if not accepted.empty
                 else float(tracking_options["initial_center"]))
    candidates = peaks[np.abs(x[peaks] - predicted) <= tracking_options["max_shift"]]
    fit = None
    if row["status"] == "detected" and len(candidates):
        candidate = int(candidates[np.argmin(np.abs(x[candidates] - row["center"]))])
        bounds, _ = _tracking_fit_region(x, corrected, peaks, candidate,
                                         tracking_options["fit_window"],
                                         tracking_options["xmin"], tracking_options["xmax"], noise)
        if bounds is not None:
            fit = fit_pseudo_voigt_peak(
                x, corrected, candidate, window=tracking_options["fit_window"],
                fwhm_guess=tracking_options["fwhm_guess"], fit_bounds=bounds,
                center_bounds=(max(bounds[0], predicted - tracking_options["max_shift"]),
                               min(bounds[1], predicted + tracking_options["max_shift"])))
    return {"result": row, "results": results, "x": x, "raw": raw,
            "baseline": baseline, "corrected": corrected, "peaks": peaks,
            "candidates": candidates, "predicted_center": predicted,
            "center_gate": (predicted - tracking_options["max_shift"], predicted + tracking_options["max_shift"]),
            "fit_window": tracking_options["fit_window"], "fit": fit}


class SimilarityConfiguration:
    """A fixed reference identity and interpolation grid; signals are reloaded each run."""

    def __init__(self, reference_file, xmin, xmax, skiprows=0):
        if not np.isfinite([xmin, xmax]).all() or xmax <= xmin:
            raise ValueError("Similarity xmax must be greater than finite xmin.")
        self.reference_file = str(Path(reference_file).resolve())
        self.xmin, self.xmax, self.skiprows = float(xmin), float(xmax), int(skiprows)
        x, _ = loadxy(self.reference_file, skiprows=self.skiprows)
        if len(x) < 2:
            raise ValueError("Reference needs at least two x samples to establish a grid.")
        # Include exact requested endpoints so coverage is never silently narrowed.
        self.grid = np.unique(np.r_[xmin, x[(x > xmin) & (x < xmax)], xmax])
        if len(self.grid) < 5:
            raise ValueError("Reference needs at least five comparison grid points in the requested range.")
        self.grid.setflags(write=False)

    def _normalized(self, filename):
        try:
            x, y = loadxy(filename, skiprows=self.skiprows)
            if x[0] > self.xmin or x[-1] < self.xmax:
                return None, "insufficient coverage"
            signal = np.interp(self.grid, x, y)
            centered = signal - np.mean(signal)
            scale = np.linalg.norm(centered)
            if not np.isfinite(scale) or scale <= np.finfo(float).eps * max(1, np.linalg.norm(signal)) * 10:
                return None, "constant pattern"
            return centered / scale, "available"
        except Exception as exc:
            return None, f"load failed: {exc}"

    def compare(self, files):
        """Recalculate all rows; unavailable scans invalidate only affected comparisons."""
        files = ordered_files(files)
        reference, reference_status = self._normalized(self.reference_file)
        rows = []
        previous, previous_status, previous_scan = None, "no previous scan", None
        for filename, scan in zip(files, scan_axis_values(files)):
            signal, status = self._normalized(filename)
            fixed = consecutive = np.nan
            fixed_status = status if status != "available" else f"reference: {reference_status}"
            consecutive_status = status if status != "available" else f"previous: {previous_status}"
            if signal is not None and reference is not None:
                fixed = float(np.clip(np.dot(signal, reference), -1, 1))
                if str(Path(filename).resolve()) == self.reference_file:
                    fixed = 1.0
                fixed_status = "available"
            if signal is not None and previous is not None:
                consecutive = float(np.clip(np.dot(previous, signal), -1, 1))
                consecutive_status = "available"
            rows.append(dict(sequence=scan, file=str(filename), fixed_reference=fixed,
                             consecutive=consecutive,
                             pair_midpoint=np.nan if previous_scan is None else (previous_scan+scan)/2,
                             fixed_status=fixed_status, consecutive_status=consecutive_status))
            previous, previous_status, previous_scan = signal, status, scan
        return pd.DataFrame(rows)


def _peak_center_bounds(x, peak_indices, peak_list_index, fit_window):
    center_guess = float(x[peak_indices[peak_list_index]])
    center_min = center_guess - fit_window
    center_max = center_guess + fit_window
    if peak_list_index > 0:
        prev_center = float(x[peak_indices[peak_list_index - 1]])
        center_min = max(center_min, 0.5 * (prev_center + center_guess))
    if peak_list_index < len(peak_indices) - 1:
        next_center = float(x[peak_indices[peak_list_index + 1]])
        center_max = min(center_max, 0.5 * (center_guess + next_center))
    return center_min, center_max


def analyze_peaks(
    xyfile,
    xmin=None,
    xmax=None,
    height=None,
    prominence=None,
    distance=None,
    fit_window=0.3,
    fwhm_guess=0.05,
    eta_guess=0.5,
    baseline_method="arpls",
    lam_stiff=5e5,
    plot=False,
):
    """Find and fit all peaks in one pattern; return the standard result table."""
    x, y = loadxy(xyfile, xmin=xmin, xmax=xmax)
    y_for_peaks, _ = baseline_correct_signal(x, y, method=baseline_method, lam=lam_stiff)
    peak_indices, _ = find_xrd_peaks(
        x,
        y_for_peaks,
        height=height,
        prominence=prominence,
        distance=distance,
    )

    rows = []
    sequence = scan_axis_values([xyfile])[0]
    for peak_list_index, peak_index in enumerate(peak_indices):
        peak_number = peak_list_index + 1
        row = {
            "sequence": sequence,
            "file": Path(xyfile).name,
            "peak_number": peak_number,
            "peak_x_guess": float(x[peak_index]),
            "center": np.nan,
            "height": np.nan,
            "fwhm": np.nan,
            "area": np.nan,
            "eta": np.nan,
            "r_squared": np.nan,
            "status": "ok",
        }
        try:
            fit = fit_pseudo_voigt_peak(
                x,
                y_for_peaks,
                peak_index,
                window=fit_window,
                fwhm_guess=fwhm_guess,
                eta_guess=eta_guess,
                center_bounds=_peak_center_bounds(x, peak_indices, peak_list_index, fit_window),
            )
            row.update(
                {
                    "center": fit["center"],
                    "height": fit["height"],
                    "fwhm": fit["fwhm"],
                    "area": fit["area"],
                    "eta": fit["eta"],
                    "r_squared": fit["r_squared"],
                }
            )
        except Exception as exc:
            row["status"] = f"fit_failed: {exc}"
        rows.append(row)

    result = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    if plot:
        plot_peak_fits(x, y_for_peaks, peak_indices, result, xyfile)
    return result


def analyze_peak_files(path_or_files, search_item="*", output_dir=None, save_name="peak_fit_results.xlsx", **kwargs):
    """Analyze a sequence-sorted series and export one peak per Excel worksheet."""
    require_baseline(kwargs.get("baseline_method", "arpls"))
    filenames = as_file_list(path_or_files, search_item)
    if not filenames:
        raise FileNotFoundError("No CHI/XY files found for peak analysis.")

    output_dir = Path(output_dir) if output_dir else Path(filenames[0]).parent / "peak_results"
    output_dir.mkdir(parents=True, exist_ok=True)

    tables = []
    for filename, sequence in zip(filenames, scan_axis_values(filenames)):
        try:
            table = analyze_peaks(filename, **kwargs)
            table["sequence"] = sequence
            tables.append(table)
        except Exception as exc:
            tables.append(
                pd.DataFrame(
                    [
                        {
                            "sequence": sequence,
                            "file": Path(filename).name,
                            "peak_number": np.nan,
                            "peak_x_guess": np.nan,
                            "center": np.nan,
                            "height": np.nan,
                            "fwhm": np.nan,
                            "area": np.nan,
                            "eta": np.nan,
                            "r_squared": np.nan,
                            "status": f"file_failed: {exc}",
                        }
                    ],
                    columns=RESULT_COLUMNS,
                )
            )

    results = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame(columns=RESULT_COLUMNS)
    if not results.empty and "sequence" in results:
        results = results.sort_values(["peak_number", "sequence"], na_position="last").reset_index(drop=True)

    save_path = output_dir / save_name
    export_peak_results(results, save_path)
    return results, str(save_path)


def inspect_peak_fit(
    xyfile,
    peak_number,
    xmin=None,
    xmax=None,
    height=None,
    prominence=None,
    distance=None,
    fit_window=0.3,
    fwhm_guess=0.05,
    eta_guess=0.5,
    baseline_method="arpls",
    lam_stiff=5e5,
):
    """Plot and return the Pseudo-Voigt fit for one selected peak number."""
    x, y = loadxy(xyfile, xmin=xmin, xmax=xmax)
    y_for_peaks, y_baseline = baseline_correct_signal(x, y, method=baseline_method, lam=lam_stiff)
    peak_indices, _ = find_xrd_peaks(
        x,
        y_for_peaks,
        height=height,
        prominence=prominence,
        distance=distance,
    )

    if peak_number < 1 or peak_number > len(peak_indices):
        raise ValueError(f"peak_number must be between 1 and {len(peak_indices)}")

    peak_list_index = peak_number - 1
    peak_index = peak_indices[peak_list_index]
    center_guess = float(x[peak_index])
    fit = fit_pseudo_voigt_peak(
        x,
        y_for_peaks,
        peak_index,
        window=fit_window,
        fwhm_guess=fwhm_guess,
        eta_guess=eta_guess,
        center_bounds=_peak_center_bounds(x, peak_indices, peak_list_index, fit_window),
    )

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(fit["x_fit"], fit["y_corrected"], "o", ms=4, label="peak data")
    ax.plot(fit["x_fit"], fit["best_fit_corrected"], "-", lw=2, label="Pseudo-Voigt fit")
    ax.axvline(center_guess, color="tab:red", linestyle=":", linewidth=1, label="detected peak")
    ax.axvline(fit["center"], color="black", linestyle="--", linewidth=1, label="refined center")
    ax.set_title(
        f"{Path(xyfile).name} | peak {peak_number} | Pseudo-Voigt fit\n"
        f"center={fit['center']:.6f}, FWHM={fit['fwhm']:.6f}, "
        f"eta={fit['eta']:.3f}, R^2={fit['r_squared']:.6f}"
    )
    ax.set_xlabel("2Theta (deg)")
    ax.set_ylabel("Corrected intensity")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    plt.show()

    return {
        "file": str(xyfile),
        "peak_number": peak_number,
        "peak_x_guess": center_guess,
        "fit": fit,
        "peak_indices": peak_indices,
        "x": x,
        "y": y,
        "y_corrected_full": y_for_peaks,
        "baseline": y_baseline,
    }


def build_intensity_map(path_or_files, search_item="*", xmin=None, xmax=None,
                        skiprows=0, usecols=(0, 1)):
    """Load a sequence-sorted intensity matrix, interpolating compatible x grids."""
    filenames = as_file_list(path_or_files, search_item)
    if not filenames:
        raise FileNotFoundError(f"No files found for {path_or_files!r} with {search_item!r}")

    data_list = []
    x_ref = None
    for filename in filenames:
        # Keep samples outside the display range for interpolation at its edges.
        x, y = loadxy(filename, skiprows=skiprows, usecols=usecols)
        left = x[0] if xmin is None else float(xmin)
        right = x[-1] if xmax is None else float(xmax)
        if right <= left:
            raise ValueError("xmax must be greater than xmin.")
        if x[0] > left or x[-1] < right:
            raise ValueError(f"Insufficient coverage in {filename}: requested {left:g} to {right:g}, "
                             f"available {x[0]:g} to {x[-1]:g}.")
        if x_ref is None:
            x_ref = x[(x >= left) & (x <= right)]
            if len(x_ref) < 2:
                raise ValueError(f"Not enough common x points in {filename}.")
        if x[0] > x_ref[0] or x[-1] < x_ref[-1]:
            raise ValueError(f"Insufficient coverage of common x grid in {filename}.")
        data_list.append(np.interp(x_ref, x, y))
    return x_ref, scan_axis_values(filenames), np.asarray(data_list)


def plot_intensity_map(path_or_files, search_item="*", xmin=None, xmax=None, norm_vmin=None, norm_vmax=None):
    """Plot a LogNorm 2D XRD intensity map with sequence number on the y-axis."""
    from matplotlib.colors import LogNorm

    x, sequences, data_array = build_intensity_map(path_or_files, search_item, xmin=xmin, xmax=xmax)
    positive = data_array[np.isfinite(data_array) & (data_array > 0)]
    if len(positive) == 0:
        raise ValueError("LogNorm intensity map requires positive intensity values.")
    vmin = norm_vmin if norm_vmin is not None else float(np.nanmin(positive))
    vmax = norm_vmax if norm_vmax is not None else float(np.nanmax(data_array))

    fig, ax = plt.subplots(figsize=(12, 6))
    y_step = float(np.median(np.diff(sequences))) if len(sequences) > 1 else 1.0
    extent = [float(x[0]), float(x[-1]), float(sequences[0] - y_step / 2), float(sequences[-1] + y_step / 2)]
    im = ax.imshow(
        data_array,
        aspect="auto",
        extent=extent,
        origin="lower",
        cmap="viridis",
        norm=LogNorm(vmin=vmin, vmax=vmax),
    )
    fig.colorbar(im, ax=ax, label="Intensity (Log scale)")
    ax.set_xlabel("2Theta (deg)")
    ax.set_ylabel("Sequence number")
    ax.set_title("XRD Intensity Map")
    fig.tight_layout()
    plt.show()
    return fig, ax


def export_peak_results(results, filename):
    """Write results to Excel with one worksheet per peak number, or CSV if requested."""
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    results = results.reindex(columns=RESULT_COLUMNS)

    if filename.suffix.lower() not in {".xlsx", ".xls"}:
        results.to_csv(filename, index=False)
        return str(filename)

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        for peak_number in sorted(results["peak_number"].dropna().astype(int).unique()):
            sheet = f"Peak_{peak_number}"[:31]
            peak_rows = results[results["peak_number"] == peak_number].sort_values("sequence")
            peak_rows.to_excel(writer, sheet_name=sheet, index=False)
        results.sort_values(["peak_number", "sequence"], na_position="last").to_excel(
            writer,
            sheet_name="All_Peaks",
            index=False,
        )
    return str(filename)


def plot_peak_fits(x, y, peak_indices, result_table, title=None):
    """Quick plot of the pattern with detected and fitted peak centers."""
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(x, y, linewidth=1)
    if len(peak_indices):
        ax.scatter(x[peak_indices], y[peak_indices], s=24, color="tab:red", label="found peaks")
    if not result_table.empty:
        for center in result_table["center"].dropna():
            ax.axvline(center, color="black", linestyle=":", linewidth=1)
    ax.set_title(Path(title).name if title else "Peak fit")
    ax.set_xlabel("2Theta (deg)")
    ax.set_ylabel("Corrected intensity")
    ax.legend(loc="best")
    fig.tight_layout()
    plt.show()
    return fig, ax
