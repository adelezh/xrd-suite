"""Tk widgets stay on the main thread; workers communicate through a queue."""
import os, sys, json, copy, queue, threading, traceback, subprocess, shutil
from pathlib import Path
from dataclasses import asdict
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from .settings import Settings, Preferences
from .naming import natural_key
from .files import read_image, write_curve, write_map, atomic_write
from .processing import Engine, sector_pixels
from .jobs import batch_plan, run_batch, manipulation_plan, run_manipulation

from .ui_methods import MethodsMixin
from .ui_layout import LayoutMixin
from .ui_plots import PlotMixin
from .ui_jobs import JobsMixin
from .presentation import short_source, curve_labels
from xrd_suite.paths import default_workspace


class App(MethodsMixin, LayoutMixin, PlotMixin, JobsMixin, tk.Tk):
    def __init__(self, preferences=None):
        if os.name == 'nt':
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError): pass
        super().__init__(); self.title('XRD Integration Workspace')
        width=min(1500,self.winfo_screenwidth()-80); height=min(950,self.winfo_screenheight()-100)
        self.geometry(f'{width}x{height}+20+20'); self.minsize(900,600)
        self.prefs = preferences or Preferences(); self.engine = None; self.files = []; self.visible = []; self.active = None; self.image_data = None
        self.curves = []; self.map_result = None; self.map_meta = {}; self.revision = 0; self.revision_1d=0; self.revision_2d=0; self.curve_revision=-1; self.map_revision=-1; self.busy = False; self.events = queue.Queue(); self.cancel = threading.Event()
        self.status = tk.StringVar(value='Load a calibration and TIFF files.'); self.loaded = tk.StringVar(value='No calibration loaded')
        self.workspace = tk.StringVar(value=self.prefs.data.get('workspace',default_workspace())); self.poni = tk.StringVar(); self.mask = tk.StringVar(); self.mask_enabled = tk.BooleanVar(value=True)
        self.shared_controls()
        self.tabs = ttk.Notebook(self); self.tabs.pack(fill='both',expand=True)
        self.integration_tab()
        from .analysis_tab import AnalysisTab
        self.analysis = AnalysisTab(self); self.tabs.add(self.analysis, text='Analysis')
        self.batch_tab(); self.manipulate_tab()
        self.tabs.bind('<<NotebookTabChanged>>', self.analysis_header)
        footer = ttk.Frame(self,padding=(12,6)); footer.pack(side='bottom',fill='x',before=self.tabs)
        self.status_label=ttk.Label(footer,textvariable=self.status,wraplength=800);self.status_label.pack(side='left',fill='x',expand=True)
        footer.bind('<Configure>',lambda e:self.status_label.configure(wraplength=max(200,e.width-160)))
        ttk.Button(footer,text='Processing log',command=self.toggle_log).pack(side='right')
        self.progress=self.integration_actions.progress
        self.log = tk.Text(self,height=7,wrap='word'); self._poll_job=self.after(100,self.poll); self.protocol('WM_DELETE_WINDOW',self.close)
        self.report_callback_exception = lambda typ,exc,tb:self.error(exc, ''.join(traceback.format_exception(typ,exc,tb)))

    def analysis_header(self, event=None):
        # Retained Analysis data do not depend on the currently loaded detector
        # calibration. Hide its editor here without changing its open state.
        if self.tabs.select() == str(self.analysis):
            self.cal_fold.pack_forget()
        elif not self.cal_fold.winfo_manager():
            self.cal_fold.pack(fill='x', pady=(6,0))

    def button(self,parent,text,command):
        b = ttk.Button(parent,text=text,width=0,style='Quiet.TButton',command=lambda:self.guard(command)); b.pack(side='left',padx=2); return b
    def guard(self,fn):
        try: return fn()
        except Exception as e: self.error(e,traceback.format_exc())
    def error(self,e,detail=''):
        self.status.set(str(e))
        if hasattr(self,'tabs'):
            index=self.tabs.index(self.tabs.select())
            if index==0 and hasattr(self,'result_status'):self.result_status.set('Check settings or display controls')
            elif index==2 and hasattr(self,'batch_validation'):self.batch_validation.set(str(e))
            elif index==3 and hasattr(self,'manip_validation'):self.manip_validation.set(str(e))
        self.log.insert('end',detail or str(e)+'\n'); messagebox.showerror('XRD workflow',str(e),parent=self)
    def toggle_log(self):
        if self.log.winfo_manager(): self.log.pack_forget()
        else: self.log.pack(side='bottom',fill='x',before=self.tabs)
    def close(self):
        self.cancel.set()
        try:self.persist_methods(); self.save_panel_sizes()
        except OSError:pass
        self.after_cancel(self._poll_job)
        self.update_idletasks()
        self.destroy()
    def initialdir(self,key): return self.prefs.data.get(key,self.workspace.get())
    def choose(self,key='input',multiple=False,folder=False,types=None):
        kwargs = dict(parent=self,initialdir=self.initialdir(key))
        if types: kwargs['filetypes']=types
        result = filedialog.askdirectory(**kwargs) if folder else (filedialog.askopenfilenames(**kwargs) if multiple else filedialog.askopenfilename(**kwargs))
        if result:
            first = result[0] if multiple else result
            self.prefs.remember(key,first if folder else str(Path(first).parent))
        return result
    def set_workspace(self):
        if not Path(self.workspace.get()).is_dir(): raise ValueError('Workspace folder does not exist.')
        self.prefs.remember('workspace',self.workspace.get()); self.recent.configure(values=self.prefs.data['recent'])
    def browse_workspace(self):
        p = self.choose('workspace',folder=True)
        if p: self.workspace.set(p); self.set_workspace()
    def load_path(self,var,key):
        p = self.choose(key,types=[('Calibration','*.poni')] if key=='calibration' else [('Masks','*.npy *.tif *.tiff *.edf *.cbf'),('All','*.*')])
        if p: var.set(p); self.load_engine()
    def _load_engine(self):
        if self.busy: raise ValueError('Wait for processing to finish before reloading calibration or mask.')
        if not self.poni.get(): raise ValueError('Load a .poni calibration first.')
        engine = Engine(self.poni.get(),self.mask.get() if self.mask_enabled.get() else '')
        if self.image_data is not None: engine.base_mask(self.image_data)
        self.engine = engine; self.loaded.set(f'Loaded: {Path(self.poni.get()).name} | mask: {Path(self.mask.get()).name if engine.mask is not None else "disabled / none"}')
        self.dirty(); self.draw_detector(); self.update_calibration_summary()
    def clear(self):
        if self.busy: raise ValueError('Cancel processing and wait before clearing.')
        self.files=[]; self.visible=[]; self.active=None; self.image_data=None; self.curves=[]; self.map_result=None
        self.refresh_files(); self.engine=None; self.poni.set(''); self.mask.set(''); self.loaded.set('No calibration loaded')
        if self.map_colorbar is not None:self.map_colorbar.remove();self.map_colorbar=None
        for ax,canvas in [(self.det_ax,self.det_canvas),(self.map_ax,self.map_canvas),(self.curve_ax,self.curve_canvas)]: ax.clear(); canvas.draw_idle()
        self.active_text.set('No active file');self.file_details.set('');self.update_calibration_summary();self.result_status.set('No results yet')
        self.refresh_filter_controls()
        self.status.set('Cleared loaded files and validation status.')
    def calibrate(self):
        import importlib.util
        if not any(importlib.util.find_spec(m) for m in ('PyQt6','PySide6','PyQt5','PySide2')): raise ValueError('pyFAI-calib2 needs a Qt binding in this Python environment. Install PyQt6; the main application uses Tkinter.')
        env=os.environ.copy()
        command=[sys.executable,'-m','pyFAI.app.calib2']
        if self.active: command.append(self.active)
        subprocess.Popen(command,cwd=self.workspace.get(),env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.status.set('Calibration launched separately. Load/Reload saved .poni and mask changes explicitly.')
    def dirty(self,*_,one=True,two=True):
        self.revision += 1
        if one:self.revision_1d+=1
        if two:self.revision_2d+=1
        if hasattr(self,'settings_summary'):
            from .presentation import UNIT_LABELS
            self.settings_summary.set(f"{UNIT_LABELS.get(self.svars['unit'].get(),self.svars['unit'].get())} | {self.svars['radial_bins'].get()} bins | "+('Sector' if self.sector.get() else 'Full azimuth'))
        if hasattr(self,'method_vars') and hasattr(self,'settings_summary'):
            self.settings_summary.set(self.settings_summary.get()+' | '+self.method_display.get())
        if self.curves or self.map_result is not None:
            self.status.set('Results need updating - Run to update. Saved results retain their original settings.')
            self.refresh_result_status()
        self.refresh_filter_controls()
    def browse_variance(self):
        p=self.choose('variance')
        if p:self.svars['variance'].set(p)
    def settings(self,one=True):
        v={k:x.get() for k,x in self.svars.items()}; radial=None
        if v['minimum'] or v['maximum']: radial=(float(v['minimum']),float(v['maximum']))
        return Settings(unit=v['unit'],radial_bins=int(v['radial_bins']),azimuth_bins=int(v['azimuth_bins']),radial_range=radial,sector=self.sector.get(),start=float(v['start']),end=float(v['end']),solid_angle=self.solid.get(),polarization=float(v['polarization']),error_model=v['error_model'],variance=v['variance'],compare_full=self.compare.get(),**self.method_options(one)).validate()
    def add_files(self):
        p=self.choose(multiple=True,types=[('TIFF images','*.tif *.tiff')])
        if p:self.files=sorted(set(self.files+list(p)),key=natural_key); self.refresh_files()
    def add_folder(self):
        p=self.choose(folder=True)
        if p:self.files=sorted(set(self.files+[str(f) for f in Path(p).iterdir() if f.suffix.lower() in ('.tif','.tiff')]),key=natural_key); self.refresh_files()
    def load_active(self):
        from xrd_suite.filter_diagnostics import image_identity
        self.image_data=read_image(self.active)
        self.detector_image_id=image_identity(self.image_data)
        self.draw_detector()
    def overlay_update(self):
        try:self.draw_detector()
        except (ValueError,TypeError):pass
    def draw_detector(self):
        if self.image_data is None:
            self.refresh_filter_controls();return
        data=self.image_data; ax=self.det_ax; ax.clear(); ax.set_axis_on(); lo,hi=float(self.low.get()),float(self.high.get())
        if not 0<=lo<hi<=100:raise ValueError('Contrast percentiles need 0 <= low < high <= 100.')
        finite=data[np.isfinite(data)]
        if not finite.size:raise ValueError('Detector image has no finite values.')
        vmin,vmax=np.percentile(finite,[lo,hi]); ax.imshow(data,origin='upper',cmap='gray',vmin=vmin,vmax=vmax); ax.set_aspect('equal')
        if self.engine:
            mask=np.zeros(data.shape,bool)
            for original in (self.engine.mask,self.engine.ai.detector.mask):
                if original is not None:mask |= original != 0
            if self.show_mask.get():
                rgba=np.zeros((*data.shape,4),np.float32);rgba[mask]=(.55,.55,.55,.7)
                ax.imshow(rgba,origin='upper',interpolation='nearest',zorder=6)
            if self.sector.get():
                start,end=float(self.svars['start'].get()),float(self.svars['end'].get()); chi=self.engine.chi(data.shape); region=sector_pixels(chi,start,end)
                ax.imshow(np.ma.masked_where(~region,region),cmap='Blues',alpha=.22,vmin=0,vmax=1,origin='upper',zorder=2)
                for angle in (start,end):
                    delta=(chi-angle+180)%360-180
                    # Mask the opposite-angle discontinuity to avoid a false contour.
                    ax.contour(np.ma.masked_where(abs(delta)>90,delta),levels=[0],colors=['cyan'],linewidths=1,zorder=20)
        self.draw_filter_overlay(ax)
        ax.set_title(short_source(self.active) if self.active else 'Detector',fontsize=10); ax.set_xlabel('Detector column (pixels)'); ax.set_ylabel('Detector row (pixels)'); self.det_canvas.draw_idle()
    def report(self,current,total,text):self.events.put(('progress',(current,total,text)))
    def require_engine(self):
        if not self.engine:raise ValueError('Load a valid calibration first.')
        return copy.deepcopy(self.engine)
    def run_integration(self,one,two):
        settings=self.settings(one); self.persist_methods(); engine=self.require_engine(); engine.freeze_variance(settings); sources=self.selected_files()
        if not sources:raise ValueError('Select one or more TIFF files.')
        active=self.active if self.active in sources else sources[0]; revision=self.revision; rev1=self.revision_1d; rev2=self.revision_2d
        def work():
            curves=[]; result=None; metadata={}
            for i,source in enumerate(sources):
                if self.cancel.is_set():break
                c,m,meta=engine.integrate(read_image(source),settings,source,one,two and source==active,diagnostics=one and source==active); curves.extend(c)
                if m is not None:result=m; metadata=meta
                self.report(i+1,len(sources),f'Integrated {Path(source).name}')
            return curves,result,metadata
        def done(payload):
            curves,result,meta=payload
            if one:self.curves=curves; self.curve_revision=rev1; self.filter_choice.set('0'); self.draw_curves(); self.draw_detector()
            for c in curves:
                missing=len(c.metadata.get("invalid_bins",[]))
                if missing:self.log.insert("end",f"{missing} empty/insufficient bins in {c.metadata.get('method_1d')} curve; reduce bins or restrict range.\n")
            if two:self.map_result=result; self.map_meta=meta; self.map_revision=rev2; self.draw_map()
            self.refresh_result_status()
            self.status.set('Cancelled; completed results retained.' if self.cancel.is_set() else ('Results need updating — inputs/settings changed during processing.' if revision!=self.revision else 'Integration complete. Results are not saved automatically.'))
        self.start_worker(work,done)
    def save_dialog(self,two):
        if (two and self.map_result is None) or (not two and not self.curves):raise ValueError('Run the requested integration first.')
        win=tk.Toplevel(self); win.title('Save 2D' if two else 'Save 1D'); win.transient(self)
        choice=tk.StringVar(value='0'); fmt=tk.StringVar(value='npz' if two else 'xy')
        if not two:
            ttk.Label(win,text='Choose computed curve (original settings retained)').pack()
            ttk.Combobox(win,textvariable=choice,values=[f'{i}: {label}' for i,label in enumerate(curve_labels(self.curves))],width=80,state='readonly').pack()
        ttk.Combobox(win,textvariable=fmt,values=['npz'] if two else ['xy','chi','xye'],state='readonly').pack()
        def save(plot=False):
            ext='.png' if plot else '.'+fmt.get()
            from .naming import output_name, add_method_tag
            meta=self.map_meta if two else self.curves[int(choice.get().split(':')[0])].metadata
            saved_settings=Settings(**meta['settings'])
            name=output_name(meta.get('source','result'),unit='tth' if saved_settings.unit=='2th_deg' else 'q',extension=ext)
            if not two:name=add_method_tag(name,saved_settings)
            p=filedialog.asksaveasfilename(parent=win,initialdir=self.initialdir('output'),initialfile=name,defaultextension=ext,filetypes=[('Output','*'+ext)])
            if not p:return
            if Path(p).exists() or Path(p+'.json').exists():raise ValueError('Choose a new filename to preserve existing output.')
            omitted=0
            if plot:atomic_write(p,lambda q:(self.map_ax if two else self.curve_ax).figure.savefig(q,dpi=180))
            elif two:write_map(p,self.map_result,self.map_meta)
            else:omitted=write_curve(p,self.curves[int(choice.get().split(':')[0])])
            self.prefs.remember('output',str(Path(p).parent)); self.status.set('Saved '+p+(f' ({omitted} undefined bins omitted; see JSON metadata)' if omitted else '')); win.destroy()
        row=ttk.Frame(win); row.pack(); self.button(row,'Save numerical data',save); self.button(row,'Export plot PNG',lambda:save(True))
    def job_folder(self,var):
        p=self.choose('output',folder=True)
        if p:var.set(p)
    def get_batch_plan(self):
        if self.batch_settings and self.bone.get() and self.bvars['extension'].get()=='.xye':self.batch_settings.validate_xye()
        return batch_plan(self.batch_files,self.bvars['folder'].get(),(['2th_deg'] if self.btth.get() else [])+(['q_A^-1'] if self.bq.get() else []),self.bone.get(),self.btwo.get(),self.bvars['extension'].get(),self.bvars['naming'].get(),settings=self.batch_settings)
    def start_batch(self):
        if self.batch_settings is None:raise ValueError('Click Use current diagnostic settings first.')
        settings=self.batch_settings; engine=self.require_engine(); engine.freeze_variance(settings); plan=self.get_batch_plan(); self.preview_batch(); policy=self.bvars['policy'].get()
        self.start_worker(lambda:run_batch(engine,settings,plan,policy,self.cancel,self.report),self.job_finished)
    def job_finished(self,counts):self.status.set('Complete: '+', '.join(f'{k}: {v}' for k,v in counts.items())); self.log.insert('end',self.status.get()+'\n')

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-check', action='store_true')
    options = parser.parse_args()
    app = App()
    if options.smoke_check:
        app.after(500, app.close)
    app.mainloop()
