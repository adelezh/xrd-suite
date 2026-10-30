"""Synthetic smooth rings/localized spots, actual pyFAI contribution diagnostics."""
from dataclasses import replace
import copy
import numpy as np
import pytest
from xrd_gui.processing import Engine, StableAzimuthalIntegrator, sector_pixels
from xrd_gui.settings import Settings
from xrd_suite.filter_diagnostics import (FilterDiagnostic, aggregate_weights, overlay_rgba,
    result_matches, image_identity, ELIGIBLE, MASKED, INVALID, OUTSIDE)
from xrd_suite.pyfai_diagnostics import percentile_decisions, UnsupportedDiagnostic


@pytest.fixture
def synthetic(tmp_path):
    # Tilted geometry and deliberately off-center beam; detector arrays are row/column.
    ai = StableAzimuthalIntegrator(dist=.1, poni1=.0028, poni2=.0049,
        pixel1=.0001, pixel2=.0001, rot1=.012, rot2=-.008, rot3=.04, wavelength=1e-10)
    path = tmp_path/'tilted.poni'; ai.save(str(path)); engine = Engine(path)
    y,x = np.indices((80,96)); radial = engine.ai.center_array(y.shape, unit='2th_deg')
    image = 20 + 90*np.exp(-((radial-1.7)/.13)**2) + np.random.default_rng(72).normal(0,.5,y.shape)
    image[20:26,62:68] += 3000
    image[49:55,8:14] += 900
    image[2,2] = np.nan; image[3,3] = np.inf
    engine.mask = np.zeros(y.shape,bool); engine.mask[6:8,:] = True
    return engine, image


@pytest.mark.parametrize('method',['sigma_clip','percentile'])
@pytest.mark.parametrize('sector',[False,True])
def test_outputs_input_mask_and_selection_unchanged(synthetic,method,sector):
    engine,image = synthetic; original = image.copy(); mask = engine.mask.copy()
    settings = Settings(method_1d=method, radial_bins=19, azimuth_bins=12,
        radial_range=(.3,3.7), sector=sector, start=150,end=-140,
        compare_average=True,compare_full=True,error_model='poisson')
    before, map_before, _ = copy.deepcopy(engine).integrate(image,settings,source='synthetic')
    after, map_after, _ = engine.integrate(image,settings,source='synthetic',diagnostics=True)
    for a,b in zip(before,after):
        np.testing.assert_array_equal(a.intensity,b.intensity)
        np.testing.assert_array_equal(a.sigma,b.sigma)
        assert a.diagnostic is None
    np.testing.assert_array_equal(map_before.intensity,map_after.intensity)
    diagnostic = after[0].diagnostic
    assert diagnostic is not None, after[0].metadata['filter_diagnostic']
    assert diagnostic.exactness == 'exact'
    assert after[1].diagnostic is None # comparison average never owns filtered diagnostics
    if sector: assert after[2].diagnostic is not None
    for opacity in [0,.2,1]:
        rgba = overlay_rgba(diagnostic,opacity)
        np.testing.assert_array_equal(rgba[diagnostic.eligible_weight == 0,3],0)
        assert np.all(rgba[engine.base_mask(image),3]==0)
        if sector:
            region = sector_pixels(engine.chi(image.shape),settings.start,settings.end)
            assert np.all(rgba[~region,3]==0)
        assert rgba.shape == (*image.shape,4)
    np.testing.assert_array_equal(image,original); np.testing.assert_array_equal(engine.mask,mask)
    np.testing.assert_array_equal(after[0].intensity,before[0].intensity)
    assert np.all(diagnostic.eligibility[mask] == MASKED)
    assert diagnostic.eligibility[2,2] == INVALID
    assert np.any(diagnostic.eligibility == OUTSIDE)
    assert np.all(diagnostic.radial_bin[diagnostic.eligible_weight == 0] == -1)


