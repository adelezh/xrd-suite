# XRD interface refinement

Launch from the project folder:

```powershell
pixi run python run_xrd_gui.py
```

The three tabs and scientific pipeline are preserved. Processing, file readers/writers, filename parsing, variance propagation, and calibration-launch behavior were not rewritten.

## Layout

- The workspace row has Browse and Open Calibration. Expand Calibration & Mask for full editable paths, Load/Reload, mask enable, and validation. Missing setup starts expanded. Clear loaded files / status is in the Workspace menu.
- Integration settings start collapsed to leave room for plots at smaller sizes. The summary shows the active unit, bin count, and azimuth mode. Expand for Basic and Sector groups; scroll for Advanced settings. Advanced settings are collapsed initially. Irrelevant angle/variance fields are disabled.
- The adjustable file table shows sample, frame, and timestamp. Frame is placed before timestamp so it stays visible in a narrow panel. Headers do not change sorting or selection. Horizontal scrolling and selectable full-path details are available. Ctrl/Shift multiselection, filter, active file, Previous/Next, and counts remain. Hide files collapses the panel.
- Plot arrangement remains detector left and 2D above 1D right. Detector Contrast and Mask overlay belong to the detector. The 2D Display dialog contains auto percentiles, manual intensity limits, Linear/Log, Apply, and Reset. The map includes an intensity color scale. 1D retains Home, Zoom, and other standard navigation controls.
- Save 1D and Save 2D each appear only at their associated plot. Their dialogs still separate numeric exports from PNG exports. Details exposes full sources and captured processing metadata. Compact plot labels disambiguate repeated frames by timestamp (and source index when needed).
- Batch and File Manipulate have scrollable left settings and expanding right preview tables. The table headers and empty-state guidance are always present. Drag the divider to allocate more width to output names; select a row to copy full details.
- Batch settings are explicitly captured. Every output product has its own preview/status row. Settings are disabled while that job runs; later diagnostic edits still cannot change its snapshot.
- Manipulation keeps a separate set of options for each operation during the session. Sum/Average show expandable groups; Copy/Rename and TOPAS show per-file outputs. Hidden settings are removed from the execution options, without erasing saved choices. The approximate sigma checkbox only appears for TOPAS XYE when a readable selected curve is missing sigma.
- Primary action, progress, and Cancel stay together on each tab. Progress/Cancel appear only during a job. One global status line and an expandable Processing log remain. Pane widths/heights are remembered on normal close.

## Display semantics

Auto contrast uses finite populated bins, based on pyFAI count (or normalization when count is unavailable). A populated zero is valid. Log display hides nonpositive values only in the plot; the map notice reports those bins. Empty/nonfinite/display-masked regions are white. Contrast and scale do not modify arrays, sigma, axes, result metadata, or numerical exports. Press Apply after adjusting the Display dialog.

## Validation

Automated tests cover the existing scientific workflow plus valid-zero contrast, log masking, normalization fallback, immutable display/export arrays, compact-label disambiguation, and hidden-option isolation. `tests/ui_smoke.py` exercises all three tabs with empty and populated states, real detector data, file selection/filtering, operation persistence, preview expansion, and display reset. It writes screenshots only under `.test-output/ui`.

Visual checks use 1280×800 and 1920×1080 windows on the current Windows display (Tk scaling approximately 2.0, corresponding to 150% Windows scaling). The operating-system scaling setting was not changed to 100% or 125%; those settings need a manual check. At smaller sizes, collapse Calibration & Mask and Integration settings, and scroll the job settings panels. Full calibration interaction remains outside the UI smoke test; its independent subprocess launch is retained.

Current results: **24 automated tests passed**, plus the display smoke checks and `tests/ui_interactions.py` worker checks (real 1D/2D integration, fixed batch settings, per-product completion statuses, TOPAS conversion, pane persistence, and a mocked nonblocking calibration launcher). No detector source files were changed. The scientific test suite reports two existing Fabio/NumPy deprecation warnings. Very small temporary plot areas during layout changes can emit a Matplotlib constrained-layout warning; collapsing settings restores plotting space.
