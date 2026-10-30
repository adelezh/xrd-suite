"""Explicitly selected detector inspector; no changes to analysis or watcher state."""
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk

import numpy as np
from matplotlib.colors import LogNorm, Normalize
import matplotlib.pyplot as plt

from . import xrd_peak_workflow as workflow
from .xrd_ring_guide import RingGuideMixin

_INTEGRATION = re.compile(r"^(?P<prefix>.+)_primary-(?P<scan>[1-9]\d*)_mean_(?P<kind>tth|q)\.chi$", re.I)
SELECTION_MESSAGE = "Select exactly one integration file to inspect its 2D/1D pattern."


def integration_metadata(filename):
    path = Path(filename).resolve()
    match = _INTEGRATION.fullmatch(path.name)
    if match is None:
        raise ValueError(f"Unrecognized integration filename: {path.name}; expected PREFIX_primary-N_mean_tth.chi or PREFIX_primary-N_mean_q.chi (N >= 1).")
    return path, match['prefix'], int(match['scan']), match['kind'].lower()


def matching_tiff(filename):
    path, prefix, scan, _ = integration_metadata(filename)
    return path.parent.parent / 'dark_sub' / f'{prefix}_primary-dk_sub_image-{scan-1:05d}.tiff'


def signature(path):
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns


class PairUnavailable(Exception):
    """A pair is not ready; the displayed pair must remain untouched."""


def read_pair(filename, *, xmin=None, xmax=None, skiprows=0):
    """Read and validate both files before committing either to the display."""
    path, _, scan, kind = integration_metadata(filename)
    tiff = matching_tiff(path)
    try:
        import tifffile
    except ImportError as exc:
        raise ImportError('2D viewer requires tifffile in the active Python environment (python -m pip install tifffile).') from exc
    try:
        before = signature(tiff)
        image = np.array(tifffile.imread(tiff), copy=True)
        if signature(tiff) != before:
            raise ValueError('TIFF changed while being read')
        if image.ndim != 2 or min(image.shape) < 1 or image.dtype.kind not in 'biuf':
            raise ValueError('Expected a single two-dimensional numeric detector image')
        if not np.isfinite(image).any():
            raise ValueError('No finite detector pixels')
    except Exception as exc:
        raise PairUnavailable(f'Cannot read matching TIFF: {tiff.name}') from exc
    try:
        chi_before = signature(path)
        x, y = workflow.loadxy(path, xmin=xmin, xmax=xmax, skiprows=skiprows)
        if len(x) < 2 or signature(path) != chi_before or signature(tiff) != before:
            raise ValueError('Pair is incomplete or changed while being read')
    except Exception as exc:
        raise PairUnavailable(f'Cannot read integration pattern: {path.name} ({exc})') from exc
    return dict(file=str(path), tiff=str(tiff), scan=scan, kind=kind,
                image=image, x=x, y=y, signatures=(chi_before, before))


def detector_display(image):
    finite = np.asarray(image)[np.isfinite(image)]
    positive = finite[finite > 0]
    if positive.size:
        low, high = np.percentile(positive, [1, 99.5])
        if 0 < low < high:
            return np.ma.masked_where(~np.isfinite(image) | (image <= 0), image), LogNorm(low, high)
    low, high = np.percentile(finite, [1, 99.5])
    if low == high:
        pad = max(abs(float(low)) * .01, .5)
        low, high = low-pad, high+pad
    return np.ma.masked_invalid(image), Normalize(low, high)