@pytest.mark.parametrize('model',['azimuthal','poisson','supplied'])
def test_sigma_exact_iterative_flags_and_weighted_reproduction(synthetic,model,tmp_path):
    engine,image = synthetic
    variance = tmp_path/'variance.npy'; np.save(variance,np.full(image.shape,4.))
    settings = Settings(method_1d='sigma_clip',radial_bins=17,sigma_threshold=3,
        sigma_iterations=7,clipping_model=model,variance=str(variance))
    curve = engine.integrate(image,settings,two=False,diagnostics=True)[0][0]
    d = curve.diagnostic; assert d is not None, curve.metadata['filter_diagnostic']
    e = next(v.engine for k,v in engine.ai.engines.items() if k.algo.lower()=='csr')
    pre = np.asarray(e.preprocessed)
    flagged = np.isnan(pre[:,3]).reshape(image.shape)
    np.testing.assert_array_equal(d.upper_weight > 0,flagged)
    assert np.any(flagged)
    assert 'iterative' in curve.metadata['filter_diagnostic']['capture']
    row = d.radial_bin.ravel(); keep = (d.retained_weight.ravel()>0) & (row>=0)
    sig = np.bincount(row[keep],weights=pre[keep,0],minlength=settings.radial_bins)
    norm = np.bincount(row[keep],weights=d.retained_weight.ravel()[keep],minlength=settings.radial_bins)
    valid = np.isfinite(curve.intensity) & (norm>0)
    np.testing.assert_allclose(sig[valid]/norm[valid],curve.intensity[valid],rtol=2e-6)
    frozen = d.upper_weight.copy()
    engine.integrate(image,replace(settings,method_1d='percentile'),two=False)
    np.testing.assert_array_equal(d.upper_weight,frozen)
    with pytest.raises(ValueError):d.upper_weight[0,0]=1
    with pytest.raises(ValueError):d.upper_weight.setflags(write=True)


@pytest.mark.parametrize('bounds',[(0,100),(25,75),(25.5,75.25),(50,50),(0,0),(100,100)])
def test_percentile_bounds_weighted_reproduction(synthetic,bounds):
    engine,image = synthetic; image = image-100 # corrected negative intensities remain eligible
    s = Settings(method_1d='percentile',radial_bins=19,percentile_low=bounds[0],percentile_high=bounds[1])
    curve = engine.integrate(image,s,two=False,diagnostics=True)[0][0]
    d = curve.diagnostic; assert d is not None, curve.metadata['filter_diagnostic']
    e = next(v.engine for k,v in engine.ai.engines.items() if k.algo.lower()=='csr')
    pre = np.asarray(e.preprocessed); row=d.radial_bin.ravel(); keep=d.retained_weight.ravel()>0
    sig=np.bincount(row[keep],weights=pre[keep,0],minlength=s.radial_bins)
    norm=np.bincount(row[keep],weights=d.retained_weight.ravel()[keep],minlength=s.radial_bins)
    good=norm>0
    np.testing.assert_allclose(sig[good]/norm[good],curve.intensity[good],rtol=3e-6,atol=1e-6)
    np.testing.assert_allclose(d.retained_weight+d.lower_weight+d.upper_weight,d.eligible_weight)
    assert np.nanmin(curve.intensity)<0
    if bounds == (0,100): assert not np.any(d.lower_weight+d.upper_weight)
    if bounds == (50,50):
        assert np.count_nonzero(keep)<=2*s.radial_bins
        assert np.count_nonzero(d.lower_weight)>100 and np.count_nonzero(d.upper_weight)>100


def test_weighted_quantiles_ties_and_single_quantile():
    f=np.float32
    # Unequal effective weights: the central contribution straddles both bounds.
    np.testing.assert_array_equal(percentile_decisions(np.array([-3,1,9],f),np.array([1,8,1],f),25,75),[1,0,2])
    # Exact equality at a cumulative boundary retains BOTH adjacent contributions.
    np.testing.assert_array_equal(percentile_decisions(np.arange(4,dtype=f),np.ones(4,f),50,50),[1,0,0,2])
    with pytest.raises(UnsupportedDiagnostic,match='Tied'):
        percentile_decisions(np.array([1,1,1,1],f),np.ones(4,f),25,75)
    np.testing.assert_array_equal(percentile_decisions(np.ones(4,f),np.ones(4,f),0,100),[0,0,0,0])
    # Safe ties wholly below, above, or inside the interval are order-invariant.
    np.testing.assert_array_equal(percentile_decisions(np.array([0,0,1,2,2,3,4,4],f),np.ones(8,f),30,70),[1,1,1,0,0,2,2,2])


def test_ambiguous_backend_ties_disable_instead_of_inventing_mask(synthetic):
    engine,image=synthetic; image=np.ones(image.shape)
    settings=Settings(method_1d='percentile',radial_bins=8,solid_angle=False,polarization=0)
    # polarization_factor=0 still angle-dependent; disable using zero-angle geometry? Instead
    # cancel the exact normalization to make all corrected keys bitwise equal.
    engine.integrate(image,settings,two=False)
    e=next(v.engine for k,v in engine.ai.engines.items() if k.algo.lower()=='csr')
    image=np.asarray(e.preprocessed)[:,2].reshape(image.shape).astype(float)
    c=engine.integrate(image,settings,two=False,diagnostics=True)[0][0]
    assert c.diagnostic is None
    assert c.metadata['filter_diagnostic']['exactness']=='unsupported'
    assert 'Tied' in c.metadata['filter_diagnostic']['reason']


