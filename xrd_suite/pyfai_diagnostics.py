"""Audited adapter for pyFAI 2026.9.0, no-split CSR/Cython only.

Never changes the engine or reruns filtering. Sigma reads the backend's iterative
NaN count flags. Percentile replays only its contribution-selection bookkeeping
from the actual float32 preprocessing and CSR tables, then validates weighted sums.
Ambiguous C++ unstable-sort bins are explicitly unresolved; other bins remain verified. See docs/FILTER_OVERLAY.md.

Percentile predicate adapted from pyFAI v2026.09 CSR_common.pxi (MIT);
see licenses/pyFAI-diagnostics.txt for its copyright and permission notice.
"""
import json
import numpy as np
from .filter_diagnostics import (FilterDiagnostic, MAX_DIAGNOSTIC_BYTES,
    aggregate_weights, image_identity, NO_CONTRIBUTION, ELIGIBLE, MASKED, INVALID, OUTSIDE)

SUPPORTED_VERSION = '2026.9.0'


class UnsupportedDiagnostic(ValueError):
    pass


class AmbiguousPercentileTies(UnsupportedDiagnostic):
    """Only identity ambiguity, not a failed numerical/compatibility check."""
    pass


def percentile_decisions(keys, weights, low, high, allow_unresolved=False):
    """One radial bin, actual corrected float32 keys/effective weights.

    Mirrors backend float64 accumulation and float32 cumulative boundaries.
    We do not invent an ordering for ties crossing either quantile boundary.
    """
    if not len(keys):
        empty = np.empty(0, np.uint8)
        return (empty, empty) if allow_unresolved else empty
    if not np.isfinite(keys).all() or not np.isfinite(weights).all() or np.any(weights <= 0):
        raise UnsupportedDiagnostic('Invalid or nonpositive percentile contribution weights/keys.')
    unknown = np.zeros(len(keys), bool)
    order = np.argsort(keys, kind='stable')
    key, weight = keys[order], weights[order]
    cumulative64 = np.cumsum(weight, dtype=np.float64)
    current = cumulative64.astype(np.float32)
    previous = np.r_[np.float32(0), current[:-1]]
    qmin, qmax = np.float32(low / 100 * cumulative64[-1]), np.float32(high / 100 * cumulative64[-1])
    # A tie wholly inside/below/above the interval has order-invariant decisions.
    # Inclusive boundary contact is conservatively unsupported, except 0--100.
    if (low, high) != (0, 100):
        edges = np.r_[0, np.flatnonzero(key[1:] != key[:-1]) + 1, len(key)]
        for start, stop in zip(edges[:-1], edges[1:]):
            if stop - start > 1:
                left, right = previous[start], current[stop-1]
                if not (right < qmin or left > qmax or (left > qmin and right < qmax)):
                    if not allow_unresolved:
                        raise AmbiguousPercentileTies('Tied values cross a percentile boundary; the backend does not expose selected pixel identities.')
                    unknown[start:stop] = True
    keep = ((qmin <= previous) & (current <= qmax)) | ((qmin >= previous) & (current >= qmax))
    selected = np.where(keep, 0, np.where(previous < qmin, 1, 2)).astype(np.uint8)
    answer = np.empty(len(keys), np.uint8)
    answer[order] = selected
    if allow_unresolved:
        resolved = answer.copy()
        if np.any(unknown):
            # Sum of float32 weights is exact in float64 under this sufficient
            # exponent bound. Thus changing tie order cannot shift a later
            # group's cumulative boundary. Otherwise withhold the entire bin.
            exponents = np.frexp(weights)[1]
            bits = int(exponents.max()-exponents.min()) + 24 + (len(weights)-1).bit_length()
            if bits > 53: unknown[:] = True
        resolved[order[unknown]] = 3
        return resolved, answer
    return answer


