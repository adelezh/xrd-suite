# XRD Suite

Two independent Tkinter/Matplotlib applications, with shared curve IO and peak
calculations. Integration retains its average, sigma-clipping, percentile,
sector, uncertainty, metadata, batch, and file-manipulation workflows. Monitor
retains its watched-folder workflow, external plots, tracking, similarity,
CIF references, detector inspector, and calibrated ring guides.

## Install and launch

Install [Pixi](https://pixi.sh/latest/installation/), download/extract the source
for a tagged suite release into its own folder, and open a terminal there.
Use the supplied `pixi.lock`:

```sh
pixi install --locked
pixi run --locked integration
pixi run --locked monitor
```

Run the applications independently. Paths containing spaces are supported; quote
them when passing paths on the command line. `--locked` fails if the manifest and
lockfile disagree instead of silently updating dependencies. The tasks are named
`integration`, `monitor`, `test`, `smoke`, and `example`; retain `--locked` in routine
commands. An existing system Python is not required. Launching from a file manager
without activating Pixi is not the documented setup.

One environment is locked for Windows x86_64 (`win-64`), Linux x86_64 (`linux-64`),
and Apple Silicon macOS (`osx-arm64`). Windows installation, tests, and real GUI
smoke checks have been executed. Linux/macOS have dependency resolutions only;
runtime checks remain pending. Intel macOS is not a declared target. See
[validation](docs/VALIDATION.md) for the exact checks and limitations.

## Integration to Analysis

1. In Integration, load a PONI calibration and optional mask, add TIFFs, and select
   one or more images. Set units, bins, corrections, and the 1D method. Run 1D or
   Run Both.
2. Click **Add to Analysis** above the 1D plot. Select computed results in the
   chooser and click **Add selected to Analysis**. Each addition captures new,
   immutable arrays, uncertainties, settings, source identity, wavelength, and
   calibration/mask provenance. Repeated additions get different IDs and labels.
3. Change integration settings and run again; retain additional results in the
   same Analysis collection. Diagnostic Clear, calibration changes, and new runs
   do not alter retained results. Analysis has its own Remove and Clear controls.
4. Select retained curves with Ctrl/Shift. Rename one selected curve using its
   label field. Visibility is separate from selection; toggle it for selected
   rows or double-click the Show column. The plot shows visible curves in the
   chosen **Display units** group, each on its original grid.
5. Edit displayed bounds, offset, or **Display normalization**, then Apply display.
   These transforms never change stored data or fitting intensities. Normalization
   means division by each curve's maximum absolute finite intensity. Hide the
   legend when comparing many curves. The Matplotlib toolbar provides navigation.
6. Open **Peak-fit settings (original intensities)**, enter a common region,
   choose an explicit baseline, and **Fit selected**. The selected curves must
   have the same known units. Each is fitted independently; no temporal tracking,
   joint fitting, resampling, or uncertainty weighting is applied.
7. Inspect the results table (scroll to additional rows), select a result, and
   **Inspect fit / residuals**. Accepted fits can also be overlaid. Export the
   table with **Export fits CSV** and the displayed overlay with **Export PNG**.

Import XY, CHI, or XYE files with **Import curves**. Keep `<filename>.json`
metadata sidecars beside them. Recognized CHI headers and `_tth`/`_q` suffixes also
supply units. Unknown units stay in their own display group; select those curves
and **Assign unknown units** before comparison with known-unit data or fitting.
This labels existing coordinates; it does not convert q and 2theta. Unsupported
units must be converted outside this first version, with provenance retained.

The Analysis collection and fitted results are in memory for the application
session. Export what you need before closing. A portable session format is
outside this version's scope; CSV exports include provenance and fit settings,
but are not a restore format for the full collection.

## Scientific fitting choices

The shared calculations are extracted verbatim from the supplied Monitor source:
area-normalized pseudo-Voigt, an independently fitted constant offset, and the
existing arPLS/asLS baselines. `none` means no pre-subtracted baseline; the fitted
constant offset is still included. Baseline correction runs on the entire finite
curve, then the common fitting region is selected on that curve's own grid.
The CSV records region, baseline, lambda, width guess, fixed eta guess 0.5,
minimum R squared, baseline domain, model, units, and source metadata.

Analysis requires one significant local maximum in the selected region. Its
candidate threshold is the larger of 5 times robust second-difference noise,
1% of the regional intensity span, and floating-point epsilon. Multiple candidates,
insufficient data, unresolved widths, and low-quality fits are explicit failures
or ambiguities with blank numerical results. This conservative screen is not a
proof that a peak contains no overlap. Review residuals and choose a resolved
single-peak region. Area is the fitted full pseudo-Voigt area, not a truncated
numerical integral over the displayed region. No fit-parameter error bars are
claimed. Input sigma is retained but not used to reweight this existing model.
Changing any fitting input clears prior fits; obsolete worker results are discarded.

## Synthetic example and tests

`examples/synthetic` contains only generated, redistributable curves, small TIFFs,
mask, calibration, and metadata. Copy that folder to a user data location, or
create a fresh copy outside the checkout:

```sh
pixi run --locked example
# Or choose a new empty destination:
pixi run --locked example --output "path with spaces/example"
pixi run --locked test
pixi run --locked smoke
```

The default example destination is `~/XRD Suite/synthetic example`; generation
refuses to overwrite an existing dataset. Load its `synthetic.poni`, `mask.npy`,
and the two TIFFs under `dark_sub`. Start with 120 radial bins. For an exact fitting
check, import `peak-1.xye` and `peak-2.xye`, fit 2.5 to 3.5 degrees with baseline
`none`: centers 3.00/3.03 degrees, FWHM 0.12 degrees, area 80.

In Monitor, choose the example's `integration` folder. Use 1.5 to 5 for 2theta,
or 0.15 to 0.55 for q. Auto-refresh is optional. Select exactly one scan and click
Inspect for its paired detector image; changing selection or refreshing the
watched folder does not implicitly replace the inspected pair. Click its 1D plot
for a calibrated ring guide. For peak tracking, use center 3.0, region 2.5 to 3.5,
shift 0.08, baseline none.

`test` includes original Integration numerical regressions and new shared-code,
Analysis, Monitor, CIF, and isolated-launch checks. It needs a display because
both GUI launchers are exercised. On headless Linux use `xvfb-run -a pixi run
--locked test`; use the same prefix for `smoke`. Smoke tests create temporary data
and preferences. To retain their screenshots/exports:

```sh
pixi run --locked python -m tests.gui_smoke --output "path/to/smoke artifacts"
```

## Settings, outputs, and upgrades

Integration settings are in `~/.xrd-suite/integration.json`. Set
`XRD_SUITE_CONFIG_DIR` to isolate/relocate them. The original applications'
preference files are never used. Monitor keeps editor settings in memory during
its run; the supplied Monitor did not persist preferences. Its beamline base can
be edited in the existing PASS controls or set with `XRD_SUITE_BEAMLINE_BASE`.
Local-file and watched-folder use do not require beamline storage.

Default workspaces/exports are under `~/XRD Suite` (override with
`XRD_SUITE_DATA_DIR`); exports are always user-initiated. File dialogs remember
user-chosen locations. Keep experimental inputs, generated products, and settings
outside the checkout. No automatic migration or data movement is performed.

For an upgrade, download another tagged release into a new source folder, run
`pixi install --locked` there, test with the synthetic example, then choose your
existing experimental data folders. Keep the earlier source/lockfile to reproduce
old work. Maintainers should update dependencies deliberately in a separate change,
regenerate `pixi.lock` with Pixi, rerun tests, and tag only after platform validation.
No remote repository, release, installer, or executable is created by this task.

See [source provenance](docs/PROVENANCE.md) and
[original Integration scientific details](docs/reference/integration/ROBUST_METHODS.md).