def test_split_contribution_fractions_and_mixed_category():
    # Synthetic contribution table, NOT a claim that the installed no-split backend splits.
    pixels=np.array([0,0,0,1,1]);weights=np.array([1.,2.,1.,1.,3.]);decisions=np.array([0,1,2,0,2])
    arrays=aggregate_weights((1,2),pixels,weights,decisions)
    d=FilterDiagnostic('percentile','Synthetic contribution test','test','hash','settings',
        *arrays,np.full((1,2),ELIGIBLE,np.uint8),np.full((1,2),-1,np.int32))
    rgba=overlay_rgba(d,.8)
    np.testing.assert_allclose(rgba[...,3],[[.6,.6]])
    np.testing.assert_allclose(rgba[0,0,:3],[.72,.12,.85])
    np.testing.assert_allclose(rgba[0,1,:3],[1,.12,.08])
    with pytest.raises(ValueError):overlay_rgba(d,1.1)


def test_zero_spread_empty_bins_and_lifecycle(synthetic):
    engine,image=synthetic;image=np.zeros(image.shape)
    s=Settings(method_1d='sigma_clip',radial_bins=200,sector=True,start=169,end=171)
    c=engine.integrate(image,s,source='file-a',two=False,diagnostics=True)[0][0]
    d=c.diagnostic;assert d is not None,c.metadata['filter_diagnostic']
    assert not np.any(d.upper_weight) # zero dispersion does not manufacture exclusions
    assert c.metadata['invalid_bins']
    identity=image_identity(image)
    assert result_matches(c,'file-a',identity,5,5)
    assert not result_matches(c,'file-b',identity,5,5)
    assert not result_matches(c,'file-a',image_identity(image+1),5,5)
    assert not result_matches(c,'file-a',identity,6,5) # settings/calibration/async revision
    assert not result_matches(replace(c,diagnostic=None),'file-a',identity,5,5)


def test_unknown_version_and_budget_fail_closed(synthetic,monkeypatch):
    import xrd_suite.pyfai_diagnostics as adapter
    engine,image=synthetic;s=Settings(method_1d='sigma_clip',radial_bins=12)
    monkeypatch.setattr(adapter,'SUPPORTED_VERSION','uninspected')
    c=engine.integrate(image,s,two=False,diagnostics=True)[0][0]
    assert c.diagnostic is None and 'audited' in c.metadata['filter_diagnostic']['reason']
    monkeypatch.setattr(adapter,'SUPPORTED_VERSION','2026.9.0')
    monkeypatch.setattr(adapter,'MAX_DIAGNOSTIC_BYTES',1)
    c=engine.integrate(image,s,two=False,diagnostics=True)[0][0]
    assert c.diagnostic is None and 'memory' in c.metadata['filter_diagnostic']['reason']

@pytest.mark.parametrize('bounds',[(25,75),(50,50)])
@pytest.mark.parametrize('sector',[False,True])
def test_partial_percentile_ties_preserve_verified_bins(synthetic,bounds,sector):
    engine,image=synthetic;image=image.copy()
    settings=Settings(method_1d='percentile',radial_bins=19,percentile_low=bounds[0],
        percentile_high=bounds[1],sector=sector,start=150,end=-140,error_model='poisson')
    engine.integrate(image,settings,two=False)
    e=next(v.engine for k,v in engine.ai.engines.items() if k.algo.lower()=='csr')
    _,pixels,indptr=map(np.asarray,e.lut)
    tied_bin=int(np.argmax(np.diff(indptr)))
    tied_pixels=pixels[indptr[tied_bin]:indptr[tied_bin+1]]
    # Exactly equal corrected float32 sort keys in ONE radial bin; other bins
    # retain the synthetic ring/spot data. No perturbation of production inputs.
    image.ravel()[tied_pixels]=np.asarray(e.preprocessed)[tied_pixels,2]
    original=image.copy();original_mask=engine.mask.copy()
    before=engine.integrate(image,settings,source='tied synthetic',two=False)[0][0]
    c=engine.integrate(image,settings,source='tied synthetic',two=False,diagnostics=True)[0][0]
    d=c.diagnostic;assert d is not None,c.metadata['filter_diagnostic']
    assert d.exactness=='partial' and 'Partial' in d.summary
    assert tied_bin in d.unresolved_bins
    assert c.metadata['filter_diagnostic']['exactness']=='partial'
    assert c.metadata['filter_diagnostic']['validated_populated_radial_bins']>0
    unknown=d.unresolved_weight>0
    np.testing.assert_array_equal(unknown,np.isin(d.radial_bin,d.unresolved_bins))
    assert np.all(d.retained_weight[unknown]==0)
    assert np.all(d.lower_weight[unknown]==0) and np.all(d.upper_weight[unknown]==0)
    np.testing.assert_allclose(d.retained_weight+d.lower_weight+d.upper_weight+d.unresolved_weight,d.eligible_weight)
    rgba=overlay_rgba(d,.8)
    np.testing.assert_allclose(rgba[unknown,:3],np.tile([1,.65,.05],(np.count_nonzero(unknown),1)))
    np.testing.assert_allclose(rgba[unknown,3],.8*.55)
    assert np.all(rgba[engine.base_mask(image),3]==0)
    if sector:assert np.all(rgba[~sector_pixels(engine.chi(image.shape),settings.start,settings.end),3]==0)
    assert np.any(d.lower_weight>0) and np.any(d.upper_weight>0)
    row=d.radial_bin.ravel();kept=d.retained_weight.ravel()>0
    pre=np.asarray(e.preprocessed)
    sig=np.bincount(row[kept],weights=pre[kept,0],minlength=settings.radial_bins)
    norm=np.bincount(row[kept],weights=d.retained_weight.ravel()[kept],minlength=settings.radial_bins)
    valid=(norm>0)&~np.isin(np.arange(settings.radial_bins),d.unresolved_bins)
    np.testing.assert_allclose(sig[valid]/norm[valid],c.intensity[valid],rtol=3e-6,atol=1e-6)
    np.testing.assert_array_equal(c.intensity,before.intensity)
    np.testing.assert_array_equal(c.sigma,before.sigma)
    np.testing.assert_array_equal(image,original);np.testing.assert_array_equal(engine.mask,original_mask)
    assert result_matches(c,'tied synthetic',image_identity(image),4,4)
    assert not result_matches(c,'different file',image_identity(image),4,4)


