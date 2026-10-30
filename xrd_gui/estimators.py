"""Robust 1D estimators using the installed direct pyFAI APIs."""
import numpy as np

ROBUST_BACKEND = ('no','csr','cython')

def uncertainty_description(method, model, quantile=False):
    if method == 'percentile' and quantile:
        return 'XYE unavailable: returned selected-pixel propagation is not a characterized uncertainty of a quantile estimator.'
    if model == 'none': return 'none; XY/CHI only'
    if model == 'azimuthal':
        return 'pyFAI post-clipping empirical standard error from azimuthal dispersion of retained pixels; not original counting uncertainty or uncertainty from selection.'
    prefix='propagated supplied variance' if model=='supplied' else 'Poisson model estimate (corrected intensity does not recover original counting variance)'
    if method != 'average':prefix+='; conditional SEM of the retained weighted mean; selection uncertainty and filtering bias are not included'
    return prefix

def robust_curve(ai,image,settings,mask,variance,radial_range,metadata,selection,method=None,reference=False,diagnostic_mask=None):
    from .files import Curve
    s=settings;method=method or s.method_1d
    model=s.clipping_model if method=='sigma_clip' else s.error_model
    kw=dict(unit=s.unit,radial_range=radial_range,correctSolidAngle=s.solid_angle,
            polarization_factor=s.polarization,method=ROBUST_BACKEND,mask=mask,
            variance=variance if model=='supplied' else None,
            error_model=model if model in ('azimuthal','poisson') else None)
    if method=='sigma_clip':
        r=ai.sigma_clip_ng(image,s.radial_bins,thres=s.sigma_threshold,max_iter=s.sigma_iterations,**kw)
        api='sigma_clip_ng'
    elif method=='percentile':
        r=ai.medfilt1d_ng(image,s.radial_bins,percentile=s.percentile_argument,**kw)
        api='medfilt1d_ng'
    else:
        r=ai.integrate1d_ng(image,s.radial_bins,**kw);api='integrate1d_ng'
    count=np.asarray(r.count)
    valid=np.isfinite(r.intensity) & np.isfinite(r.sum_normalization) & (r.sum_normalization>0) & (count>0)
    # A single retained pixel cannot characterize dispersion for sigma-clipping.
    if method=='sigma_clip':valid &= count>=2
    y=np.asarray(r.intensity,dtype=float).copy();y[~valid]=np.nan
    quantile=method=='percentile' and s.percentile_low==s.percentile_high
    sigma=None if quantile or r.sigma is None else np.asarray(r.sigma,dtype=float).copy()
    if sigma is not None:sigma[~valid]=np.nan
    uncertainty=uncertainty_description(method,model,quantile)
    meta=dict(metadata,method_1d=method,method=list(ROBUST_BACKEND),api=api,selection=selection,
              comparison=reference,uncertainty_model=model,uncertainty=uncertainty,
              effective_radial_range=list(radial_range),invalid_bins=np.flatnonzero(~valid).tolist(),
              sparse_bins=int(np.count_nonzero(count<2)),retained_count=count.tolist(),
              xye_supported=not quantile and sigma is not None)
    if quantile:meta['xye_reason']=uncertainty
    meta['settings']=dict(metadata['settings'],method_1d=method)
    diagnostic = None
    if diagnostic_mask is not None and method != 'average':
        from xrd_suite.pyfai_diagnostics import capture
        diagnostic, meta['filter_diagnostic'] = capture(ai,r,image,s,mask,diagnostic_mask,meta)
    return Curve(r.radial,y,sigma,meta,diagnostic)