def _validate_sums(result, bins, pixels, coefficients, pre, decisions, method, verified_bins=None, return_failures=False):
    keep = decisions == 0
    ids, coef, row = pixels[keep], coefficients[keep], bins[keep]
    # Sigma uses double coefficients; percentile rounds each product to float32.
    dtype = np.float64 if method == 'sigma_clip' else np.float32
    signal = pre[ids, 0].astype(dtype) * coef.astype(dtype)
    normalization = pre[ids, 2].astype(dtype) * coef.astype(dtype)
    size = len(result.intensity)
    check = np.ones(size, bool) if verified_bins is None else np.asarray(verified_bins, bool)
    sums = (np.bincount(row, weights=signal, minlength=size),
            np.bincount(row, weights=normalization, minlength=size))
    failures = np.zeros(size, bool)
    for actual, expected, contributions in zip(sums, (result.sum_signal, result.sum_normalization), (signal, normalization)):
        # Cancellation can make a relative tolerance inappropriate for raw sums.
        scale = np.bincount(row, weights=np.abs(contributions), minlength=size)
        failures |= ~(np.abs(actual - expected) <= 2e-6 * np.maximum(scale, 1))
    if method == 'percentile':
        failures |= np.bincount(row, minlength=size) != np.asarray(result.count)
    populated = sums[1] > 0
    failures[populated] |= ~np.isclose(sums[0][populated] / sums[1][populated],
        np.asarray(result.intensity)[populated], rtol=3e-6, atol=1e-6)
    failures &= check
    if return_failures: return failures
    if np.any(failures):
        raise UnsupportedDiagnostic('Reconstructed retained weighted sums/counts/intensities disagree with the backend result.')


