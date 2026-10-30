"""Detector filter overlay controls. Rendering never invokes an estimator."""
import tkinter as tk
from tkinter import ttk
import numpy as np
from matplotlib.patches import Patch
from xrd_suite.filter_diagnostics import overlay_rgba, result_matches
from .widgets import Tooltip

FILTER_HELP = (
    'Filtering exclusions are specific to this image and integration settings. '
    'They may include genuine diffraction signal and are separate from the detector mask.\n\n'
    'Percentile filtering removes both low and high contributions; 25–75 is not merely '
    'a bright-spot rejection filter. Equal bounds use the backend single-quantile selection, '
    'which can retain very few contributions. A large exclusion overlay can be expected.\n\n'
    'Opacity is the display opacity multiplied by excluded effective normalization weight / '
    'eligible effective normalization weight at each detector pixel. Partial exclusion is '
    'fainter; purple means both lower and upper contributions are excluded. This is not a '
    'percentage of unique pixels. The current backend uses no pixel splitting.\n\n'
    'A Partial percentile overlay shows only verified, order-independent decisions. '
    'Amber marks ambiguous tied contributions (or an entire bin if weighted replay fails): '
    'these pixels are NOT classified '
    'as retained or rejected. This is incomplete diagnostic coverage, not an estimated mask.\n\n'
    'Sigma-clipping shows the actual union of iterative rejections, including pyFAI’s '
    'Chauvenet minimum threshold. It does not reconstruct a threshold from the final mean.\n\n'
    'Only the active image at Run time is prepared (primary and full filtered comparison). '
    'Changing inputs or settings disables the overlay until 1D is rerun. '
    'Diagnostics are never saved as a detector mask.'
)


class FilterOverlayMixin:
    def build_filter_controls(self, frame, controls):
        self.show_filter = tk.BooleanVar(value=False)
        self.filter_opacity = tk.StringVar(value='0.5')
        self.filter_choice = tk.StringVar(value='0')
        self.filter_notice = tk.StringVar(value='Filter overlay: run a filtered 1D result')
        self.filter_artist = self.filter_legend = None
        self.filter_check = ttk.Checkbutton(controls, text='Show filter exclusions',
            variable=self.show_filter, command=lambda:self.guard(self.draw_detector), state='disabled')
        self.filter_check.pack(side='left', padx=3)
        Tooltip(self.filter_check, FILTER_HELP)
        label = ttk.Label(frame, textvariable=self.filter_notice, style='Muted.TLabel', wraplength=420)
        label.pack(side='bottom', fill='x', before=self.det_canvas.get_tk_widget())
        frame.bind('<Configure>', lambda e:label.configure(wraplength=max(120, e.width-20)))

    def filter_candidates(self):
        return [(i, c) for i, c in enumerate(self.curves)
                if c.metadata.get('source') == str(self.active)
                and c.metadata.get('method_1d') in ('sigma_clip', 'percentile')]

    def selected_filter_curve(self):
        candidates = self.filter_candidates()
        if not candidates: return None
        try: index = int(self.filter_choice.get().split(':')[0])
        except ValueError: index = -1
        return next((curve for i, curve in candidates if i == index), candidates[0][1])

    def remove_filter_artists(self):
        for name in ('filter_artist', 'filter_legend'):
            artist = getattr(self, name, None)
            if artist is not None:
                try: artist.remove()
                except (ValueError, NotImplementedError): pass
                setattr(self, name, None)

    def refresh_filter_controls(self):
        if not hasattr(self, 'filter_check'): return None
        curve = self.selected_filter_curve()
        usable = curve is not None and result_matches(curve, self.active,
            getattr(self, 'detector_image_id', None), self.revision_1d, self.curve_revision)
        if usable:
            self.filter_check.configure(state='normal')
            selection = curve.metadata.get('selection', '')
            self.filter_notice.set(curve.diagnostic.summary + ' · ' + selection)
            return curve.diagnostic
        self.show_filter.set(False)
        self.filter_check.configure(state='disabled')
        self.remove_filter_artists()
        if self.image_data is None:
            message = 'Select a detector image'
        elif self.curves and self.curve_revision != self.revision_1d:
            message = 'Outdated result — rerun 1D to prepare this image’s overlay'
        elif curve is None:
            message = 'Average has no filter exclusions' if self.curves else 'Run a filtered 1D result'
        elif curve.diagnostic is not None:
            message = 'Image differs from the completed result — rerun 1D'
        else:
            message = curve.metadata.get('filter_diagnostic', {}).get('reason') or 'Not prepared for this image — rerun 1D'
        self.filter_notice.set('Filter overlay: ' + message)
        self.det_canvas.draw_idle()
        return None

    def filter_display_settings(self, form):
        form.field('Filter overlay opacity (0–1)', self.filter_opacity)
        candidates = self.filter_candidates()
        choices = [f'{i}: {c.metadata["method_1d"]} · {c.metadata.get("selection", "")}' for i,c in candidates]
        if choices:
            curve = self.selected_filter_curve()
            self.filter_choice.set(next(label for label, (_, c) in zip(choices, candidates) if c is curve))
            form.field('Filtered result', self.filter_choice, choices)
        form.note('Red: sigma / upper percentile. Blue: lower percentile. Purple: both.\n'
                  'Opacity follows the excluded contribution fraction; gray is the detector mask.\n'
                  'Amber: unresolved selection, NOT a filter rejection.')
        row = ttk.Frame(form); form.add(row)
        self.button(row, 'About filter exclusions', lambda:self.help_dialog('Filter exclusions', FILTER_HELP))

    def draw_filter_overlay(self, ax):
        # draw_detector clears the axes before calling this method.
        self.filter_artist = self.filter_legend = None
        diagnostic = self.refresh_filter_controls()
        if diagnostic is None or not self.show_filter.get(): return
        rgba = overlay_rgba(diagnostic, float(self.filter_opacity.get()))
        self.filter_artist = ax.imshow(rgba, origin='upper', interpolation='nearest', zorder=5)
        handles = []
        if diagnostic.method == 'sigma_clip':
            handles.append(Patch(facecolor=(1,.12,.08), label='Sigma exclusions'))
        else:
            handles += [Patch(facecolor=(.08,.3,1), label='Below lower bound'),
                        Patch(facecolor=(1,.12,.08), label='Above upper bound')]
            if np.any((diagnostic.lower_weight > 0) & (diagnostic.upper_weight > 0)):
                handles.append(Patch(facecolor=(.72,.12,.85), label='Both low and high'))
        if diagnostic.unresolved_bins:
            handles.append(Patch(facecolor=(1,.65,.05), label='Unknown (ties)'))
        if self.show_mask.get(): handles.append(Patch(facecolor='.55', label='Detector mask'))
        self.filter_legend = ax.legend(handles=handles, title='Partial diagnostics\nAmber = unknown' if diagnostic.unresolved_bins else 'Fainter = partial exclusion',
            fontsize=7, title_fontsize=7, loc='upper right', framealpha=.85)
        self.filter_legend.set_in_layout(False)
        self.filter_legend.set_zorder(30)
