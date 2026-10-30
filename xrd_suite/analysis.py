"""Independent curve snapshots and fitting. No GUI or temporal tracking state."""
from dataclasses import dataclass, asdict, field, replace
from pathlib import Path
import csv
import json
import uuid
import warnings
import numpy as np
from scipy.optimize import OptimizeWarning
from scipy.signal import find_peaks
from .peaks import baseline_correct_signal, fit_pseudo_voigt_peak

UNITS = ('2th_deg', 'q_A^-1', 'unknown')

def canonical_unit(value):
    aliases = {'2theta':'2th_deg', 'tth':'2th_deg', '2theta_deg':'2th_deg',
               'q':'q_A^-1', 'q_A-1':'q_A^-1'}
    value = aliases.get(value, value)
    return value if value in UNITS else 'unknown'

def immutable_array(values):
    a = np.asarray(values, dtype=float)
    if a.ndim != 1:
        raise ValueError('Curves must have one-dimensional coordinates and intensities.')
    # Bytes backing prevents callers from turning the write flag back on.
    return np.frombuffer(a.tobytes(), dtype=float)

@dataclass(frozen=True)
class Snapshot:
    id: str
    x: np.ndarray
    intensity: np.ndarray
    sigma: np.ndarray | None
    metadata_json: str

    @property
    def metadata(self):
        return json.loads(self.metadata_json)

    @property
    def unit(self):
        return canonical_unit(self.metadata.get('unit'))

    @classmethod
    def capture(cls, curve):
        x, y = immutable_array(curve.x), immutable_array(curve.intensity)
        sigma = None if curve.sigma is None else immutable_array(curve.sigma)
        if len(x) != len(y) or (sigma is not None and len(sigma) != len(x)):
            raise ValueError('Curve array lengths differ.')
        metadata = json.loads(json.dumps(curve.metadata, default=str))
        metadata['unit'] = canonical_unit(metadata.get('unit', metadata.get('settings', {}).get('unit')))
        return cls(uuid.uuid4().hex, x, y, sigma, json.dumps(metadata))

@dataclass
class Entry:
    snapshot: Snapshot
    label: str
    visible: bool = True
    fit: object = None

class Collection:
    def __init__(self):
        self.entries = {}
        self.serial = 0

    def add(self, curves):
        snapshots = [Snapshot.capture(c) for c in curves]
        added = []
        for snap in snapshots:
            self.serial += 1
            meta = snap.metadata
            source = Path(meta.get('source', 'Curve')).name
            method = meta.get('method_1d', 'imported')
            selection = meta.get('selection', '')
            short = source if len(source) <= 38 else source[:22] + '...' + source[-12:]
            label = f'#{self.serial} {method} {selection} | {short}'
            self.entries[snap.id] = Entry(snap, label)
            added.append(snap.id)
        return added

    def assign_unit(self, ids, unit):
        if unit not in UNITS[:2]:
            raise ValueError('Assign q in inverse angstroms or 2theta in degrees.')
        for key in ids:
            if self.entries[key].snapshot.unit != 'unknown':
                raise ValueError('Only unknown units can be assigned; no unit conversion is performed.')
        for key in ids:
            entry = self.entries[key]
            meta = entry.snapshot.metadata
            meta.update(unit=unit, unit_assignment='explicit user assignment; coordinates unchanged')
            entry.snapshot = replace(entry.snapshot, metadata_json=json.dumps(meta))
            entry.fit = None

    def remove(self, ids):
        for key in ids:
            self.entries.pop(key, None)

    def invalidate_fits(self):
        for entry in self.entries.values():
            entry.fit = None

    def selected_snapshots(self, ids):
        snapshots = [self.entries[key].snapshot for key in ids]
        if not snapshots:
            raise ValueError('Select at least one curve.')
        units = {snap.unit for snap in snapshots}
        if 'unknown' in units:
            raise ValueError('Assign units before fitting unknown-unit curves.')
        if len(units) != 1:
            raise ValueError('Select curves in the same units. No implicit conversion is performed.')
        return snapshots

def import_curve(path):
    from .io import read_curve
    curve = read_curve(path)
    # Preserve source recorded by a sidecar and the imported file identity.
    curve.metadata['import_path'] = str(Path(path).resolve())
    unit = canonical_unit(curve.metadata.get('unit'))
    if unit == 'unknown':
        unit = canonical_unit(curve.metadata.get('settings', {}).get('unit'))
    if unit == 'unknown' and Path(path).suffix.lower() == '.chi':
        lines = Path(path).read_text(encoding='utf-8-sig').splitlines()
        if len(lines) >= 2:
            unit = canonical_unit(lines[1].strip())
    curve.metadata['unit'] = unit
    return curve

def display_values(snapshot, normalization='none', offset=0.):
    """Return new display values; original intensities/uncertainties stay immutable."""
    if normalization not in ('none', 'max absolute') or not np.isfinite(offset):
        raise ValueError('Invalid display normalization or offset.')
    y = snapshot.intensity.copy()
    finite = np.isfinite(y)
    scale = float(np.max(np.abs(y[finite]))) if normalization != 'none' and finite.any() else 1.
    if scale == 0:
        scale = 1.
    return y / scale + offset, scale

