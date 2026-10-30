"""Unweighted Monitor numerical routines, extracted verbatim; no tracking state."""
import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import find_peaks
try:
    from pybaselines import Baseline
except ImportError:
    Baseline = None

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
