import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk, font
from pathlib import Path
from dataclasses import dataclass, field
import threading
import queue
import os
from xrd_suite.paths import default_workspace

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

from . import xrd_peak_workflow as xrdpeak
from .xrd_detector_inspector import DetectorInspectorMixin
from .xrd_ui_layout import LayoutMixin
from . import xrd_calculated_phases as calculated

natural_sort_key = xrdpeak.natural_sort_key


def loadxy(filepath, skiprows=0, xmin=None, xmax=None, usecols=(0, 1)):
    """Use the same text parser as library analysis."""
    return xrdpeak.loadxy(filepath, xmin=xmin, xmax=xmax,
                          skiprows=skiprows, usecols=usecols)


def similarity_ylim(values):
    """Pad finite correlations independently, preserving detail near unity."""
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if not finite.size:
        return -1.05, 1.05
    low, high = float(np.min(finite)), float(np.max(finite))
    padding = max(0.1*(high-low), 1e-4)
    return low-padding, high+padding


@dataclass
class PeakTrack:
    """Independent configuration and results for one conservatively tracked peak."""
    track_id: int
    enabled: bool = True
    name: str = ""
    initial_center: float = 5.5
    xmin: float = 5.0
    xmax: float = 6.0
    max_shift: float = .05
    fit_window: float = .3
    fwhm_guess: float = .05
    prominence: float | None = None
    baseline_method: str | None = "arpls"
    start_file: str | None = None
    results: object | None = field(default=None, repr=False)

