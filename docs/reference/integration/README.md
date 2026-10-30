# XRD Integration Workspace

A separate Python/Tkinter application implementing `Build_GUI.md`. The original `main.py`, `tools.py`, `xrd_peak_workflow.py`, and Mo notebook are preserved. No PDF, peak analysis, Combine Scalar, or TOPAS input-generation dependencies are imported.

## Launch on this computer

From this folder in PowerShell:

```powershell
pixi run python run_xrd_gui.py
```

The launcher uses the active Python environment. This project has a Python 3.12 Pixi environment; `pixi run` selects it. Alternatively, run `.\.pixi\envs\default\python.exe run_xrd_gui.py`. The old `.vendor` directory is ignored: its Python 3.13 compiled packages cannot be used with Python 3.12. The main application does not require Qt.

For a clean installation on another Windows computer (Python 3.11–3.13 recommended):

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m xrd_gui
```

Both launch methods use the active environment. Python's Windows installer includes Tcl/Tk; select that component if needed. For the optional external calibration program, install a Qt binding in the same environment:

```powershell
.\.venv\Scripts\python.exe -m pip install PyQt6
```

For Pixi, use `pixi add pyqt`. The calibration button checks for a binding and launches `python -m pyFAI.app.calib2` in a separate process, with the active TIFF when available. Load or Reload its saved calibration and mask explicitly. Calibration's interactive workflow was not tested because no Qt binding is installed here.

## Shared controls

Choose a workspace, then load a `.poni` and optional mask. Workspace history and browsing locations are saved to `%USERPROFILE%\.xrd_tk_settings.json`. Inputs and outputs may be outside the workspace. Mask formats include `.npy` and Fabio-supported image formats. **Nonzero mask pixels are excluded**; detector masks and nonfinite image pixels are excluded too. Dimensions must match.

Path edits do not load files: use Load/Reload. The loaded-status line identifies the current calibration and mask. Clear resets loaded diagnostic files, results, and calibration/mask status. Job input lists remain separately managed.

## Integration

1. Add TIFF files or a folder; filter by filename. Files sort naturally. Ctrl/Shift select comparisons; the active file is labeled. Previous/Next selects a single file.
2. Set units (`2th_deg` = 2θ degrees; `q_A^-1` = q in inverse ångströms), bins, optional radial bounds, and corrections. Blank bounds use the available range. q requires calibration wavelength.
3. Optionally enable Sector/Cake and edit its angles. A calibration-derived region and cyan boundary contours appear immediately. Processing only starts with Run 1D, Run 2D, or Run Both.
4. Selected files produce labeled independent 1D curves. Only the active file produces the 2D map. No implicit image sums or averages occur. Compare full azimuth adds a separately integrated full curve.
5. Save 1D opens a curve selector and XY/CHI/XYE format selector. Save 2D offers NPZ. Numerical exports and PNG plot exports are distinct buttons. Nothing is saved automatically. Choose a new filename for diagnostic exports.

The adjustable panes place the narrow list left, a square detector view in the middle, and stacked 2D/1D plots right. Contrast percentile controls change display only. The 1D Matplotlib toolbar provides zoom, pan, and Home; Home restores the computed data extent. Settings edits mark results outdated. Exports use metadata captured with each result, including calibration/mask hashes, not current edits.

### Sector convention and numerical method

Angles use pyFAI chi in [-180°, 180°), obtained through `center_array(shape, unit='chi_rad')`, with detector rows increasing down the displayed image. The calibrated geometry, including tilt, determines angles; no arbitrary image-center wedge is used. Start is inclusive and end exclusive. Start > end crosses ±180°; -180° to 180° selects the full circle. Equal endpoints are rejected.

The selected set is `(chi - start) modulo 360 < (end - start) modulo 360`. Both the overlay and integration use that set. The engine uses pyFAI's **no-splitting, histogram, Cython** method, assigning whole pixel centers consistently to the sector. This deliberately avoids ambiguous split-pixel sector boundaries and avoids averaging normalized sector curves. Tilted synthetic geometry and boundary-crossing selection are tested. A boundary outside the detector has no visible contour.

2D maps retain the full [-180°,180°] azimuth axis even in sector mode; excluded regions are empty. Disable Sector and Run 2D for full-azimuth inspection.

### Uncertainties

No dark subtraction is performed. Choices are none, pyFAI Poisson model, or a supplied variance image (variance, not sigma), in `.npy` or image format. Supplied variance is captured at job start and must match the detector. Batch supplied variance currently uses the same variance image for all frames; per-frame variance pairing is not implemented.

Poisson uncertainties on already corrected images are model estimates; true original counting uncertainties cannot be recovered from corrected intensity alone. XYE uses pyFAI's propagated `sigma` (standard error of normalized intensity), never sqrt of the integrated intensity. XYE export rejects the entire export if any bin has missing, zero, negative, or nonfinite sigma. Reduce bins or restrict the radial range to exclude empty bins; no fabricated error values are written.

## Batch Integration

Choose inputs and output folder, click **Use current diagnostic settings**, then select 1D/2D products, 2θ and/or q, output format, naming, and existing-file policy. Settings are shown above the original → output preview. For both units, a supplied numerical radial range is interpreted in each unit separately; leave it blank when that is not intended.

Standard shortening anchors on timestamp and six-character alphanumeric UID, preserves underscored samples, padded frames, mean/sequence identifiers, and unit endings. Unrecognized patterns are rejected; use Keep original. Duplicate planned names block execution. Existing files are flagged in preview; Skip is the default, with explicit Overwrite or Unique name options.

Start captures calibration, mask, settings, and supplied variance. Later diagnostic edits cannot change the running batch. Processing retains one image/product at a time. Cancel takes effect between engine calls/products; pyFAI calls are not interrupted. Completed products remain valid. Each individual numerical file is staged and atomically committed, and temporary files are cleaned on errors. JSON sidecars are written separately after numeric data; the pair is not a filesystem transaction. Progress and per-product errors appear in the expandable log, followed by saved/skipped/failed counts.

## File Manipulate

Choose Sum, Average, Copy / Rename, or For TOPAS, then input files and an output folder. Preview shows every group's members, count, and output name.

- Sum/Average: group all selected, by sample, sample + timestamp, or a custom basename section. Character sections use Python-style **0-based start:end, end excluded**. One uniquely named output is made per group. TIFF dimensions and text x grids must match; interpolation is not performed. TIFF calculations use float64 and preserve fractional averages. Text sigma is propagated as independent variance: sqrt(sum(sigma²)), divided by N for averages. A missing sigma makes combined sigma unavailable, so XYE is rejected.
- Copy / Rename: originals remain intact. Keep original, standard shortening, or Custom naming support section extraction, prefix/suffix, and numbering. The Preserve frame / mean checkbox appends the parsed identifier after a custom section (unrecognized patterns are rejected). Standard shortening preserves frame/mean and unit endings. Unit suffixes are not duplicated. Existing sidecar metadata is copied.
- For TOPAS: exports headerless XY or XYE, preserving x and unit metadata. Existing sigma scales by the absolute intensity factor. The explicit approximation checkbox fills only missing sigma using sqrt(max(original I,1)), then applies scaling; original intensity is preserved except for the chosen scale. The floor is numerical convenience, not recovered uncertainty. No `.inp` files or q↔2θ conversion are generated.

## Formats and modules

XY: two numeric columns. XYE: three numeric columns. CHI: four header lines (title, radial unit, intensity label, point count), then two columns, compatible with the reference workflow's numeric-row reader. Readers scan actual numeric columns rather than assuming fixed header length. Metadata lives in `<filename>.json`, keeping TOPAS exports headerless. Preserve sidecars when moving files.

NPZ keys: `intensity` (azimuth rows × radial columns), `radial`, `azimuth`, optional `sigma`, and scalar JSON string `metadata`. Load with `numpy.load(path, allow_pickle=False)`; parse metadata using `json.loads(str(data['metadata']))`.

Modules: `settings.py` for validated immutable settings and preferences; `naming.py` for parsing/grouping; `files.py` for IO and uncertainty arithmetic; `processing.py` for pyFAI; `jobs.py` for batch/manipulation; `gui.py` for Tk and worker coordination.

## Verification

```powershell
python -m pytest -q tests
```

**15 tests passed** on this computer: filename parsing/padding/unit endings, mean names, collisions, grouping, XY/CHI/XYE round trips, uncertainty arithmetic, approximate sigma, grids, crossing-sector masks with tilt, 1D/2D mask consistency, supplied-sigma semantics, variance snapshots, immutable settings, actual batch exports/skip/cancel, manipulation, and atomic-write failure cleanup.

Real-data validation used `Mo_3_20260711-100105_4f04e9_primary-dk_sub_image-00000.tiff` (2048×2048), `CeO2_2_poni.poni`, and `CeO2_2.npy` from the notebook's `Flash_07112026` directory. Both units and crossing-sector 1D/2D integrations succeeded. This checks execution and numerical validity, not calibration accuracy or material interpretation.

The Windows Tk GUI smoke test loaded that frame, rendered the detector and calibrated overlay, ran asynchronous integration, rendered both plots, and opened all three tabs. `tests/smoke_gui.py` reproduces that local-data test; its data path is specific to this computer. Screenshot: `.test-output/gui-smoke.png`.

Manual follow-up: exercise calibration after installing Qt; drag pane dividers; compare multiple frames; zoom/Home; save each numeric/plot format; run batch with both units and each overwrite policy; cancel a long batch; inspect manipulated group outputs. Text-file unit metadata absent from both sidecar and filename is retained as unknown, never relabeled. No interpolation or uncertainty recovery is implied.


### Coordinate correctness fix (2026-10-23)

The application now evaluates pyFAI center-coordinate unit equations with NumPy, locally to its integrator. The installed Windows NumExpr 2.14.2 path produced incorrect results on interleaved coordinate views, stretching radial coordinates toward 180 degrees and compressing azimuth structure. This affects both scientific results and displays; rerun and re-export results produced before this fix. Restart the application to discard old geometry caches. Regression tests compare 2theta, q, and chi against independent geometric formulas, including worker copies, and verify full azimuth occupancy.

## Refined interface

See [UI_REFINEMENT.md](UI_REFINEMENT.md) for the current layout and display controls. Integration settings now start collapsed, Clear is in the Workspace menu, and 2D display controls are accessed through the map's Display button. Batch and manipulation settings scroll independently of their preview tables. Scientific processing and numerical exports retain the behavior documented above.

## Robust 1D estimators

See [ROBUST_METHODS.md](ROBUST_METHODS.md) for Sigma-clipping, Percentile filtering, comparison controls, uncertainty limitations, and verification.

