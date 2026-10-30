# Detector filter-exclusion overlay

The detector's **Show filter exclusions** checkbox visualizes a completed filtered
1D curve for the active image. **Display…** beside Details contains opacity and
filtered-result selection (primary or full-azimuth filtered comparison). An
Average comparison is never used as the source of an exclusion overlay. The
ordinary 2D intensity map and all numerical integration methods are unchanged.

Red indicates Sigma-clipping rejection or upper-percentile exclusion; blue
indicates lower-percentile exclusion. The original detector mask is neutral gray.
The original image, sector shading, and cyan cake boundaries remain visible;
boundaries draw above all exclusion layers. Opacity changes only presentation.
Filtering exclusions may include genuine diffraction signal; they are not a
reusable detector mask and are never automatically exported as one.

## Audited implementation and exactness

Inspected installed **pyFAI 2026.9.0**, `('no', 'csr', 'cython')`, engine
`pyFAI.ext.splitBBoxCSR.HistoBBox1d`. Both existing robust methods already use
this backend with **no pixel splitting**. No installed package modifications,
monkey-patching, estimator/backend changes, error-model changes, or new filtering
runs are used to obtain diagnostics.

The isolated adapter is `xrd_suite/pyfai_diagnostics.py`. It checks the version,
backend, engine class, preprocessing buffer, and contribution-table structure.
Unknown versions/backends and incompatible data disable diagnostics with a
visible reason, leaving the scientific result unchanged.

* **Sigma-clipping: exact iterative exclusions.** Immediately after the backend
  returns, capture the NaN count flags left in its actual float32 preprocessing
  buffer. These are the union of the backend's iterative decisions, including
  its Chauvenet minimum threshold. Source, calibration, mask, radial/sector
  selection, corrections, normalization, threshold, iteration limit, variance,
  and model are those of the completed call. Azimuthal, Poisson, and supplied
  variance models are covered. This is not a final-mean/spread reconstruction.
* **Percentile: exact decisions where provable, partial coverage for ties.** The backend discards its sorted work array and does not expose
  selected pixel identities. Replay only its audited selection bookkeeping from
  the *actual* CSR contribution table and float32 preprocessing buffer: corrected
  signal/normalization sort keys, coefficient-times-normalization weights,
  float64 cumulative sums rounded to float32 boundaries, and the backend's
  inclusive interval/straddling predicate. Verify retained signal and
  normalization sums, contribution counts, and weighted intensities against the
  returned result. This does not run a second estimator or alter any curve.
* C++ `std::sort` has an unstable tie order. Tied groups that cross or touch
  a percentile boundary have unresolved pixel identities. **Partial exclusions**
  keeps verified decisions visible and marks unresolved contributions amber:
  these are explicitly neither retained nor rejected. Known decisions outside
  tied groups are order-independent. A sufficient exponent-range/count bound
  verifies that summing the float32 weights is exact in float64, so changing tie
  order cannot shift subsequent groups' cumulative boundaries.
* Stable-order replay is used only to validate aggregate weighted signal,
  normalization, counts and intensities against the actual backend result; its
  guessed tied identities are never displayed. If a tied bin's replay fails
  validation, that entire bin is amber. If the sum-invariance bound cannot be
  proven, the whole bin is also unresolved. A failed check in an unambiguous bin,
  invalid sort keys, incompatible backend, or no resolved contribution anywhere
  still disables the overlay. No artificial noise, tie-breaking perturbation,
  package patch or new estimator is applied to user data.
* In a Partial result, `exactness='partial'`, explicit unresolved weights and
  unresolved radial-bin indices distinguish incomplete coverage programmatically.
  Display opacity still modulates red/blue contribution fractions; amber is a
  separate fixed-relative-opacity uncertainty indication, not an exclusion
  fraction. Perfectly symmetric and quantized images can therefore retain a
  useful verified overlay even when every radial bin contains a tied boundary.
* Equal bounds use the backend's actual single-quantile predicate. This can
  select one contribution, or two adjacent contributions at an exact cumulative
  boundary. It is not a zero-width intensity interval. A large exclusion overlay
  is expected for such an estimator. Unequal bounds remove both low and high
  contributions: 25–75 is not simply bright-spot rejection.

**No estimated rejection masks are generated.** Partial coverage explicitly marks unknown decisions rather than estimating them. There is no silent fallback to a global
percentile, spatial filter, unweighted mean, final-threshold reconstruction, or
alternative integration backend. Partial and unsupported statuses are programmatic as well as
visible in the GUI and result metadata.

Sources inspected, matching the installed version:

* [pyFAI 2026.9.0 Sigma-clipping reconstruction tutorial](https://pyfai.readthedocs.io/en/stable/usage/tutorial/Separation/sigma_clip_mask.html)
* [v2026.09 CSR backend source](https://github.com/silx-kit/pyFAI/blob/v2026.09/src/pyFAI/ext/CSR_common.pxi)
* [v2026.09 preprocessing source](https://github.com/silx-kit/pyFAI/blob/v2026.09/src/pyFAI/ext/preproc.pyx)

The percentile bookkeeping adaptation retains the upstream MIT notice in
`licenses/pyFAI-diagnostics.txt`. An upgrade requires inspecting the new backend
and revalidating this adapter before adding another supported version.

## Contributions and future diagnostics

Each immutable `FilterDiagnostic` owns four float32 detector-shaped arrays:
eligible, retained, lower-excluded, and upper-excluded effective normalization
weights. Sigma rejections use upper-excluded weight. It also owns eligibility
codes and the eligible radial-bin index for this no-split backend. Original-mask,
invalid-input, out-of-selection, and no-contribution pixels do not acquire
filter-exclusion color. Mask/sector and radial membership come from the actual
integration selection and CSR table, not a separate azimuth-unwrapping algorithm.

Rendering alpha equals display opacity times excluded weight / eligible weight.
The aggregation and renderer support multiple contributions per pixel: partial
exclusion is fainter, and simultaneous lower and upper exclusions are purple.
They never force such a pixel into a binary mask or discard one category.
An optional immutable boolean array marks unresolved no-split contributions;
`unresolved_weight` is their eligible weight, computed separately. Retained,
lower, upper and unresolved weights together account for eligible weight. The
current audited backend is unsplit, so ordinary eligible pixels are wholly
retained or excluded. Split backends remain unsupported until their decisions
can be retrieved and validated; synthetic contribution tests cover future mixed
and partial rendering without claiming backend support. No weighted fraction is
reported as a percentage of unique pixels. No radial–azimuth exclusion map is
implemented in this iteration.

## Association, memory, and performance

Diagnostics belong to the completed Curve, separately from serializable metadata
and retained Analysis snapshots. Provenance includes the source, calibration and
mask hashes, immutable settings, and a SHA256 identity of detector values/shape.
The GUI also requires matching source identity and processing revision. Changing
files/settings/calibration/mask hides the overlay and marks it outdated; even a
late asynchronous completion cannot display it on a newer revision or different
image. Rerunning replaces the associated diagnostics. Existing old 1D curves can
remain displayed with their usual outdated status.

Only the active image captured when interactive integration starts is prepared,
including at most its primary and full filtered comparison. Other selected files
and batch jobs retain no pixel diagnostic arrays. Each diagnostic is capped at
128 MiB (21 bytes per detector pixel, plus one byte for unresolved flags in a Partial result), hence completed interactive results retain
at most 256 MiB. Replaced results and any worker in flight can temporarily overlap;
preprocessing, sorting, validation, aggregation, and RGBA rendering need additional
temporary memory. Oversized images retain valid integration results with the
overlay disabled. No arrays are retained in a growing per-file cache.

Preparation runs in the existing worker; Tk changes remain on the main thread.
Toggling visibility, selecting a prepared comparison, and changing opacity only
render existing arrays. Selecting an unprepared file requires an explicit 1D run.

A warm synthetic 1024×1024 integration on the available Windows machine took
about 1.17 s for Sigma with exact diagnostics (21 MiB stored). This is an
illustrative total integration-plus-diagnostic timing, not an overhead-only
benchmark or guarantee for larger detectors. Partial percentile preparation also
validates candidate weighted totals and can require additional temporary arrays. No real experimental data were
provided for this feature.

## Verification

Run:

```sh
pixi run --locked test
pixi run --locked python -m tests.filter_overlay_smoke --output test-output/filter-overlay
```

`test_filter_diagnostics.py` exercises synthetic rings/spots on a tilted,
off-center detector; boundary-crossing sectors; input/mask/curve/2D numerical
invariance; the actual iterative Sigma flags in all three clipping models;
weighted retained-result reproduction; percentile ties, fractional/equal/extreme
bounds, unequal weights, and negative corrected intensities; zero spread, empty
bins; immutable data; mixed/partial contribution rendering; unknown-version and
memory-limit refusal; order invariance across tied permutations, partial weighted
validation, and unchanged symmetric examples at 40/120/5000 bins; and revision/source association.

The live Tk smoke uses clearly identified synthetic rings/spots with deterministic
noise. It checks show/hide/opacity without integration calls, source arrays and
2D maps unchanged, original image origin and extent, equal detector aspect,
boundaries above exclusions, primary/full comparison selection, bounded retention,
file/settings/mask changes, stale asynchronous completion, Average disabling,
clearing the input list, and small-window control/plot geometry. Captures are of
the specific application window and detector figure. Linux/macOS GUI checks and
real beamline-data validation remain unexecuted.
