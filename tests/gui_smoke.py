"""Run real Tk workflows on a local display, with temporary data/settings only."""
from pathlib import Path
import os
import tempfile
import time
import json
from unittest.mock import patch


def pump(app,condition=lambda:True,timeout=90):
    start=time.monotonic()
    while True:
        app.update()
        if condition():return
        if time.monotonic()-start>timeout:raise TimeoutError('GUI operation timed out')
        time.sleep(.02)

def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)

def invoke(widget,text):
    from tkinter import ttk
    buttons=[w for w in descendants(widget) if isinstance(w,ttk.Button) and w.cget('text')==text]
    assert len(buttons)==1,(text,len(buttons))
    buttons[0].invoke()

def capture(app,path):
    from PIL import ImageGrab
    app.lift();app.update()
    x,y=app.winfo_rootx(),app.winfo_rooty()
    ImageGrab.grab(bbox=(x,y,x+app.winfo_width(),y+app.winfo_height())).save(path)

def integration_checks(folder,output):
    import tkinter as tk
    import numpy as np
    from xrd_gui.gui import App
    from xrd_gui.settings import Preferences
    from xrd_suite.analysis import import_curve
    app=App(Preferences(Path(os.environ['XRD_SUITE_CONFIG_DIR'])/'integration.json'))
    errors=[];app.error=lambda exc,detail='':errors.append(str(exc))
    try:
        app.geometry('1450x950+10+10');pump(app)
        assert [app.tabs.tab(t,'text') for t in app.tabs.tabs()]==['Integration','Analysis','Batch Integration','File Manipulate']
        app.poni.set(str(folder/'synthetic.poni'));app.mask.set(str(folder/'mask.npy'));app.load_engine();app.cal_fold.set_open(False)
        app.files=list(map(str,sorted((folder/'dark_sub').glob('*.tiff'))));app.refresh_files()
        app.file_tree.selection_set(app.file_tree.get_children());app.select_file()
        app.svars['radial_bins'].set('120');app.svars['azimuth_bins'].set('36');app.svars['error_model'].set('poisson')
        app.run_integration(True,True);pump(app,lambda:not app.busy)
        assert len(app.curves)==2 and app.map_result is not None
        panel=app.analysis
        panel.choose_results();invoke(app,'Add selected to Analysis');pump(app)
        assert len(panel.collection.entries)==2
        first=next(iter(panel.collection.entries.values())).snapshot;old_y=first.intensity.copy();old_meta=first.metadata
        app.tabs.select(0);app.mask_enabled.set(False);app.load_engine();app.method_display.set('Percentile filtering');app.compare_average.set(True)
        app.run_integration(True,False);pump(app,lambda:not app.busy)
        assert len(app.curves)==4
        panel.choose_results();invoke(app,'Add selected to Analysis');pump(app)
        assert len(panel.collection.entries)==6
        np.testing.assert_array_equal(first.intensity,old_y);assert first.metadata==old_meta
        # Existing batch/manipulation workflows must still target their action bars.
        app.tabs.select(2);app.batch_files=app.files[:1];app.bvars['folder'].set(str(output/'batch'));app.bvars['naming'].set('Keep original');app.capture_batch()
        app.start_batch();pump(app,lambda:not app.busy)
        products=list((output/'batch').glob('*.xy'));assert products
        app.tabs.select(3);app.manip_files=[str(products[0])];app.operation.set('For TOPAS');app.mvars['folder'].set(str(output/'topas'));app.mvars['naming'].set('Keep original');app.mvars['extension'].set('.xy')
        app.start_manip();pump(app,lambda:not app.busy);assert list((output/'topas').glob('*.xy'))
        app.clear();assert len(panel.collection.entries)==6
        np.testing.assert_array_equal(first.intensity,old_y)
        app.tabs.select(panel)
        ids=panel.add_curves([import_curve(folder/'peak-1.xye'),import_curve(folder/'peak-2.xye')])
        panel.fit_fold.set_open(True)
        panel.tree.selection_set(ids);panel.fit_selected();pump(app,lambda:not panel.busy)
        panel.fit_fold.set_open(False)
        assert all(panel.collection.entries[key].fit.status=='ok' for key in ids)
        panel.normalization.set('max absolute');panel.offset.set('1.2');panel.redraw()
        for key in ids:assert panel.collection.entries[key].fit.parameters['area']>79.99
        panel.tree.selection_set(ids[0]);panel.label.set('Reference peak');panel.rename()
        assert panel.collection.entries[ids[0]].label=='Reference peak'
        panel.results.selection_set(ids[0]);panel.inspect_fit();pump(app)
        for win in app.winfo_children():
            if isinstance(win,tk.Toplevel):win.destroy()
        panel.ax.set_xlim(2.7,3.3);limits=panel.ax.get_xlim();selection=panel.tree.selection()
        for tab in app.tabs.tabs():app.tabs.select(tab);pump(app)
        app.tabs.select(panel);pump(app)
        assert panel.tree.selection()==selection and panel.ax.get_xlim()==limits
        panel.tree.selection_set(ids);panel.fit_selected()
        panel.fit_vars['lam'].set('450000');pump(app,lambda:not panel.busy)
        assert all(entry.fit is None for entry in panel.collection.entries.values())
        panel.fit_vars['lam'].set('400000');assert all(entry.fit is None for entry in panel.collection.entries.values())
        panel.tree.selection_set(ids);panel.fit_selected();pump(app,lambda:not panel.busy)
        with patch('tkinter.filedialog.asksaveasfilename',return_value=str(output/'fits.csv')):panel.export_csv()
        with patch('tkinter.filedialog.asksaveasfilename',return_value=str(output/'overlay.png')):panel.export_plot()
        assert (output/'fits.csv').stat().st_size>100 and (output/'overlay.png').stat().st_size>1000
        panel.tree.selection_set(ids[0]);panel.toggle_visibility();assert not panel.collection.entries[ids[0]].visible
        panel.toggle_visibility();panel.remove_selected();assert ids[0] not in panel.collection.entries
        # Unknown units require an explicit assignment; no implicit conversion.
        unknown=output/'unknown.xy';np.savetxt(unknown,np.c_[np.arange(10.),np.arange(10.)])
        with patch('tkinter.filedialog.askopenfilenames',return_value=[str(unknown)]):panel.import_dialog()
        pump(app,lambda:not panel.busy);unknown_id=panel.tree.selection()[0]
        assert panel.collection.entries[unknown_id].snapshot.unit=='unknown'
        panel.assign_units();invoke(app,'Assign');pump(app)
        assert panel.collection.entries[unknown_id].snapshot.unit=='2th_deg'
        panel.tree.selection_set(unknown_id);panel.remove_selected()
        panel.tree.selection_set(ids[1]);panel.results.see(ids[1]);panel.unit.set('2th_deg');panel.legend.set(False);panel.redraw()
        app.geometry('1100x800+10+10');pump(app);assert panel.canvas.get_tk_widget().winfo_width()>400
        capture(app,output/'analysis-small.png')
        assert panel.canvas.get_tk_widget().winfo_height()>180
        app.geometry('1450x950+10+10');pump(app);capture(app,output/'analysis-window.png')
        panel.clear_collection();assert not panel.collection.entries
        assert not errors,errors
        print('Integration GUI: four tabs, repeated snapshots, batch, manipulation, retention, import, units, fitting, residuals, rename, visibility, exports, removal, resize passed.',flush=True)
    finally:app.close()

