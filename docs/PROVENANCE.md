# Source provenance

Integration source and numerical tests were copied from the supplied Integration_GUI
working tree. Scientific behavior, including the NumPy coordinate workaround, is
preserved. Only application wiring, preferences, and wavelength metadata are changed.
Reference documentation in docs/reference describes the original application and
may contain historical machine-specific examples; it is not the suite setup guide.

Monitor source was copied from the supplied xrd_inline_monitor working tree after
it was populated. No Monitor tests, dependency manifests, or documentation were
present. Six calculation functions were extracted verbatim into xrd_suite/peaks.py;
the copied Monitor imports these functions. A frozen test-only reference verifies
numerical equivalence and tracking behavior. Monitor algorithms and layout remain
unchanged; only relative imports, a launcher, and default browsing/output locations
were adapted. No personal preferences are read by Monitor.
No license files were present in these inspected source folders. No third-party
license has been invented or removed. Confirm redistribution rights before release.
No experimental data, notebooks, source Git history, environments, or caches copied.

Shared `xrd_suite/io.py` is the copied Integration IO implementation; its former
module is a compatibility import. A small Monitor lifecycle fix suppresses the
ring-guide redraw when its inspector is being destroyed, avoiding a queued draw
against a closed Tk window. Numerical geometry and monitoring algorithms were
not changed. The existing `twoThetaArray` call intentionally remains unchanged.

The CI workflow uses the official [setup-pixi action](https://github.com/prefix-dev/setup-pixi)
and the documented [runner labels](https://github.com/actions/runner-images#available-images).
`macos-15` is the Apple Silicon runner. CI has been authored, not executed here.