class DetectorInspectorMixin(RingGuideMixin):
    def _init_detector_inspector(self):
        self._detector_fig = None
        self._detector_pair = None
        self.detector_status_var = tk.StringVar(value='Viewer closed')
        self._init_ring_guide()
        self.bind('<Destroy>', self._detector_destroyed, add='+')

    def show_detector_inspector(self):
        """Only this explicit action reads/replaces the measured pair."""
        selected = self._selected_file_paths()
        if len(selected) != 1:
            self.detector_status_var.set(SELECTION_MESSAGE)
            return
        filename = selected[0]
        try:
            xmin = self._safe_float(self.xmin_var, 'xmin', allow_empty=True)
            xmax = self._safe_float(self.xmax_var, 'xmax', allow_empty=True)
            if xmin is not None and xmax is not None and xmax <= xmin:
                raise ValueError('xmax must be greater than xmin')
            pair = read_pair(filename, xmin=xmin, xmax=xmax,
                             skiprows=int(self.skiprows_var.get() or 0))
        except Exception as exc:
            previous = self._detector_pair
            retained = (f" Still displaying scan {previous['scan']}: {Path(previous['file']).name}."
                        if previous is not None else ' No scan displayed.')
            self.detector_status_var.set(f'Could not inspect {Path(filename).name}: {exc}.{retained} Click Inspect again to retry.')
            return
        self._draw_detector_pair(pair)
        self._detector_pair = pair
        self.detector_status_var.set(f"Displaying scan {pair['scan']}: {Path(pair['file']).name} | {Path(pair['tiff']).name}")
        self._detector_fig.show()

    def _ensure_detector_figure(self):
        """Create one inspector window, reused for subsequent explicit inspections."""
        if self._detector_fig is not None and plt.fignum_exists(self._detector_fig.number):
            return self._detector_fig
        fig = self._detector_fig = plt.figure(figsize=(11, 9))
        self._detector_close_cid = fig.canvas.mpl_connect('close_event', self._detector_closed)
        self._ring_connect(fig)
        self._build_inspector_controls(fig)
        axis = fig.add_subplot(111)
        axis.set_axis_off()
        axis.text(.5, .5, 'Inspect a selected 2D / 1D pair', ha='center', va='center',
                  transform=axis.transAxes)
        fig.suptitle('2D / 1D Inspector')
        fig.canvas.draw_idle()
        # Explicitly ask the figure manager to show the window; ``plt.show``
        # alone can leave a nonblocking figure hidden behind the Tk main window.
        fig.show()
        plt.show(block=False)
        return fig

    def _detector_closed(self, event=None):
        self._ring_disconnect()
        self._detector_fig = None
        self._detector_pair = None
        self.detector_status_var.set('Viewer closed')

    def _detector_destroyed(self, event):
        if event.widget is self:
            if self._detector_fig is not None:
                # Close while the Tk controls still exist is handled by normal close;
                # on app destruction avoid callbacks accessing destroyed controls.
                self._ring_disconnect()
                self._detector_fig.canvas.mpl_disconnect(self._detector_close_cid)
                plt.close(self._detector_fig)
                self._detector_fig = None

    def _draw_detector_pair(self, pair):
        pixels, norm = detector_display(pair['image'])
        fig = self._ensure_detector_figure()
        self._remove_ring_artists()
        fig.clear()
        grid = fig.add_gridspec(2, 2, height_ratios=[3, 2], width_ratios=[30, 1])
        image_ax = fig.add_subplot(grid[0, 0])
        color_ax = fig.add_subplot(grid[0, 1])
        line_ax = fig.add_subplot(grid[1, :])
        artist = image_ax.imshow(pixels, norm=norm, cmap='viridis', origin='lower', aspect='equal', interpolation='nearest')
        fig.colorbar(artist, cax=color_ax, label='Intensity (log)' if isinstance(norm, LogNorm) else 'Intensity')
        image_ax.set(xlabel='Detector x pixel', ylabel='Detector y pixel', title=Path(pair['tiff']).name)
        line_ax.plot(pair['x'], pair['y'], lw=1)
        if hasattr(self, '_draw_calculated_references'):
            self._draw_calculated_references(line_ax, pair['kind'], float(np.min(pair['x'])),
                                              float(np.max(pair['x'])), overlay=True)
        line_ax.set(xlabel='2Theta (deg)' if pair['kind'] == 'tth' else 'q', ylabel='Intensity', title=Path(pair['file']).name)
        line_ax.grid(True, alpha=.25)
        fig.suptitle(f"2D / 1D Inspector — scan {pair['scan']}")
        self._ring_new_frame(pair, image_ax, line_ax)
        fig.tight_layout()
        fig.canvas.draw_idle()
        plt.show(block=False)
