"""Synthetic smooth rings with localized spots; direct installed-API checks."""
from dataclasses import replace, FrozenInstanceError
import threading
import numpy as np
import pytest
from xrd_gui.processing import Engine, StableAzimuthalIntegrator, sector_pixels
from xrd_gui.settings import Settings,restore_method_preferences
from xrd_gui.naming import add_method_tag
from xrd_gui.files import write_curve,read_curve
from xrd_gui.jobs import batch_plan,run_batch

@pytest.fixture
def data(tmp_path):
    ai=StableAzimuthalIntegrator(dist=.1,poni1=.0064,poni2=.0064,pixel1=.0001,pixel2=.0001,wavelength=1e-10)
    path=tmp_path/'synthetic.poni';ai.save(str(path));engine=Engine(path)
    y,x=np.indices((128,128));r=np.hypot(x-63.5,y-63.5)
    clean=30+80*np.exp(-((r-38)/3)**2)+4*np.sin(r/8)
    image=clean.copy();image[60:65,22:27]+=4000;image[65:70,101:106]+=5000
    engine.mask=np.zeros_like(image,bool);engine.mask[5:8,:]=True
    return engine,image,clean

@pytest.mark.parametrize('method',['sigma_clip','percentile'])
@pytest.mark.parametrize('sector',[False,True])
def test_direct_and_comparisons(data,method,sector):
    engine,image,clean=data
    s=Settings(method_1d=method,radial_bins=24,azimuth_bins=16,sector=sector,start=160,end=-160,compare_full=True,compare_average=True,error_model='poisson')
    curves,m,meta=engine.integrate(image,s)
    c=curves[0];mask=engine.base_mask(image)
    if sector:mask|=~sector_pixels(engine.chi(image.shape),s.start,s.end)
    kw=dict(mask=mask,unit=s.unit,radial_range=c.metadata['effective_radial_range'],correctSolidAngle=s.solid_angle,polarization_factor=s.polarization,method=('no','csr','cython'))
    if method=='sigma_clip':r=engine.ai.sigma_clip_ng(image,24,thres=5,max_iter=5,error_model='azimuthal',**kw)
    else:r=engine.ai.medfilt1d_ng(image,24,percentile=(25,75),error_model='poisson',**kw)
    valid=np.isfinite(c.intensity)
    np.testing.assert_allclose(c.intensity[valid],r.intensity[valid]);np.testing.assert_allclose(c.sigma[valid],r.sigma[valid])
    ref=engine.ai.integrate1d_ng(image,24,error_model='poisson',**kw)
    np.testing.assert_array_equal(c.x,curves[1].x)
    np.testing.assert_allclose(curves[1].intensity[np.isfinite(curves[1].intensity)],ref.intensity[np.isfinite(curves[1].intensity)])
    assert len(curves)==(3 if sector else 2)
    assert c.metadata['method']==['no','csr','cython']
    ordinary,oldmap,_=engine.integrate(image,replace(s,method_1d='average'))
    np.testing.assert_array_equal(m.intensity,oldmap.intensity)
    assert meta['method_1d']=='average'
    if not sector:assert np.nanmax(curves[1].intensity-c.intensity)>20

@pytest.mark.parametrize('bounds',[(0,100),(25.5,75.25),(50,50),(0,0),(100,100)])
def test_percentile_bounds(data,bounds,tmp_path):
    engine,image,_=data;s=Settings(method_1d='percentile',radial_bins=20,percentile_low=bounds[0],percentile_high=bounds[1],error_model='poisson')
    c=engine.integrate(image,s,two=False)[0][0]
    arg=bounds[0] if bounds[0]==bounds[1] else bounds
    assert s.percentile_argument==arg
    r=engine.ai.medfilt1d_ng(image,20,percentile=arg,method=('no','csr','cython'),unit=s.unit,radial_range=c.metadata['effective_radial_range'],mask=engine.base_mask(image),correctSolidAngle=True,polarization_factor=.99,error_model='poisson')
    np.testing.assert_allclose(c.intensity,r.intensity)
    if bounds[0]==bounds[1]:
        assert c.sigma is None
        with pytest.raises(ValueError,match='quantile'):write_curve(tmp_path/'bad.xye',c)
    else:
        np.testing.assert_allclose(c.sigma,np.sqrt(r.sum_variance)/r.sum_normalization,rtol=1e-6)
        write_curve(tmp_path/'interval.xye',c)

@pytest.mark.parametrize('bounds',[(-1,75),(0,101),(80,20),(float('nan'),50)])
def test_invalid_bounds(bounds):
    with pytest.raises(ValueError,match='Percentiles'):Settings(method_1d='percentile',percentile_low=bounds[0],percentile_high=bounds[1]).validate()