def monitor_checks(folder,output):
    import numpy as np
    import matplotlib.pyplot as plt
    from xrd_monitor.xrd_map_gui import XRDMapGUI
    app=XRDMapGUI();errors=[]
    app.report_callback_exception=lambda typ,exc,tb:errors.append(str(exc))
    try:
        with patch('tkinter.messagebox.showerror',side_effect=lambda *a,**k:errors.append(str(a))),patch('tkinter.messagebox.showwarning'):
            app.geometry('1000x950+10+10');pump(app)
            app.watch_folder_var.set(str(folder/'integration'));app.xmin_var.set('1.5');app.xmax_var.set('5')
            app._auto_scan_and_plot();pump(app)
            assert len(app.selected_files)==2 and all('_tth.chi' in p for p in app.selected_files)
            assert app._ext_fig is not None and app._calibration is not None
            app.plot_mode_var.set('overlay');app.plot();pump(app)
            selected=app.selected_files[0];app.file_list.selection_set(selected);app.show_detector_inspector();pump(app)
            assert app._detector_pair['scan']==1 and app._detector_fig is not None
            app._ring_angle=np.radians(3);app._render_ring();pump(app);assert app._ring_contour is not None
            pair=app._detector_pair
            app.file_list.selection_set(app.selected_files[1]);app._file_selection_changed();pump(app)
            assert app._detector_pair is pair
            before=app._last_snapshot
            path=folder/'integration/synthetic_primary-2_mean_tth.chi';path.write_text(path.read_text()+'\n')
            app._auto_scan_and_plot();pump(app);assert app._last_snapshot!=before and app._detector_pair is pair
            app.type_var.set('q');app.xmin_var.set('0.15');app.xmax_var.set('0.55');app._auto_scan_and_plot();pump(app)
            assert len(app.selected_files)==2 and all('_q.chi' in p for p in app.selected_files)
            app.type_var.set('tth');app.xmin_var.set('1.5');app.xmax_var.set('5');app._auto_scan_and_plot();pump(app)
            app.add_peak_track(initial_center=3.,xmin=2.5,xmax=3.5,max_shift=.08,baseline_method='none')
            app.fit_peak_trend();pump(app);assert app._peak_fig is not None
            app.sim_xmin_var.set('2.5');app.sim_xmax_var.set('3.5');app.plot_similarity_trend();pump(app)
            assert app._similarity_fig is not None
            capture(app,output/'monitor-window.png')
            assert not errors,errors
            print('Monitor GUI: watcher signatures, q/tth filtering, map/overlay external plots, scan identity, explicit detector inspection, calibration, ring guide, tracking and similarity passed.',flush=True)
    finally:
        plt.close('all');app.update_idletasks()
        app.destroy()

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    options=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='xrd suite smoke ') as directory:
        temp=Path(directory);output=options.output or temp/'artifacts';output.mkdir(parents=True,exist_ok=True)
        os.environ.update(XRD_SUITE_CONFIG_DIR=str(temp/'config'),XRD_SUITE_DATA_DIR=str(temp/'data'),MPLCONFIGDIR=str(temp/'mpl'))
        from xrd_suite.example import generate
        folder=generate(temp/'synthetic example')
        integration_checks(folder,output)
        monitor_checks(folder,output)
        (output/'smoke-results.json').write_text(json.dumps({'integration':'passed','monitor':'passed','platform':os.name},indent=2))
        print('GUI smoke checks passed. Artifacts:',output,flush=True)

if __name__=='__main__':main()
