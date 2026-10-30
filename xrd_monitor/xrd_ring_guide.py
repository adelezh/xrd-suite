"""Optional calibrated guide; interaction only changes inspector artists."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import numpy as np
from . import xrd_calibration as calibration


class RingGuideMixin:
    def _init_ring_guide(self):
        self._calibration = None
        self._calibration_folder = None
        self._geometry_cache = calibration.GeometryCache()
        self._ring_angle = None
        self._ring_marker = self._ring_contour = None
        self._ring_line_ax = self._ring_image_ax = None
        self._ring_display_pair = None
        self._ring_click_cid = None
        self._ring_backend_ready = False
        self._calibration_message = 'Calibration unavailable: select an integration folder'
        self.calibration_status_var = tk.StringVar(value=self._calibration_message)
        self.ring_readout_var = tk.StringVar(value='')
        self.watch_folder_var.trace_add('write', self._ring_folder_changed)
        self.calc_wavelength_var.trace_add('write', self._ring_wavelength_changed)

    def _build_calibration_controls(self, parent):
        panel = ttk.LabelFrame(parent, text='Calibration source', padding=8)
        panel.pack(fill='x', pady=6)
        ttk.Button(panel, text='Load calibration', command=self._load_ring_calibration).pack(anchor='w')
        ttk.Label(panel, textvariable=self.calibration_status_var, wraplength=450).pack(fill='x')
        self._ring_update_controls()

    def _build_inspector_controls(self, fig):
        window = fig.canvas.manager.window
        controls = ttk.Frame(window, padding=4)
        controls.pack(side='bottom', fill='x', before=fig.canvas.get_tk_widget())
        ttk.Button(controls, text='Clear guide', command=self.clear_ring_guide).pack(side='left', padx=4)
        self._inspector_ring_status_var = tk.StringVar(value='')
        ttk.Label(controls, textvariable=self._inspector_ring_status_var, wraplength=600).pack(anchor='w')
        ttk.Label(controls, textvariable=self.ring_readout_var, wraplength=800).pack(anchor='w')
        self._ring_update_controls()

    def _ring_folder_changed(self, *_):
        try:
            value = self.watch_folder_var.get().strip()
            folder = str(Path(value).expanduser().resolve()) if value else ''
        except (OSError, ValueError):
            folder = self.watch_folder_var.get()
        if folder != self._calibration_folder:
            self._calibration_folder = folder
            self._load_ring_calibration()

    def _autoload_calibration_for_files(self, files):
        """Load calibration for a manually selected, single integration folder.

        Adding files is deliberately independent of watching a folder, but the
        inspector still needs the matching metadata and wavelength.  Restrict
        this to one recognized integration directory so mixed/manual file
        selections cannot silently replace the active calibration.
        """
        try:
            folders = {Path(filename).expanduser().resolve().parent for filename in files}
        except (OSError, ValueError, TypeError):
            return
        if len(folders) != 1:
            return
        folder = folders.pop()
        if folder.name.lower() != 'integration':
            return
        resolved = str(folder)
        if resolved == self._calibration_folder:
            return
        self._calibration_folder = resolved
        self._load_ring_calibration(folder)

    def _load_ring_calibration(self, folder=None):
        self.clear_ring_guide()
        self._calibration = None
        self._ring_backend_ready = False
        self._geometry_cache.clear()
        try:
            source = folder if folder is not None else self.watch_folder_var.get().strip()
            result = calibration.load_folder_calibration(source)
            self._calibration = result
            self._calibration_message = 'Calibration: ' + ', '.join(Path(p).name for p in result.sources)
            self.calc_wavelength_var.set(f'{result.wavelength_angstrom:.12g}')
            try:
                calibration.make_geometry(result)
                self._ring_backend_ready = True
            except Exception as exc:
                self._calibration_message += f'; guide unavailable: {exc}'
        except Exception as exc:
            self._calibration_message = str(exc)
        self._ring_update_controls()

    def _ring_wavelength_changed(self, *_):
        # Existing CIF cache keys include wavelength; the next explicit Inspect
        # uses the edited value without replacing the current measured display.
        self._ring_update_controls()

    def _ring_pair_matches(self):
        pair = self._ring_display_pair
        return bool(self._calibration and (pair is None or
            str(Path(pair['file']).resolve().parent) == self._calibration.folder))

    def _ring_update_controls(self):
        available = self._calibration is not None and self._ring_backend_ready and self._ring_pair_matches()
        if hasattr(self, 'calibration_compact_var'):
            self.calibration_compact_var.set('Calibration ready' if self._calibration else 'Calibration unavailable')
        if hasattr(self, '_inspector_ring_status_var'):
            reason = ('different sample folder' if self._calibration and not self._ring_pair_matches() else
                      'geometry dependency/configuration unavailable' if self._calibration else 'calibration unavailable')
            self._inspector_ring_status_var.set('Ring guide ready: click the 1D pattern' if available else f'Ring guide unavailable: {reason}')
        message = self._calibration_message
        if self._calibration:
            wave = self._calibration.wavelength_angstrom
            message += f'; calibration wavelength {wave:.8g} Å'
            try:
                different = not np.isclose(float(self.calc_wavelength_var.get()), wave, rtol=1e-10, atol=0)
            except ValueError:
                different = True
            if different:
                message += '; CIF wavelength differs; ring still uses calibration wavelength'
            if not self._ring_pair_matches():
                message += '; guide disabled: displayed file belongs to a different folder'
        self.calibration_status_var.set(message)
        return available

    def _remove_ring_artists(self):
        for artist in (self._ring_marker, self._ring_contour):
            if artist is not None:
                if hasattr(artist, 'remove'):
                    artist.remove()
                else:  # older Matplotlib ContourSet
                    for collection in artist.collections:
                        collection.remove()
        self._ring_marker = self._ring_contour = None

    def clear_ring_guide(self, redraw=True):
        self._remove_ring_artists()
        self._ring_angle = None
        self.ring_readout_var.set('')
        if redraw and self._detector_fig is not None:
            self._detector_fig.canvas.draw_idle()

    def _ring_connect(self, fig):
        self._ring_click_cid = fig.canvas.mpl_connect('button_press_event', self._ring_clicked)

    def _ring_disconnect(self):
        if self._detector_fig is not None and self._ring_click_cid is not None:
            self._detector_fig.canvas.mpl_disconnect(self._ring_click_cid)
        self._ring_click_cid = None
        self.clear_ring_guide(redraw=False)
        self._ring_display_pair = self._ring_line_ax = self._ring_image_ax = None

    def _ring_new_frame(self, pair, image_ax, line_ax):
        self._ring_display_pair = pair
        self.ring_readout_var.set('')
        self._ring_image_ax, self._ring_line_ax = image_ax, line_ax
        self._ring_update_controls()
        self._render_ring()

    def _ring_clicked(self, event):
        if (not self._ring_update_controls()
                or self._ring_display_pair is None or event.inaxes is not self._ring_line_ax
                or event.button != 1 or event.xdata is None):
            return
        toolbar = getattr(event.canvas, 'toolbar', None)
        if toolbar is not None and toolbar.mode:
            return
        try:
            angle = calibration.click_to_angle(float(event.xdata), self._ring_display_pair['kind'],
                                              self._calibration.wavelength_angstrom)
            self._geometry_cache.angles(self._calibration, self._ring_display_pair['image'].shape)
        except Exception as exc:
            self.ring_readout_var.set(str(exc))
            return
        self._ring_angle = angle
        self._render_ring()

    def _render_ring(self):
        self._remove_ring_artists()
        if (self._ring_angle is None
                or not self._ring_update_controls() or self._ring_display_pair is None):
            return
        try:
            pair = self._ring_display_pair
            angles = self._geometry_cache.angles(self._calibration, pair['image'].shape)
            x = calibration.angle_to_x(self._ring_angle, pair['kind'], self._calibration.wavelength_angstrom)
            # axvline must not expand the measured pattern's visible x limits.
            limits = self._ring_line_ax.get_xlim()
            self._ring_marker = self._ring_line_ax.axvline(x, color='crimson', linestyle='--', lw=1)
            self._ring_line_ax.set_xlim(limits)
            units = 'deg 2θ' if pair['kind'] == 'tth' else 'Å⁻¹ q'
            message = f'{x:.7g} {units} (2θ = {np.degrees(self._ring_angle):.7g} deg)'
            if angles.min() < self._ring_angle < angles.max():
                rows, columns = angles.shape
                self._ring_contour = self._ring_image_ax.contour(
                    np.arange(columns), np.arange(rows), angles, levels=[self._ring_angle],
                    colors=['crimson'], linestyles='--', linewidths=1)
            else:
                message += '; ring lies outside the detector'
            self.ring_readout_var.set(message)
        except Exception as exc:
            self.ring_readout_var.set(f'Guide unavailable: {exc}')
        if self._detector_fig is not None:
            self._detector_fig.canvas.draw_idle()
