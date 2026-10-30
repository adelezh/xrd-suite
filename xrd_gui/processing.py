from dataclasses import asdict, replace
from pathlib import Path
import hashlib
import copy
from pyFAI.integrator.azimuthal import AzimuthalIntegrator
from pyFAI import units


class StableAzimuthalIntegrator(AzimuthalIntegrator):
    """Use NumPy unit equations on strided detector-coordinate arrays.

    Some Windows numexpr builds mis-evaluate pyFAI unit equations on the
    interleaved x/y/z views returned by position_array. Keep this workaround
    local to this integrator; do not mutate global pyFAI unit definitions.
    """
    def center_array(self, shape=None, unit="2th_deg", scale=True):
        safe_unit = copy.copy(units.to_unit(unit))
        if safe_unit._equation_np is None:
            raise ValueError(f"No NumPy coordinate equation for {safe_unit.name}")
        safe_unit.equation = safe_unit._equation_np
        return super().center_array(shape, unit=safe_unit, scale=scale)

import numpy as np
from .files import Curve, read_image

def sector_pixels(chi_degrees, start, end):
    width = (end-start) % 360
    if abs(end-start) == 360: return np.ones(np.shape(chi_degrees),dtype=bool)
    return ((chi_degrees-start) % 360) < width

class Engine:
    def __init__(self, poni, mask=''):
        import pyFAI
        self.ai = StableAzimuthalIntegrator()
        self.ai.load(str(poni)); self.ai.setChiDiscAtPi()
        self.mask = read_image(mask) != 0 if mask else None
        self.variance_cache = {}
        self.metadata = {'calibration':str(poni),'calibration_sha256':hashlib.sha256(Path(poni).read_bytes()).hexdigest(), 'mask':str(mask),'mask_sha256':hashlib.sha256(Path(mask).read_bytes()).hexdigest() if mask else None,'pyFAI_version':pyFAI.version,'mask_convention':'nonzero = excluded','azimuth_convention':'pyFAI chi, [-180,180), pixel centers, start inclusive/end exclusive','method':['no','histogram','cython'],'coordinate_backend':'NumPy unit equations (strided-coordinate safety)'}
    def base_mask(self, image):
        mask = ~np.isfinite(image)
        for source in (self.mask, self.ai.detector.mask):
            if source is not None:
                if source.shape != image.shape: raise ValueError(f'Mask shape {source.shape} does not match image {image.shape}.')
                mask |= source != 0
        return mask
    def freeze_variance(self, settings):
        if settings.error_model == 'supplied' or (settings.method_1d == 'sigma_clip' and settings.clipping_model == 'supplied'):
            self.variance_cache[settings.variance] = read_image(settings.variance).copy()
            self.metadata['variance_sha256'] = hashlib.sha256(Path(settings.variance).read_bytes()).hexdigest()

    def chi(self, shape): return np.degrees(self.ai.center_array(shape, unit='chi_rad'))
    def integrate(self, image, settings, source='', one=True, two=True, diagnostics=False):
        s = (settings if one else replace(settings,method_1d='average',compare_average=False)).validate()
        if s.unit == 'q_A^-1' and not self.ai.wavelength: raise ValueError('q integration needs a wavelength in the calibration.')
        base = self.base_mask(image); mask = base.copy()
        if s.sector: mask |= ~sector_pixels(self.chi(image.shape),s.start,s.end)
        variance = None
        if s.error_model == 'supplied' or (one and s.method_1d == 'sigma_clip' and s.clipping_model == 'supplied'):
            variance = self.variance_cache.get(s.variance)
            if variance is None: variance = read_image(s.variance)
            if variance.shape != image.shape or not np.isfinite(variance).all() or (variance < 0).any(): raise ValueError('Variance must match the image and contain finite nonnegative variances.')
        kw = dict(unit=s.unit,radial_range=s.radial_range,correctSolidAngle=s.solid_angle,polarization_factor=s.polarization,method=('no','histogram','cython'),variance=variance if s.error_model=='supplied' else None,error_model='poisson' if s.error_model=='poisson' else None)
        meta = dict(self.metadata,method_1d='average',api='integrate1d_ng',source=str(source),settings=asdict(s),unit=s.unit,wavelength_m=self.ai.wavelength,uncertainty='propagated supplied variance' if s.error_model=='supplied' else ('pyFAI Poisson model estimate; corrected intensity cannot recover true counting variance' if s.error_model=='poisson' else 'none'),dark_subtraction='none')
        curves = []
        if one and s.method_1d == 'average':
            r = self.ai.integrate1d_ng(image,s.radial_bins,mask=mask,**kw)
            curves.append(Curve(r.radial,r.intensity,r.sigma,dict(meta,selection='sector' if s.sector else 'full',comparison=False,invalid_bins=np.flatnonzero(np.asarray(r.count)<=0).tolist())))
            if s.sector and s.compare_full:
                r = self.ai.integrate1d_ng(image,s.radial_bins,mask=base,**kw)
                curves.append(Curve(r.radial,r.intensity,r.sigma,dict(meta,selection='full comparison',comparison=True,invalid_bins=np.flatnonzero(np.asarray(r.count)<=0).tolist())))
        elif one:
            from .estimators import robust_curve
            if np.all(mask):raise ValueError('No valid pixels in the selected sector after masking.')
            radial_range=s.radial_range
            if radial_range is None:
                coordinates=self.ai.center_array(image.shape,unit=s.unit)
                available=coordinates[(~base) & np.isfinite(coordinates)]
                radial_range=(float(available.min()),float(available.max()))
            if radial_range[0]>=radial_range[1]:raise ValueError('Insufficient radial extent for integration.')
            diagnostic_mask = None
            if diagnostics:
                diagnostic_mask = np.zeros(image.shape, bool)
                for original in (self.mask, self.ai.detector.mask):
                    if original is not None: diagnostic_mask |= original != 0
            selection='sector' if s.sector else 'full' 
            curves.append(robust_curve(self.ai,image,s,mask,variance,radial_range,meta,selection,diagnostic_mask=diagnostic_mask))
            if s.compare_average:
                curves.append(robust_curve(self.ai,image,s,mask,variance,radial_range,meta,selection,method='average',reference=True))
            if s.sector and s.compare_full:
                curves.append(robust_curve(self.ai,image,s,base,variance,radial_range,meta,'full comparison',reference=True,diagnostic_mask=diagnostic_mask))
        # Map metadata records its actual ordinary estimator, not the selected 1D estimator.
        meta=dict(meta,method_1d='average',api='integrate2d_ng',settings=dict(meta['settings'],method_1d='average'))
        # 2D retains the full azimuth axis; excluded sector pixels remain empty.
        map_result = self.ai.integrate2d_ng(image,s.radial_bins,s.azimuth_bins,mask=mask,azimuth_range=(-180,180),**kw) if two else None
        return curves,map_result,meta
