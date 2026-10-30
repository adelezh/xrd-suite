"""Batch and manipulation layouts, previews, and UI job coordination."""
import json, queue, threading, traceback
from dataclasses import asdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from .widgets import ScrollPanel, Form, Fold, PreviewTable, ActionBar
from .presentation import UNIT_LABELS, short_source, effective_manipulation
from .naming import natural_key
from .files import read_curve
from xrd_suite.paths import data_dir
from .jobs import manipulation_plan, run_manipulation

class JobsMixin:
    def job_shell(self,title,prefix,action,command,tree=False):
        tab=ttk.Frame(self.tabs);self.tabs.add(tab,text=title)
        if prefix=='manip':
            ops=ttk.Frame(tab,padding=(12,10));ops.pack(fill='x');self.operation_row=ops
            for name in ('Sum','Average','Copy / Rename','For TOPAS'):
                ttk.Radiobutton(ops,text=name,variable=self.operation,value=name,style='Toolbutton').pack(side='left',padx=(0,8))
        bar=ActionBar(tab,action,lambda:self.guard(command),self.cancel.set);bar.pack(side='bottom',fill='x')
        panes=ttk.Panedwindow(tab,orient='horizontal');panes.pack(fill='both',expand=True,padx=12,pady=8)
        scroll=ScrollPanel(panes);panes.add(scroll,weight=1)
        preview=PreviewTable(panes,[('input','Input / members',210),('output','Proposed output',260),('status','Status',150)],tree=tree);panes.add(preview,weight=2)
        self.register_panes(prefix,panes,[.34]);setattr(self,prefix+'_actions',bar);setattr(self,prefix+'_preview',preview);setattr(self,prefix+'_controls',scroll.body)
        return scroll.body
    def input_section(self,parent,prefix):
        box=Form(parent,'Input');box.pack(fill='x',pady=(0,10))
        box.add(ttk.Button(box,text='Choose files…',command=lambda:self.guard(lambda:self.job_inputs(prefix))))
        box.add(ttk.Button(box,text='Use diagnostic file selection',command=lambda:self.guard(lambda:self.job_use_diagnostic(prefix))))
        count=tk.StringVar(value='0 input files');box.add(ttk.Label(box,textvariable=count,style='Muted.TLabel'));setattr(self,prefix+'_count',count)
    def destination_section(self,parent,variables,styles=True):
        box=Form(parent,'Destination');box.pack(fill='x',pady=(0,10))
        box.field('Output folder',variables['folder']);box.add(ttk.Button(box,text='Browse folder…',command=lambda:self.guard(lambda:self.job_folder(variables['folder']))))
        if styles:box.field('Filename style',variables['naming'],['Keep original','Shorten standard'])
        box.field('Existing files',variables['policy'],['Skip','Overwrite','Unique name'])
        return box
    def batch_tab(self):
        self.batch_files=[];self.batch_settings=None;self.bvars={k:tk.StringVar(value=v) for k,v in dict(folder=str(data_dir()/'exports'),naming='Shorten standard',policy='Skip',extension='.xy').items()}
        self.bone=tk.BooleanVar(value=True);self.btwo=tk.BooleanVar();self.btth=tk.BooleanVar(value=True);self.bq=tk.BooleanVar()
        body=self.job_shell('Batch Integration','batch','Start Batch',self.start_batch);self.input_section(body,'batch')
        box=Form(body,'Integration');box.pack(fill='x',pady=(0,10));box.add(ttk.Button(box,text='Use current diagnostic settings',command=lambda:self.guard(self.capture_batch)))
        self.batch_summary=tk.StringVar(value='Capture diagnostic settings before starting.');label=ttk.Label(box,textvariable=self.batch_summary,wraplength=260);box.add(label);box.bind('<Configure>',lambda e,lbl=label:lbl.configure(wraplength=max(160,e.width-30)))
        box.add(ttk.Button(box,text='Captured settings details…',command=lambda:self.help_dialog('Captured settings',json.dumps(asdict(self.batch_settings),indent=2) if self.batch_settings else 'No settings captured.')))
        box=Form(body,'Output');box.pack(fill='x',pady=(0,10))
        row=ttk.Frame(box);box.add(row)
        for name,var in [('1D curves',self.bone),('2D maps',self.btwo)]:ttk.Checkbutton(row,text=name,variable=var).pack(side='left',padx=(0,8))
        row=ttk.Frame(box);box.add(row)
        for name,var in [('2θ (°)',self.btth),('q (Å⁻¹)',self.bq)]:ttk.Checkbutton(row,text=name,variable=var).pack(side='left',padx=(0,8))
        self.batch_format=box.field('1D format',self.bvars['extension'],['.xy','.chi','.xye'])
        box.note('Both units use the same numeric range in their respective units. Leave the range blank for full coverage.')
        self.destination_section(body,self.bvars)
        self.batch_validation=tk.StringVar();label=ttk.Label(body,textvariable=self.batch_validation,style='Error.TLabel',wraplength=280);label.pack(fill='x')
        body.bind('<Configure>',lambda e:label.configure(wraplength=max(140,e.width-24)))
        for var in list(self.bvars.values())+[self.bone,self.btwo,self.btth,self.bq]:var.trace_add('write',lambda *_:self.live_preview('batch'))
        self.live_preview('batch')
    def capture_batch(self):
        self.batch_settings=self.settings(); self.persist_methods();s=self.batch_settings
        from .presentation import method_label
        self.batch_summary.set(method_label(s.__dict__)+(f' | clipping model: {s.clipping_model}, max iterations: {s.sigma_iterations}' if s.method_1d=='sigma_clip' else '')+'\n'+f'{s.radial_bins:,} radial bins · {s.azimuth_bins} azimuth bins\n'+(f'Sector {s.start:g}°–{s.end:g}°' if s.sector else 'Full azimuth')+f' · {s.error_model} uncertainty')
        self.live_preview('batch')
    def job_inputs(self,prefix):
        types=[('TIFF images','*.tif *.tiff')] if prefix=='batch' else [('Detector / curves','*.tif *.tiff *.xy *.chi *.xye')]
        files=self.choose(multiple=True,types=types)
        if files:setattr(self,prefix+'_files',sorted(files,key=natural_key));self.input_changed(prefix)
    def job_use_diagnostic(self,prefix):setattr(self,prefix+'_files',self.selected_files());self.input_changed(prefix)
    def input_changed(self,prefix):
        if prefix=='manip':self._sigma_inputs=None;self.update_manip_visibility()
        self.live_preview(prefix)
    def preview_batch(self):
        table=self.batch_preview;table.clear();self.batch_count.set(f'{len(self.batch_files)} input files');self.batch_validation.set('');self.batch_format.configure(state='readonly' if self.bone.get() else 'disabled')
        if not self.batch_files:table.notice('Select input files to preview output names.');return []
        plan=self.get_batch_plan()
        for i,(source,unit,dim,p) in enumerate(plan):
            exists=p.exists() or Path(str(p)+'.json').exists()
            table.add(str(i),(short_source(source),p.name,('Exists · '+self.bvars['policy'].get()) if exists else f'Ready · {dim} · {UNIT_LABELS[unit]}'),f'{source} → {p} | {dim}, {UNIT_LABELS[unit]}')
        table.notice(f'{len(self.batch_files)} input files · {len(plan)} output products');return plan
    def live_preview(self,prefix):
        if getattr(self,'busy',False) and getattr(self,'active_job',None)==prefix:return
        if getattr(self,'_switching_operation',False):return
        try:getattr(self,'preview_'+prefix)()
        except (ValueError,TypeError,OSError) as e:
            table=getattr(self,prefix+'_preview');table.clear();table.notice(str(e),True);getattr(self,prefix+'_validation').set(str(e))
            for i,p in enumerate(getattr(self,prefix+'_files')):table.add(str(i),(short_source(p),'—','Needs attention'),p)

    def manipulate_tab(self):
        self.operation=tk.StringVar(value='Copy / Rename');self.manip_files=[];self._operation_values={};self._current_operation='Copy / Rename';self._switching_operation=False;self._sigma_inputs=None;self._missing_sigma=False
        defaults=dict(folder=str(data_dir()/'exports'),naming='Shorten standard',policy='Skip',extension='.xy',operation='Copy / Rename',grouping='All selected',section='',prefix='',suffix='',scale='1')
        self.mvars={k:tk.StringVar(value=v) for k,v in defaults.items()};self.numbered=tk.BooleanVar();self.approx=tk.BooleanVar();self.preserve_identifier=tk.BooleanVar()
        body=self.job_shell('File Manipulate','manip','Copy & Rename',self.start_manip,tree=True);self.input_section(body,'manip')
        self.operation_forms=ttk.Frame(body);self.operation_forms.pack(fill='x')
        self.manip_validation=tk.StringVar();label=ttk.Label(body,textvariable=self.manip_validation,style='Error.TLabel',wraplength=280);label.pack(fill='x');body.bind('<Configure>',lambda e:label.configure(wraplength=max(140,e.width-24)))
        self.build_operation_forms();self.operation.trace_add('write',self.switch_operation)
        for var in list(self.mvars.values())+[self.numbered,self.approx,self.preserve_identifier]:var.trace_add('write',self.manip_changed)
        self.live_preview('manip')
    def switch_operation(self,*_):
        if self.busy and getattr(self,'active_job',None)=='manip':return
        old={k:v.get() for k,v in self.mvars.items()};old['operation']=self._current_operation
        old.update(numbered=self.numbered.get(),approx=self.approx.get(),preserve=self.preserve_identifier.get());self._operation_values[self._current_operation]=old
        op=self.operation.get();values=self._operation_values.get(op,dict(folder=old['folder'],naming='Shorten standard',policy='Skip',extension='.xy',operation=op,grouping='All selected',section='',prefix='',suffix='',scale='1',numbered=False,approx=False,preserve=False))
        self._switching_operation=True
        for k,var in self.mvars.items():var.set(values[k])
        self.numbered.set(values['numbered']);self.approx.set(values['approx']);self.preserve_identifier.set(values['preserve']);self._current_operation=op
        self.build_operation_forms();self._switching_operation=False;self.update_manip_visibility();self.live_preview('manip')
    def build_operation_forms(self):
        for child in self.operation_forms.winfo_children():child.destroy()
        parent=self.operation_forms;op=self.mvars['operation'].get();grouped=op in ('Sum','Average')
        self.group_section=None;self.custom_section=None;self.topas_section=None;self.approx_widget=None;self.manip_format=None
        if grouped:
            box=Form(parent,'Grouping');box.pack(fill='x',pady=(0,10));box.field('Group files',self.mvars['grouping'],['All selected','Sample','Sample + timestamp','Custom section'])
            section=Form(parent,'Custom grouping');self.group_section=section;section.field('Basename section',self.mvars['section']);section.note('0-based start:end; end excluded. Example: 0:6.')
        box=Form(parent,'Output naming');box.pack(fill='x',pady=(0,10));self.naming_section=box
        if not grouped:box.field('Filename style',self.mvars['naming'],['Keep original','Shorten standard','Custom'])
        box.field('Prefix',self.mvars['prefix']);box.field('Suffix',self.mvars['suffix'])
        if not grouped:
            custom=Form(parent,'Custom naming');self.custom_section=custom;custom.field('Basename section',self.mvars['section']);custom.check('Numbered names',self.numbered);custom.check('Preserve frame / mean',self.preserve_identifier);custom.note('0-based start:end, end excluded. Ending preservation requires a recognized standard filename.')
        if op!='Copy / Rename':
            box=Form(parent,'Output format');box.pack(fill='x',pady=(0,10));self.manip_format=box.field('Curve format',self.mvars['extension'],['.xy','.xye'] if op=='For TOPAS' else ['.xy','.chi','.xye'])
            if grouped:box.note('TIFF groups are written as TIFF; curve groups use the selected format.')
        if op=='For TOPAS':
            box=Form(parent,'TOPAS conversion');box.pack(fill='x',pady=(0,10));self.topas_section=box;box.field('Intensity scale',self.mvars['scale'])
            self.approx_widget=ttk.Checkbutton(box,text='Estimate sigma from sqrt(I) — approximate',variable=self.approx,wraplength=240) if False else ttk.Checkbutton(box,text='Estimate sigma from sqrt(I)\n— approximate',variable=self.approx)
            box.add(self.approx_widget)
            box.add(ttk.Button(box,text='Uncertainty help…',command=lambda:self.help_dialog('TOPAS uncertainties','Existing sigma is preserved and scaled by the absolute scale factor.\n\nFor missing sigma only, the optional estimate is sqrt(max(original I, 1)), before scaling. The floor avoids zero or undefined sigma; it does not recover true counting uncertainties. Original intensity is preserved except for the chosen scale.\n\nExports preserve x values and units; no q-to-2theta conversion is performed.')))
            box.note('Headerless XY / XYE only. Existing valid sigma is preserved.')
        self.destination_section(parent,self.mvars,styles=False)
        self.manip_actions.primary.configure(text={'Sum':'Sum Groups','Average':'Average Groups','Copy / Rename':'Copy & Rename','For TOPAS':'Prepare TOPAS Files'}[op])
        self.update_manip_visibility()
    def detect_missing_sigma(self):
        key=tuple(self.manip_files)
        if key==self._sigma_inputs:return self._missing_sigma
        self._sigma_inputs=key;self._missing_sigma=False
        for p in self.manip_files:
            try:
                if read_curve(p).sigma is None:self._missing_sigma=True;break
            except (OSError,ValueError,UnicodeError):continue
        return self._missing_sigma
    def update_manip_visibility(self):
        if self.manip_format is not None:
            images_only=bool(self.manip_files) and all(Path(p).suffix.lower() in ('.tif','.tiff') for p in self.manip_files)
            self.manip_format.configure(state='disabled' if images_only and self.mvars['operation'].get() in ('Sum','Average') else 'readonly')
        if self.group_section:
            if self.mvars['grouping'].get()=='Custom section':self.group_section.pack(fill='x',pady=(0,10),before=self.naming_section)
            else:self.group_section.pack_forget()
        if self.custom_section:
            if self.mvars['naming'].get()=='Custom':self.custom_section.pack(fill='x',pady=(0,10),after=self.naming_section)
            else:self.custom_section.pack_forget()
        if self.approx_widget:
            if self.mvars['extension'].get()=='.xye' and self.detect_missing_sigma():self.approx_widget.grid()
            else:self.approx_widget.grid_remove()
    def manip_changed(self,*_):
        if self._switching_operation:return
        self.update_manip_visibility();self.live_preview('manip')
    def manip_values(self):
        v={k:var.get() for k,var in self.mvars.items()}
        return effective_manipulation(v,self.numbered.get(),self.preserve_identifier.get(),self.approx.get(),self.detect_missing_sigma() if v['operation']=='For TOPAS' else False)
    def get_manip_plan(self):
        v,numbered,preserve,approx=self.manip_values()
        return manipulation_plan(self.manip_files,v['folder'],v['operation'],v['grouping'],v['section'],v['naming'],v['prefix'],v['suffix'],numbered,v['extension'],preserve)
    def preview_manip(self):
        table=self.manip_preview;table.clear();self.manip_validation.set('');self.manip_count.set(f'{len(self.manip_files)} input files')
        table.tree.configure(show='tree headings' if self.mvars['operation'].get() in ('Sum','Average') else 'headings')
        if not self.manip_files:table.notice('Select input files to preview groups and output names.');return []
        plan=self.get_manip_plan();grouped=self.mvars['operation'].get() in ('Sum','Average')
        for i,(members,p) in enumerate(plan):
            state='Exists · '+self.mvars['policy'].get() if p.exists() or Path(str(p)+'.json').exists() else 'Ready'
            table.add(str(i),(f'{len(members)} members' if grouped else short_source(members[0]),p.name,state),'\n'.join(members)+' → '+str(p),text=f'Group {i+1}' if grouped else str(i+1))
            if grouped:
                for j,source in enumerate(members):table.add(f'{i}.{j}',(short_source(source),'','Input'),source,parent=str(i),text=f'Member {j+1}')
        table.notice(f'{len(plan)} '+('groups' if grouped else 'outputs')+f' · {len(self.manip_files)} input files'+(' · Expand a group to inspect members.' if grouped else ''))
        return plan
    def start_manip(self):
        plan=self.get_manip_plan();self.preview_manip();v,_,_,approx=self.manip_values()
        self.start_worker(lambda:run_manipulation(plan,v['operation'],v['policy'],v['scale'],approx,self.cancel,self.report),self.job_finished)

    def start_worker(self,work,done):
        if self.busy:raise ValueError('A job is already running. Cancel or wait for completion.')
        self.active_job=['integration','analysis','batch','manip'][self.tabs.index(self.tabs.select())]
        self.busy=True;self.cancel.clear();bar=getattr(self,self.active_job+'_actions');self.progress=bar.progress;self.progress['value']=0;bar.running(True)
        self.status.set('Processing…');self.done=done;self.frozen_widgets=[]
        if self.active_job in ('batch','manip'):
            self.freeze_controls(getattr(self,self.active_job+'_controls'))
            if self.active_job=='manip':self.freeze_controls(self.operation_row)
        def target():
            try:self.events.put(('done',work()))
            except Exception as e:self.events.put(('error',(e,traceback.format_exc())))
        threading.Thread(target=target,daemon=True).start()
    def freeze_controls(self,parent):
        for widget in parent.winfo_children():
            if isinstance(widget,(ttk.Entry,ttk.Combobox,ttk.Button,ttk.Checkbutton,ttk.Radiobutton)):
                self.frozen_widgets.append((widget,str(widget.cget('state'))));widget.configure(state='disabled')
            self.freeze_controls(widget)
    def finish_job_ui(self):
        self.busy=False;getattr(self,self.active_job+'_actions').running(False)
        for widget,state in self.frozen_widgets:
            if widget.winfo_exists():widget.configure(state=state)
        self.frozen_widgets=[]
        if self.active_job in ('batch','manip'):
            table=getattr(self,self.active_job+'_preview')
            for iid in table.tree.get_children():
                values=list(table.tree.item(iid,'values'))
                if values and (values[-1].startswith('Ready') or values[-1].startswith('Exists')):values[-1]='Not processed' if self.cancel.is_set() else values[-1];table.tree.item(iid,values=values)
    def poll(self):
        try:
            while True:
                kind,payload=self.events.get_nowait()
                if kind=='progress':
                    n,total,text=payload;self.progress['value']=100*n/max(total,1);self.status.set(text);self.log.insert('end',text+'\n')
                    if self.active_job in ('batch','manip'):
                        table=getattr(self,self.active_job+'_preview');iid=str(n-1)
                        if table.tree.exists(iid):
                            values=list(table.tree.item(iid,'values'));values[-1]=text;table.tree.item(iid,values=values);table.tree.see(iid);table.paths[iid]+=' | '+text
                elif kind=='done':
                    self.finish_job_ui();self.guard(lambda:self.done(payload))
                    if self.active_job=='integration':self.refresh_result_status()
                else:self.finish_job_ui();self.error(*payload)
        except queue.Empty:pass
        self._poll_job=self.after(100,self.poll)
