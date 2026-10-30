"""Real Tk detector-overlay lifecycle and visual smoke check (synthetic data only)."""
from pathlib import Path
import os
import tempfile
import tkinter as tk
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from tests.gui_smoke import pump, invoke


def capture(window, path):
    from PIL import ImageGrab
    window.update_idletasks()
    if os.name == "nt":
        ImageGrab.grab(window=int(window.wm_frame(), 0)).save(path)
    else:
        from tests.gui_smoke import capture as screen_capture
        screen_capture(window, path)
    if hasattr(window, "det_ax"):
        window.det_ax.figure.savefig(path.with_stem(path.stem+"-detector"), dpi=140)


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    output=parser.parse_args().output;output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='xrd filter overlay ') as folder:
        temp=Path(folder)
        os.environ.update(XRD_SUITE_CONFIG_DIR=str(temp/'config'),XRD_SUITE_DATA_DIR=str(temp/'data'),MPLCONFIGDIR=str(temp/'mpl'))
        from xrd_suite.example import generate
        from xrd_gui.gui import App
        from xrd_gui.settings import Preferences
        from xrd_gui.processing import Engine
        fixture=generate(temp/'synthetic')
        # Deterministic synthetic noise breaks radial-symmetry ties for visual checks.
        # A separate unchanged symmetric image below exercises partial tie diagnostics.
        from tifffile import imread, imwrite
        tied_path=temp/'symmetric-with-ties.tiff'
        imwrite(tied_path,imread(next((fixture/'dark_sub').glob('*.tiff'))))
        rng=np.random.default_rng(357)
        for path in (fixture/'dark_sub').glob('*.tiff'):
            data=imread(path).astype(float);data+=rng.normal(0,.01,data.shape)
            data[50:55,15:20]+=2000
            imwrite(path,data)
        app=App(Preferences(temp/'config/integration.json'));errors=[]
        app.error=lambda exc,detail='':errors.append(str(exc)+'\n'+detail)
        try:
            app.geometry('1450x950+10+10');pump(app)
            app.poni.set(str(fixture/'synthetic.poni'));app.mask.set(str(fixture/'mask.npy'));app.load_engine();app.cal_fold.set_open(False)
            app.files=list(map(str,sorted((fixture/'dark_sub').glob('*.tiff'))));app.refresh_files()
            app.file_tree.selection_set(app.file_tree.get_children());app.file_tree.focus('0');app.select_file()
            app.svars['radial_bins'].set('40');app.svars['azimuth_bins'].set('24')
            app.method_display.set('Sigma-clipping');app.compare_average.set(True)
            app.sector.set(True);app.svars['start'].set('150');app.svars['end'].set('-140');app.compare.set(True)
            pump(app);app.run_integration(True,True);pump(app,lambda:not app.busy)
            assert not errors,errors
            assert 'disabled' not in app.filter_check.state(),app.filter_notice.get()
            assert sum(c.diagnostic is not None for c in app.curves)==2 # only active file, primary/full
            original=[c.intensity.copy() for c in app.curves];image=app.image_data.copy();mask=app.engine.mask.copy();map_data=app.map_result.intensity.copy()
            app.filter_check.invoke();pump(app)
            assert app.filter_artist is not None
            assert app.filter_artist.origin=='upper'
            assert app.det_ax.get_aspect()==1
            h,w=image.shape;assert tuple(app.filter_artist.get_extent())==(-.5,w-.5,h-.5,-.5)
            assert all(artist.get_zorder()>app.filter_artist.get_zorder() for artist in app.det_ax.collections)
            capture(app,output/'sigma-overlay.png')
            with patch.object(Engine,'integrate',side_effect=AssertionError('Rendering invoked integration')):
                for opacity in ['0','0.25','0.8']:
                    app.filter_opacity.set(opacity);app.draw_detector();pump(app)
                    assert app.filter_artist is not None
                app.filter_check.invoke();pump(app);assert app.filter_artist is None
                app.filter_check.invoke();pump(app)
                app.contrast_dialog(False);pump(app)
                assert not errors,errors
                capture(next(w for w in app.winfo_children() if isinstance(w,tk.Toplevel)),output/'display-settings.png')
                # Select the full filtered comparison; comparison average never appears.
                choices=app.filter_candidates();assert len(choices)==2
                app.filter_choice.set(str(choices[-1][0]));invoke(app,'Apply');pump(app)
                assert app.selected_filter_curve().metadata['selection']=='full comparison'
                assert 'full comparison' in app.filter_notice.get()
                for win in app.winfo_children():
                    if isinstance(win,tk.Toplevel):win.destroy()
            for old,curve in zip(original,app.curves):np.testing.assert_array_equal(old,curve.intensity)
            np.testing.assert_array_equal(image,app.image_data);np.testing.assert_array_equal(mask,app.engine.mask)
            np.testing.assert_array_equal(map_data,app.map_result.intensity)
            # Changing method/settings immediately removes the old exclusion artist.
            app.method_display.set('Percentile filtering');assert app.filter_artist is None
            assert 'disabled' in app.filter_check.state()
            app.run_integration(True,False);pump(app,lambda:not app.busy)
            assert 'disabled' not in app.filter_check.state(),app.filter_notice.get()
            app.filter_check.invoke();app.filter_opacity.set('0.55');app.draw_detector();pump(app)
            assert app.filter_artist is not None
            capture(app,output/'percentile-overlay.png')
            app.geometry('1100x800+10+10');pump(app);capture(app,output/'overlay-small.png')
            assert app.filter_check.winfo_ismapped()
            assert app.filter_check.winfo_width()>=app.filter_check.winfo_reqwidth()
            assert app.det_ax.get_window_extent().width>180
            assert app.curve_ax.get_window_extent().height>50
            assert len(app.curve_ax.lines)==len(app.curves)
            assert app.filter_check.winfo_x()+app.filter_check.winfo_width()<=app.filter_check.master.winfo_width()
            # Actual asynchronous computation, deliberately delivered after input revision changes.
            pending=[]
            with patch.object(app,'start_worker',side_effect=lambda work,done:pending.append((work,done))):
                app.run_integration(True,False)
            work,done=pending.pop()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(work)
                app.file_tree.focus('1');app.select_file();pump(app)
                assert app.filter_artist is None and not app.show_filter.get()
                payload=future.result(timeout=60)
            done(payload);pump(app)
            assert 'disabled' in app.filter_check.state() and app.filter_artist is None
            assert 'Outdated' in app.filter_notice.get()
            # Calibration/mask reload invalidates the overlay even for identical image content.
            app.run_integration(True,False);pump(app,lambda:not app.busy)
            assert 'disabled' not in app.filter_check.state(),app.filter_notice.get()
            app.filter_check.invoke();app.mask_enabled.set(False);app.load_engine();pump(app)
            assert app.filter_artist is None and 'disabled' in app.filter_check.state()
            # Regression: the original symmetric example used to disable the entire overlay.
            app.files.append(str(tied_path));app.refresh_files()
            iid=str(app.visible.index(str(tied_path)))
            app.file_tree.selection_set(iid);app.file_tree.focus(iid);app.select_file()
            app.sector.set(False);app.compare.set(False);app.svars['radial_bins'].set('40')
            app.run_integration(True,False);pump(app,lambda:not app.busy)
            diagnostic=app.selected_filter_curve().diagnostic
            assert diagnostic is not None and diagnostic.exactness=='partial',app.filter_notice.get()
            assert 'Partial' in app.filter_notice.get() and 'disabled' not in app.filter_check.state()
            values=app.curves[0].intensity.copy()
            with patch.object(Engine,'integrate',side_effect=AssertionError('Rendering invoked integration')):
                app.filter_check.invoke();app.draw_detector();pump(app)
                assert app.filter_artist is not None
                assert any('Unknown' in label.get_text() for label in app.filter_legend.get_texts())
                capture(app,output/'percentile-ties-partial.png')
                app.filter_opacity.set('0.3');app.draw_detector();pump(app)
                app.filter_check.invoke();app.filter_check.invoke();pump(app)
            np.testing.assert_array_equal(values,app.curves[0].intensity)
            app.method_display.set('Average');app.run_integration(True,False);pump(app,lambda:not app.busy)
            assert all(c.diagnostic is None for c in app.curves)
            assert 'disabled' in app.filter_check.state()
            app.clear_file_list();pump(app)
            assert app.image_data is None and app.filter_artist is None and 'disabled' in app.filter_check.state()
            assert not errors,errors
            print('Filter GUI passed: render-only toggles/opacity, exact alignment, legend/cake ordering, comparison selection, two-result bound, file/settings/mask invalidation, async stale rejection, Average, clear, resize.',flush=True)
        finally:app.close()


if __name__=='__main__':main()