def test_sparse_negative_and_empty(data,tmp_path):
    engine,image,_=data
    s=Settings(method_1d='percentile',radial_bins=200,sector=True,start=0,end=.1)
    with pytest.raises(ValueError,match='No valid pixels'):engine.integrate(image,s,two=False)
    s=replace(s,end=3)
    c=engine.integrate(image-200,s,two=False)[0][0]
    assert c.metadata['invalid_bins'] and np.isnan(c.intensity).any() and np.nanmin(c.intensity)<0
    count=write_curve(tmp_path/'empty.xy',c)
    saved=read_curve(tmp_path/'empty.xy')
    assert count==len(c.metadata['invalid_bins'])
    np.testing.assert_allclose(saved.intensity,c.intensity[np.isfinite(c.intensity)])
    assert saved.metadata['export_original_bin_count']==200
    assert np.isnan(c.intensity).any()
    engine.mask[:]=True
    with pytest.raises(ValueError,match='No valid pixels'):engine.integrate(image,s,two=False)

def test_models_preferences_and_snapshot(data,tmp_path):
    engine,image,_=data;path=tmp_path/'variance.npy';np.save(path,np.full_like(image,9))
    s=Settings(method_1d='sigma_clip',radial_bins=20,error_model='supplied',variance=str(path))
    c=engine.integrate(image,s,two=False)[0][0]
    d=engine.integrate(image,replace(s,error_model='none'),two=False)[0][0]
    np.testing.assert_array_equal(c.intensity,d.intensity);np.testing.assert_array_equal(c.sigma,d.sigma)
    assert c.metadata['uncertainty_model']=='azimuthal'
    assert restore_method_preferences({})['method_1d']=='average'
    assert restore_method_preferences({'integration_methods':{'percentile_low':'bad'}})['percentile_low']==25
    Settings(sigma_threshold=-1,percentile_low=900).validate() # inactive
    with pytest.raises(FrozenInstanceError):s.sigma_threshold=3
    for threshold in (0,float('nan')):
        with pytest.raises(ValueError):replace(s,sigma_threshold=threshold).validate()
    with pytest.raises(ValueError):replace(s,sigma_iterations=1.5).validate()
    with pytest.raises(ValueError):Settings(method_1d='percentile').validate_xye()

def test_batch_names_metadata(data,tmp_path):
    engine,image,_=data;src=tmp_path/'synthetic.npy';np.save(src,image)
    s=Settings(method_1d='percentile',radial_bins=20,percentile_low=25.5,percentile_high=75.25,compare_full=True,compare_average=True)
    plan=batch_plan([src],tmp_path/'out',['2th_deg'],True,False,'.xy','Keep original',s)
    assert plan[0][3].name=='synthetic_pct25p5-75p25_tth.xy'
    counts=run_batch(engine,s,plan,'Skip',threading.Event(),lambda *args:None)
    assert counts['saved']==1
    c=read_curve(plan[0][3]);assert c.metadata['settings']['percentile_low']==25.5
    assert not c.metadata['comparison'] and not c.metadata['settings']['compare_average']
    assert add_method_tag('sample_q.xy',Settings())=='sample_q.xy'
    assert add_method_tag('sample_q.xy',replace(s,method_1d='sigma_clip')).endswith('_sigclip_s5_i5_azimuthal_q.xy')

@pytest.mark.parametrize('extension',['xy','chi','xye'])
def test_export_omits_only_undefined_bins(tmp_path,extension):
    from xrd_gui.files import Curve
    c=Curve(np.arange(5.),np.array([0.,-2.,np.nan,0.,8.]),np.array([0.,2.,np.nan,1.,3.]),{'unit':'2th_deg','invalid_bins':[0]})
    path=tmp_path/('gapped.'+extension)
    assert write_curve(path,c)==2
    result=read_curve(path)
    np.testing.assert_array_equal(result.x,[1,3,4])
    np.testing.assert_array_equal(result.intensity,[-2,0,8])
    assert result.metadata['export_omitted_bins']==[0,2]
    assert result.metadata['invalid_bins']==[]
    assert write_curve(tmp_path/('again.'+extension),result)==0
    assert c.metadata['invalid_bins']==[0]
    if extension=='xye':np.testing.assert_array_equal(result.sigma,[2,1,3])

def test_export_does_not_hide_bad_uncertainty(tmp_path):
    from xrd_gui.files import Curve
    with pytest.raises(ValueError,match='invalid/empty'):
        write_curve(tmp_path/'bad.xye',Curve(np.arange(2.),np.ones(2),np.array([0.,1.])))
    with pytest.raises(ValueError,match='No finite populated'):
        write_curve(tmp_path/'empty.xy',Curve(np.arange(2.),np.full(2,np.nan)))
    assert not list(tmp_path.glob('*.xy*'))
