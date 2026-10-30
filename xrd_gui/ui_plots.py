import numpy as np
"""Plot presentation only; integration and exported arrays are untouched."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from .widgets import Form, Tooltip
from .presentation import UNIT_LABELS, short_source, curve_labels, map_display

class PlotMixin:
    def new_plot(self,parent,title):
        frame=ttk.Frame(parent,padding=6);head=ttk.Frame(frame);head.pack(fill='x',pady=(0,4))
        ttk.Label(head,text=title,font=('Segoe UI',10,'bold')).pack(side='left')
        controls=ttk.Frame(frame);controls.pack(fill='x',pady=(0,4))
        fig=Figure(figsize=(3,2),dpi=90,layout='constrained');ax=fig.add_subplot()
        ax.tick_params(labelsize=9);ax.set_axis_off()
        canvas=FigureCanvasTkAgg(fig,master=frame);canvas.get_tk_widget().configure(width=100,height=100);canvas.get_tk_widget().pack(fill='both',expand=True)
        return frame,head,controls,ax,canvas
    def build_plots(self,parent):
        self.low=tk.StringVar(value='1');self.high=tk.StringVar(value='99')
        self.map_low=tk.StringVar(value='1');self.map_high=tk.StringVar(value='99');self.map_min=tk.StringVar();self.map_max=tk.StringVar();self.map_mode=tk.StringVar(value='Auto percentiles');self.map_scale=tk.StringVar(value='Linear');self.map_colorbar=None
        frame,head,controls,self.det_ax,self.det_canvas=self.new_plot(parent,'Detector image');parent.add(frame,weight=4)
        self.button(head,'Details',lambda:self.plot_details('detector'))
        self.button(controls,'Contrast…',lambda:self.contrast_dialog(False));ttk.Checkbutton(controls,text='Mask overlay',variable=self.show_mask,command=lambda:self.guard(self.draw_detector)).pack(side='left',padx=6)
        self.right_plots=ttk.Panedwindow(parent,orient='vertical');parent.add(self.right_plots,weight=3)
        frame,head,controls,self.map_ax,self.map_canvas=self.new_plot(self.right_plots,'2D map');self.right_plots.add(frame,weight=1)
        self.button(head,'Save 2D',lambda:self.save_dialog(True));self.button(head,'Display...',lambda:self.contrast_dialog(True));self.button(head,'Details',lambda:self.plot_details('map'))
        controls.pack_forget()
        self.map_notice=tk.StringVar(value='Run 2D to display a map');label=ttk.Label(frame,textvariable=self.map_notice,style='Muted.TLabel',wraplength=350);label.pack(side='bottom',fill='x',before=self.map_canvas.get_tk_widget());frame.bind('<Configure>',lambda e:label.configure(wraplength=max(120,e.width-20)))
        frame,head,controls,self.curve_ax,self.curve_canvas=self.new_plot(self.right_plots,'1D curve');self.right_plots.add(frame,weight=1)
        self.button(head,'Save 1D',lambda:self.save_dialog(False));self.button(head,'Add to Analysis',lambda:self.analysis.choose_results());self.button(head,'Details',lambda:self.plot_details('curve'))
        controls.pack_forget()
        self.curve_nav=NavigationToolbar2Tk(self.curve_canvas,frame,pack_toolbar=False);self.curve_nav.pack(side='bottom',fill='x',before=self.curve_canvas.get_tk_widget());self.curve_nav.update()
        Tooltip(self.curve_nav,'Home restores the full view. Use Zoom to inspect a region; processing settings are unchanged.')
        self.det_ax.set_aspect('equal')
        for ax,text in [(self.det_ax,'Select a detector image'),(self.map_ax,'No 2D result yet'),(self.curve_ax,'No 1D result yet')]:ax.text(.5,.5,text,ha='center',va='center',transform=ax.transAxes,fontsize=9)
    def contrast_dialog(self,two):
        win=tk.Toplevel(self);win.title('2D map display' if two else 'Detector display');win.transient(self);win.resizable(False,False)
        form=Form(win,'Display only');form.pack(fill='both',expand=True,padx=12,pady=12)
        if two:
            form.field('Scale',self.map_scale,['Linear','Log'])
            form.field('Range mode',self.map_mode,['Auto percentiles','Manual limits'])
        lo=form.field('Low percentile',self.map_low if two else self.low);hi=form.field('High percentile',self.map_high if two else self.high)
        if two:
            minimum=form.field('Intensity minimum',self.map_min);maximum=form.field('Intensity maximum',self.map_max)
            def states(*_):
                auto=self.map_mode.get()=='Auto percentiles'
                for w in (lo,hi):w.configure(state='normal' if auto else 'disabled')
                for w in (minimum,maximum):w.configure(state='disabled' if auto else 'normal')
            trace=self.map_mode.trace_add('write',states);states()
            win.bind('<Destroy>',lambda e:self.map_mode.trace_remove('write',trace) if e.widget==win else None)
            form.note('Auto uses finite populated bins, including valid zeros. Log hides nonpositive values on screen only. White areas have no displayed data.')
        else:form.note('Percentiles affect the detector display only. The mask and scientific image remain unchanged.')
        row=ttk.Frame(form);form.add(row);self.button(row,'Apply',self.draw_map if two else self.draw_detector)
        self.button(row,'Reset',self.reset_map_display if two else self.reset_detector_display);self.button(row,'Close',win.destroy)
    def reset_detector_display(self):self.low.set('1');self.high.set('99');self.draw_detector()
    def reset_map_display(self):
        self.map_low.set('1');self.map_high.set('99');self.map_mode.set('Auto percentiles');self.map_scale.set('Linear');self.map_min.set('');self.map_max.set('');self.draw_map()
    def draw_map(self):
        r=self.map_result
        if r is None:return
        limits=(float(self.map_min.get()),float(self.map_max.get())) if self.map_mode.get()=='Manual limits' else None
        data,norm,hidden=map_display(r,float(self.map_low.get()),float(self.map_high.get()),self.map_scale.get()=='Log',limits)
        if self.map_colorbar is not None:self.map_colorbar.remove();self.map_colorbar=None
        self.map_ax.clear();self.map_ax.set_axis_on();artist=self.map_ax.pcolormesh(r.radial,r.azimuthal,data,shading='auto',norm=norm,cmap='viridis',rasterized=True)
        self.map_colorbar=self.map_ax.figure.colorbar(artist,ax=self.map_ax,pad=.025,fraction=.045);self.map_colorbar.set_label('Intensity',fontsize=9);self.map_colorbar.ax.tick_params(labelsize=8)
        self.map_ax.set_xlabel(UNIT_LABELS.get(self.map_meta.get('unit'),self.map_meta.get('unit','Radial')));self.map_ax.set_ylabel('Azimuth (°)');self.map_ax.tick_params(labelsize=9)
        self.map_notice.set(f'{self.map_scale.get()} | white = no displayed data'+(f' | {hidden} nonpositive hidden' if self.map_scale.get()=='Log' else ''))
        if self.map_mode.get()=='Auto percentiles':self.map_min.set(f'{norm.vmin:.6g}');self.map_max.set(f'{norm.vmax:.6g}')
        self.map_canvas.draw_idle()
    def draw_curves(self):
        self.curve_ax.clear();self.curve_ax.set_axis_on()
        labels=curve_labels(self.curves)
        if len({c.metadata.get('source') for c in self.curves})==1:
            from .presentation import method_label
            labels=[method_label(c.metadata['settings'])+' | '+('Sector' if c.metadata.get('selection')=='sector' else 'Full azimuth')+(' (ref)' if c.metadata.get('comparison') else '') for c in self.curves]
        for c,label in zip(self.curves,labels):
            y=np.array(c.intensity,dtype=float,copy=True);y[c.metadata.get('invalid_bins',[])]=np.nan
            self.curve_ax.plot(c.x,y,label=label,linewidth=1,linestyle='--' if c.metadata.get('comparison') else '-')
        if self.curves:
            self.curve_ax.set_xlabel(UNIT_LABELS.get(self.curves[0].metadata['unit'],self.curves[0].metadata['unit']))
            # A compact legend; complete source paths remain in Details.
            import textwrap
            handles,_=self.curve_ax.get_legend_handles_labels()
            self.curve_ax.legend(handles,['\n'.join(textwrap.wrap(label,65)) for label in labels],fontsize=7,loc='best',framealpha=.8)
        self.curve_ax.set_ylabel('Intensity');self.curve_ax.tick_params(labelsize=9);self.curve_ax.relim();self.curve_ax.autoscale();self.curve_nav.update();self.curve_canvas.draw_idle()
    def plot_details(self,kind):
        if kind=='detector':text=self.active or 'No active detector image.'
        elif kind=='map':text=json.dumps(self.map_meta,indent=2,default=str) if self.map_meta else 'No 2D result yet.'
        else:text='\n\n'.join(label+'\n'+json.dumps(c.metadata,indent=2,default=str) for label,c in zip(curve_labels(self.curves),self.curves)) or 'No 1D results yet.'
        self.help_dialog('Source and processing details',text)
