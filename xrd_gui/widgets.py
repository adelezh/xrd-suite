"""Reusable Tk layout components; no scientific processing."""
import tkinter as tk
from tkinter import ttk

class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.window, self.timer = widget, text, None, None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')
    def schedule(self, event=None): self.timer = self.widget.after(650, self.show)
    def show(self):
        self.timer = None
        self.window = tk.Toplevel(self.widget); self.window.wm_overrideredirect(True)
        self.window.geometry(f'+{self.widget.winfo_rootx()+12}+{self.widget.winfo_rooty()+self.widget.winfo_height()+4}')
        ttk.Label(self.window,text=self.text,wraplength=360,padding=8,relief='solid').pack()
    def hide(self, event=None):
        if self.timer: self.widget.after_cancel(self.timer); self.timer = None
        if self.window: self.window.destroy(); self.window = None

class ScrollPanel(ttk.Frame):
    def __init__(self, parent, height=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self,highlightthickness=0,borderwidth=0,height=height or 100,background='#f3f5f7')
        self.scroll = ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.grid(row=0,column=0,sticky='nsew'); self.scroll.grid(row=0,column=1,sticky='ns')
        self.rowconfigure(0,weight=1); self.columnconfigure(0,weight=1)
        self.body = ttk.Frame(self.canvas,padding=(12,8))
        self.window = self.canvas.create_window((0,0),window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width))
        # Bind on the containing toplevel, but only scroll when the pointer is inside this panel.
        self.winfo_toplevel().bind('<MouseWheel>',self.wheel,add='+')
    def wheel(self,event):
        under=self.winfo_containing(event.x_root,event.y_root)
        if under and str(under).startswith(str(self)) and self.body.winfo_height()>self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta/120),'units')

class Fold(ttk.Frame):
    def __init__(self,parent,title,opened=False,summary=None):
        super().__init__(parent)
        self.title=title; self.opened=opened
        head=ttk.Frame(self); head.pack(fill='x')
        self.toggle_button=ttk.Button(head,command=self.toggle,style='Quiet.TButton'); self.toggle_button.pack(side='left')
        if summary is not None:
            label=ttk.Label(head,textvariable=summary,style='Muted.TLabel'); label.pack(side='left',fill='x',expand=True,padx=8)
            head.bind('<Configure>',lambda e:label.configure(wraplength=max(120,e.width-self.toggle_button.winfo_reqwidth()-24)))
        self.body=ttk.Frame(self,padding=(12,6)); self.set_open(opened)
    def toggle(self): self.set_open(not self.opened)
    def set_open(self, opened):
        self.opened=opened; self.toggle_button.configure(text=('▾ ' if opened else '▸ ')+self.title)
        if opened: self.body.pack(fill='x')
        else: self.body.pack_forget()

class Form(ttk.LabelFrame):
    def __init__(self,parent,title):
        super().__init__(parent,text=title,padding=12)
        self.columnconfigure(1,weight=1); self.next_row=0
    def field(self,label,var,values=None,width=16):
        r=self.next_row; self.next_row+=1
        ttk.Label(self,text=label).grid(row=r,column=0,sticky='w',padx=(0,8),pady=4)
        widget=ttk.Combobox(self,textvariable=var,values=values,width=width,state='readonly') if values else ttk.Entry(self,textvariable=var,width=width)
        widget.grid(row=r,column=1,sticky='ew',pady=4)
        return widget
    def add(self,widget):
        widget.grid(row=self.next_row,column=0,columnspan=2,sticky='ew',pady=4); self.next_row+=1
        return widget
    def check(self,label,var,command=None): return self.add(ttk.Checkbutton(self,text=label,variable=var,command=command))
    def note(self,text):
        label=ttk.Label(self,text=text,style='Muted.TLabel',wraplength=280)
        self.add(label); self.bind('<Configure>',lambda e:label.configure(wraplength=max(120,e.width-32)),add='+')
        return label

class PreviewTable(ttk.Frame):
    def __init__(self,parent,columns,tree=False):
        super().__init__(parent,padding=12)
        self.columnconfigure(0,weight=1); self.rowconfigure(1,weight=1)
        self.message=tk.StringVar(); self.details=tk.StringVar()
        self.label=ttk.Label(self,textvariable=self.message,style='Muted.TLabel',wraplength=500)
        self.label.grid(row=0,column=0,columnspan=2,sticky='ew',pady=(0,8))
        self.tree=ttk.Treeview(self,columns=[c[0] for c in columns],show='tree headings' if tree else 'headings',selectmode='extended',height=5)
        if tree: self.tree.heading('#0',text='Group / member'); self.tree.column('#0',width=160,minwidth=90)
        for key,title,width in columns: self.tree.heading(key,text=title); self.tree.column(key,width=width,minwidth=70,stretch=True)
        self.tree.grid(row=1,column=0,sticky='nsew')
        ttk.Scrollbar(self,orient='vertical',command=self.tree.yview).grid(row=1,column=1,sticky='ns')
        self.tree.configure(yscrollcommand=lambda a,b:self.grid_slaves(row=1,column=1)[0].set(a,b))
        x=ttk.Scrollbar(self,orient='horizontal',command=self.tree.xview); x.grid(row=2,column=0,sticky='ew'); self.tree.configure(xscrollcommand=x.set)
        ttk.Label(self,text='Selected item details (select and copy the full text)').grid(row=3,column=0,sticky='w',pady=(8,0))
        ttk.Entry(self,textvariable=self.details,state='readonly').grid(row=4,column=0,columnspan=2,sticky='ew',pady=(4,0))
        self.paths={}; self.tree.bind('<<TreeviewSelect>>',self.selected)
        self.bind('<Configure>',lambda e:self.label.configure(wraplength=max(160,e.width-30)))
    def selected(self,event=None):
        items=self.tree.selection(); self.details.set(self.paths.get(items[0],'') if items else '')
    def clear(self):
        self.tree.delete(*self.tree.get_children()); self.paths={}; self.details.set('')
    def add(self,iid,values,details='',parent='',text=''):
        self.tree.insert(parent,'end',iid=iid,values=values,text=text); self.paths[iid]=details
    def notice(self,text,error=False): self.message.set(text); self.label.configure(style='Error.TLabel' if error else 'Muted.TLabel')

class ActionBar(ttk.Frame):
    def __init__(self,parent,label,command,cancel):
        super().__init__(parent,padding=(12,8))
        self.primary=ttk.Button(self,text=label,command=command,style='Primary.TButton');self.primary.pack(side='left')
        self.progress=ttk.Progressbar(self,length=140)
        self.cancel=ttk.Button(self,text='Cancel',command=cancel)
    def running(self,value):
        self.primary.configure(state='disabled' if value else 'normal')
        if value:self.progress.pack(side='left',fill='x',expand=True,padx=12);self.cancel.pack(side='right')
        else:self.progress.pack_forget();self.cancel.pack_forget()
