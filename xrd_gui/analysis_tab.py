"""Retained-curve Analysis UI. All Tk operations run on the main thread."""
import queue
import textwrap
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from .widgets import Fold
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from xrd_suite.analysis import (Collection, FitSettings, UNITS, import_curve,
    display_values, fit_snapshot, export_fits)

class AnalysisTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.tabs, padding=6)
        self.app = app
        self.collection = Collection()
        self.generation = 0
        self.busy = False
        self.events = queue.Queue()
        self.notice = tk.StringVar(value='Retain computed curves with Add to Analysis, or import XY / CHI / XYE.')
        self.unit = tk.StringVar(value='2th_deg')
        self.label = tk.StringVar()
        self.normalization = tk.StringVar(value='none')
        self.offset = tk.StringVar(value='0')
        self.display_min = tk.StringVar()
        self.display_max = tk.StringVar()
        self.show_fit = tk.BooleanVar(value=True)
        self.legend = tk.BooleanVar(value=True)
        self.fit_vars = {key:tk.StringVar(value=value) for key,value in
            dict(xmin='2.5', xmax='3.5', baseline='none', lam='500000', fwhm_guess='0.05', min_r_squared='0.9').items()}
        self.build()
        for var in self.fit_vars.values():
            var.trace_add('write', self.invalidate)
        self._poll_id = self.after(100, self.poll)
        self.bind('<Destroy>', self.on_destroy, add='+')

    def on_destroy(self, event):
        if event.widget is self:
            self.after_cancel(self._poll_id)

    def button(self, parent, text, command):
        return self.app.button(parent, text, command)

    def build(self):
        panes = ttk.Panedwindow(self, orient='horizontal')
        panes.pack(fill='both', expand=True)
        left, main = ttk.Frame(panes, padding=4), ttk.Frame(panes, padding=4)
        panes.add(left, weight=1); panes.add(main, weight=4)
        row = ttk.Frame(left); row.pack(fill='x')
        self.button(row, 'Import curves', self.import_dialog)
        self.button(row, 'Remove', self.remove_selected)
        self.button(row, 'Clear', self.clear_collection)
        self.tree = ttk.Treeview(left, columns=('visible','label'), show='headings', selectmode='extended', height=12)
        self.tree.heading('visible', text='Show'); self.tree.heading('label', text='Retained curves')
        self.tree.column('visible', width=66, stretch=False); self.tree.column('label', width=230)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.selected)
        self.tree.bind('<Double-1>', self.double_click)
        row = ttk.Frame(left); row.pack(fill='x', pady=3)
        self.button(row, 'Toggle visibility', self.toggle_visibility)
        self.button(row, 'Assign unknown units', self.assign_units)
        ttk.Label(left, text='Label for selected curve').pack(anchor='w')
        row = ttk.Frame(left); row.pack(fill='x')
        ttk.Entry(row, textvariable=self.label).pack(side='left', fill='x', expand=True)
        self.button(row, 'Rename', self.rename)
        self.button(left, 'Metadata', self.metadata_dialog)
        self.figure = Figure(figsize=(8,5))
        self.figure.subplots_adjust(left=.11,right=.98,bottom=.18,top=.90)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, main)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        self.toolbar = NavigationToolbar2Tk(self.canvas, main, pack_toolbar=False)
        self.toolbar.pack(fill='x')
        row = ttk.Frame(main); row.pack(fill='x', pady=3)
        ttk.Label(row, text='Display units').pack(side='left')
        box=ttk.Combobox(row,textvariable=self.unit,values=UNITS,state='readonly',width=10);box.pack(side='left')
        box.bind('<<ComboboxSelected>>',lambda _:self.app.guard(self.redraw))
        for title,var,width in [('Min',self.display_min,7),('Max',self.display_max,7),('Offset',self.offset,6)]:
            ttk.Label(row,text=title).pack(side='left',padx=(5,1));ttk.Entry(row,textvariable=var,width=width).pack(side='left')
        self.button(row,'Apply display',self.redraw)
        row=ttk.Frame(main);row.pack(fill='x')
        ttk.Label(row,text='Display normalization').pack(side='left')
        ttk.Combobox(row,textvariable=self.normalization,values=['none','max absolute'],state='readonly',width=13).pack(side='left')
        ttk.Checkbutton(row,text='Show fits',variable=self.show_fit,command=lambda:self.app.guard(self.redraw)).pack(side='left')
        ttk.Checkbutton(row,text='Legend',variable=self.legend,command=lambda:self.app.guard(self.redraw)).pack(side='left')
        self.button(row,'Export PNG',self.export_plot)
        self.fit_fold=Fold(main,'Peak-fit settings (original intensities)',opened=False)
        self.fit_fold.pack(fill='x',pady=4)
        fit=self.fit_fold.body
        row=ttk.Frame(fit);row.pack(fill='x')
        for title,key,width in [('Region min','xmin',7),('Region max','xmax',7),('FWHM guess','fwhm_guess',7)]:
            ttk.Label(row,text=title).pack(side='left',padx=(4,1));ttk.Entry(row,textvariable=self.fit_vars[key],width=width).pack(side='left')
        self.button(row,'Fit selected',self.fit_selected)
        row=ttk.Frame(fit);row.pack(fill='x',pady=3)
        ttk.Label(row,text='Baseline').pack(side='left')
        ttk.Combobox(row,textvariable=self.fit_vars['baseline'],values=['none','arpls','asls'],state='readonly',width=7).pack(side='left')
        for title,key,width in [('Lambda','lam',9),('Min R squared','min_r_squared',5)]:
            ttk.Label(row,text=title).pack(side='left',padx=(5,1));ttk.Entry(row,textvariable=self.fit_vars[key],width=width).pack(side='left')
        ttk.Label(fit,text='Unweighted fit + constant offset; baseline uses the entire finite curve.',style='Muted.TLabel',wraplength=700).pack(anchor='w')
        self.results=ttk.Treeview(main,columns=('label','center','fwhm','area','status'),show='headings',height=2)
        for key,width in [('label',210),('center',85),('fwhm',85),('area',95),('status',110)]:
            self.results.heading(key,text={'fwhm':'FWHM','area':'Peak area'}.get(key,key.title()));self.results.column(key,width=width,stretch=key=='label')
        self.results.pack(fill='x')
        self.results.bind('<<TreeviewSelect>>',self.result_selected)
        row=ttk.Frame(main);row.pack(fill='x')
        self.button(row,'Inspect fit / residuals',self.inspect_fit)
        self.button(row,'Export fits CSV',self.export_csv)
        # Reserve controls before distributing the remaining height to the plot/list.
        # A packed Matplotlib widget otherwise consumes the requested height and
        # can push the fitting controls outside shorter/high-DPI windows.
        for container, expanding_row in ((main,0),(left,1)):
            children=container.winfo_children()
            for child in children:child.pack_forget()
            for row,child in enumerate(children):
                child.grid(row=row,column=0,sticky='nsew' if row==expanding_row else 'ew')
            container.columnconfigure(0,weight=1)
            container.rowconfigure(expanding_row,weight=1)
        self.canvas.get_tk_widget().configure(height=180,width=400)
        ttk.Label(self,textvariable=self.notice,wraplength=1000,style='Muted.TLabel').pack(side='bottom',fill='x',pady=4,before=panes)
        self.redraw()

    def selected(self, event=None):
        ids=self.tree.selection()
        self.label.set(self.collection.entries[ids[0]].label if len(ids)==1 else '')

    def result_selected(self,event=None):
        ids=self.results.selection()
        if ids:
            self.tree.selection_set(ids)
            entry=self.collection.entries[ids[0]]
            if entry.fit:self.notice.set(entry.fit.status+': '+entry.fit.detail)

    def double_click(self,event):
        if self.tree.identify_column(event.x)=='#1':self.app.guard(self.toggle_visibility)

    def refresh(self,selected=None):
        selected=list(self.tree.selection() if selected is None else selected)
        for key,entry in self.collection.entries.items():
            values=('yes' if entry.visible else 'no',entry.label)
            if self.tree.exists(key):self.tree.item(key,values=values)
            else:self.tree.insert('', 'end',iid=key,values=values)
        for key in self.tree.get_children():
            if key not in self.collection.entries:self.tree.delete(key)
        self.tree.selection_set([key for key in selected if key in self.collection.entries])
        self.refresh_results()

    def refresh_results(self):
        selection=self.results.selection()
        for key in self.results.get_children():self.results.delete(key)
        for key,entry in self.collection.entries.items():
            fit=entry.fit;params=fit.parameters if fit else {}
            values=[entry.label]+[f'{params[k]:.7g}' if k in params else '' for k in ('center','fwhm','area')]+[fit.status if fit else 'not fitted']
            self.results.insert('','end',iid=key,values=values)
        self.results.selection_set([key for key in selection if key in self.collection.entries])

    def add_curves(self,curves):
        ids=self.collection.add(curves)
        if ids:
            self.unit.set(self.collection.entries[ids[0]].snapshot.unit)
            self.refresh(ids);self.redraw()
            self.notice.set(f'Added {len(ids)} independent snapshots. Analysis has {len(self.collection.entries)} curves. Collection is held in memory.')
        return ids

    def choose_results(self):
        if not self.app.curves:raise ValueError('Run a 1D integration first.')
        from .presentation import curve_labels
        # Freeze now so later diagnostic updates cannot change the chooser content.
        from xrd_suite.analysis import Snapshot
        captures=[Snapshot.capture(c) for c in self.app.curves]
        win=tk.Toplevel(self);win.title('Add computed curves to Analysis');win.transient(self.app)
        ttk.Label(win,text='Select computed results to retain as independent snapshots.').pack(padx=12,pady=8)
        choices=tk.Listbox(win,selectmode='extended',exportselection=False,width=100,height=min(12,len(captures)))
        choices.pack(fill='both',expand=True,padx=12)
        for label in curve_labels(self.app.curves):choices.insert('end',label)
        choices.selection_set(0,'end')
        def add():
            selected=choices.curselection()
            if not selected:raise ValueError('Select at least one computed result.')
            self.add_curves([captures[i] for i in selected])
            self.app.tabs.select(self);win.destroy()
        self.button(win,'Add selected to Analysis',add)

    def import_dialog(self):
        paths=filedialog.askopenfilenames(parent=self,initialdir=self.app.initialdir('input'),filetypes=[('Curves','*.xy *.chi *.xye')])
        if not paths:return
        def done(curves):
            self.add_curves(curves)
            if any(e.snapshot.unit=='unknown' for e in self.collection.entries.values()):
                self.notice.set('Unknown-unit curves are isolated in the unknown display group. Assign their units before fitting or comparing with known-unit curves.')
        self.work(lambda:[import_curve(p) for p in paths],done)

    def assign_units(self):
        ids=self.tree.selection()
        if not ids:raise ValueError('Select unknown-unit curves first.')
        if any(self.collection.entries[key].snapshot.unit!='unknown' for key in ids):raise ValueError('Select only unknown-unit curves.')
        win=tk.Toplevel(self);win.title('Assign units (no conversion)');win.transient(self.app)
        var=tk.StringVar(value=UNITS[0])
        ttk.Label(win,text='What units do these coordinates already use?').pack(padx=12,pady=8)
        ttk.Combobox(win,textvariable=var,values=UNITS[:2],state='readonly').pack(padx=12)
        def assign():
            self.collection.assign_unit(ids,var.get());self.generation+=1;self.unit.set(var.get());self.refresh(ids);self.redraw();win.destroy()
        self.button(win,'Assign',assign)

    def rename(self):
        ids=self.tree.selection()
        if len(ids)!=1 or not self.label.get().strip():raise ValueError('Select one curve and enter a nonempty label.')
        self.collection.entries[ids[0]].label=self.label.get().strip();self.refresh(ids);self.redraw()

    def toggle_visibility(self):
        for key in self.tree.selection():self.collection.entries[key].visible=not self.collection.entries[key].visible
        self.refresh();self.redraw()

    def remove_selected(self):
        self.collection.remove(self.tree.selection());self.refresh();self.redraw()
        self.notice.set(f'{len(self.collection.entries)} retained curves; open Peak-fit settings to fit selected curves.')

    def clear_collection(self):
        self.collection.remove(list(self.collection.entries));self.generation+=1;self.refresh();self.redraw()
        self.notice.set('Analysis collection cleared explicitly.')

    def metadata_dialog(self):
        ids=self.tree.selection()
        if not ids:raise ValueError('Select a curve to inspect metadata.')
        import json
        text='\n\n'.join(self.collection.entries[key].label+'\n'+json.dumps(self.collection.entries[key].snapshot.metadata,indent=2) for key in ids)
        self.app.help_dialog('Retained curve provenance',text)

    def redraw(self):
        offset=float(self.offset.get())
        if not np.isfinite(offset):raise ValueError('Display offset must be finite.')
        limits=None
        if self.display_min.get() or self.display_max.get():
            limits=(float(self.display_min.get()),float(self.display_max.get()))
            if not np.isfinite(limits).all() or limits[0]>=limits[1]:raise ValueError('Display range needs finite minimum < maximum.')
        self.ax.clear();count=0
        for entry in self.collection.entries.values():
            snap=entry.snapshot
            if not entry.visible or snap.unit!=self.unit.get():continue
            y,scale=display_values(snap,self.normalization.get(),count*offset)
            line,=self.ax.plot(snap.x,y,label=textwrap.fill(entry.label,52),linewidth=1)
            if self.show_fit.get() and entry.fit and entry.fit.status=='ok':
                fit=entry.fit
                self.ax.plot(fit.x,fit.best_fit/scale+count*offset,'--',color=line.get_color(),linewidth=1.6)
            count+=1
        self.ax.set_xlabel({'2th_deg':'2theta (degrees)','q_A^-1':'q (1/angstrom)','unknown':'Unknown units - assign before combining'}.get(self.unit.get()))
        self.ax.set_ylabel('Intensity' if self.normalization.get()=='none' else 'Display intensity\n(max normalized)')
        self.ax.set_title('Retained curves'+(f' | display offset {offset:g}' if offset else ''))
        if count and self.legend.get():self.ax.legend(fontsize=7,loc='best')
        if limits:self.ax.set_xlim(*limits)
        self.toolbar.update();self.canvas.draw_idle()

    def invalidate(self,*_):
        self.generation+=1;self.collection.invalidate_fits()
        self.refresh_results()
        # Remove old overlays immediately, even while display fields are being edited.
        self.redraw_safely()
        self.notice.set('Fit inputs changed; previous fits cleared. Fit selected to recalculate.')

    def redraw_safely(self):
        try:self.redraw()
        except ValueError:
            self.ax.clear();self.canvas.draw_idle()

    def fit_settings(self):
        return FitSettings(**{key:(var.get() if key=='baseline' else float(var.get())) for key,var in self.fit_vars.items()}).validate()

    def fit_selected(self):
        snapshots=self.collection.selected_snapshots(self.tree.selection())
        settings=self.fit_settings();generation=self.generation
        def done(results):
            if generation!=self.generation:
                self.notice.set('Fit inputs changed during processing; obsolete results discarded.');return
            for result in results:
                if result.snapshot_id in self.collection.entries:self.collection.entries[result.snapshot_id].fit=result
            self.refresh_results();self.redraw_safely()
            self.notice.set(f'Finished {len(results)} independent fits; '+', '.join(f'{status}: {sum(r.status==status for r in results)}' for status in ('ok','failed','ambiguous')))
        self.work(lambda:[fit_snapshot(snap,settings) for snap in snapshots],done)

    def work(self,operation,done):
        if self.busy:raise ValueError('Wait for the current Analysis operation to finish.')
        self.busy=True;self.notice.set('Processing Analysis...');self._done=done
        def target():
            try:self.events.put((True,operation()))
            except Exception as exc:self.events.put((False,exc))
        threading.Thread(target=target,daemon=True).start()

    def poll(self):
        try:
            ok,payload=self.events.get_nowait();self.busy=False
            if ok:self.app.guard(lambda:self._done(payload))
            else:self.app.error(payload)
        except queue.Empty:pass
        self._poll_id=self.after(100,self.poll)

    def inspect_fit(self):
        ids=self.results.selection() or self.tree.selection()
        if len(ids)!=1:raise ValueError('Select one fitted result to inspect.')
        entry=self.collection.entries[ids[0]];fit=entry.fit
        if not fit or fit.status!='ok':raise ValueError('No accepted fit for this curve. '+(fit.detail if fit else ''))
        win=tk.Toplevel(self);win.title(entry.label+' - fit and residuals');win.geometry('850x650')
        figure=Figure(figsize=(8,6),constrained_layout=True);ax,res=figure.subplots(2,1,sharex=True,gridspec_kw={'height_ratios':[3,1]})
        ax.plot(fit.x,fit.observed,label='Original intensity');ax.plot(fit.x,fit.best_fit,'--',label='Peak + fitted offset + baseline');ax.legend(fontsize=8)
        ax.set_ylabel('Original intensity');ax.set_title(entry.label,fontsize=10)
        res.plot(fit.x,fit.residual);res.axhline(0,color='gray',linewidth=.7);res.set_ylabel('Residual');res.set_xlabel(entry.snapshot.unit)
        canvas=FigureCanvasTkAgg(figure,win);canvas.get_tk_widget().pack(fill='both',expand=True);NavigationToolbar2Tk(canvas,win);canvas.draw()
        win._canvas=canvas

    def export_csv(self):
        if not self.collection.entries:raise ValueError('No retained curves to export.')
        path=filedialog.asksaveasfilename(parent=self,initialdir=self.app.initialdir('output'),defaultextension='.csv',filetypes=[('CSV','*.csv')])
        if path:
            export_fits(path,self.collection.entries.values());self.app.prefs.remember('output',str(Path(path).parent))

    def export_plot(self):
        path=filedialog.asksaveasfilename(parent=self,initialdir=self.app.initialdir('output'),defaultextension='.png',filetypes=[('PNG','*.png')])
        if path:
            self.figure.savefig(path,dpi=180);self.app.prefs.remember('output',str(Path(path).parent))
