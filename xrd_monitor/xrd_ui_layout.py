"""Layout/accessibility helpers, independent of scientific state and plot fonts."""
import tkinter as tk
from tkinter import ttk, font
from pathlib import Path


class ScrollPane(ttk.Frame):
    def __init__(self, parent, height=None):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, width=1, height=height or 1)
        self.content = ttk.Frame(self.canvas, padding=8)
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor='nw')
        vertical = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.rowconfigure(0, weight=1); self.columnconfigure(0, weight=1)
        self.content.bind('<Configure>', self._resize)
        self.canvas.bind('<Configure>', self._resize)

    def _resize(self, event=None):
        self.canvas.itemconfigure(self.item, width=max(self.canvas.winfo_width(), self.content.winfo_reqwidth()),
                                  height=max(self.canvas.winfo_height(), self.content.winfo_reqheight()))
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))


class LayoutMixin:
    def _layout_shell(self):
        self.geometry('1320x850'); self.minsize(850, 600)
        self.columnconfigure(0, weight=1); self.rowconfigure(1, weight=1)
        self.source_toolbar = ttk.Frame(self, padding=8)
        self.source_toolbar.grid(row=0, column=0, sticky='ew')
        self.source_toolbar.columnconfigure(0, weight=1)
        self.source_controls = ttk.Frame(self.source_toolbar)
        self.source_controls.grid(row=0, column=0, sticky='ew')
        fonts = ttk.Frame(self.source_toolbar)
        fonts.grid(row=0, column=1, sticky='ne', padx=(10, 0))
        self.ui_font_size = 11
        self.ui_font_label = tk.StringVar(value='11 pt')
        ttk.Label(fonts, text='UI font:').pack(side='left')
        ttk.Button(fonts, text='−', width=2, command=lambda: self._set_ui_font(self.ui_font_size-1)).pack(side='left')
        ttk.Label(fonts, textvariable=self.ui_font_label, width=5, anchor='center').pack(side='left')
        ttk.Button(fonts, text='+', width=2, command=lambda: self._set_ui_font(self.ui_font_size+1)).pack(side='left')
        self.pass_toggle = ttk.Button(self.source_toolbar, text='Show PASS settings', command=self._toggle_pass)
        self.pass_toggle.grid(row=1, column=0, sticky='w', pady=(4, 0))
        self.pass_scroll = ScrollPane(self.source_toolbar, height=150)
        self.pass_scroll.grid(row=2, column=0, columnspan=2, sticky='ew')
        self.pass_scroll.grid_remove()
        self.main_split = ttk.Panedwindow(self, orient='horizontal')
        self.main_split.grid(row=1, column=0, sticky='nsew', padx=8)
        self.scan_scroll = ScrollPane(self.main_split)
        self.scan_panel = self.scan_scroll.content
        self.main_split.add(self.scan_scroll, weight=3)
        self.task_container = ttk.Frame(self.main_split)
        self.main_split.add(self.task_container, weight=7)
        self.task_navigation = ttk.Frame(self.task_container)
        self.task_name_var = tk.StringVar(value='Map / Overlay')
        ttk.Label(self.task_navigation, text='Task:').pack(side='left')
        self.task_picker = ttk.Combobox(self.task_navigation, textvariable=self.task_name_var,
            values=('Map / Overlay', 'Peak Tracking', 'Similarity', 'CIF References'), state='readonly', width=18)
        self.task_picker.pack(side='left', padx=4)
        self.task_picker.bind('<<ComboboxSelected>>', lambda event: self.task_tabs.select(self.task_panes[self.task_name_var.get()]))
        self.task_tabs = ttk.Notebook(self.task_container)
        self.task_tabs.pack(fill='both', expand=True)
        self.task_tabs.bind('<Configure>', self._task_navigation_visibility)
        self.task_tabs.bind('<<NotebookTabChanged>>', self._task_changed)
        self.task_panes = {}
        for name in ('Map / Overlay', 'Peak Tracking', 'Similarity', 'CIF References'):
            pane = ScrollPane(self.task_tabs)
            self.task_panes[name] = pane
            self.task_tabs.add(pane, text=name)
        self.shared_status_var = tk.StringVar(value='No scans loaded')
        ttk.Label(self, textvariable=self.shared_status_var, anchor='w', width=1).grid(row=2, column=0, sticky='ew', padx=8, pady=4)
        self.watch_folder_var.trace_add('write', lambda *_: self._update_layout_selection())
        self._split_initialized = False
        self.main_split.bind('<Configure>', self._initial_split)

    def _initial_split(self, event):
        if not self._split_initialized and event.width > 100:
            self.main_split.sashpos(0, int(event.width*.3))
            self._split_initialized = True

    def _task_changed(self, event=None):
        selected = self.task_tabs.select()
        if selected:
            self.task_name_var.set(self.task_tabs.tab(selected, 'text'))

    def _task_navigation_visibility(self, event=None):
        required = sum(font.nametofont('TkDefaultFont', root=self).measure(name)+30 for name in self.task_panes)
        if self.task_tabs.winfo_width() < required:
            self.task_navigation.pack(side='top', fill='x', before=self.task_tabs)
        else:
            self.task_navigation.pack_forget()

    def _toggle_pass(self):
        if self.pass_scroll.winfo_manager():
            self.pass_scroll.grid_remove(); self.pass_toggle.configure(text='Show PASS settings')
        else:
            self.pass_scroll.grid(); self.pass_toggle.configure(text='Hide PASS settings')

    def _set_ui_font(self, size):
        self.ui_font_size = max(9, min(18, int(size)))
        self.ui_font_label.set(f'{self.ui_font_size} pt')
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont', 'TkCaptionFont', 'TkSmallCaptionFont', 'TkIconFont'):
            font.nametofont(name, root=self).configure(size=self.ui_font_size)
        style = ttk.Style(self)
        style.configure('.', font='TkDefaultFont')
        style.configure('Treeview', font='TkDefaultFont', rowheight=font.nametofont('TkDefaultFont', root=self).metrics('linespace')+8)
        style.configure('Treeview.Heading', font='TkHeadingFont')
        style.configure('TButton', padding=(6, max(2, self.ui_font_size//4)))
        self.option_add('*TCombobox*Listbox.font', 'TkTextFont')
        if not hasattr(self, '_table_column_widths'):
            self._table_column_widths = {}
            def find_tables(widget):
                if isinstance(widget, ttk.Treeview):
                    for column in ('#0', *widget.cget('columns')):
                        self._table_column_widths[(widget, column)] = int(widget.column(column, 'width'))
                for child in widget.winfo_children(): find_tables(child)
            find_tables(self)
        for (table, column), width in self._table_column_widths.items():
            if table.winfo_exists():
                table.column(column, width=round(width*self.ui_font_size/11))
        self._task_navigation_visibility()

    def _update_layout_selection(self):
        if not hasattr(self, 'inspect_scan_button'):
            return
        from .xrd_detector_inspector import integration_metadata
        selected = self._selected_file_paths()
        valid = False
        if len(selected) == 1:
            try:
                _, _, scan, _ = integration_metadata(selected[0]); valid = True
                message = f'Scan {scan} selected'
            except ValueError:
                message = 'Select an integration file'
        else:
            message = f'{len(selected)} files selected' if selected else 'No scan selected'
        self.scan_summary_var.set(message)
        self.inspect_scan_button.configure(state='normal' if valid else 'disabled')
        folder = self.watch_folder_var.get().strip()
        short = ('…'+folder[-85:]) if len(folder)>86 else folder
        self.shared_status_var.set(f'{len(self.selected_files)} scans loaded | {short or "No watch folder"}')

    def _install_wheel_routing(self):
        # A private bindtag is attached only to main-window widgets; never bind_all.
        self._wheel_tag = f'XRDWheel{id(self)}'
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.bind_class(self._wheel_tag, sequence, self._route_wheel)
        def attach(widget):
            widget.bindtags((self._wheel_tag, *widget.bindtags()))
            for child in widget.winfo_children(): attach(child)
        for child in self.winfo_children(): attach(child)
        self.bind('<Destroy>', self._cleanup_wheel, add='+')

    def _cleanup_wheel(self, event):
        if event.widget is self:
            for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                self.unbind_class(self._wheel_tag, sequence)

    def _route_wheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None or widget.winfo_toplevel() is not self:
            return
        number = getattr(event, 'num', None)
        delta = getattr(event, 'delta', 0)
        units = -1 if number == 4 else 1 if number == 5 else (-max(1, abs(int(delta))//120) if delta>0 else max(1, abs(int(delta))//120))
        if number not in (4, 5) and not delta:
            return
        current = widget
        while current is not self:
            if isinstance(current, (ttk.Treeview, tk.Listbox)):
                current.yview_scroll(units, 'units'); return 'break'
            if isinstance(current, ScrollPane):
                current.canvas.yview_scroll(units, 'units'); return 'break'
            if isinstance(current, ttk.Combobox):
                # Scrolling a tab must not silently alter analysis parameters.
                pass
            current = current.master
            if current is None: return
        return 'break'
