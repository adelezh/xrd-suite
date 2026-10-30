"""Method controls and product-specific invalidation."""
import tkinter as tk
from tkinter import ttk
from .widgets import Form
from .settings import METHOD_DEFAULTS, restore_method_preferences

METHOD_LABELS={'Average':'average','Sigma-clipping':'sigma_clip','Percentile filtering':'percentile'}

class MethodsMixin:
    def build_methods(self,basic,advanced):
        values=restore_method_preferences(self.prefs.data)
        self.method_vars={k:tk.StringVar(value=str(v)) for k,v in values.items() if k!='compare_average'}
        self.method_display=tk.StringVar(value=next(k for k,v in METHOD_LABELS.items() if v==values['method_1d']))
        self.compare_average=tk.BooleanVar(value=values['compare_average'])
        basic.field('1D method',self.method_display,list(METHOD_LABELS))
        self.method_area=ttk.Frame(basic);basic.add(self.method_area)
        self.clip_form=Form(self.method_area,'Sigma-clipping')
        self.clip_form.field('Sigma threshold',self.method_vars['sigma_threshold'])
        self.clip_form.note('Lower thresholds reject more strongly.')
        self.percentile_form=Form(self.method_area,'Percentile filtering')
        self.percentile_preset=tk.StringVar(value='Middle 50%')
        preset=self.percentile_form.field('Preset',self.percentile_preset,['Middle 50%','Median','Custom'])
        preset.bind('<<ComboboxSelected>>',self.apply_percentile_preset)
        self.percentile_form.field('Lower (0-100)',self.method_vars['percentile_low'])
        self.percentile_form.field('Upper (0-100)',self.method_vars['percentile_high'])
        self.percentile_form.note('Interval: weighted trimmed mean. Equal bounds: single quantile (50 = median).')
        self.average_check=ttk.Checkbutton(self.method_area,text='Compare with average (same selection)',variable=self.compare_average)
        self.clip_advanced=Form(advanced,'Clipping model')
        self.clip_advanced.grid(row=1,column=0,columnspan=2,sticky='ew')
        self.clip_advanced.field('Maximum iterations',self.method_vars['sigma_iterations'])
        self.clip_advanced.field('Clipping variance',self.method_vars['clipping_model'],['azimuthal','poisson','supplied'])
        self.clip_advanced.note('Determines rejection and retained-pixel SEM. It does not use the Average / percentile / 2D model.')
        basic.add(ttk.Button(basic,text='Filtering / uncertainty help',command=lambda:self.help_dialog('1D estimators',
            'Average is unchanged. Filtering operates within radial bins, not between neighboring curve points. It can suppress genuine spotty Bragg scattering and change peak areas.\n\nSigma-clipping uses no pixel splitting. Azimuthal dispersion is the default diagnostic model. Its returned SEM describes retained pixels, not selection uncertainty.\n\nPercentile bounds are 0-100 in the installed Cython API. An interval computes a weighted trimmed mean. Equal bounds request a quantile. The 2D azimuth bins do not control filtering.\n\nPoisson or supplied-variance interval errors are conditional propagated SEM; filtering bias and selection uncertainty are not included. Median/single-quantile XYE is unavailable; use XY/CHI. Undefined bins appear as gaps and are omitted on export, with omitted indices recorded in JSON metadata. No interpolation is performed.\n\nCompare with average keeps the same selection and grid. Compare full azimuth keeps the chosen estimator. References are diagnostic and are saved only when explicitly selected.')))
        # Keep the selector and active parameters at the top of the scrollable form.
        for widget in basic.winfo_children():
            info=widget.grid_info()
            if info:
                row=int(info['row'])
                widget.grid_configure(row={0:2,1:3,2:4,3:0,4:1}.get(row,row))
        self.method_display.trace_add('write',lambda *_:self.method_vars['method_1d'].set(METHOD_LABELS[self.method_display.get()]))
        for key,var in self.method_vars.items():var.trace_add('write',lambda *_,k=key:self.method_changed(k))
        self.compare_average.trace_add('write',lambda *_:self.dirty(two=False) if self.method_vars['method_1d'].get()!='average' else None)
        self.update_method_visibility()

    def apply_percentile_preset(self,event=None):
        values={'Middle 50%':(25,75),'Median':(50,50)}.get(self.percentile_preset.get())
        if values:
            self.method_vars['percentile_low'].set(str(values[0]));self.method_vars['percentile_high'].set(str(values[1]))

    def update_method_visibility(self):
        method=self.method_vars['method_1d'].get()
        if method=='average':self.method_area.grid_remove()
        else:self.method_area.grid()
        for form in (self.clip_form,self.percentile_form,self.average_check):form.pack_forget()
        if method=='sigma_clip':self.clip_form.pack(fill='x');self.clip_advanced.grid()
        else:self.clip_advanced.grid_remove()
        if method=='percentile':self.percentile_form.pack(fill='x')
        if method!='average':self.average_check.pack(anchor='w',pady=4)
        try:
            pair=tuple(float(self.method_vars[k].get()) for k in ('percentile_low','percentile_high'))
        except ValueError:pair=None
        self.percentile_preset.set({(25.,75.):'Middle 50%',(50.,50.):'Median'}.get(pair,'Custom'))
        if hasattr(self,'variance_control'):self.update_setting_states()

    def method_changed(self,key):
        self.update_method_visibility()
        method=self.method_vars['method_1d'].get()
        if key=='method_1d' or (method=='sigma_clip' and key in ('sigma_threshold','sigma_iterations','clipping_model')) or (method=='percentile' and key.startswith('percentile_')):
            self.dirty(two=False)

    def method_options(self,one=True):
        values=dict(METHOD_DEFAULTS)
        if not one:return values
        method=self.method_vars['method_1d'].get();values['method_1d']=method
        values['compare_average']=self.compare_average.get() if method!='average' else False
        if method=='sigma_clip':
            values.update(sigma_threshold=float(self.method_vars['sigma_threshold'].get()),sigma_iterations=int(self.method_vars['sigma_iterations'].get()),clipping_model=self.method_vars['clipping_model'].get())
        if method=='percentile':
            values.update(percentile_low=float(self.method_vars['percentile_low'].get()),percentile_high=float(self.method_vars['percentile_high'].get()))
        return values

    def persist_methods(self):
        self.prefs.data['integration_methods']={k:v.get() for k,v in self.method_vars.items()}
        self.prefs.data['integration_methods']['compare_average']=self.compare_average.get()
        self.prefs.save()

    def refresh_result_status(self):
        parts=[]
        if self.curves:parts.append('1D '+('outdated' if self.curve_revision!=self.revision_1d else 'ready'))
        if self.map_result is not None:parts.append('2D '+('outdated' if self.map_revision!=self.revision_2d else 'ready'))
        if hasattr(self,'result_status'):self.result_status.set(' | '.join(parts) or 'No results yet')
