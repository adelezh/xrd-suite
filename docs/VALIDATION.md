# Validation record ? 2026-10-29

## Executed on Windows x86_64

- Pixi 0.67.1 generated `pixi.lock` for `win-64`, `linux-64`, and `osx-arm64`.
- `pixi install --locked` installed a new environment inside this suite only.
- `pixi run --locked test`: **76 passed**, 2 dependency deprecation warnings,
  30.02 seconds on the final full run. This includes all 44 supplied Integration
  numerical tests, Analysis snapshot/import/unit/display/fitting tests, extracted
  baseline and pseudo-Voigt equivalence, Monitor scan/tracking/map/similarity
  equivalence, detector/calibration/ring and CIF checks, and both launchers.
- Launcher checks copy only suite packages into a temporary path containing
  spaces, run each launcher in a child process, and block attempts to open source
  beneath either original project directory. Settings and outputs are isolated.
- `pixi run --locked python -m tests.gui_smoke --output .test-output/gui`:
  **passed** on a real Windows Tk display. The final run exercised all four
  Integration tabs; actual asynchronous integration; repeated Add to Analysis;
  multiple input curves; mask/setting changes; batch/manipulation; diagnostic
  clearing without Analysis loss; rename, visibility, removal, and explicit clear;
  imports and unknown-unit assignment; display normalization/offsets; independent
  fitting and residual inspection; rejection of obsolete in-flight fit results;
  CSV/PNG exports; tab/selection/zoom preservation; and 1100?800/1450?950 resizing.
- Monitor smoke exercised watched-folder signatures and changed-file updates,
  q/tth filtering with explicit matching ranges, scan identity/order, external
  map/overlay windows, explicitly selected detector pairs, calibration loading,
  ring rendering, peak tracking and similarity windows. Selection and folder
  refresh did not implicitly replace the inspected detector pair.
- Screenshots of both windows and the small Analysis layout were visually
  reviewed. Generated evidence is in ignored `.test-output/gui`; it is not
  experimental data and is not intended for source distribution.
- `pixi run --locked python -m xrd_suite.example --output examples/synthetic`
  generated the bundled synthetic example without experimental inputs.
- Static AST parsing succeeded for 43 suite-owned Python source/test files.
- Targeted before/after SHA-256 checks confirmed **32 original source/reference
  files unchanged**, Integration Git status unchanged, and Monitor source
  inventory unchanged. See [source-integrity.json](source-integrity.json).
  No large experimental datasets were read or hashed for this audit.

## Dependency choices

The existing Integration lockfile was the baseline where its requirements text
and manifest disagreed. Preserve pyFAI 2026.9.0, Fabio 2025.10.0, NumPy 2.5.4,
SciPy 1.18.1, and Matplotlib 3.11.2. The NumPy coordinate-equation workaround is
retained and covered by the original independent-geometry regression tests.
Monitor arrived as seven source modules without tests, license files, or a
working dependency manifest; required dependencies were inferred from imports.
The common lock includes pybaselines, pandas, tifffile, pymatgen, PyYAML, openpyxl,
and Tk, preserving CIF, detector, calibration, and spreadsheet export capabilities.

The two pytest warnings are Fabio's NumPy shape-assignment deprecation. GUI smoke
also emitted a transient Matplotlib constrained-layout warning during widget
resize and pyFAI's deprecation notice for Monitor's existing `twoThetaArray`
geometry call. The final figures were checked and the calculations passed. The
geometry call was preserved to avoid silently changing scientific behavior.
The prior inspector shutdown callback warning was fixed by avoiding redraw of a
closing window; no orphan draw warning occurred in the final smoke run.

## Not yet executed

Linux x86_64 and Apple Silicon macOS dependency resolution is complete, but their
installation and GUI/runtime tests have **not** been run. The CI matrix is
configured for Ubuntu 24.04, Windows 2022, and Apple Silicon `macos-15`; this
workflow has **not** run on a remote service. Do not describe CI or those platforms
as validated until those jobs and local usability checks pass. Intel macOS is
not supported by this manifest.

The external interactive pyFAI calibration editor, real beamline data, prolonged
live acquisition, and manual beamline deployment have not been validated here.
This version deliberately excludes session save/restore, inter-application
messaging, joint/overlapping-peak fits, installers, and release publishing.

## Detector filter-overlay follow-up (2026-10-29)

* Final `pixi run --locked test`: **94 passed**, including 18 focused filter
  diagnostic tests. The two Fabio/NumPy deprecation warnings remain unchanged.
* `python -m tests.filter_overlay_smoke --output test-output/filter-overlay`
  passed on Windows using the locked Pixi environment and temporary preferences
  and synthetic data. The final run had no layout warnings. Window-specific
  captures and detector figure exports were visually inspected at 1450×950 and
  1100×800: transparent categories, neutral mask, cyan cake boundaries, detector
  aspect/origin, legend, full checkbox text, opacity dialog, ordinary 2D map, and
  multiple 1D comparison curves. The compact comparison legend uses file numbers
  (mapped to paths in Details), P for Percentile, Avg for Average, and * for a
  comparison curve. No numerical curves or map values changed.
* Confirmed rendering never invokes integration; active-image-only diagnostic
  retention; primary/full filtered selection; stale completion rejection after
  file changes; settings/mask invalidation; Average disabling; and clear/remove
  behavior. Existing Analysis snapshots remain independent of detector arrays.
* Inspected pyFAI 2026.9.0 no-split CSR/Cython. Sigma is exact from iterative
  backend flags. Percentile is exact after validated contribution replay only
  when selected identities are unambiguous; tied boundaries or other failed
  checks disable the overlay. No estimated masks are generated.
* See [FILTER_OVERLAY.md](FILTER_OVERLAY.md) for the audited source references,
  tie and backend limitations, contribution weighting, bounded storage, and
  measured synthetic performance. No real beamline data, Linux GUI, or macOS GUI
  was validated for this feature. Original-source integrity was rechecked.

## Percentile tie handling correction (2026-10-29)

The initial all-or-nothing tie safeguard disabled the checkbox even when useful
order-independent decisions were available. Percentile diagnostics now preserve
those decisions and explicitly label incomplete coverage **Partial**. Amber
marks unresolved contributions, never a rejection. Tied-group replay is used to
validate weighted backend totals, not to invent selected pixel identities. A
failed tied-bin replay or unprovable cumulative-sum invariance withholds the entire
bin. If no contribution can be classified, the overlay remains unsupported.

* Full regression suite: **107 passed**, five existing Fabio/NumPy deprecation
  warnings (three additional TIFF fixture reads exercise the same warning).
* Added symmetric-example regressions at 40, 120 and 5000 radial bins, all now
  showing Partial overlays; equal and unequal quantiles; exact tied-order
  invariance; extreme-weight refusal; known-bin weighted validation; immutable
  uncertainty flags; unchanged inputs/masks/intensities/uncertainties; and sector
  selection. No noise or tie-breaking perturbation is applied to production data.
* Live Tk smoke confirms the enabled checkbox on the unchanged symmetric fixture,
  amber legend/Partial status, rendering-only toggles/opacity, and existing
  lifecycle checks. The final partial-overlay screenshot was visually inspected.
* Fully resolved Sigma and Percentile results keep their previous exact behavior.
  Details and [FILTER_OVERLAY.md](FILTER_OVERLAY.md) document unresolved weights,
  validated bins, and memory accounting (one extra byte per pixel when partial).
