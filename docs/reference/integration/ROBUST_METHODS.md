# Robust 1D methods (2026-10-26)

Launch from C:\PythonProject\Integration_GUI:

```powershell
pixi run python run_xrd_gui.py
```

The installed pyFAI version is 2026.9.0. Average retains the existing
`integrate1d_ng` no-splitting histogram backend. Sigma-clipping uses
`sigma_clip_ng`; percentile filtering uses `medfilt1d_ng`. Both use
`('no', 'csr', 'cython')`. No detector spatial filter or curve smoothing is used.
The existing NumPy coordinate-equation workaround remains in place.

Open Integration settings to select the 1D method. Average is the default.
Sigma-clipping initially uses threshold 5, five iterations, and azimuthal
dispersion. Threshold is in the basic controls; iteration limit and clipping
model are under Advanced settings. Poisson and supplied variance are alternatives.
The separate Average / percentile / 2D model never overrides the clipping model.

Percentile filtering initially uses 25-75: the weighted trimmed mean over that
interval. Both bounds are editable; presets select Middle 50% or Median (50-50).
Other equal bounds request a single quantile. Equal bounds are passed as a scalar;
intervals are passed as a tuple. The installed Cython implementation supports
0 through 100 inclusive, verified against direct calls at both endpoints.
This API has no azimuthal regrouping-bin parameter; 2D azimuth bins affect only
maps. Switching methods preserves field values but drops inactive parameters
from computation. Old preferences restore Average safely.

Full/sector selection is independent. A combined pixel mask handles wrapping
sectors, so robust statistics operate on the union rather than separate pieces.
Masking, polarization, solid-angle correction, units and radial limits remain
consistent. No additional dark subtraction occurs. Run Both produces the chosen
1D estimator and the ordinary 2D map.

Compare with average uses the same mask, corrections, CSR backend and radial grid.
When no radial range is specified, robust calculations and their references use
the same explicit range from valid full-detector pixel centers. Compare full
azimuth uses the chosen estimator with full available azimuth. References are
dashed and labeled, are individually selectable in Save 1D, and do not create
additional batch products. Filtering can suppress genuine spotty Bragg scattering
and change peak areas; it need not lower every point.

## Uncertainty and empty bins

Sigma-clipping returns pyFAI's retained-pixel standard error. Azimuthal dispersion
is an empirical diagnostic; Poisson and supplied-variance models propagate the
retained contributions. Interval percentile filtering can return propagated
SEM with Poisson or supplied variance. These errors are conditional on selection;
selection uncertainty and filtering bias are not included. Corrected-image
Poisson estimates do not recover original counting variance.

Median/single-quantile XYE is blocked even when pyFAI returns a sigma: selected-pixel
propagation is not a characterized quantile-estimator uncertainty. Choose XY/CHI.
No-model percentile results also require XY/CHI. XYE requires finite positive
sigma in every exported bin. No average sigma or sqrt(filtered intensity) is used.
The existing explicit sqrt(I) approximation in File Manipulate remains separate.

Empty bins are recorded in metadata, shown as gaps and reported in the processing
log. Sigma-clipped bins with fewer than two retained contributions are undefined.
Numerical export omits undefined bins and records their original indices in the JSON sidecar. Valid coordinates and intensities are preserved. Export status reports the omitted count; an entirely undefined result still fails.
There is no interpolation or automatic replacement with zeros. The underlying
Average API arrays remain unchanged for backward numerical compatibility.

## Snapshots and outputs

Batch settings are frozen dataclasses captured from current diagnostic settings;
workers use a copied integrator and frozen supplied variance. Method parameters,
API/backend, selection, uncertainty limitations and invalid-bin information are
stored with results and in JSON sidecars. Saved preferences retain each method's
values. Changing method or comparison marks 1D outdated without invalidating 2D;
azimuth-bin changes affect only 2D. Display changes do not invalidate data.

Average names are unchanged. Filtered filenames insert tags before `_tth`/`_q`:
`pct25-75`, `pct25p5-75p25`, or `sigclip_s5_i5_azimuthal`. Save 1D derives its
suggested name from the computed curve, not current controls. Existing collision
policies remain in place; diagnostic save refuses existing targets.

## Verification

40 pytest cases passed, including existing workflow and coordinate tests. New
synthetic 128x128 smooth-ring images with localized bright spots verify direct
API agreement, unified wrapping selections, masked/narrow/empty bins, negative
corrected intensities, scalar endpoint quantiles, interval SEM, common reference
grids, unchanged maps, naming, snapshots, inactive settings and XYE rejection.

`tests/ui_methods.py` checks all method states, presets, comparison line styles,
product-specific invalidation, persistence and batch snapshots on the local
Windows display. Screenshots are in `.test-output/methods/`.
`tests/ui_interactions.py` passes with the local 2048x2048 AIC3_6 frame, calibration
and mask over the populated 1-10 degree range, exercising asynchronous integration,
batch export and TOPAS conversion. The full automatic range contains three empty
edge bins at 121 radial bins and are omitted during numerical export, with their indices recorded in metadata.
The new scientific filtering tests use explicitly synthetic data; they do not
establish an optimal threshold or scientifically appropriate estimator for the
real sample. DPI variants and external Qt calibration were not retested here.