def capture(ai, result, image, settings, integration_mask, original_mask, metadata):
    """Return frozen diagnostic + serializable status; errors never change results."""
    import pyFAI
    report = dict(exactness='unsupported', pyfai_version=pyFAI.version,
                  backend=['no', 'csr', 'cython'], reason='')
    try:
        if pyFAI.version != SUPPORTED_VERSION:
            raise UnsupportedDiagnostic(f'Overlay adapter is audited for pyFAI {SUPPORTED_VERSION}, not {pyFAI.version}.')
        method = result.method
        if tuple(str(part).lower() for part in (method.split, method.algo, method.impl)) != ('no', 'csr', 'cython'):
            raise UnsupportedDiagnostic('This backend/pixel-splitting scheme has no audited diagnostic adapter.')
        engine = ai.engines[method].engine
        if type(engine).__module__ != 'pyFAI.ext.splitBBoxCSR' or type(engine).__name__ != 'HistoBBox1d':
            raise UnsupportedDiagnostic('Unrecognized CSR engine type.')
        if image.size * (22 if settings.method_1d == 'percentile' else 21) > MAX_DIAGNOSTIC_BYTES:
            raise UnsupportedDiagnostic('Overlay exceeds the 128 MiB per-result diagnostic memory limit.')
        pre = np.asarray(engine.preprocessed)
        coefficients, pixels, indptr = map(np.asarray, engine.lut)
        if pre.shape != (image.size, 4) or pre.dtype != np.float32 or len(indptr) != len(result.intensity)+1:
            raise UnsupportedDiagnostic('Unrecognized preprocessing buffer or contribution table.')
        if np.any(coefficients != 1) or len(np.unique(pixels)) != len(pixels):
            raise UnsupportedDiagnostic('Expected one unsplit contribution per detector pixel.')
        bins = np.repeat(np.arange(len(indptr)-1), np.diff(indptr))
        values = pre[pixels]
        eligible = np.isfinite(values[:, :3]).all(axis=1) & (values[:, 2] > 0)
        count = values[:, 3]
        eligible &= (count > 0) | np.isnan(count)
        eligible &= ~np.asarray(integration_mask).ravel()[pixels]
        eligible &= np.isfinite(np.asarray(image).ravel()[pixels])
        if settings.method_1d == 'percentile' and not eligible.all():
            # NaN sort keys violate strict ordering in C++ std::sort; never infer
            # selected identities by just dropping those entries before sorting.
            raise UnsupportedDiagnostic('Invalid contributions in the percentile sort table; exact identities are unavailable.')
        pixels, bins, coefficients = pixels[eligible], bins[eligible], coefficients[eligible]
        values = values[eligible]
        weights = (values[:, 2] * coefficients).astype(np.float32)
        unresolved_bins = []
        verified_bins = np.ones(len(result.intensity), bool)
        if settings.method_1d == 'sigma_clip':
            decisions = np.where(np.isnan(values[:, 3]), 2, 0).astype(np.uint8)
            summary = f'Exact exclusions · Sigma-clipping · {settings.sigma_threshold:g}σ'
            capture_kind = 'backend iterative rejection flags'
        else:
            decisions = np.empty(len(pixels), np.uint8)
            keys = values[:, 0] / values[:, 2]
            replay = np.empty(len(pixels), np.uint8)
            for radial_bin_index, (start, stop) in enumerate(zip(indptr[:-1], indptr[1:])):
                decisions[start:stop], replay[start:stop] = percentile_decisions(
                    keys[start:stop], weights[start:stop], settings.percentile_low,
                    settings.percentile_high, allow_unresolved=True)
                if np.any(decisions[start:stop] == 3):
                    unresolved_bins.append(radial_bin_index)
            failures = _validate_sums(result, bins, pixels, coefficients, pre, replay,
                                      settings.method_1d, return_failures=True)
            if np.any(failures & ~np.isin(np.arange(len(failures)), unresolved_bins)):
                raise UnsupportedDiagnostic('Reconstructed retained weighted sums/counts/intensities disagree with the backend result.')
            # A different tie ordering can change the weighted selection. Keep
            # that entire bin unresolved when the stable replay does not match.
            decisions[failures[bins]] = 3
            verified_bins = ~failures
            if not np.any(decisions != 3):
                raise UnsupportedDiagnostic('Tied values make every eligible contribution ambiguous; no verified exclusions are available.')
            summary = f'Exact contribution fractions · Percentile {settings.percentile_low:g}–{settings.percentile_high:g}'
            capture_kind = 'validated contribution-selection replay; unambiguous sort order'
        exactness = 'partial' if unresolved_bins else 'exact'
        if unresolved_bins:
            populated_bins = int(np.count_nonzero(np.diff(indptr)))
            summary = (f'Partial exclusions · Percentile {settings.percentile_low:g}–{settings.percentile_high:g}'
                       ' · amber = unknown')
            capture_kind = 'validated weighted replay; only order-invariant identities classified, tied identities unresolved'
            report.update(unresolved_radial_bins=unresolved_bins,
                          fully_resolved_populated_radial_bins=populated_bins-len(unresolved_bins),
                          validated_populated_radial_bins=int(np.count_nonzero(verified_bins & (np.diff(indptr)>0))),
                          unresolved_eligible_weight=float(np.sum(weights[decisions == 3], dtype=np.float64)))
        _validate_sums(result, bins, pixels, coefficients, pre, replay if settings.method_1d == 'percentile' else decisions, settings.method_1d, verified_bins)
        arrays = aggregate_weights(image.shape, pixels, weights, decisions)
        eligibility = np.full(image.shape, NO_CONTRIBUTION, np.uint8)
        coordinates = ai.center_array(image.shape, unit=settings.unit)
        lower, upper = metadata['effective_radial_range']
        outside = integration_mask & ~original_mask & np.isfinite(image)
        outside |= (coordinates < lower) | (coordinates > upper)
        eligibility[outside] = OUTSIDE
        eligibility[~np.isfinite(image) | ~np.isfinite(coordinates)] = INVALID
        eligibility[original_mask] = MASKED
        eligibility.ravel()[pixels] = ELIGIBLE
        radial_bin = np.full(image.shape, -1, np.int32)
        radial_bin.ravel()[pixels] = bins
        provenance = json.dumps(metadata, sort_keys=True, default=str)
        unresolved = None
        if unresolved_bins:
            unresolved = np.zeros(image.shape, bool)
            unresolved.ravel()[pixels[decisions == 3]] = True
        diagnostic = FilterDiagnostic(settings.method_1d, summary, str(metadata['source']),
            image_identity(image), provenance, *arrays, eligibility, radial_bin, exactness=exactness, unresolved_bins=tuple(unresolved_bins), unresolved=unresolved)
        report.update(exactness=exactness, summary=summary, capture=capture_kind,
                      denominator='eligible effective normalization contribution weight')
        return diagnostic, report
    except (UnsupportedDiagnostic, AttributeError, KeyError, ValueError, TypeError, IndexError, MemoryError) as exc:
        report['reason'] = str(exc)
        return None, report