# --------------- GUI -----------------
class XRDMapGUI(LayoutMixin, DetectorInspectorMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("XRD Map / Overlay (popup figure)")
        self.geometry("940x920")
        self.selected_files = []
        self._ext_fig = None  # external matplotlib figure handle
        self._peak_fig = None
        self._similarity_fig = None
        self._last_snapshot = None
        self._auto_job = None
        self.last_dir = default_workspace()
        self.calculated_phases = []
        self._next_calculated_phase_id = 1
        self._cif_results = queue.Queue()
        self._similarity_config = None
        self._similarity_reference = None
        self._peak_start_file = None
        self.peak_results = None
        self.peak_tracks = []
        self._next_peak_track_id = 1
        self._selected_peak_track_id = None
        self._peak_manager_tree = None
        self.similarity_results = None
        self._updating_range_defaults = False
        self._xmax_auto_q_default = False
        self._sim_xmax_auto_q_default = False

        # Beamline info
        self.basepath_var = tk.StringVar(value=os.environ.get("XRD_SUITE_BEAMLINE_BASE", "/nsls2/data/xpd-new/proposals"))
        self.cycle_var = tk.StringVar(value="2026-3")
        self.proposal_var = tk.StringVar(value="")
        self.saf_var = tk.StringVar(value="")
        self.passpath_var = tk.StringVar(value="")

        # Plot options
        self.type_var = tk.StringVar(value="tth")        # tth or q
        self.plot_mode_var = tk.StringVar(value="map")   # "map" or "overlay"
        self.use_selected_only_var = tk.BooleanVar(value=False)

        self.xmin_var = tk.StringVar(value="1.5")
        self.xmax_var = tk.StringVar(value="13")
        self.skiprows_var = tk.StringVar(value="0")
        self.cmap_var = tk.StringVar(value="viridis")
        self.log_var = tk.BooleanVar(value=True)
        self.figw_var = tk.StringVar(value="12")  # used for Save Figure only
        self.figh_var = tk.StringVar(value="6")   # used for Save Figure only
        self.yoffset_var = tk.StringVar(value="20")  # NEW: overlay y-offset per trace
        self.show_legend_var = tk.BooleanVar(value=True)
        self.calc_wavelength_var = tk.StringVar(value="1.5406")
        self.calc_show_var = tk.BooleanVar(value=False)
        self.calc_hkl_var = tk.BooleanVar(value=False)
        self.calc_min_intensity_var = tk.StringVar(value="3")
        self.calc_status_var = tk.StringVar(value="pymatgen available" if calculated.PYMATGEN_AVAILABLE else "Calculated reflections unavailable: install pymatgen")
        # Peak tracking
        self.peak_xmin_var = tk.StringVar(value="5")
        self.peak_xmax_var = tk.StringVar(value="6")
        self.peak_fit_window_var = tk.StringVar(value="0.3")
        self.peak_fwhm_guess_var = tk.StringVar(value="0.05")
        self.peak_baseline_var = tk.StringVar(value="arpls" if xrdpeak.Baseline is not None else "none")
        self.peak_center_var = tk.StringVar(value="5.5")
        self.peak_shift_var = tk.StringVar(value="0.05")
        self.peak_prominence_var = tk.StringVar(value="")
        self.peak_status_var = tk.StringVar(value="Set initial center; ambiguous tracks require reselection.")
        self.peak_start_var = tk.StringVar(value="Start: first scan")
        self.peak_plot_var = tk.StringVar(value="both")
        self.peak_editor_enabled_var = tk.BooleanVar(value=True)
        self.peak_editor_name_var = tk.StringVar(value="")
        self.peak_editor_center_var = tk.StringVar(value="5.5")
        self.peak_editor_xmin_var = tk.StringVar(value="5")
        self.peak_editor_xmax_var = tk.StringVar(value="6")
        self.peak_editor_shift_var = tk.StringVar(value="0.05")
        self.peak_editor_window_var = tk.StringVar(value="0.3")
        self.peak_editor_fwhm_var = tk.StringVar(value="0.05")
        self.peak_editor_prominence_var = tk.StringVar(value="")
        self.peak_editor_baseline_var = tk.StringVar(value="arpls" if xrdpeak.Baseline is not None else "none")
        self.peak_editor_start_var = tk.StringVar(value="Start: first scan")
        self.peak_editor_notice_var = tk.StringVar(value="Create a new peak or select a saved track.")
        self.peak_track_plot_mode_var = tk.StringVar(value="Separate panels")
        self.peak_global_summary_var = tk.StringVar(value="0 enabled tracks")
        self.peak_selected_scan_var = tk.StringVar(value="No scan selected")
        self.peak_active_detail_var = tk.StringVar(value="Select a track and scan to inspect its tracking decision.")
        # Pattern similarity
        self.sim_xmin_var = tk.StringVar(value="1.5")
        self.sim_xmax_var = tk.StringVar(value="13")
        self.sim_reference_var = tk.StringVar(value="Reference: first scan (chosen when plotted)")
        self.sim_status_var = tk.StringVar(value="")
        # Auto-refresh
        self.watch_folder_var = tk.StringVar(value="")
        self.auto_update_var = tk.BooleanVar(value=False)
        self.interval_var = tk.StringVar(value="5")  # seconds

        self.goto_scan_var = tk.StringVar(value="")
        self._init_detector_inspector()
        self._build_left_panel()
        self._cif_poll_job = self.after(100, self._poll_cif_results)
        self.bind("<Destroy>", self._cancel_cif_poll, add="+")
        self._wire_passpath_updates()
        self.xmax_var.trace_add("write", lambda *_: self._mark_xmax_custom())
        self.sim_xmax_var.trace_add("write", lambda *_: self._mark_sim_xmax_custom())
        self.type_var.trace_add("write", lambda *_: self._on_data_type_changed())
        self.use_selected_only_var.trace_add("write", lambda *_: self._refresh_scan_numbers())

    # ---------- UI ----------
    def _reflow_peak_bottom(self, event=None):
        """Keep peak editor and scan controls side by side until text can no longer fit."""
        if not hasattr(self, "_peak_bottom"):
            return
        ui_font = font.nametofont("TkDefaultFont", root=self)
        minimum = max(620, ui_font.measure("Selected / New Peak") + ui_font.measure("Selected Peak / Scan") + 470)
        stacked = self._peak_bottom.winfo_width() < minimum
        scan_info = self._peak_scan_panel.grid_info()
        desired_row = 1 if stacked else 0
        desired_column = 0 if stacked else 1
        if str(scan_info.get("row")) != str(desired_row) or str(scan_info.get("column")) != str(desired_column):
            self._peak_scan_panel.grid(row=desired_row, column=desired_column, sticky="nsew",
                                       padx=(0, 0) if stacked else (6, 0), pady=(6, 0) if stacked else 0)
        if stacked:
            self._peak_editor_panel.grid(row=0, column=0, sticky="nsew", padx=0)
        else:
            self._peak_editor_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

    def _build_left_panel(self):
        self._layout_shell()
        # Beamline Info
        info = ttk.LabelFrame(self.pass_scroll.content, text="PASS settings", padding=8); info.pack(fill="x", pady=(0,8))
        r = 0
        ttk.Label(info, text="Base path:").grid(row=r, column=0, sticky="e")
        ttk.Entry(info, textvariable=self.basepath_var, width=44).grid(row=r, column=1, columnspan=3, sticky="we", padx=4)

        r += 1
        ttk.Label(info, text="Cycle:").grid(row=r, column=0, sticky="e")
        ttk.Entry(info, textvariable=self.cycle_var, width=12).grid(row=r, column=1, sticky="w", padx=4)
        ttk.Label(info, text="Proposal #:").grid(row=r, column=2, sticky="e")
        ttk.Entry(info, textvariable=self.proposal_var, width=18).grid(row=r, column=3, sticky="w", padx=4)

        r += 1
        ttk.Label(info, text="SAF #:").grid(row=r, column=0, sticky="e")
        ttk.Entry(info, textvariable=self.saf_var, width=12).grid(row=r, column=1, sticky="w", padx=4)

        r += 1
        ttk.Label(info, text="PASS path:").grid(row=r, column=0, sticky="ne")
        self.passpath_lbl = ttk.Label(info, textvariable=self.passpath_var, justify="left", wraplength=420)
        self.passpath_lbl.grid(row=r, column=1, columnspan=2, sticky="w", padx=4)
        ttk.Button(info, text="Browse PASS Folder…", command=self.browse_passpath).grid(row=r, column=3, sticky="e")

        # Auto-Refresh
        watch = ttk.LabelFrame(self.source_controls, text="Data source", padding=8); watch.pack(fill="x", pady=8)
        rr = 0
        ttk.Label(watch, text="Watch folder:").grid(row=rr, column=0, sticky="e")
        ttk.Entry(watch, textvariable=self.watch_folder_var, width=12).grid(row=rr, column=1, columnspan=2, sticky="we", padx=4)
        ttk.Button(watch, text="Choose…", command=self.choose_watch_folder).grid(row=rr, column=3, sticky="w")

        rr += 1
        ttk.Checkbutton(watch, text="Auto-update", variable=self.auto_update_var, command=self._toggle_auto_update).grid(row=rr, column=0, sticky="w")
        ttk.Label(watch, text="Interval (s):").grid(row=rr, column=1, sticky="e")
        ttk.Entry(watch, textvariable=self.interval_var, width=6).grid(row=rr, column=2, sticky="w", padx=4)
        watch.columnconfigure(1, weight=1)

        left = self.scan_panel
        actions = ttk.Frame(left); actions.pack(fill='x', pady=4)
        for column, (label, callback) in enumerate((('Add files…', self.add_files), ('Clear', self.clear_files), ('Remove', self.remove_selected), ('Up', self.move_up), ('Down', self.move_down))):
            ttk.Button(actions, text=label, command=callback).grid(row=column//3, column=column%3, sticky='ew', padx=2, pady=2)
        footer = ttk.Frame(left); footer.pack(side='bottom', fill='x')
        goto = ttk.Frame(footer); goto.pack(fill='x', pady=4)
        ttk.Label(goto, text='Go to scan:').pack(side='left')
        entry = ttk.Entry(goto, textvariable=self.goto_scan_var, width=6); entry.pack(side='left', padx=3)
        entry.bind('<Return>', lambda event: self.go_to_scan())
        ttk.Button(goto, text='Go', command=self.go_to_scan).pack(side='left')
        selected = ttk.Frame(footer); selected.pack(fill='x', pady=4)
        self.scan_summary_var = tk.StringVar(value='No scan selected')
        ttk.Label(selected, textvariable=self.scan_summary_var).grid(row=0, column=0, sticky='w')
        self.inspect_scan_button = ttk.Button(selected, text='Inspect 2D/1D', command=self.show_detector_inspector, state='disabled')
        self.inspect_scan_button.grid(row=0, column=1, sticky='w', padx=4)
        ttk.Checkbutton(footer, text='Plot only selected files', variable=self.use_selected_only_var).pack(anchor='w')
        self.calibration_compact_var = tk.StringVar(value='Calibration unavailable')
        ttk.Label(footer, textvariable=self.calibration_compact_var).pack(anchor='w', pady=4)
        fl = ttk.Frame(left); fl.pack(fill='both', expand=True)
        self.file_list = ttk.Treeview(fl, columns=('scan', 'filename'), show='headings', height=5, selectmode='extended')
        for key, title, width in (('scan', 'Scan', 65), ('filename', 'Filename', 260)):
            self.file_list.heading(key, text=title)
            self.file_list.column(key, width=width, minwidth=50, stretch=key=='filename')
        vs = ttk.Scrollbar(fl, orient='vertical', command=self.file_list.yview)
        hs = ttk.Scrollbar(fl, orient='horizontal', command=self.file_list.xview)
        self.file_list.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.file_list.grid(row=0, column=0, sticky='nsew'); vs.grid(row=0, column=1, sticky='ns'); hs.grid(row=1, column=0, sticky='ew')
        fl.rowconfigure(0, weight=1); fl.columnconfigure(0, weight=1)
        self.file_list.bind('<<TreeviewSelect>>', self._file_selection_changed)
        self.file_list.bind('<Double-1>', self._inspect_double_clicked_file)
        # Map / overlay plot
        opts = ttk.LabelFrame(self.task_panes["Map / Overlay"].content, text="Map / Overlay Plot", padding=8); opts.pack(fill="x", pady=8)
        row = 0
        ttk.Label(opts, text="Data type:").grid(row=row, column=0, sticky="e")
        ttk.Combobox(opts, textvariable=self.type_var, values=["tth","q"], width=6, state="readonly").grid(row=row, column=1, sticky="w", padx=4)

        ttk.Label(opts, text="Plot mode:").grid(row=row, column=2, sticky="e")
        ttk.Combobox(opts, textvariable=self.plot_mode_var, values=["map","overlay"], width=8, state="readonly").grid(row=row, column=3, sticky="w", padx=4)

        row += 1
        ttk.Label(opts, text="xmin:").grid(row=row, column=0, sticky="e")
        ttk.Entry(opts, textvariable=self.xmin_var, width=8).grid(row=row, column=1, sticky="w", padx=4)
        ttk.Label(opts, text="xmax:").grid(row=row, column=2, sticky="e")
        ttk.Entry(opts, textvariable=self.xmax_var, width=8).grid(row=row, column=3, sticky="w", padx=4)

        row += 1
        ttk.Label(opts, text="skiprows:").grid(row=row, column=0, sticky="e")
        ttk.Entry(opts, textvariable=self.skiprows_var, width=8).grid(row=row, column=1, sticky="w", padx=4)
        ttk.Label(opts, text="cmap:").grid(row=row, column=2, sticky="e")
        ttk.Combobox(opts, textvariable=self.cmap_var, values=[
            "viridis","plasma","inferno","magma","cividis","turbo","Greys","jet"
        ], width=10, state="readonly").grid(row=row, column=3, sticky="w", padx=4)

        row += 1
        self.log_check = ttk.Checkbutton(opts, text="Log scale", variable=self.log_var)
        self.log_check.grid(row=row, column=0, sticky="w")

        # 🔹 Legend toggle
        row += 1
        self.overlay_legend = ttk.Checkbutton(opts, text="Show legend (overlay)", variable=self.show_legend_var)
        self.overlay_legend.grid(row=row, column=0, columnspan=2, sticky="w")
        ttk.Label(opts, text="Y offset per trace:").grid(row=row, column=2, sticky="e")
        self.overlay_offset = ttk.Entry(opts, textvariable=self.yoffset_var, width=8)
        self.overlay_offset.grid(row=row, column=3, sticky="w", padx=4)
        self.plot_mode_var.trace_add("write", lambda *_: self._update_overlay_controls())
        self._update_overlay_controls()

        row += 1
        ttk.Button(opts, text="Plot", command=self.plot).grid(row=row, column=0, sticky="w", pady=(6,0))
        ttk.Button(opts, text="Clear", command=self.clear_plot).grid(row=row, column=1, sticky="w", padx=4, pady=(6,0))
        ttk.Button(opts, text="Save", command=self.save_figure).grid(row=row, column=2, sticky="w", padx=4, pady=(6,0))
        self._build_calculated_phase_panel(self.task_panes["CIF References"].content)
        self._build_calibration_controls(self.task_panes["CIF References"].content)
        
        peak = ttk.LabelFrame(self.task_panes['Peak Tracking'].content, text='Peak tracks', padding=8)
        peak.pack(fill='x', pady=4)
        self._peak_manager_panel = peak
        peak.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(peak); toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text='Analyze tracks', command=self.fit_peak_trend).grid(row=0, column=0, padx=(0, 4))
        ttk.Label(toolbar, text='Plot mode:').grid(row=0, column=1, sticky='e')
        ttk.Combobox(toolbar, textvariable=self.peak_track_plot_mode_var, values=['Separate panels', 'Normalized comparison'], width=22, state='readonly').grid(row=0, column=2, sticky='w', padx=4)
        ttk.Button(toolbar, text='Plot tracks', command=self.plot_tracks).grid(row=0, column=3, padx=4)
        ttk.Button(toolbar, text='Results', command=lambda: self.show_results('peak')).grid(row=0, column=4, padx=(4, 0))
        ttk.Label(peak, textvariable=self.peak_global_summary_var, wraplength=900).grid(row=1, column=0, sticky="w", pady=(3, 0))

        table = ttk.Frame(peak); table.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        table.columnconfigure(0, weight=1)
        columns = ("enabled", "name", "center", "range", "status")
        tree_height = 5
        self._peak_manager_tree = ttk.Treeview(table, columns=columns, show="headings", height=tree_height, selectmode="browse")
        for column, title, width in zip(columns, ("Enabled", "Track name", "Initial center", "Range", "Status"), (70, 150, 95, 130, 290)):
            self._peak_manager_tree.heading(column, text=title)
            self._peak_manager_tree.column(column, width=width, stretch=column == "status")
        track_scroll = ttk.Scrollbar(table, orient="vertical", command=self._peak_manager_tree.yview)
        self._peak_manager_tree.configure(yscrollcommand=track_scroll.set)
        self._peak_manager_tree.grid(row=0, column=0, sticky="ew")
        track_scroll.grid(row=0, column=1, sticky="ns")
        self._peak_manager_tree.bind("<<TreeviewSelect>>", lambda event: self._manager_select_track())
        self._peak_manager_tree.heading("range", text="Allowed x range")

        bottom = ttk.Frame(peak); bottom.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self._peak_bottom = bottom
        editor = self._peak_editor_panel = ttk.LabelFrame(bottom, text="Selected / New Peak", padding=6)
        scan = self._peak_scan_panel = ttk.LabelFrame(bottom, text="Selected Peak / Scan", padding=6)
        bottom.columnconfigure(0, weight=3); bottom.columnconfigure(1, weight=2)
        editor.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        scan.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ttk.Checkbutton(editor, text="Enabled", variable=self.peak_editor_enabled_var).grid(row=0, column=0, sticky="w")
        fields = (("Track name:", self.peak_editor_name_var), ("Initial center:", self.peak_editor_center_var),
                  ("Maximum shift:", self.peak_editor_shift_var), ("Fit half-window:", self.peak_editor_window_var),
                  ("FWHM guess:", self.peak_editor_fwhm_var), ("Prominence:", self.peak_editor_prominence_var))
        for row, (label, variable) in enumerate(fields, start=1):
            ttk.Label(editor, text=label).grid(row=row, column=0, sticky="e")
            ttk.Entry(editor, textvariable=variable, width=16).grid(row=row, column=1, sticky="w", padx=4, pady=1)
        ttk.Label(editor, text="Baseline:").grid(row=7, column=0, sticky="e")
        ttk.Combobox(editor, textvariable=self.peak_editor_baseline_var,
                     values=["arpls", "asls", "none"] if xrdpeak.Baseline is not None else ["none"], state="readonly", width=13).grid(row=7, column=1, sticky="w", padx=4)
        self._peak_advanced_visible = False
        self._peak_advanced_button = ttk.Button(editor, text="Show advanced: allowed x range", command=self.toggle_peak_advanced)
        self._peak_advanced_button.grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._peak_advanced = ttk.LabelFrame(editor, text="Advanced: allowed x range", padding=4)
        ttk.Label(self._peak_advanced, text="Allowed xmin:").grid(row=0, column=0, sticky="e")
        ttk.Entry(self._peak_advanced, textvariable=self.peak_editor_xmin_var, width=10).grid(row=0, column=1, padx=4)
        ttk.Label(self._peak_advanced, text="Allowed xmax:").grid(row=0, column=2, sticky="e")
        ttk.Entry(self._peak_advanced, textvariable=self.peak_editor_xmax_var, width=10).grid(row=0, column=3, padx=4)
        self._peak_advanced.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._peak_advanced.grid_remove()

        editor_actions = ttk.Frame(editor); editor_actions.grid(row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(editor_actions, text="New peak", command=self.new_peak_editor).grid(row=0, column=0, padx=(0, 4))
        self._peak_save_button = ttk.Button(editor_actions, text="Save peak", command=self.save_peak); self._peak_save_button.grid(row=0, column=1, padx=4)
        self._peak_remove_button = ttk.Button(editor_actions, text="Remove peak", command=self.remove_selected_peak); self._peak_remove_button.grid(row=0, column=2, padx=4)
        ttk.Label(editor, textvariable=self.peak_editor_notice_var, wraplength=370).grid(row=11, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self._peak_active_name_label = ttk.Label(scan, text="Active track: none", wraplength=260); self._peak_active_name_label.pack(anchor="w")
        ttk.Label(scan, textvariable=self.peak_selected_scan_var, wraplength=260).pack(anchor="w", pady=(3, 6))
        self._peak_inspect_button = ttk.Button(scan, text="Inspect peak fit", command=self.inspect_selected_peak); self._peak_inspect_button.pack(fill="x", pady=2)
        self._peak_reselect_button = ttk.Button(scan, text="Reselect at selected scan", command=self.reselect_peak); self._peak_reselect_button.pack(fill="x", pady=2)
        ttk.Label(scan, textvariable=self.peak_active_detail_var, wraplength=270).pack(fill="x", pady=(8, 0))
        bottom.bind('<Configure>', self._reflow_peak_bottom, add='+')
        self._refresh_peak_manager(); self.new_peak_editor(); self._update_selected_scan_controls()

        # Similarity trend
        sim = ttk.LabelFrame(self.task_panes["Similarity"].content, text="Pattern Similarity", padding=8); sim.pack(fill="x", pady=(4,8))
        sr = 0
        ttk.Label(sim, text="Similarity xmin:").grid(row=sr, column=0, sticky="e")
        ttk.Entry(sim, textvariable=self.sim_xmin_var, width=8).grid(row=sr, column=1, sticky="w", padx=4)
        ttk.Label(sim, text="Similarity xmax:").grid(row=sr, column=2, sticky="e")
        ttk.Entry(sim, textvariable=self.sim_xmax_var, width=8).grid(row=sr, column=3, sticky="w", padx=4)
        ttk.Button(sim, text="Plot", command=self.plot_similarity_trend).grid(row=sr, column=4, sticky="w", padx=(10,0))

        sr += 1
        ttk.Button(sim, text="Use selected scan as reference", command=self.use_selected_reference).grid(row=sr, column=0, columnspan=3, sticky="w")
        ttk.Button(sim, text="Use first scan", command=self.use_first_reference).grid(row=sr, column=3, sticky="w")
        ttk.Button(sim, text="Results / statuses", command=lambda: self.show_results("similarity")).grid(row=sr, column=4, sticky="w")
        sr += 1
        ttk.Label(sim, textvariable=self.sim_reference_var, wraplength=450).grid(row=sr, column=0, columnspan=5, sticky="w")
        sr += 1
        ttk.Label(sim, textvariable=self.sim_status_var, wraplength=450).grid(row=sr, column=0, columnspan=5, sticky="w")

        # Figure save size (used only when saving)
        size_row = ttk.Frame(self.task_panes["Map / Overlay"].content); size_row.pack(fill="x", pady=(0,8))
        ttk.Label(size_row, text="Save size (W,H inches):").pack(side="left")
        ttk.Entry(size_row, textvariable=self.figw_var, width=5).pack(side="left", padx=(6,2))
        ttk.Label(size_row, text=",").pack(side="left")
        ttk.Entry(size_row, textvariable=self.figh_var, width=5).pack(side="left", padx=(2,8))

        self._set_ui_font(11)
        self._install_wheel_routing()
        self._update_layout_selection()

    # --- PASS path helpers ---
    def _wire_passpath_updates(self):
        for var in (self.basepath_var, self.cycle_var, self.proposal_var):
            var.trace_add("write", lambda *_: self._update_passpath())
        self._update_passpath()

    def _compute_passpath(self) -> Path:
        basepath = Path(self.basepath_var.get().strip() or "/nsls2/data/xpd-new/proposals")
        cycle = self.cycle_var.get().strip()
        proposal = self.proposal_var.get().strip()
        return (basepath / cycle / f"pass-{proposal}") if proposal else (basepath / cycle)

    def _update_passpath(self):
        self.passpath_var.set(str(self._compute_passpath()))

    # --- File dialog helpers ---
    def _chi_filetypes(self):
        dtype = (self.type_var.get() or "tth").lower()
        if dtype == "tth":
            return [("CHI files (tth)", "*tth.chi"), ("All CHI (*.chi)", "*.chi"), ("All files", "*.*")]
        elif dtype == "q":
            return [("CHI files (q)", "*q.chi"), ("All CHI (*.chi)", "*.chi"), ("All files", "*.*")]
        else:
            return [("CHI files", "*.chi"), ("All files", "*.*")]

    def _glob_pattern(self):
        dtype = (self.type_var.get() or "tth").lower()
        if dtype == "q":
            return "*q.chi"
        if dtype == "tth":
            return "*tth.chi"
        return "*.chi"

    # --- Choose/browse ---
    def _folder_dialog_initial_dir(self):
        if self.last_dir and Path(self.last_dir).exists():
            return Path(self.last_dir)

        initial_dir = self._compute_passpath()
        if initial_dir.exists():
            return initial_dir
        return Path(self.basepath_var.get().strip() or "/")

    def choose_watch_folder(self):
        # use last_dir if available, else use passpath
        initial_dir = self._folder_dialog_initial_dir()

        d = filedialog.askdirectory(
            title="Choose folder to watch",
            initialdir=str(initial_dir)
        )

        if d:
            # save this directory for next time
            self.watch_folder_var.set(d)
            self.last_dir = d
            self._last_snapshot = None

    def browse_passpath(self):
        initial_dir = self._compute_passpath()
        if not initial_dir.exists():
            if not messagebox.askyesno("Path not found",
                                       f"PASS path does not exist:\n{initial_dir}\n\nOpen parent folder instead?"):
                return
            while not initial_dir.exists() and initial_dir != initial_dir.parent:
                initial_dir = initial_dir.parent
            if not initial_dir.exists():
                initial_dir = Path(self.basepath_var.get().strip() or "/")
        d = filedialog.askdirectory(
            title="Choose PASS folder",
            initialdir=str(initial_dir)
        )
        if d:
            self.last_dir = d

    # ---------- File operations ----------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select .chi files",
            initialdir=str(self._folder_dialog_initial_dir()),
            filetypes=self._chi_filetypes()
        )
        if paths:
            self._sync_file_list_from_folder(self.selected_files + list(paths))

    def _selected_file_paths(self):
        return [item for item in self.file_list.get_children() if item in self.file_list.selection()]

    def _selected_indices(self):
        selected = set(self.file_list.selection())
        return [i for i, path in enumerate(self.selected_files) if path in selected]

    def _inspect_double_clicked_file(self, event):
        """Inspect the filename under the pointer, ignoring headers/empty space."""
        if (self.file_list.identify_region(event.x, event.y) != "cell"
                or self.file_list.identify_column(event.x) != "#2"):
            return
        item = self.file_list.identify_row(event.y)
        if not item:
            return
        self.file_list.selection_set(item)
        self.file_list.focus(item)
        self._file_selection_changed()
        self.show_detector_inspector()
        return "break"

    def _file_selection_changed(self, event=None):
        self._refresh_scan_numbers()
        self._update_selected_scan_controls()

    def _refresh_scan_numbers(self):
        # Number the exact active analysis series, including selection fallback.
        # Non-active rows are blank instead of inventing contradictory indices.
        if not hasattr(self, "file_list"):
            return
        files = self._files_to_plot()
        values = dict(zip(map(lambda p: str(Path(p).resolve()), files),
                          self._scan_axis_values(files)))
        for item in self.file_list.get_children():
            self.file_list.set(item, "scan", str(values[item]) if item in values else "")

    def _rebuild_file_table(self, selected=()):
        selected = set(selected)
        children = self.file_list.get_children()
        if children:
            self.file_list.delete(*children)
        for path in self.selected_files:
            self.file_list.insert("", "end", iid=path, values=("", Path(path).name))
        self.file_list.selection_set([p for p in self.selected_files if p in selected])
        self._refresh_scan_numbers()
        self._update_selected_scan_controls()

    def go_to_scan(self):
        text = self.goto_scan_var.get().strip()
        try:
            number = int(text)
        except ValueError:
            messagebox.showinfo("Go to scan", "Enter an integer scan number shown in the table.")
            return
        matches = [item for item in self.file_list.get_children()
                   if self.file_list.set(item, "scan") == str(number)]
        if not matches:
            messagebox.showinfo("Scan unavailable", f"Scan {number} is not present in the displayed active series.")
            return
        item = matches[0]
        self.file_list.selection_set(item)
        self.file_list.focus(item)
        self.file_list.see(item)
        self._file_selection_changed()

    def clear_files(self):
        self.selected_files.clear()
        self._rebuild_file_table()

    def remove_selected(self):
        selected = set(self._selected_file_paths())
        self.selected_files = [p for p in self.selected_files if p not in selected]
        self._rebuild_file_table()

    def move_up(self):
        indices = self._selected_indices()
        if not indices or indices[0] == 0:
            return
        selected = self._selected_file_paths()
        for i in indices:
            self.selected_files[i-1], self.selected_files[i] = self.selected_files[i], self.selected_files[i-1]
        self._rebuild_file_table(selected)

    def move_down(self):
        indices = self._selected_indices()
        if not indices or indices[-1] == len(self.selected_files)-1:
            return
        selected = self._selected_file_paths()
        for i in reversed(indices):
            self.selected_files[i+1], self.selected_files[i] = self.selected_files[i], self.selected_files[i+1]
        self._rebuild_file_table(selected)

    def _reselect(self, indices):
        self.file_list.selection_set([self.selected_files[i] for i in indices])
        self._file_selection_changed()

    # ---------- Plot helpers ----------
    def _files_to_plot(self):
        if self.auto_update_var.get():
            return self._scan_folder_files()
        if not self.selected_files:
            return []
        if self.use_selected_only_var.get():
            idxs = list(self._selected_indices())
            if not idxs:
                return []
            return xrdpeak.ordered_files([self.selected_files[i] for i in idxs])
        return xrdpeak.ordered_files(self.selected_files)

    # ---------- Auto update ----------
    def _toggle_auto_update(self):
        if self.auto_update_var.get():
            self._schedule_next_scan(immediate=True)
        else:
            if self._auto_job is not None:
                self.after_cancel(self._auto_job)
                self._auto_job = None

    def _schedule_next_scan(self, immediate=False):
        if self._auto_job is not None:
            try: self.after_cancel(self._auto_job)
            except Exception: pass
            self._auto_job = None
        try:
            ms = int(float(self.interval_var.get()) * 1000)
        except Exception:
            ms = 5000; self.interval_var.set("5")
        delay = 0 if immediate else ms
        self._auto_job = self.after(delay, self._auto_scan_and_plot)

    def _mark_xmax_custom(self):
        if not self._updating_range_defaults:
            self._xmax_auto_q_default = False

    def _mark_sim_xmax_custom(self):
        if not self._updating_range_defaults:
            self._sim_xmax_auto_q_default = False

    def _set_default_xmax(self, var, value):
        self._updating_range_defaults = True
        try:
            var.set(value)
        finally:
            self._updating_range_defaults = False

    def _update_range_defaults_for_type(self):
        dtype = (self.type_var.get() or "tth").lower()
        if dtype == "q":
            self._set_default_xmax(self.xmax_var, "8")
            self._set_default_xmax(self.sim_xmax_var, "8")
            self._xmax_auto_q_default = True
            self._sim_xmax_auto_q_default = True
        elif dtype == "tth":
            if self._xmax_auto_q_default and self.xmax_var.get().strip() == "8":
                self._set_default_xmax(self.xmax_var, "13")
            if self._sim_xmax_auto_q_default and self.sim_xmax_var.get().strip() == "8":
                self._set_default_xmax(self.sim_xmax_var, "13")
            self._xmax_auto_q_default = False
            self._sim_xmax_auto_q_default = False

    def _on_data_type_changed(self):
        self._update_range_defaults_for_type()
        self._last_snapshot = None
        if self.auto_update_var.get():
            files = self._scan_folder_files()
            self._sync_file_list_from_folder(files)
            self._schedule_next_scan(immediate=True)

    def _folder_snapshot(self, folder: Path):
        pattern = self._glob_pattern()
        paths = sorted(Path(folder).glob(pattern), key=natural_sort_key)
        paths = [p for p in paths if p.is_file() and p.suffix.lower() == ".chi"]
        if not paths: return set(), 0.0
        signatures = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
        return set(map(str, paths)), signatures

    def _scan_folder_files(self):
        folder = Path(self.watch_folder_var.get().strip() or "")
        if not folder.exists() or not folder.is_dir():
            return []
        pattern = self._glob_pattern()
        return xrdpeak.as_file_list(folder, search_item=pattern)

    def _safe_float(self, var, label, allow_empty=False):
        text = var.get().strip()
        if allow_empty and not text:
            return None
        try:
            return float(text)
        except Exception:
            raise ValueError(f"{label} must be a number.")

    def _scan_axis_values(self, files):
        return xrdpeak.scan_axis_values(files)

    def _sync_file_list_from_folder(self, files):
        selected = self._selected_file_paths()
        self.selected_files = xrdpeak.ordered_files(set(str(Path(p).resolve()) for p in files))
        self._rebuild_file_table(selected)
        self._autoload_calibration_for_files(self.selected_files)

    def _auto_scan_and_plot(self):
        try:
            folder = Path(self.watch_folder_var.get().strip() or "")
            if not folder.exists() or not folder.is_dir():
                self._schedule_next_scan(); return
            current_set, current_max_mtime = self._folder_snapshot(folder)
            if self._last_snapshot is None or current_set != self._last_snapshot[0] or current_max_mtime != self._last_snapshot[1]:
                files = self._scan_folder_files()
                self._sync_file_list_from_folder(files)
                if files:
                    self.plot()
                    if self._peak_fig is not None and plt.fignum_exists(self._peak_fig.number):
                        self.fit_peak_trend(show_warnings=False)
                    if self._similarity_fig is not None and plt.fignum_exists(self._similarity_fig.number):
                        self.plot_similarity_trend()
                self._last_snapshot = (current_set, current_max_mtime)
        finally:
            if self.auto_update_var.get():
                self._schedule_next_scan()

    # ---------- Calculated CIF references ----------
    def _build_calculated_phase_panel(self, parent):
        panel = ttk.LabelFrame(parent, text="Calculated Phases / HKL", padding=8); panel.pack(fill="x", pady=(4, 8))
        ttk.Label(panel, text="Wavelength (A):").grid(row=0, column=0, sticky="e")
        wavelength_entry = ttk.Entry(panel, textvariable=self.calc_wavelength_var, width=9)
        wavelength_entry.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Checkbutton(panel, text="Show calculated reflections", variable=self.calc_show_var).grid(row=1, column=0, columnspan=2, sticky="w", padx=4)
        ttk.Checkbutton(panel, text="Show HKL labels", variable=self.calc_hkl_var).grid(row=1, column=2, sticky="w", padx=4)
        ttk.Label(panel, text="Minimum relative intensity (%):").grid(row=2, column=0, sticky="e")
        ttk.Entry(panel, textvariable=self.calc_min_intensity_var, width=6).grid(row=2, column=1, sticky="w", padx=4)
        self._phase_swatch_images = {}
        self.calc_phase_tree = ttk.Treeview(panel, columns=("show", "name", "file", "color"), show="tree headings", height=3, selectmode="browse")
        self.calc_phase_tree.heading("#0", text=""); self.calc_phase_tree.column("#0", width=18, minwidth=18, stretch=False)
        for key, title, width in (("show", "Show", 55), ("name", "Phase name", 150), ("file", "CIF filename", 300), ("color", "Color", 120)):
            self.calc_phase_tree.heading(key, text=title); self.calc_phase_tree.column(key, width=width, stretch=key == "file")
        self.calc_phase_tree.bind("<Button-1>", self._phase_tree_click, add="+")
        self.calc_phase_tree.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        ttk.Button(panel, text="Add CIF...", command=self.add_cif_phase).grid(row=4, column=0, sticky="ew", padx=(5, 0))
        ttk.Button(panel, text="Remove selected phase", command=self.remove_selected_cif_phase).grid(row=4, column=1, sticky="ew", padx=(5, 0))
        ttk.Label(panel, textvariable=self.calc_status_var, wraplength=450).grid(row=5, column=0, columnspan=3, sticky="w")
        scroll = ttk.Scrollbar(panel, orient='vertical', command=self.calc_phase_tree.yview)
        scroll.grid(row=3, column=3, sticky='ns')
        self.calc_phase_tree.configure(yscrollcommand=scroll.set)
        if not calculated.PYMATGEN_AVAILABLE:
            for child in panel.winfo_children():
                if isinstance(child, ttk.Treeview):
                    child.state(["disabled"])
                elif isinstance(child, (ttk.Entry, ttk.Checkbutton, ttk.Button)):
                    child.configure(state="disabled")

        wavelength_entry.configure(state="normal")

    def _calculated_settings(self):
        wavelength = float(self.calc_wavelength_var.get())
        minimum = float(self.calc_min_intensity_var.get())
        if not np.isfinite(wavelength) or wavelength <= 0:
            raise ValueError("Wavelength must be finite and positive.")
        if not np.isfinite(minimum) or minimum < 0:
            raise ValueError("Minimum relative intensity must be finite and nonnegative.")
        return wavelength, minimum

    def add_cif_phase(self):
        filename = filedialog.askopenfilename(title="Add CIF reference", filetypes=[("CIF files", "*.cif"), ("All files", "*.*")])
        if not filename:
            return
        colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
        phase = calculated.CalculatedPhase(self._next_calculated_phase_id, Path(filename).stem, str(Path(filename).resolve()),
                                            colors[(self._next_calculated_phase_id - 1) % len(colors)])
        try:
            wavelength, minimum = self._calculated_settings()
            dtype, xmin, xmax = (self.type_var.get() or "tth").lower(), float(self.xmin_var.get() or 0), float(self.xmax_var.get() or 13)
        except Exception as exc:
            self.calc_status_var.set(str(exc)); return
        self._next_calculated_phase_id += 1; self.calculated_phases.append(phase)
        self._refresh_calculated_phase_tree(); self.calc_status_var.set(f"{phase.name}: Loading calculated reflections...")
        def worker():
            try:
                calculated.calculate_reflections(phase, wavelength, minimum, dtype=dtype, xmin=xmin, xmax=xmax)
                result = None
            except Exception as exc:
                result = str(exc)
            self._cif_results.put((phase.phase_id, result))
        threading.Thread(target=worker, daemon=True, name=f"cif-{phase.phase_id}").start()

    def _poll_cif_results(self):
        self._cif_poll_job = None
        try:
            while True:
                self._finish_cif_phase_load(*self._cif_results.get_nowait())
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            if self.winfo_exists():
                self._cif_poll_job = self.after(100, self._poll_cif_results)
        except tk.TclError:
            return

    def _cancel_cif_poll(self, event):
        if event.widget is self and getattr(self, "_cif_poll_job", None) is not None:
            try:
                self.after_cancel(self._cif_poll_job)
            except tk.TclError:
                pass
            self._cif_poll_job = None

    def _finish_cif_phase_load(self, phase_id, error):
        phase = next((item for item in self.calculated_phases if item.phase_id == phase_id), None)
        if phase is None:
            return
        self.calc_status_var.set(f"{phase.name}: {error}" if error else f"Loaded calculated reference: {phase.name}")
        self._refresh_calculated_phase_tree()

    def remove_selected_cif_phase(self):
        selected = self.calc_phase_tree.selection()
        if not selected: return
        phase_id = int(selected[0]); self.calculated_phases = [p for p in self.calculated_phases if p.phase_id != phase_id]
        self._refresh_calculated_phase_tree()

    def _phase_tree_click(self, event):
        tree = self.calc_phase_tree
        item = tree.identify_row(event.y)
        if item and tree.identify("region", event.x, event.y) == "cell" and tree.identify_column(event.x) == "#1":
            tree.selection_set(item)
            self._toggle_cif_phase(int(item))
            return "break"

    def _toggle_selected_cif_phase(self, event=None):
        selected = self.calc_phase_tree.selection()
        if selected:
            self._toggle_cif_phase(int(selected[0]))

    def _toggle_cif_phase(self, phase_id):
        phase = next((item for item in self.calculated_phases if item.phase_id == phase_id), None)
        if phase is not None:
            phase.enabled = not phase.enabled
            self._refresh_calculated_phase_tree()

    @staticmethod
    def _phase_color_label(color):
        named = {"#1f77b4": "blue", "#ff7f0e": "orange", "#2ca02c": "green", "#d62728": "red",
                 "#9467bd": "purple", "#8c564b": "brown", "#e377c2": "pink", "#7f7f7f": "gray",
                 "#bcbd22": "olive", "#17becf": "cyan"}
        try:
            hex_color = matplotlib.colors.to_hex(color)
        except ValueError:
            return str(color)
        return named.get(hex_color.lower(), hex_color)

    def _phase_swatch(self, color):
        try:
            hex_color = matplotlib.colors.to_hex(color)
        except ValueError:
            hex_color = "#000000"
        image = tk.PhotoImage(width=12, height=12)
        image.put(hex_color, to=(0, 0, 12, 12))
        return image

    def _refresh_calculated_phase_tree(self):
        tree = self.calc_phase_tree; tree.delete(*tree.get_children())
        self._phase_swatch_images.clear()
        for phase in self.calculated_phases:
            swatch = self._phase_swatch(phase.color)
            self._phase_swatch_images[phase.phase_id] = swatch
            tree.insert("", "end", iid=str(phase.phase_id), image=swatch,
                        values=("☑" if phase.enabled else "☐", phase.name, Path(phase.filename).name,
                                self._phase_color_label(phase.color)))

    def _calculated_references(self, dtype, xmin, xmax):
        if not self.calc_show_var.get() or not calculated.PYMATGEN_AVAILABLE:
            return []
        wavelength, minimum = self._calculated_settings()
        references = []
        for phase in self.calculated_phases:
            if not phase.enabled: continue
            try:
                reflections = calculated.calculate_reflections(phase, wavelength, minimum, dtype=dtype,
                                                               xmin=xmin if xmin is not None else 0,
                                                               xmax=xmax if xmax is not None else 180)
                for reflection, position in zip(reflections, calculated.positions_for_dtype(reflections, dtype)):
                    if (xmin is None or position >= xmin) and (xmax is None or position <= xmax):
                        references.append({**reflection, "position": position, "phase": phase})
            except Exception as exc:
                self.calc_status_var.set(f"{phase.name}: {exc}")
        return references

    def _draw_calculated_references(self, ax, dtype, xmin, xmax, overlay=False):
        references = self._calculated_references(dtype, xmin, xmax)
        if not references: return
        if overlay:
            ymin, ymax = ax.get_ylim(); span = ymax - ymin
            for ref in references:
                top = ymin + span * (.03 + .14 * ref["intensity"] / 100)
                ax.vlines(ref["position"], ymin, top, color=ref["phase"].color, linestyles="--", lw=1.2, zorder=5)
                if self.calc_hkl_var.get() and ref["hkl"]:
                    ax.text(ref["position"], top, ref["hkl"], color=ref["phase"].color, rotation=90, va="bottom", ha="center", fontsize="x-small", clip_on=True)
        else:
            for index, ref in enumerate(references):
                ax.axvline(ref["position"], color=ref["phase"].color, ls="--", lw=1, alpha=.9, zorder=4)
                if self.calc_hkl_var.get() and ref["hkl"]:
                    ax.text(ref["position"], .98 - .06 * (index % 3), ref["hkl"], color=ref["phase"].color, rotation=90,
                            va="top", ha="center", transform=ax.get_xaxis_transform(), fontsize="x-small", clip_on=True)

    # ---------- Plot / Clear / Save ----------
    def plot(self):
        """Open/replace an external matplotlib window with current data."""
        try:
            files = self._files_to_plot()
            if not files:
                messagebox.showwarning(
                    "No files",
                    f"No files to plot. Add files or set a valid watch folder with matching {self._glob_pattern()} files.")
                return

            xmin = float(self.xmin_var.get()) if self.xmin_var.get() else None
            xmax = float(self.xmax_var.get()) if self.xmax_var.get() else None
            skiprows = int(self.skiprows_var.get() or 0)
            cmap = self.cmap_var.get()
            use_log = self.log_var.get()
            mode = (self.plot_mode_var.get() or "map").lower()
            axis_label = "2Theta (deg)" if (self.type_var.get() or "tth").lower() == "tth" else "q"

            if self._ext_fig is None or not plt.fignum_exists(self._ext_fig.number):
                self._ext_fig = plt.figure(figsize=(12, 6))
            self._ext_fig.clf()
            ax = self._ext_fig.add_subplot(111)
            plt.subplots_adjust(bottom=0.12, left=0.1, right=0.95, top=0.9)

            if mode == "map":
                x_common, scan_values, data_array = xrdpeak.build_intensity_map(
                    files, xmin=xmin, xmax=xmax, skiprows=skiprows)
                norm = None
                if use_log:
                    pos = data_array[data_array > 0]
                    if pos.size == 0:
                        messagebox.showerror("Log scale error", "All intensities are <= 0; cannot use Log scale.")
                        return
                    vmin = max(float(np.min(pos)), 1e-12)
                    vmax = float(np.max(data_array))
                    norm = LogNorm(vmin=vmin, vmax=vmax)
                im = ax.imshow(
                    data_array, aspect="auto",
                    extent=[x_common[0], x_common[-1], scan_values[0] - 0.5, scan_values[-1] + 0.5],
                    origin="lower", cmap=cmap, norm=norm
                )
                cbar = self._ext_fig.colorbar(im, ax=ax)
                cbar.set_label("Intensity (Log scale)" if use_log else "Intensity")
                ax.set_ylabel("Scans")
                ax.set_title("XRD Intensity Map")
                self._draw_calculated_references(ax, (self.type_var.get() or "tth").lower(), xmin, xmax)
            else:
                x_list, y_list = zip(*(loadxy(f, skiprows=skiprows, xmin=xmin, xmax=xmax)
                                       for f in files))
                # Overlay mode with Y offset
                try:
                    yoffset = float(self.yoffset_var.get() or 0.0)
                except Exception:
                    yoffset = 0.0
                    self.yoffset_var.set("0")
                if use_log:
                    ax.set_yscale("log")
                for i, (f, x, y) in enumerate(zip(files, x_list, y_list)):
                    y_plot = y + i * yoffset
                    if use_log:
                        # guard non-positives for log scale
                        y_plot = np.where(y_plot > 0, y_plot, np.nan)
                        if np.all(np.isnan(y_plot)):
                            continue
                    ax.plot(x, y_plot, label=Path(f).name)
                ax.set_ylabel("Intensity" + (", log scale" if use_log else ""))
                ax.set_title("XRD Overlay (offset per trace)")
                self._draw_calculated_references(ax, (self.type_var.get() or "tth").lower(), xmin, xmax, overlay=True)

                # ✅ Show legend only if checkbox is checked
                if self.show_legend_var.get():
                    ax.legend(loc="best", fontsize="small")
                #if len(files) <= 15:
                    #ax.legend(loc="best", fontsize="small")

            ax.set_xlabel(axis_label)
            self._ext_fig.canvas.draw_idle()
            plt.show(block=False)

        except Exception as e:
            messagebox.showerror("Plot error", f"{type(e).__name__}: {e}")

    def clear_plot(self):
        """Close the external matplotlib figure."""
        try:
            if self._ext_fig is not None and plt.fignum_exists(self._ext_fig.number):
                plt.close(self._ext_fig)
            self._ext_fig = None
        except Exception as e:
            messagebox.showerror("Clear plot error", f"{type(e).__name__}: {e}")

    def save_figure(self):
        """Save the current external figure with chosen size."""
        if self._ext_fig is None or not plt.fignum_exists(self._ext_fig.number):
            messagebox.showwarning("No figure", "Open a plot first."); return
        path = filedialog.asksaveasfilename(
            initialdir=self.last_dir,
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")]
        )
        if not path: return
        try:
            curw, curh = self._ext_fig.get_size_inches()
            w = float(self.figw_var.get() or 12)
            h = float(self.figh_var.get() or 6)
            self._ext_fig.set_size_inches(w, h, forward=True)
            self._ext_fig.savefig(path, bbox_inches="tight", dpi=300)
            self._ext_fig.set_size_inches(curw, curh, forward=True)
            messagebox.showinfo("Saved", f"Figure saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Save error", f"{type(e).__name__}: {e}")

    # ---------- Peak tracking / similarity ----------
    def _next_peak_name(self):
        used = {track.name for track in self.peak_tracks}
        number = 1
        while f"Peak {number}" in used:
            number += 1
        return f"Peak {number}"

    def add_peak_track(self, **values):
        """Create an independently configured track; exposed for manager and tests."""
        name = values.pop("name", self._next_peak_name())
        track = PeakTrack(track_id=self._next_peak_track_id, name=name, **values)
        self._validate_peak_track(track)
        self._next_peak_track_id += 1
        self.peak_tracks.append(track)
        self._selected_peak_track_id = track.track_id
        return track

    def edit_peak_track(self, track_id, **values):
        track = self._peak_track(track_id)
        if track is None:
            raise ValueError("Selected peak track no longer exists.")
        updated = PeakTrack(**{**track.__dict__, **values})
        self._validate_peak_track(updated)
        for key, value in values.items():
            setattr(track, key, value)
        return track

    def duplicate_peak_track(self, track_id):
        track = self._peak_track(track_id)
        if track is None:
            raise ValueError("Select a peak track to duplicate.")
        values = {key: getattr(track, key) for key in (
            "enabled", "initial_center", "xmin", "xmax", "max_shift", "fit_window",
            "fwhm_guess", "prominence", "baseline_method", "start_file")}
        return self.add_peak_track(**values)

    def remove_peak_track(self, track_id):
        self.peak_tracks = [track for track in self.peak_tracks if track.track_id != track_id]
        if self._selected_peak_track_id == track_id:
            self._selected_peak_track_id = None

    def _peak_track(self, track_id=None):
        track_id = self._selected_peak_track_id if track_id is None else track_id
        return next((track for track in self.peak_tracks if track.track_id == track_id), None)

    def _validate_peak_track(self, track):
        values = [track.initial_center, track.xmin, track.xmax, track.max_shift,
                  track.fit_window, track.fwhm_guess]
        if not track.name.strip():
            raise ValueError("Track name cannot be blank.")
        if not np.all(np.isfinite(values)) or not track.xmin < track.initial_center < track.xmax:
            raise ValueError("Initial center must be inside a finite peak range.")
        if min(track.max_shift, track.fit_window, track.fwhm_guess) <= 0:
            raise ValueError("Shift, fit half-window, and FWHM guess must be positive.")
        if track.prominence is not None and (not np.isfinite(track.prominence) or track.prominence <= 0):
            raise ValueError("Prominence must be positive or blank for automatic detection.")

    def _legacy_peak_track(self):
        """Keep programmatic callers of the former one-track controls working."""
        track = self.add_peak_track(
            initial_center=self._safe_float(self.peak_center_var, "Initial center"),
            max_shift=self._safe_float(self.peak_shift_var, "Maximum center shift"),
            xmin=self._safe_float(self.peak_xmin_var, "Peak xmin"),
            xmax=self._safe_float(self.peak_xmax_var, "Peak xmax"),
            fit_window=self._safe_float(self.peak_fit_window_var, "Fit window"),
            fwhm_guess=self._safe_float(self.peak_fwhm_guess_var, "FWHM guess"),
            baseline_method=None if self.peak_baseline_var.get() == "none" else self.peak_baseline_var.get(),
            prominence=self._safe_float(self.peak_prominence_var, "Prominence", allow_empty=True))
        self._legacy_peak_track_id = track.track_id
        return track

    def _track_options(self, track):
        self._validate_peak_track(track)
        return dict(initial_center=track.initial_center, max_shift=track.max_shift,
                    xmin=track.xmin, xmax=track.xmax, fit_window=track.fit_window,
                    fwhm_guess=track.fwhm_guess, baseline_method=track.baseline_method,
                    skiprows=int(self.skiprows_var.get() or 0), prominence=track.prominence,
                    start_file=track.start_file)

    def _track_summary(self, track):
        if track.results is None:
            return "Not analyzed"
        detected = int((track.results.status == "detected").sum())
        return f"{detected} detected; {len(track.results)-detected} unavailable"

    def analyze_enabled_tracks(self, show_warnings=True):
        files = self._files_to_plot()
        if not files:
            raise ValueError("No files available for peak tracking.")
        enabled = [track for track in self.peak_tracks if track.enabled]
        if not enabled:
            raise ValueError("Add and enable at least one peak track.")
        tables = []
        for track in enabled:
            result = xrdpeak.track_peak_files(files, **self._track_options(track))
            track.results = result
            table = result.copy()
            table.insert(2, "track_id", track.track_id)
            table.insert(3, "track_name", track.name)
            tables.append(table)
        self.peak_results = pd.concat(tables, ignore_index=True)
        summaries = []
        for track in enabled:
            summary = f"{track.name}: {self._track_summary(track)}"
            rejected = track.results[(~track.results.status.isin(["detected", "tracking paused"])) &
                                     (track.results.detail != "Before selected starting scan")]
            if not rejected.empty:
                first = rejected.iloc[0]
                summary += f". First rejection ({Path(first.file).name}): {first.detail}"
            summaries.append(summary)
        self.peak_status_var.set("; ".join(summaries))
        self._update_peak_global_summary()
        self._refresh_peak_manager()
        return enabled, files

    def fit_peak_trend(self, show_warnings=True):
        if xrdpeak is None:
            messagebox.showerror("Peak analysis error", "Could not import xrd_peak_workflow.py.")
            return
        try:
            if not self.peak_tracks:
                self._legacy_peak_track()
            elif getattr(self, "_legacy_peak_track_id", None) is not None and len(self.peak_tracks) == 1:
                legacy = self._peak_track(self._legacy_peak_track_id)
                if legacy is not None:
                    legacy.initial_center = self._safe_float(self.peak_center_var, "Initial center")
                    legacy.max_shift = self._safe_float(self.peak_shift_var, "Maximum center shift")
                    legacy.xmin = self._safe_float(self.peak_xmin_var, "Peak xmin")
                    legacy.xmax = self._safe_float(self.peak_xmax_var, "Peak xmax")
                    legacy.fit_window = self._safe_float(self.peak_fit_window_var, "Fit window")
                    legacy.fwhm_guess = self._safe_float(self.peak_fwhm_guess_var, "FWHM guess")
                    legacy.baseline_method = None if self.peak_baseline_var.get() == "none" else self.peak_baseline_var.get()
                    legacy.prominence = self._safe_float(self.peak_prominence_var, "Prominence", allow_empty=True)
            tracks, files = self.analyze_enabled_tracks(show_warnings)
            scan_values = self._scan_axis_values(files)
            plot_choice = self.peak_plot_var.get()
            if self._peak_fig is None or not plt.fignum_exists(self._peak_fig.number):
                self._peak_fig = plt.figure(figsize=(10, max(3, 3 * len(tracks))))
                self._peak_fig.canvas.mpl_connect("close_event", lambda event: setattr(self, "_peak_fig", None))
            self._peak_fig.clf()
            metrics = ([('center', 'Center')] if plot_choice == 'position' else
                       [('height', 'Fitted peak height')] if plot_choice == 'height' else
                       [('center', 'Center'), ('height', 'Fitted peak height')])
            axes = self._peak_fig.subplots(len(tracks), len(metrics), squeeze=False, sharex=True)
            colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
            for row, track in enumerate(tracks):
                color = colors[row % len(colors)]
                for col, (metric, ylabel) in enumerate(metrics):
                    ax = axes[row, col]
                    ax.plot(scan_values, track.results[metric], 'o-', color=color, label=track.name)
                    ax.set_ylabel(ylabel); ax.set_title(track.name, loc='left', fontsize='small')
                    ax.grid(True, alpha=.3)
                    if row == len(tracks)-1: ax.set_xlabel('Scan')
            self._peak_fig.suptitle("Independent pseudo-Voigt peak tracks")
            self._peak_fig.tight_layout()
            self._peak_fig.canvas.draw_idle()
            plt.show(block=False)
        except Exception as e:
            messagebox.showerror("Peak analysis error", f"{type(e).__name__}: {e}")

    def manage_peak_tracks(self):
        self._peak_manager_tree.focus_set()

    def _refresh_peak_manager(self):
        tree = self._peak_manager_tree
        if tree is None or not tree.winfo_exists():
            return
        tree.delete(*tree.get_children())
        for track in self.peak_tracks:
            tree.insert("", "end", iid=str(track.track_id), values=("Yes" if track.enabled else "No", track.name,
                f"{track.initial_center:g}", f"{track.xmin:g} to {track.xmax:g}", self._track_summary(track)))
        if self._selected_peak_track_id is not None and tree.exists(str(self._selected_peak_track_id)):
            tree.selection_set(str(self._selected_peak_track_id))
        self._update_peak_button_states()

    def _update_peak_button_states(self):
        has_track = self._peak_track() is not None
        state = "normal" if has_track else "disabled"
        for button in (getattr(self, "_peak_remove_button", None),):
            if button is not None:
                button.configure(state=state)
        save_button = getattr(self, "_peak_save_button", None)
        if save_button is not None:
            save_button.configure(text="Save changes" if has_track else "Save new peak")
        self._update_selected_scan_controls()

    def _update_selected_scan_controls(self):
        self._update_layout_selection()
        selected = self._selected_indices() if hasattr(self, "file_list") else ()
        if len(selected) == 1:
            self.peak_selected_scan_var.set(f"Selected scan: {Path(self.selected_files[selected[0]]).name}")
        else:
            self.peak_selected_scan_var.set("No scan selected" if not selected else "Select exactly one scan")
        enabled = self._peak_track() is not None and len(selected) == 1
        for button in (getattr(self, "_peak_inspect_button", None), getattr(self, "_peak_reselect_button", None)):
            if button is not None:
                button.configure(state="normal" if enabled else "disabled")

    def _update_peak_global_summary(self):
        enabled = [track for track in self.peak_tracks if track.enabled]
        detected = sum(int((track.results.status == "detected").sum()) for track in enabled if track.results is not None)
        unavailable = sum(len(track.results) - int((track.results.status == "detected").sum()) for track in enabled if track.results is not None)
        suffix = f"{detected} detected measurements; {unavailable} unavailable" if any(track.results is not None for track in enabled) else "not analyzed"
        self.peak_global_summary_var.set(f"{len(enabled)} enabled tracks • {suffix}")

    def plot_tracks(self):
        if self.peak_track_plot_mode_var.get() == "Normalized comparison":
            self.plot_peak_comparison()
        else:
            self.fit_peak_trend()

    def toggle_peak_advanced(self):
        self._peak_advanced_explicit = True
        self._peak_advanced_visible = not self._peak_advanced_visible
        if self._peak_advanced_visible:
            self._peak_advanced.grid()
        else:
            self._peak_advanced.grid_remove()
        self._peak_advanced_button.configure(
            text="Hide advanced: allowed x range" if self._peak_advanced_visible else "Show advanced: allowed x range")

    def save_peak(self):
        if self._peak_track() is None:
            self.save_new_peak()
        else:
            self.update_selected_peak()

    def _load_peak_editor(self, track):
        self._peak_advanced_explicit = True
        self.peak_editor_enabled_var.set(track.enabled)
        self.peak_editor_name_var.set(track.name)
        self.peak_editor_center_var.set(f"{track.initial_center:g}")
        self.peak_editor_xmin_var.set(f"{track.xmin:g}")
        self.peak_editor_xmax_var.set(f"{track.xmax:g}")
        self.peak_editor_shift_var.set(f"{track.max_shift:g}")
        self.peak_editor_window_var.set(f"{track.fit_window:g}")
        self.peak_editor_fwhm_var.set(f"{track.fwhm_guess:g}")
        self.peak_editor_prominence_var.set("" if track.prominence is None else f"{track.prominence:g}")
        self.peak_editor_baseline_var.set(track.baseline_method or "none")
        self.peak_editor_start_var.set("Start: first scan" if track.start_file is None else f"Start: {Path(track.start_file).name}; earlier scans unavailable")
        if hasattr(self, "_peak_active_name_label"):
            self._peak_active_name_label.configure(text=f"Active track: {track.name}")
        self._update_active_track_detail(track)

    def _editor_is_dirty(self, track):
        try:
            values = self._editor_peak_values()
        except (TypeError, ValueError):
            return True
        return any(values[key] != getattr(track, key) for key in values)

    def _update_active_track_detail(self, track):
        if track.results is None:
            self.peak_active_detail_var.set("No analysis for this track yet.")
            return
        selected = self._selected_indices()
        if len(selected) == 1:
            filename = str(Path(self.selected_files[selected[0]]))
            row = track.results[track.results.file.map(lambda value: str(Path(value)) == filename)]
            if not row.empty:
                result = row.iloc[0]
                detail = result.detail or "accepted"
                self.peak_active_detail_var.set(f"{result.status}: {detail}")
                return
        self.peak_active_detail_var.set(self._track_summary(track))

    def new_peak_editor(self):
        self._selected_peak_track_id = None
        self._peak_advanced_explicit = False
        self.peak_editor_enabled_var.set(True)
        self.peak_editor_name_var.set(self._next_peak_name())
        self.peak_editor_center_var.set("5.5"); self.peak_editor_xmin_var.set("5"); self.peak_editor_xmax_var.set("6")
        self.peak_editor_shift_var.set("0.05"); self.peak_editor_window_var.set("0.3"); self.peak_editor_fwhm_var.set("0.05")
        self.peak_editor_prominence_var.set("")
        self.peak_editor_baseline_var.set("none" if xrdpeak.Baseline is None else "arpls")
        self.peak_editor_start_var.set("Start: first scan")
        self.peak_editor_notice_var.set("New peak editor. Saving creates a new independent track.")
        if hasattr(self, "_peak_active_name_label"):
            self._peak_active_name_label.configure(text="Active track: none")
        self.peak_active_detail_var.set("Select a track and scan to inspect its tracking decision.")
        tree = self._peak_manager_tree
        if tree is not None and tree.winfo_exists(): tree.selection_remove(tree.selection())
        self._update_peak_button_states()

    def _editor_peak_values(self):
        prominence = self.peak_editor_prominence_var.get().strip()
        initial_center = float(self.peak_editor_center_var.get())
        xmin, xmax = float(self.peak_editor_xmin_var.get()), float(self.peak_editor_xmax_var.get())
        # A new track's collapsed range is an automatic guardrail, not a hidden
        # second required input. Explicit advanced settings remain strict.
        if not getattr(self, "_peak_advanced_explicit", False) and not xmin < initial_center < xmax:
            span = max(.5, abs(initial_center) * .1)
            xmin, xmax = initial_center - span, initial_center + span
            self.peak_editor_xmin_var.set(f"{xmin:g}")
            self.peak_editor_xmax_var.set(f"{xmax:g}")
        return dict(enabled=self.peak_editor_enabled_var.get(), name=self.peak_editor_name_var.get().strip(),
                    initial_center=initial_center, xmin=xmin, xmax=xmax, max_shift=float(self.peak_editor_shift_var.get()),
                    fit_window=float(self.peak_editor_window_var.get()), fwhm_guess=float(self.peak_editor_fwhm_var.get()),
                    prominence=None if not prominence else float(prominence),
                    baseline_method=None if self.peak_editor_baseline_var.get() == "none" else self.peak_editor_baseline_var.get())

    def save_new_peak(self):
        try:
            track = self.add_peak_track(**self._editor_peak_values())
            self._selected_peak_track_id = track.track_id; self._load_peak_editor(track)
            self.peak_editor_notice_var.set(f"Saved new track: {track.name}.")
            self._refresh_peak_manager()
        except Exception as exc:
            messagebox.showerror("Invalid peak track", str(exc))

    def update_selected_peak(self):
        track = self._peak_track()
        if track is None:
            messagebox.showwarning("Select a peak track", "Select a saved track before updating it."); return
        try:
            self.edit_peak_track(track.track_id, **self._editor_peak_values())
            track.results = None
            self._rebuild_peak_results()
            self.peak_editor_notice_var.set(f"Updated {track.name}; only this track's cached results were invalidated.")
            self._refresh_peak_manager()
        except Exception as exc:
            messagebox.showerror("Invalid peak track", str(exc))

    def duplicate_selected_peak(self):
        track = self._peak_track()
        if track is None: return
        duplicate = self.duplicate_peak_track(track.track_id)
        self._selected_peak_track_id = duplicate.track_id; self._load_peak_editor(duplicate)
        self._refresh_peak_manager()

    def remove_selected_peak(self):
        track = self._peak_track()
        if track is None: return
        self.remove_peak_track(track.track_id); self._rebuild_peak_results(); self.new_peak_editor(); self._refresh_peak_manager()

    def _rebuild_peak_results(self):
        tables = []
        for track in self.peak_tracks:
            if track.results is not None:
                table = track.results.copy(); table.insert(2, "track_id", track.track_id); table.insert(3, "track_name", track.name); tables.append(table)
        self.peak_results = pd.concat(tables, ignore_index=True) if tables else None
        self._update_peak_global_summary()

    def _manager_select_track(self):
        selected = self._peak_manager_tree.selection()
        if not selected: return
        requested_id = int(selected[0])
        previous = self._peak_track()
        if previous is not None and previous.track_id != requested_id and self._editor_is_dirty(previous):
            choice = messagebox.askyesnocancel("Unsaved peak changes", "Save changes to the current peak before selecting another track?")
            if choice is None:
                self._peak_manager_tree.selection_set(str(previous.track_id)); return
            if choice:
                self.update_selected_peak()
                if self._editor_is_dirty(previous):
                    self._peak_manager_tree.selection_set(str(previous.track_id)); return
        self._selected_peak_track_id = requested_id
        track = self._peak_track()
        self._load_peak_editor(track)
        self.peak_editor_notice_var.set(f"Editing {track.name} — changes are not saved until Save changes.")
        self._update_peak_button_states()

    def plot_peak_comparison(self):
        tracks = [track for track in self.peak_tracks if track.enabled and track.results is not None]
        if not tracks:
            messagebox.showwarning("No peak results", "Analyze enabled tracks first."); return
        fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
        for index, track in enumerate(tracks):
            result = track.results; accepted = result.status.eq('detected')
            height = result.height.where(accepted); center = result.center.where(accepted)
            first_height, first_center = height.first_valid_index(), center.first_valid_index()
            relative_height = height / height.loc[first_height] if first_height is not None else height
            center_shift = center - center.loc[first_center] if first_center is not None else center
            scan = result.sequence
            axes[0].plot(scan, relative_height, 'o-', color=colors[index % len(colors)], label=track.name)
            axes[1].plot(scan, center_shift, 'o-', color=colors[index % len(colors)], label=track.name)
        axes[0].set_ylabel('Relative fitted peak height'); axes[1].set_ylabel('Center shift from first accepted center')
        axes[1].set_xlabel('Scan')
        for ax in axes: ax.grid(True, alpha=.3); ax.legend(loc='best')
        fig.tight_layout(); plt.show(block=False)

    def _update_overlay_controls(self):
        mode = (self.plot_mode_var.get() or "map").lower()
        overlay_state = "normal" if mode == "overlay" else "disabled"
        self.overlay_legend.configure(state=overlay_state)
        self.overlay_offset.configure(state=overlay_state)
        if mode == "overlay":
            self.log_var.set(False)
            self.log_check.configure(state="disabled")
        else:
            self.log_var.set(True)
            self.log_check.configure(state="normal")

    def _selected_scan(self):
        selected = self._selected_indices()
        if len(selected) != 1:
            messagebox.showwarning("Select one scan", "Select exactly one scan in the GUI file list.")
            return None
        return str(Path(self.selected_files[selected[0]]).resolve())

    def inspect_selected_peak(self):
        """Show the tracker decision and raw-data diagnostic for one selected scan."""
        filename = self._selected_scan()
        if filename is None:
            return
        track = self._peak_track()
        if track is None:
            messagebox.showwarning("Select a peak track", "Select a track in Peak Track Manager before inspecting a scan.")
            return
        try:
            files = self._files_to_plot()
            options = self._track_options(track)
            info = xrdpeak.inspect_tracked_peak(files, filename, **options)
            result, x, raw = info["result"], info["x"], info["raw"]
            fig, (ax, residual_ax) = plt.subplots(2, 1, figsize=(9, 7), sharex=True,
                                                   gridspec_kw={"height_ratios": [3, 1]})
            ax.plot(x, raw, color="0.35", lw=1, label="Raw intensity")
            ax.plot(x, info["baseline"], color="tab:green", lw=1, label="Estimated baseline")
            if len(info["peaks"]):
                ax.plot(x[info["peaks"]], raw[info["peaks"]], "x", color="tab:orange", label="Detected candidates")
            ax.axvspan(*info["center_gate"], color="tab:blue", alpha=.08, label="Center gate")
            ax.axvline(info["predicted_center"], color="tab:blue", ls=":", label="Predicted center")
            if np.isfinite(result["center"]):
                ax.axvline(result["center"], color="black", ls="--", label="Accepted fit center")
            fit = info["fit"]
            if fit is not None:
                raw_fit = fit["best_fit"] + np.interp(fit["x_fit"], x, info["baseline"])
                ax.plot(fit["x_fit"], raw_fit, color="tab:red", lw=2, label="Pseudo-Voigt fit (raw level)")
                residual_ax.plot(fit["x_fit"], fit["y_fit"] - fit["best_fit"], color="tab:red", lw=1)
            else:
                residual_ax.text(.01, .8, "No accepted fit was available; see status above.",
                                 transform=residual_ax.transAxes, fontsize="small")
            ax.set_ylabel("Intensity")
            ax.grid(True, alpha=.3); ax.legend(loc="best", fontsize="small")
            residual_ax.axhline(0, color="0.4", lw=1)
            residual_ax.set_ylabel("Residual"); residual_ax.set_xlabel("x")
            detail = result["detail"] or "accepted"
            fig.suptitle(f"{track.name}: {Path(filename).name}\n{result['status']}: {detail}")
            fig.tight_layout(); plt.show(block=False)
        except Exception as exc:
            messagebox.showerror("Peak inspection error", f"{type(exc).__name__}: {exc}")

    def reselect_peak(self):
        filename = self._selected_scan()
        track = self._peak_track()
        if filename is None:
            return
        if track is None:
            messagebox.showwarning("Select a peak track", "Select a track in Peak Track Manager before reselection.")
            return
        track.start_file = filename
        self._selected_peak_track_id = track.track_id
        self.fit_peak_trend()

    def reset_peak_start(self):
        track = self._peak_track()
        if track is not None:
            track.start_file = None
            self.fit_peak_trend()

    def use_selected_reference(self):
        filename = self._selected_scan()
        if filename is not None:
            self._set_similarity_reference(filename)

    def use_first_reference(self):
        files = self._files_to_plot()
        if files:
            self._set_similarity_reference(files[0])

    def _set_similarity_reference(self, filename):
        self._similarity_reference = str(Path(filename).resolve())
        self._similarity_config = None
        self.sim_reference_var.set(f"Reference: {Path(filename).name}")
        if self._similarity_fig is not None and plt.fignum_exists(self._similarity_fig.number):
            self.plot_similarity_trend()

    def show_results(self, kind):
        table = self.peak_results if kind == "peak" else self.similarity_results
        if table is None:
            messagebox.showinfo("No results", "Calculate the trend first.")
            return
        window = tk.Toplevel(self)
        window.title(f"{kind.title()} results / statuses (snapshot)")
        window.geometry("1100x450")
        columns = list(table.columns)
        tree = ttk.Treeview(window, columns=columns, show="headings")
        vertical = ttk.Scrollbar(window, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(window, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        vertical.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x")
        tree.pack(fill="both", expand=True)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=280 if column in {"file", "detail"} else 140, stretch=False)
        for row in table.itertuples(index=False, name=None):
            tree.insert("", "end", values=[f"{value:.6g}" if isinstance(value, float) else str(value) for value in row])

    def plot_similarity_trend(self):
        try:
            files = self._files_to_plot()
            if not files:
                messagebox.showwarning("No files", "Need at least one scan for similarity.")
                return
            xmin = self._safe_float(self.sim_xmin_var, "Similarity xmin")
            xmax = self._safe_float(self.sim_xmax_var, "Similarity xmax")
            skiprows = int(self.skiprows_var.get() or 0)
            if self._similarity_reference is None:
                self._similarity_reference = str(Path(files[0]).resolve())
            self.sim_reference_var.set(f"Reference: {Path(self._similarity_reference).name}")
            config = self._similarity_config
            key = (self._similarity_reference, xmin, xmax, skiprows)
            if config is None or (config.reference_file, config.xmin, config.xmax, config.skiprows) != key:
                config = xrdpeak.SimilarityConfiguration(*key)
                self._similarity_config = config
            self.similarity_results = config.compare(files)
            results = self.similarity_results
            unavailable = int(results["fixed_reference"].isna().sum())
            pair_unavailable = int(results["consecutive"].iloc[1:].isna().sum())
            self.sim_status_var.set(f"Unavailable: {unavailable} reference comparisons; {pair_unavailable} consecutive pairs. See Results / statuses.")
            if self._similarity_fig is None or not plt.fignum_exists(self._similarity_fig.number):
                self._similarity_fig = plt.figure(figsize=(10, 7))
                self._similarity_fig.canvas.mpl_connect("close_event", lambda event: setattr(self, "_similarity_fig", None))
            self._similarity_fig.clf()
            axes = self._similarity_fig.subplots(2, 1, sharex=True)
            axes[0].plot(results["pair_midpoint"], results["consecutive"], "o-", color="tab:green")
            axes[0].set_title("Consecutive scans (points at scan-pair midpoints)")
            axes[1].plot(results["sequence"], results["fixed_reference"], "o-", color="tab:blue")
            axes[1].set_title(f"Fixed reference: {Path(config.reference_file).name}")
            for ax, column in zip(axes, ("consecutive", "fixed_reference")):
                ax.set_ylabel("Pearson correlation")
                ax.set_ylim(*similarity_ylim(results[column]))
                ax.grid(True, alpha=0.3)
            axes[-1].set_xlabel("Scan / scan-pair midpoint")
            self._similarity_fig.suptitle(f"Pattern similarity: {xmin:g} to {xmax:g}")
            self._similarity_fig.tight_layout()
            self._similarity_fig.canvas.draw_idle()
            plt.show(block=False)
        except Exception as e:
            messagebox.showerror("Similarity error", f"{type(e).__name__}: {e}")

# --------------- Run -----------------
if __name__ == "__main__":
    app = XRDMapGUI()
    app.mainloop()
