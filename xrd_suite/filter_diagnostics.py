"""Immutable, result-owned detector diagnostics; no integration or mask mutation."""
from dataclasses import dataclass
import hashlib
import numpy as np

MAX_DIAGNOSTIC_BYTES = 128 * 1024 * 1024
# Pixel eligibility, independent of the filtering decision.
NO_CONTRIBUTION, ELIGIBLE, MASKED, INVALID, OUTSIDE = range(5)


def image_identity(image):
    data = np.ascontiguousarray(image, dtype=np.float64)
    digest = hashlib.sha256(str(data.shape).encode())
    digest.update(memoryview(data).cast('B'))
    return digest.hexdigest()


def frozen(array):
    array = np.ascontiguousarray(array)
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


@dataclass(frozen=True)
class FilterDiagnostic:
    method: str
    summary: str
    source: str
    image_id: str
    provenance: str
    eligible_weight: np.ndarray
    retained_weight: np.ndarray
    lower_weight: np.ndarray
    upper_weight: np.ndarray
    eligibility: np.ndarray
    radial_bin: np.ndarray
    exactness: str = 'exact'
    unresolved_bins: tuple[int, ...] = ()
    unresolved: np.ndarray | None = None

    def __post_init__(self):
        if self.unresolved is not None:
            object.__setattr__(self, "unresolved", frozen(np.asarray(self.unresolved, bool)))
        for name in ('eligible_weight', 'retained_weight', 'lower_weight',
                     'upper_weight', 'eligibility', 'radial_bin'):
            object.__setattr__(self, name, frozen(getattr(self, name)))

    @property
    def unresolved_weight(self):
        """Eligible weight whose selection is unknown, never treated as retained/rejected.

        This compact representation is for the audited no-split backend: every
        unresolved contribution is withheld from classification. A boolean array
        distinguishes unresolved tied groups from resolved pixels in the same bin.
        """
        unknown = self.unresolved if self.unresolved is not None else np.isin(self.radial_bin, self.unresolved_bins)
        return np.where(unknown, self.eligible_weight, 0)

    @property
    def nbytes(self):
        return sum(getattr(self, name).nbytes for name in (
            'eligible_weight', 'retained_weight', 'lower_weight', 'upper_weight',
            'eligibility', 'radial_bin')) + (0 if self.unresolved is None else self.unresolved.nbytes)


def aggregate_weights(shape, pixels, weights, decisions):
    """Effective normalization weights, including multiple contributions per pixel.

    decisions: 0 retained, 1 lower-excluded, 2 upper/sigma-excluded, 3 unresolved.
    Unresolved weight remains eligible but enters none of the three classifications.
    Keep these quantities separate for future radial-azimuth diagnostics. A weighted
    contribution fraction is NOT a fraction of unique detector pixels.
    """
    n = int(np.prod(shape))
    arrays = [np.bincount(pixels, weights=weights, minlength=n)]
    for category in range(3):
        use = decisions == category
        arrays.append(np.bincount(pixels[use], weights=weights[use], minlength=n))
    return tuple(array.astype(np.float32).reshape(shape) for array in arrays)


def overlay_rgba(diagnostic, opacity):
    """Pure presentation: opacity follows excluded effective contribution weight."""
    if not 0 <= opacity <= 1:
        raise ValueError('Filter overlay opacity must be between 0 and 1.')
    eligible = diagnostic.eligible_weight
    low, high = diagnostic.lower_weight, diagnostic.upper_weight
    rgba = np.zeros((*eligible.shape, 4), dtype=np.float32)
    rgba[..., :3][high > 0] = (1., .12, .08)
    rgba[..., :3][low > 0] = (.08, .3, 1.)
    rgba[..., :3][(low > 0) & (high > 0)] = (.72, .12, .85)
    np.divide(low + high, eligible, out=rgba[..., 3], where=eligible > 0)
    rgba[..., 3] = np.clip(rgba[..., 3], 0, 1) * opacity
    if diagnostic.unresolved_bins:
        unknown = diagnostic.unresolved_weight > 0
        rgba[unknown, :3] = (1., .65, .05)
        # Amber is an uncertainty indicator, not an exclusion fraction.
        rgba[unknown, 3] = opacity * .55
    return rgba


def result_matches(curve, source, image_id, current_revision, result_revision):
    diagnostic = getattr(curve, 'diagnostic', None)
    return bool(diagnostic is not None and diagnostic.exactness in ('exact', 'partial', 'estimated')
                and current_revision == result_revision and diagnostic.source == str(source)
                and diagnostic.image_id == image_id)
