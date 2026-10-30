"""Workspace, settings and diagnostic file layout."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, font as tkfont
from .widgets import ScrollPanel, Fold, Form, Tooltip, PreviewTable, ActionBar
from .presentation import UNIT_LABELS, file_fields, short_source

class LayoutMixin:
    def configure_style(self):
        for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont'):
            tkfont.nametofont(name).configure(size=10)
        style=ttk.Style(self); style.theme_use('clam')
        style.configure('.',font='TkDefaultFont',background='#f3f5f7')
        style.configure('TButton',padding=(10,6))
        style.configure('Quiet.TButton',padding=(5,3),width=0)
        style.configure('Primary.TButton',background='#2463a0',foreground='white',padding=(14,7))
        style.map('Primary.TButton',background=[('active','#174b80'),('disabled','#9daab6')])
        style.configure('TNotebook.Tab',padding=(16,8))
        style.map('TNotebook.Tab',background=[('selected','#dbeafa')],foreground=[('selected','#174b80')])
        style.configure('Treeview',rowheight=int(25*float(self.tk.call('tk','scaling'))/1.333),background='white',fieldbackground='white')
        style.configure('Treeview.Heading',padding=(6,5))
        style.configure('Muted.TLabel',foreground='#51616f')
        style.configure('Error.TLabel',foreground='#a12724')
        self.option_add('*Text.Font','TkTextFont')

    def shared_controls(self):
        self.configure_style(); self.panel_registry={}
        menu=tk.Menu(self); workspace_menu=tk.Menu(menu,tearoff=False)
        workspace_menu.add_command(label='Clear loaded files / status',command=lambda:self.guard(self.clear))
        workspace_menu.add_separator();workspace_menu.add_command(label='Exit',command=self.close)
        menu.add_cascade(label='Workspace',menu=workspace_menu);self.configure(menu=menu)
        box=ttk.Frame(self,padding=(12,8));box.pack(fill='x')
        row=ttk.Frame(box);row.pack(fill='x');row.columnconfigure(1,weight=1)
        ttk.Label(row,text='Workspace').grid(row=0,column=0,padx=(0,8))
        self.recent=ttk.Combobox(row,textvariable=self.workspace,values=self.prefs.data.get('recent',[]),width=20)
        self.recent.grid(row=0,column=1,sticky='ew');self.recent.bind('<<ComboboxSelected>>',lambda e:self.guard(self.set_workspace));self.recent.bind('<Return>',lambda e:self.guard(self.set_workspace))
        ttk.Button(row,text='Browse',command=lambda:self.guard(self.browse_workspace)).grid(row=0,column=2,padx=8)
        ttk.Button(row,text='Open Calibration',command=lambda:self.guard(self.calibrate)).grid(row=0,column=3)
        self.cal_summary=tk.StringVar(value='Setup needed: load a calibration; mask optional')
        self.cal_fold=Fold(box,'Calibration & Mask',opened=True,summary=self.cal_summary);self.cal_fold.pack(fill='x',pady=(6,0))
        body=self.cal_fold.body;body.columnconfigure(1,weight=1)
        for r,(label,var,key) in enumerate([('Calibration',self.poni,'calibration'),('Mask',self.mask,'mask')]):
            ttk.Label(body,text=label).grid(row=r,column=0,sticky='w',padx=(0,8),pady=3)
            ttk.Entry(body,textvariable=var).grid(row=r,column=1,sticky='ew',pady=3)
            ttk.Button(body,text='Load…',command=lambda v=var,k=key:self.guard(lambda:self.load_path(v,k))).grid(row=r,column=2,padx=6)
            ttk.Button(body,text='Reload',command=lambda:self.guard(self.load_engine)).grid(row=r,column=3)
        enabled=ttk.Checkbutton(body,text='Enable mask',variable=self.mask_enabled,command=lambda:self.guard(self.load_engine));enabled.grid(row=2,column=3,sticky='e',pady=4)
        Tooltip(enabled,'Mask convention: nonzero pixels are excluded from integration.')
        self.cal_feedback=ttk.Label(body,textvariable=self.loaded,style='Muted.TLabel',wraplength=800);self.cal_feedback.grid(row=2,column=0,columnspan=3,sticky='ew',padx=(0,8))
        for var in (self.poni,self.mask):var.trace_add('write',self.header_edited)

    def header_edited(self,*_):
        self.dirty()
        if self.engine:self.cal_summary.set('Paths edited — Load / Reload to apply. '+self.loaded.get())
    def load_engine(self):
        try:self._load_engine()
        except Exception as e:
            self.loaded.set(str(e));self.cal_summary.set('Calibration / mask needs attention')
            self.cal_feedback.configure(style='Error.TLabel');self.cal_fold.set_open(True)
            raise

    def update_calibration_summary(self):
        if not self.engine:
            self.cal_summary.set('Setup needed: load a calibration; mask optional');self.cal_fold.set_open(True);return
        meta=self.engine.metadata
        self.cal_summary.set(f"Calibration: {Path(meta['calibration']).name} · Mask: {Path(meta['mask']).name if meta['mask'] else 'none'} · {'Enabled' if self.engine.mask is not None else 'Disabled / not loaded'}")
        self.cal_feedback.configure(style='Muted.TLabel')

    def help_dialog(self,title,text):
        win=tk.Toplevel(self);win.title(title);win.transient(self);win.geometry('640x360')
        frame=ttk.Frame(win,padding=16);frame.pack(fill='both',expand=True)
        box=tk.Text(frame,wrap='word',height=10,padx=10,pady=10);box.insert('1.0',text);box.configure(state='disabled');box.pack(fill='both',expand=True)
        ttk.Button(frame,text='Close',command=win.destroy).pack(anchor='e',pady=(8,0))
    def science_help(self):
        self.help_dialog('Integration settings', 'Angles use calibrated pyFAI chi in [−180°, 180°). Start is inclusive and end exclusive; start > end crosses the boundary. The detector overlay uses the same pixel selection as integration.\n\nNo dark subtraction is applied. Poisson sigma is a model estimate for corrected images, not recovery of original counting uncertainty. Supplied images contain variance, not sigma, and must match the detector dimensions. XYE requires valid positive propagated sigma in every exported bin.\n\nDisplay contrast and log scaling do not alter scientific data. Results remain associated with the settings used when Run was pressed.')

    def integration_tab(self):
        tab=ttk.Frame(self.tabs);self.tabs.add(tab,text='Integration');self.integration_frame=tab
        self.svars={k:tk.StringVar(value=str(v)) for k,v in dict(unit='2th_deg',radial_bins=5000,azimuth_bins=360,minimum='',maximum='',start=100,end=180,polarization=.99,error_model='none',variance='').items()}
        self.sector=tk.BooleanVar();self.solid=tk.BooleanVar(value=True);self.compare=tk.BooleanVar();self.show_mask=tk.BooleanVar(value=True)
        self.settings_summary=tk.StringVar(value='2\u03b8 (\u00b0) | 5,000 bins | Full azimuth')
        self.settings_fold=Fold(tab,'Integration settings',opened=False,summary=self.settings_summary);self.settings_fold.pack(fill='x',padx=12)
        scroll=ScrollPanel(self.settings_fold.body,height=260);self.settings_scroll=scroll;scroll.pack(fill='x')
        body=scroll.body;body.columnconfigure(0,weight=1,uniform='settings');body.columnconfigure(1,weight=1,uniform='settings')
        basic=Form(body,'Basic integration');basic.grid(row=0,column=0,sticky='nsew',padx=(0,8))
        self.unit_display=tk.StringVar(value=UNIT_LABELS['2th_deg']);basic.field('Radial unit',self.unit_display,list(UNIT_LABELS.values()))
        self.unit_display.trace_add('write',lambda *_:self.svars['unit'].set(next(k for k,v in UNIT_LABELS.items() if v==self.unit_display.get())))
        basic.field('Radial bins',self.svars['radial_bins'])
        range_row=ttk.Frame(basic);basic.add(range_row);range_row.columnconfigure(1,weight=1);range_row.columnconfigure(3,weight=1)
        for col,text,var in [(0,'Min',self.svars['minimum']),(2,'Max',self.svars['maximum'])]:
            ttk.Label(range_row,text=text).grid(row=0,column=col,padx=(0,6));ttk.Entry(range_row,textvariable=var,width=8).grid(row=0,column=col+1,sticky='ew',padx=(0,6))
        Tooltip(range_row,'Optional radial range in the selected unit. Leave both fields blank for full range.')
        sector=Form(body,'Azimuth selection');sector.grid(row=0,column=1,sticky='nsew')
        mode=ttk.Frame(sector);sector.add(mode)
        ttk.Radiobutton(mode,text='Full azimuth',variable=self.sector,value=False).pack(side='left',padx=(0,12));ttk.Radiobutton(mode,text='Sector',variable=self.sector,value=True).pack(side='left')
        self.angle_start=sector.field('Start (°)',self.svars['start']);self.angle_end=sector.field('End (°)',self.svars['end']);self.compare_control=sector.check('Compare full azimuth',self.compare)
        adv=Fold(body,'Advanced settings',opened=False);adv.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(8,0));self.advanced_fold=adv
        adv.body.columnconfigure(0,weight=1);adv.body.columnconfigure(1,weight=1)
        corrections=Form(adv.body,'Corrections');corrections.grid(row=0,column=0,sticky='nsew',padx=(0,8))
        corrections.field('2D azimuth bins',self.svars['azimuth_bins']);corrections.check('Solid-angle correction',self.solid);corrections.field('Polarization',self.svars['polarization'])
        error=Form(adv.body,'Average / percentile / 2D uncertainty');error.grid(row=0,column=1,sticky='nsew')
        self.error_display=tk.StringVar(value='None');error.field('Model',self.error_display,['None','Poisson estimate','Supplied variance'])
        self.error_display.trace_add('write',lambda *_:self.svars['error_model'].set({'None':'none','Poisson estimate':'poisson','Supplied variance':'supplied'}[self.error_display.get()]))
        self.variance_control=error.field('Variance image',self.svars['variance']);self.variance_browse=error.add(ttk.Button(error,text='Browse variance…',command=lambda:self.guard(self.browse_variance)))
        self.build_methods(basic,adv.body)
        self.integration_actions=ActionBar(tab,'Run Both',lambda:self.guard(lambda:self.run_integration(True,True)),self.cancel.set);self.integration_actions.pack(fill='x')
        # Secondary actions are grouped next to the primary action.
        for text,one,two in [('Run 1D',True,False),('Run 2D',False,True)]:
            ttk.Button(self.integration_actions,text=text,command=lambda a=one,b=two:self.guard(lambda:self.run_integration(a,b))).pack(side='left',padx=(6,0))
        ttk.Button(self.integration_actions,text='Settings help',command=self.science_help).pack(side='right')
        self.result_status=tk.StringVar(value='No results yet');ttk.Label(self.integration_actions,textvariable=self.result_status,style='Muted.TLabel',wraplength=240).pack(side='left',padx=12)
        outer=ttk.Frame(tab);outer.pack(fill='both',expand=True,padx=12,pady=(0,8));self.file_toggle=ttk.Button(self.integration_actions,text='Hide files',style='Quiet.TButton',command=self.toggle_files);self.file_toggle.pack(side='right',padx=6)
        self.plot_panes=ttk.Panedwindow(outer,orient='horizontal');self.plot_panes.pack(fill='both',expand=True)
        self.files_panel=ttk.Frame(self.plot_panes,width=250,padding=(0,0,8,0));self.plot_panes.add(self.files_panel,weight=1);self.file_panel_visible=True
        self.build_file_panel(self.files_panel)
        self.build_plots(self.plot_panes)
        self.register_panes('diagnostic',self.plot_panes,[.22,.63]);self.register_panes('plots_vertical',self.right_plots,[.5],vertical=True)
        for key,var in self.svars.items():var.trace_add('write',lambda *_,k=key:self.dirty(one=k!='azimuth_bins'))
        for var in (self.sector,self.solid):var.trace_add('write',self.dirty)
        self.compare.trace_add('write',lambda *_:self.dirty(two=False))
        for var in [self.svars['start'],self.svars['end'],self.sector]:var.trace_add('write',lambda *_:self.overlay_update())
        self.sector.trace_add('write',lambda *_:self.update_setting_states());self.svars['error_model'].trace_add('write',lambda *_:self.update_setting_states());self.update_setting_states()

    def update_setting_states(self):
        for widget in (self.angle_start,self.angle_end,self.compare_control):widget.configure(state='normal' if self.sector.get() else 'disabled')
        for widget in (self.variance_control,self.variance_browse):widget.configure(state='normal' if self.svars['error_model'].get()=='supplied' or (hasattr(self,'method_vars') and self.method_vars['method_1d'].get()=='sigma_clip' and self.method_vars['clipping_model'].get()=='supplied') else 'disabled')
    def build_file_panel(self,parent):
        row=ttk.Frame(parent);row.pack(fill='x',pady=(0,6))
        add_files=self.button(row,'Add files',self.add_files)
        actions=ttk.Frame(row);actions.pack(side='left')
        self.button(actions,'Add folder',self.add_folder)
        self.remove_files_button=self.button(actions,'Remove',self.remove_selected_files)
        self.clear_files_button=self.button(actions,'Clear',self.clear_file_list)
        Tooltip(self.remove_files_button,'Remove selected entries from this list; files on disk are not deleted.')
        Tooltip(self.clear_files_button,'Clear the entire input list, including filtered entries. Calibration and computed curves are retained.')
        # Keep Add folder / Remove / Clear together when the file pane is narrow.
        def arrange_actions(event):
            stacked=event.width < add_files.winfo_reqwidth()+actions.winfo_reqwidth()+8
            if stacked==getattr(row,'_stacked',None):return
            row._stacked=stacked
            add_files.pack_forget();actions.pack_forget()
            options=dict(side='top',anchor='w') if stacked else dict(side='left')
            add_files.pack(padx=2,**options);actions.pack(**options)
        row.bind('<Configure>',arrange_actions)
        self.filter=tk.StringVar();search=ttk.Frame(parent);search.pack(fill='x',pady=(0,6));ttk.Label(search,text='Filter').pack(side='left',padx=(0,6));ttk.Entry(search,textvariable=self.filter,width=12).pack(side='left',fill='x',expand=True)
        self.filter.trace_add('write',lambda *_:self.refresh_files())
        table_frame=ttk.Frame(parent)
        self.file_tree=ttk.Treeview(table_frame,columns=('sample','stamp','frame'),displaycolumns=('sample','frame','stamp'),show='headings',selectmode='extended',height=4)
        for key,label,width in [('sample','Sample',90),('stamp','Timestamp',135),('frame','Frame',75)]:self.file_tree.heading(key,text=label);self.file_tree.column(key,width=width,minwidth=65,stretch=True)
        y=ttk.Scrollbar(table_frame,orient='vertical',command=self.file_tree.yview);x=ttk.Scrollbar(table_frame,orient='horizontal',command=self.file_tree.xview);self.file_tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        table_frame.columnconfigure(0,weight=1);table_frame.rowconfigure(0,weight=1);self.file_tree.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew')
        self.file_tree.bind('<<TreeviewSelect>>',self.select_file)
        bottom=ttk.Frame(parent);bottom.pack(side='bottom',fill='x')
        self.file_count=tk.StringVar(value='0 selected / 0 files');ttk.Label(bottom,textvariable=self.file_count,style='Muted.TLabel').pack(anchor='w',pady=6)
        row=ttk.Frame(bottom);row.pack(fill='x');self.button(row,'Previous',lambda:self.navigate(-1));self.button(row,'Next',lambda:self.navigate(1))
        self.active_text=tk.StringVar(value='No active file');label=ttk.Label(bottom,textvariable=self.active_text,wraplength=220);label.pack(fill='x',pady=6)
        parent.bind('<Configure>',lambda e:label.configure(wraplength=max(80,e.width-20)))
        self.file_details=tk.StringVar();ttk.Entry(bottom,textvariable=self.file_details,state='readonly').pack(fill='x');table_frame.pack(fill='both',expand=True);Tooltip(parent,'Select a row to see the full path below. Use Ctrl/Shift for multiple selections; selected files are never implicitly summed.')

    def remove_selected_files(self):
        selected=self.selected_files()
        if not selected:
            self.status.set('Select one or more files to remove from the list.')
            return
        self._remove_input_files(selected)

    def clear_file_list(self):
        self._remove_input_files(self.files)

    def _remove_input_files(self, paths):
        removed=set(paths)
        previous_index=self.visible.index(self.active) if self.active in self.visible else 0
        active_removed=self.active in removed
        self.files=[path for path in self.files if path not in removed]
        if active_removed:
            self.active=None;self.image_data=None
            self.active_text.set('No active file');self.file_details.set('')
            self.det_ax.clear();self.det_ax.set_axis_off()
            self.det_ax.text(.5,.5,'Select a detector image',ha='center',va='center',transform=self.det_ax.transAxes,fontsize=9)
            self.det_canvas.draw_idle()
        self.refresh_files()
        if active_removed and self.visible:
            iid=str(min(previous_index,len(self.visible)-1))
            self.file_tree.selection_set(iid);self.file_tree.focus(iid);self.file_tree.see(iid)
        self.select_file()
        if removed:self.dirty()
        self.status.set(f'Removed {len(removed)} file(s) from the input list.' if self.files else 'Input file list cleared.')

    def selected_files(self):return [self.visible[int(i)] for i in self.file_tree.selection() if int(i)<len(self.visible)]
    def refresh_files(self):
        old=set(self.selected_files()) if hasattr(self,'file_tree') else set()
        self.visible=[p for p in self.files if self.filter.get().lower() in Path(p).name.lower()]
        self.file_tree.delete(*self.file_tree.get_children())
        for i,p in enumerate(self.visible):
            self.file_tree.insert('','end',iid=str(i),values=file_fields(p))
            if p in old:self.file_tree.selection_add(str(i))
            if p==self.active:self.file_tree.focus(str(i))
        self.file_count.set(f'{len(self.file_tree.selection())} selected / {len(self.files)} files · {len(self.visible)} shown')
    def select_file(self,event=None):
        selection=self.file_tree.selection()
        selected=tuple(self.selected_files())
        if selected!=getattr(self,'last_selection',()):self.last_selection=selected;self.dirty()
        self.file_count.set(f'{len(selection)} selected / {len(self.files)} files · {len(self.visible)} shown')
        if not selection:return
        focus=self.file_tree.focus();iid=focus if focus in selection else selection[-1];self.file_tree.focus(iid)
        source=self.visible[int(iid)];self.file_details.set(source);self.active_text.set('Active: '+short_source(source))
        if source!=self.active:self.active=source;self.dirty();self.guard(self.load_active)
    def navigate(self,step):
        if not self.visible:return
        idx=self.visible.index(self.active) if self.active in self.visible else -1;idx=max(0,min(len(self.visible)-1,idx+step));iid=str(idx)
        self.file_tree.selection_set(iid);self.file_tree.focus(iid);self.file_tree.see(iid);self.select_file()
    def toggle_files(self):
        if self.file_panel_visible:
            self.last_file_width=self.plot_panes.sashpos(0);self.plot_panes.forget(self.files_panel);self.file_toggle.configure(text='Show files')
        else:
            self.plot_panes.insert(0,self.files_panel,weight=1);self.plot_panes.sashpos(0,getattr(self,'last_file_width',250));self.file_toggle.configure(text='Hide files')
        self.file_panel_visible=not self.file_panel_visible
    def register_panes(self,name,panes,ratios,vertical=False):
        self.panel_registry[name]=(panes,ratios,vertical)
        restored=[False]
        def restore():
            if restored[0] or not panes.winfo_ismapped():return
            extent=panes.winfo_height() if vertical else panes.winfo_width()
            if extent<50:return
            restored[0]=True
            saved=self.prefs.data.get('panels',{}).get(name,ratios)
            for i,fraction in enumerate(saved[:len(panes.panes())-1]):panes.sashpos(i,int(extent*fraction))
        self.after(300,restore)
        panes.bind('<Map>',lambda e:self.after(150,restore),add='+')
        def constrain(event=None):
            count=len(panes.panes())
            if count!=len(ratios)+1:return
            extent=panes.winfo_height() if vertical else panes.winfo_width()
            minimum=([140]*count if vertical else ([180,240,280] if count==3 else [340,300]))
            factor=min(1.,max(0.,extent-12)/sum(minimum));minimum=[int(v*factor) for v in minimum]
            previous=0
            for i in range(count-1):
                lower=previous+minimum[i];upper=extent-sum(minimum[i+1:])
                position=max(lower,min(upper,panes.sashpos(i)));panes.sashpos(i,position);previous=position
        panes.bind('<ButtonRelease-1>',constrain,add='+')
    def save_panel_sizes(self):
        values=dict(self.prefs.data.get('panels',{}))
        for name,(panes,ratios,vertical) in self.panel_registry.items():
            extent=panes.winfo_height() if vertical else panes.winfo_width()
            if extent>50 and len(panes.panes())==len(ratios)+1:values[name]=[panes.sashpos(i)/extent for i in range(len(ratios))]
        self.prefs.data['panels']=values;self.prefs.save()
