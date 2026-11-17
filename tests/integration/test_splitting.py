"""Splitting selection through numerical, UI, diagnostic and export paths."""
from dataclasses import replace
from pathlib import Path
import threading
import numpy as np
import pytest
from xrd_gui.processing import Engine, sector_pixels
from xrd_gui.settings import Settings, Preferences, restore_method_preferences
from xrd_gui.files import read_image, read_curve
from xrd_gui.jobs import batch_plan, run_batch

EXAMPLE=Path(__file__).resolve().parents[2]/'examples'/'synthetic'


@pytest.mark.parametrize('split',['bbox','full','no'])
@pytest.mark.parametrize('mode',['average','percentile'])
@pytest.mark.parametrize('sector',[False,True])
def test_preview_batch_and_backend(tmp_path,split,mode,sector):
    engine=Engine(EXAMPLE/'synthetic.poni',EXAMPLE/'mask.npy')
    source=next((EXAMPLE/'dark_sub').glob('*.tiff'));image=read_image(source)
    s=Settings(pixel_splitting=split,method_1d=mode,radial_bins=80,
               azimuth_bins=24,radial_range=(1,5),sector=sector,start=150,end=-140,
               error_model='poisson',compare_average=True)
    curves,m,meta=engine.integrate(image,s,source,diagnostics=True)
    curve=curves[0]
    assert curve.metadata['method']==[split,'csr','cython']
    assert meta['method']==[split,'csr','cython']
    mask=engine.base_mask(image)
    if sector:mask |= ~sector_pixels(engine.chi(image.shape),s.start,s.end)
    call=engine.ai.integrate1d_ng if mode=='average' else engine.ai.medfilt1d_ng
    args={} if mode=='average' else {'percentile':(25,75)}
    expected=call(image,s.radial_bins,mask=mask,unit=s.unit,radial_range=s.radial_range,
                  correctSolidAngle=s.solid_angle,polarization_factor=s.polarization,
                  error_model='poisson',method=(split,'csr','cython'),**args)
    valid=np.isfinite(curve.intensity)
    np.testing.assert_allclose(curve.intensity[valid],expected.intensity[valid])
    if mode=='percentile':
        np.testing.assert_array_equal(curve.x,curves[1].x)
        assert curve.diagnostic is not None,curve.metadata['filter_diagnostic']
        d=curve.diagnostic
        np.testing.assert_allclose(d.retained_weight+d.lower_weight+d.upper_weight+d.unresolved_weight,
                                   d.eligible_weight,rtol=1e-6,atol=1e-6)
    # Reuse the very same engine with a different scheme, then switch back.
    engine.integrate(image,replace(s,pixel_splitting='no' if split!='no' else 'full'),two=False)
    again=engine.integrate(image,s,two=False)[0][0]
    np.testing.assert_array_equal(curve.intensity,again.intensity)
    plan=batch_plan([source],tmp_path,['2th_deg'],True,True,'.xye','Keep original',s)
    counts=run_batch(engine,s,plan,'Skip',threading.Event(),lambda *a:None)
    assert counts['saved']==2 and counts['failed']==0
    saved=read_curve(plan[0][3]);keep=valid & ~np.isin(np.arange(len(valid)),curve.metadata['invalid_bins'])
    np.testing.assert_allclose(saved.intensity,curve.intensity[keep],rtol=1e-7)
    np.testing.assert_allclose(saved.sigma,curve.sigma[keep],rtol=1e-7)
    assert saved.metadata['method']==[split,'csr','cython']
    with np.load(plan[1][3]) as exported:
        np.testing.assert_array_equal(exported['intensity'],m.intensity)


def test_defaults_and_strict_backend(monkeypatch):
    from xrd_gui.splitting import integration_method,actual_method,IntegrationMethod
    for mode in ('average','percentile'):
        assert Settings(method_1d=mode).pixel_splitting=='bbox'
    assert restore_method_preferences({})['pixel_splitting']=='bbox'
    assert restore_method_preferences({'integration_methods':{'pixel_splitting':'bad'}})['pixel_splitting']=='bbox'
    monkeypatch.setattr(IntegrationMethod,'select_method',lambda **kw:[])
    with pytest.raises(ValueError,match='unavailable'):integration_method('full')
    from types import SimpleNamespace
    result=SimpleNamespace(method=SimpleNamespace(split='no',algo='csr',impl='cython'))
    with pytest.raises(ValueError,match='substituted'):actual_method(result,('bbox','csr','cython'))


def test_gui_preferences_revisions_and_sigma(tmp_path):
    import tkinter as tk
    try:
        probe=tk.Tk();probe.withdraw();probe.destroy()
    except tk.TclError as exc:
        pytest.skip(f'Tk runtime/display unavailable: {exc}')
    from xrd_gui.gui import App
    prefs=Preferences(tmp_path/'preferences.json')
    app=App(preferences=prefs);app.withdraw()
    try:
        assert app.splitting_display.get()=='Bounding box'
        assert not app.save_metadata.get()
        app.save_metadata.set(True)
        before=(app.revision_1d,app.revision_2d)
        app.splitting_display.set('Full')
        assert (app.revision_1d,app.revision_2d)==(before[0]+1,before[1]+1)
        assert app.settings().pixel_splitting==app.settings(one=False).pixel_splitting=='full'
        app.method_display.set('Sigma-clipping')
        assert app.splitting_control.instate(['disabled'])
        app.method_display.set('Percentile filtering')
        assert app.splitting_control.instate(['readonly','!disabled'])
        assert app.settings().pixel_splitting=='full'
        assert app.settings().percentile_argument==(25,75)
        app.persist_methods()
    finally:
        app.after_cancel(app._poll_job);app.destroy()
    reopened=App(preferences=Preferences(prefs.path));reopened.withdraw()
    try:
        assert reopened.splitting_display.get()=='Full'
        assert reopened.save_metadata.get()
    finally:
        reopened.after_cancel(reopened._poll_job);reopened.destroy()
