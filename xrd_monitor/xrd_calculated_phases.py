"""Optional CIF powder-reference calculations; measured-data analysis never depends on this module."""
from dataclasses import dataclass, field
from pathlib import Path
import math

import numpy as np

try:
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    from pymatgen.core import Structure
    PYMATGEN_AVAILABLE = True
except ImportError:
    XRDCalculator = Structure = None
    PYMATGEN_AVAILABLE = False


@dataclass
class CalculatedPhase:
    phase_id: int
    name: str
    filename: str
    color: str
    enabled: bool = True
    _raw_cache: dict = field(default_factory=dict, repr=False)


_STRUCTURE_CACHE = {}


def _hkl_label(families):
    labels = []
    for family in families or []:
        hkl = family.get("hkl", family) if isinstance(family, dict) else family
        labels.append("(" + " ".join(str(int(value)) for value in hkl) + ")")
    return ", ".join(dict.fromkeys(labels))


def tth_range_for_display(dtype, xmin, xmax, wavelength, margin=.05):
    """Convert a visible x range to an XRDCalculator 2theta range."""
    if dtype == "q":
        values = []
        for q in (xmin, xmax):
            argument = float(q) * float(wavelength) / (4 * np.pi)
            if not 0 <= argument <= 1:
                raise ValueError("Requested q range and wavelength are physically invalid for 2theta conversion.")
            values.append(np.degrees(2 * np.arcsin(argument)))
        xmin, xmax = values
    return max(0., float(xmin) - margin), float(xmax) + margin


def _structure(path):
    signature = (str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size)
    if signature not in _STRUCTURE_CACHE:
        _STRUCTURE_CACHE.clear()
        _STRUCTURE_CACHE[signature] = Structure.from_file(path)
    return signature, _STRUCTURE_CACHE[signature]


def calculate_reflections(phase, wavelength, minimum_intensity, *, dtype="tth", xmin=0, xmax=180):
    """Return one metadata record per calculated reflection position.

    Positions remain based on pymatgen's pattern x values, while q consumers must
    use the retained d-spacing. Equivalent HKL families at equal positions are
    combined before filtering/display.
    """
    if not PYMATGEN_AVAILABLE:
        raise ImportError("Calculated reflections require pymatgen (python -m pip install pymatgen).")
    wavelength = float(wavelength)
    minimum_intensity = float(minimum_intensity)
    if not math.isfinite(wavelength) or wavelength <= 0:
        raise ValueError("Wavelength must be finite and positive.")
    if not math.isfinite(minimum_intensity) or minimum_intensity < 0:
        raise ValueError("Minimum relative intensity must be finite and nonnegative.")
    path = Path(phase.filename)
    requested = tth_range_for_display(dtype, xmin, xmax, wavelength)
    structure_signature, structure = _structure(path)
    reusable = next(((covered, rows) for (signature, wave, covered), rows in phase._raw_cache.items()
                     if signature == structure_signature and wave == wavelength and covered[0] <= requested[0] and covered[1] >= requested[1]), None)
    if reusable is None:
        pattern = XRDCalculator(wavelength=wavelength).get_pattern(structure, two_theta_range=requested)
        raw = zip(pattern.x, pattern.y, pattern.d_hkls, pattern.hkls)
    else:
        raw = ((row["tth"], row["intensity"], row["d"], row["families"]) for row in reusable[1])
    merged = []
    for tth, intensity, spacing, families in raw:
        if merged and np.isclose(tth, merged[-1]["tth"], rtol=0, atol=1e-7):
            merged[-1]["families"].extend(families or [])
            merged[-1]["intensity"] = max(merged[-1]["intensity"], float(intensity))
        else:
            merged.append(dict(tth=float(tth), d=float(spacing), intensity=float(intensity), families=list(families or [])))
    result = [dict(tth=item["tth"], d=item["d"], intensity=item["intensity"],
                   hkl=_hkl_label(item["families"])) for item in merged]
    if reusable is None:
        phase._raw_cache.clear()
        phase._raw_cache[(structure_signature, wavelength, requested)] = [dict(tth=item["tth"], d=item["d"], intensity=item["intensity"], families=item["families"]) for item in merged]
    positions = positions_for_dtype(result, dtype)
    return [reflection for reflection, position in zip(result, positions) if xmin <= position <= xmax and reflection["intensity"] >= minimum_intensity]


def positions_for_dtype(reflections, dtype):
    """Use d-spacing directly for q rather than a rounded 2theta conversion."""
    if dtype == "q":
        return [2 * np.pi / reflection["d"] for reflection in reflections]
    return [reflection["tth"] for reflection in reflections]