def test_partial_validation_still_rejects_wrong_known_bins():
    from types import SimpleNamespace
    from xrd_suite.pyfai_diagnostics import _validate_sums
    result=SimpleNamespace(intensity=np.array([3.,999.]),sum_signal=np.array([3.,999.]),
                           sum_normalization=np.ones(2),count=np.ones(2))
    pre=np.array([[3.,1.,1.,1.],[8.,1.,1.,1.]],np.float32)
    args=(result,np.array([0,1]),np.array([0,1]),np.ones(2),pre,np.array([0,3]),'percentile')
    _validate_sums(*args,verified_bins=np.array([True,False]))
    result.sum_signal[0]=4
    with pytest.raises(UnsupportedDiagnostic,match='weighted sums'):
        _validate_sums(*args,verified_bins=np.array([True,False]))

@pytest.mark.parametrize('bins',[40,120,5000])
def test_symmetric_example_keeps_partial_percentile_overlay(tmp_path,bins):
    from xrd_suite.example import generate
    from xrd_gui.files import read_image
    folder=generate(tmp_path/'symmetric')
    engine=Engine(folder/'synthetic.poni',folder/'mask.npy')
    image=read_image(next((folder/'dark_sub').glob('*.tiff')))
    s=Settings(method_1d='percentile',radial_bins=bins)
    before=engine.integrate(image,s,two=False)[0][0]
    c=engine.integrate(image,s,two=False,diagnostics=True)[0][0]
    d=c.diagnostic;assert d is not None,c.metadata['filter_diagnostic']
    assert d.exactness=='partial'
    assert np.any(d.lower_weight>0) and np.any(d.upper_weight>0)
    assert np.any(d.unresolved_weight>0)
    assert np.any((d.unresolved_weight==0)&np.isin(d.radial_bin,d.unresolved_bins))
    assert c.metadata['filter_diagnostic']['validated_populated_radial_bins']>0
    np.testing.assert_array_equal(c.intensity,before.intensity)
    assert d.nbytes<=128*1024*1024
    with pytest.raises(ValueError):d.unresolved.setflags(write=True)


@pytest.mark.parametrize('bounds',[(25,75),(50,50),(0,60),(40,100)])
def test_resolved_tie_decisions_are_invariant_to_tie_order(bounds):
    import itertools
    keys=np.array([0,1,1,2,3,3,4,5],np.float32)
    weights=np.array([.5,.25,1,.75,.5,.25,1,.5],np.float32)
    resolved,_=percentile_decisions(keys,weights,*bounds,allow_unresolved=True)
    known=resolved!=3
    for first in itertools.permutations([1,2]):
        for second in itertools.permutations([4,5]):
            order=np.array([0,*first,3,*second,6,7])
            _,candidate=percentile_decisions(keys[order],weights[order],*bounds,allow_unresolved=True)
            original=np.empty(len(keys),np.uint8);original[order]=candidate
            np.testing.assert_array_equal(original[known],resolved[known])


def test_extreme_weight_range_withholds_bin_instead_of_assuming_tie_sum_invariance():
    keys=np.array([0,1,1,2],np.float32)
    weights=np.array([1e-20,1,1,1e-20],np.float32)
    resolved,_=percentile_decisions(keys,weights,25,75,allow_unresolved=True)
    assert np.all(resolved==3)