@dataclass(frozen=True)
class FitSettings:
    xmin: float
    xmax: float
    baseline: str = 'none'
    lam: float = 5e5
    fwhm_guess: float = .05
    eta_guess: float = .5
    min_r_squared: float = .9
    baseline_domain: str = 'entire finite curve before fitting region'
    model: str = 'area-normalized pseudo-Voigt plus constant offset; unweighted'

    def validate(self):
        if not np.isfinite([self.xmin, self.xmax, self.lam, self.fwhm_guess, self.eta_guess, self.min_r_squared]).all():
            raise ValueError('Fit settings must be finite.')
        if self.xmin >= self.xmax or self.lam <= 0 or self.fwhm_guess <= 0:
            raise ValueError('Fit minimum must be below maximum; lambda and width must be positive.')
        if self.baseline not in ('none', 'arpls', 'asls') or not 0 <= self.eta_guess <= 1 or not 0 <= self.min_r_squared <= 1:
            raise ValueError('Invalid baseline, eta, or minimum R squared.')
        return self

@dataclass
class FitResult:
    snapshot_id: str
    settings: FitSettings
    status: str
    detail: str = ''
    parameters: dict = field(default_factory=dict)
    x: np.ndarray | None = None
    observed: np.ndarray | None = None
    best_fit: np.ndarray | None = None
    residual: np.ndarray | None = None

def fit_snapshot(snapshot, settings):
    """Apply a common region independently; never seed a fit from another curve."""
    settings.validate()
    result = FitResult(snapshot.id, settings, 'failed')
    try:
        if snapshot.unit == 'unknown':
            raise ValueError('Assign units before fitting.')
        x, y = snapshot.x, snapshot.intensity
        good = np.isfinite(x) & np.isfinite(y)
        bad = np.asarray(snapshot.metadata.get('invalid_bins', []), dtype=int)
        if bad.size:
            if (bad < 0).any() or (bad >= len(x)).any():
                raise ValueError('Invalid bin metadata is outside the curve grid.')
            good[bad] = False
        x, y = x[good], y[good]
        if len(x) < 7 or not np.all(np.diff(x) > 0):
            raise ValueError('Need at least seven finite points on a strictly increasing grid.')
        corrected, baseline = baseline_correct_signal(x, y, method=settings.baseline, lam=settings.lam)
        keep = (x >= settings.xmin) & (x <= settings.xmax)
        xr, yr = x[keep], corrected[keep]
        if len(xr) < 7:
            raise ValueError('Fitting region contains fewer than seven finite points.')
        noise = np.median(np.abs(np.diff(yr, n=2) - np.median(np.diff(yr, n=2)))) / (0.6745*np.sqrt(6))
        threshold = max(5*noise, .01*np.ptp(yr), np.finfo(float).eps)
        peaks, _ = find_peaks(yr, prominence=threshold)
        if len(peaks) != 1:
            result.status = 'ambiguous' if len(peaks) > 1 else 'failed'
            result.detail = f'{len(peaks)} significant peaks in region; choose a region containing one resolved peak.'
            return result
        peak = int(peaks[0])
        if peak < 2 or peak > len(xr)-3:
            raise ValueError('Insufficient samples on both sides of peak.')
        with warnings.catch_warnings():
            warnings.simplefilter('error', OptimizeWarning)
            fitted = fit_pseudo_voigt_peak(xr, yr, peak,
                window=settings.xmax-settings.xmin,
                fwhm_guess=settings.fwhm_guess, eta_guess=settings.eta_guess,
                center_bounds=(settings.xmin, settings.xmax),
                fit_bounds=(settings.xmin, settings.xmax))
        keys = ('center', 'fwhm', 'area', 'eta', 'height', 'offset', 'r_squared')
        values = [fitted[k] for k in keys]
        step = float(np.median(np.diff(xr)))
        if (not np.isfinite(values).all() or not np.isfinite(fitted['covariance']).all()
                or fitted['r_squared'] < settings.min_r_squared
                or fitted['fwhm'] >= settings.xmax-settings.xmin
                or fitted['fwhm'] <= step*.501
                or min(fitted['center']-settings.xmin, settings.xmax-fitted['center']) <= step):
            result.status, result.detail = 'ambiguous', 'Poorly resolved or low-quality single-peak fit; narrow/review region.'
            return result
        result.status = 'ok'
        result.parameters = {k: float(fitted[k]) for k in keys}
        result.x = xr.copy()
        result.observed = y[keep].copy()
        result.best_fit = fitted['best_fit'] + baseline[keep]
        result.residual = result.observed - result.best_fit
    except Exception as exc:
        result.detail = str(exc)
    return result

def export_fits(path, entries):
    fields = ['id','label','source','unit','status','detail','center','fwhm','area','eta','height','offset','r_squared','fit_settings','metadata']
    with Path(path).open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for entry in entries:
            snap, fit = entry.snapshot, entry.fit
            row = dict(id=snap.id, label=entry.label, source=snap.metadata.get('source',''), unit=snap.unit,
                       status=fit.status if fit else 'not fitted', detail=fit.detail if fit else '', metadata=snap.metadata_json)
            if fit:
                row.update(fit.parameters, fit_settings=json.dumps(asdict(fit.settings)))
            writer.writerow(row)
