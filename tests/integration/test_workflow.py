import threading
from dataclasses import replace, FrozenInstanceError
from pathlib import Path
import numpy as np
import pytest
from xrd_gui.naming import *
from xrd_gui.files import *
from xrd_gui.settings import Settings
from xrd_gui.processing import Engine, sector_pixels
from xrd_gui.jobs import *

NAME='AlC3_6_20260711-134044_fb35z4_primary-dk_sub_image-00000.tiff'

def test_naming():
    assert parse(NAME)['sample']=='AlC3_6'
    assert output_name(NAME,'Custom',section='0:6',preserve_identifier=True)=='AlC3_6_00000.tiff'
    assert output_name(NAME,'Shorten standard','tth','.chi')=='AlC3_6_20260711-134044_00000_tth.chi'
    name='AlC3_6_20260711-134044_fb3584_primary-1_mean_tth.chi'
    assert output_name(name,'Shorten standard')=='AlC3_6_20260711-134044_1_mean_tth.chi'
    assert output_name('abc_q.xy',unit='q')=='abc_q.xy'
    with pytest.raises(ValueError):parse('unrecognized.tiff')
    with pytest.raises(ValueError):check_collisions(['A.xy','a.xy'])

def test_grouping(tmp_path):
    other=NAME.replace('AlC3_6','Other_sample')
    groups=group_files([NAME,other],'Sample'); assert len(groups)==2
    plan=manipulation_plan([NAME,other],tmp_path,'Average','Sample','','Keep original','','',False,'.xy')
    assert len({p.name for _,p in plan})==2
    assert list(group_files(['/dir/abcdef.xy'],'Custom section','0:3'))==['abc']

@pytest.mark.parametrize('ext',['.xy','.chi','.xye'])
def test_curve_roundtrip(tmp_path,ext):
    c=Curve(np.arange(4.),np.array([-1.,0.,4.,9.]),np.ones(4),{'unit':'q_A^-1'})
    p=tmp_path/('test'+ext); write_curve(p,c); r=read_curve(p)
    np.testing.assert_equal(r.x,c.x); np.testing.assert_equal(r.intensity,c.intensity); assert r.metadata['unit']=='q_A^-1'
    if ext=='.xye':np.testing.assert_equal(r.sigma,c.sigma)
    if ext=='.chi':assert p.read_text().splitlines()[3]=='4'

def test_uncertainties():
    c=Curve(np.arange(3.),np.array([4.,0.,-3.]),None,{'unit':'2th_deg'})
    a=scale_curve(c,-2,True); np.testing.assert_equal(a.sigma,[4,2,2]);np.testing.assert_equal(a.intensity,[-8,0,6])
    s=combine_curves([a,a]);np.testing.assert_allclose(s.sigma,a.sigma*np.sqrt(2))
    avg=combine_curves([a,a],True);np.testing.assert_allclose(avg.sigma,a.sigma/np.sqrt(2))
    assert combine_curves([a,c]).sigma is None
    with pytest.raises(ValueError):combine_curves([a,Curve(c.x+.1,c.intensity)])
    with pytest.raises(ValueError):validate_sigma(c)
    with pytest.raises(ValueError):validate_sigma(Curve(c.x,c.intensity,np.array([1,0,np.nan])))

def test_sector():
    chi=np.array([-180,-175,-170,0,169,170,179])
    np.testing.assert_equal(sector_pixels(chi,170,-170),[1,1,0,0,0,1,1])
    np.testing.assert_equal(sector_pixels(chi,-180,180),np.ones(7,bool))

@pytest.fixture
def engine(tmp_path):
    from pyFAI.integrator.azimuthal import AzimuthalIntegrator
    ai=AzimuthalIntegrator(dist=.1,poni1=.0032,poni2=.0032,pixel1=.0001,pixel2=.0001,rot1=.015,rot2=.01,wavelength=1e-10)
    p=tmp_path/'synthetic.poni';ai.save(str(p)); return Engine(p)

def test_engine_mask_and_sector(engine,tmp_path):
    image=np.arange(4096,dtype=float).reshape(64,64)+20
    mask=np.zeros_like(image); mask[4:8,:]=1;engine.mask=mask.astype(bool)
    s=Settings(radial_bins=20,azimuth_bins=24,sector=True,start=170,end=-170,error_model='poisson')
    curves,m,meta=engine.integrate(image,s,'synthetic')
    expected=engine.mask | ~sector_pixels(engine.chi(image.shape),170,-170)
    r=engine.ai.integrate1d_ng(image,20,mask=expected,unit='2th_deg',correctSolidAngle=True,polarization_factor=.99,error_model='poisson',method=('no','histogram','cython'))
    np.testing.assert_allclose(curves[0].intensity,r.intensity);np.testing.assert_allclose(curves[0].sigma,r.sigma)
    assert m.intensity.shape==(24,20)
    p=tmp_path/'map.npz';write_map(p,m,meta);d=np.load(p);np.testing.assert_equal(d['radial'],m.radial)
    engine.mask=np.zeros((2,2),bool)
    with pytest.raises(ValueError,match='Mask shape'):engine.integrate(image,s)

def test_supplied_sigma_semantics(engine,tmp_path):
    image=np.full((64,64),100.); p=tmp_path/'var.npy';np.save(p,np.full_like(image,25.))
    s=Settings(radial_bins=10,solid_angle=False,polarization=0,error_model='supplied',variance=str(p))
    c,_,_=engine.integrate(image,s,two=False)
    # sigma is standard error of normalized mean, not sqrt(final intensity).
    r=engine.ai.integrate1d_ng(image,10,variance=np.full_like(image,25.),unit=s.unit,correctSolidAngle=False,polarization_factor=0,method=('no','histogram','cython'))
    np.testing.assert_allclose(c[0].sigma,np.sqrt(r.sum_variance)/r.sum_normalization)
    assert np.max(c[0].sigma)<10

def test_safe_outputs(tmp_path):
    p=tmp_path/'a.xy'; p.write_text('original')
    assert resolve_output(p,'Skip') is None
    assert resolve_output(p,'Unique name').name=='a_1.xy'
    with pytest.raises(FileExistsError):atomic_write(p,lambda q:q.write_text('bad'))
    assert p.read_text()=='original'
    def failed(q):q.write_text('partial');raise RuntimeError()
    with pytest.raises(RuntimeError):atomic_write(tmp_path/'b.xy',failed)
    assert not (tmp_path/'b.xy').exists();assert not list(tmp_path.glob('.xrd-*'))

def test_batch_fixed_and_cancel(engine,tmp_path):
    s=Settings(radial_bins=20)
    with pytest.raises(FrozenInstanceError):s.radial_bins=4
    new=replace(s,radial_bins=4);assert s.radial_bins==20
    plan=batch_plan([NAME],tmp_path,['2th_deg','q_A^-1'],True,True,'.chi','Shorten standard');assert len(plan)==4
    cancel=threading.Event();cancel.set()
    counts=run_batch(engine,s,plan,'Skip',cancel,lambda *a:None);assert counts['saved']==0

def test_settings():
    for s in [Settings(radial_bins=0),Settings(radial_range=(3,2)),Settings(start=181,sector=True),Settings(polarization=float('nan'))]:
        with pytest.raises(ValueError):s.validate()

def test_batch_writes_and_skip(engine,tmp_path):
    from fabio.tifimage import TifImage
    source=tmp_path/NAME;TifImage(data=np.full((64,64),10.)).write(str(source))
    folder=tmp_path/'out';plan=batch_plan([source],folder,['2th_deg'],True,True,'.chi','Shorten standard')
    report=[];cancel=threading.Event()
    counts=run_batch(engine,Settings(radial_bins=10,azimuth_bins=12),plan,'Skip',cancel,lambda *a:report.append(a))
    assert counts==dict(saved=2,skipped=0,failed=0,cancelled=False)
    assert run_batch(engine,Settings(radial_bins=10),plan,'Skip',cancel,lambda *a:None)['skipped']==2
    assert len(read_curve(plan[0][3]).x)==10

def test_manipulation(tmp_path):
    c=Curve(np.arange(3.),np.array([3.,5.,7.]),np.ones(3),{'unit':'q_A^-1'})
    a=tmp_path/'a_q.xye';b=tmp_path/'b_q.xye';write_curve(a,c);write_curve(b,c)
    plan=manipulation_plan([a,b],tmp_path/'out','Average','All selected','','Keep original','','',False,'.xye')
    result=run_manipulation(plan,'Average','Skip',1,False,threading.Event(),lambda *a:None)
    assert result['saved']==1;np.testing.assert_allclose(read_curve(plan[0][1]).sigma,1/np.sqrt(2))
    plan=manipulation_plan([a],tmp_path/'topas','For TOPAS','All selected','','Keep original','','',False,'.xye')
    result=run_manipulation(plan,'For TOPAS','Skip',-2,False,threading.Event(),lambda *a:None)
    assert result['saved']==1;data=np.loadtxt(plan[0][1]);np.testing.assert_equal(data[:,2],2);np.testing.assert_equal(data[:,0],c.x)

def test_frozen_variance(engine,tmp_path):
    p=tmp_path/'variance.npy';np.save(p,np.full((64,64),4.));s=Settings(radial_bins=10,error_model='supplied',variance=str(p));engine.freeze_variance(s)
    a=engine.integrate(np.ones((64,64))*10,s,two=False)[0][0]
    np.save(p,np.full((64,64),100.))
    b=engine.integrate(np.ones((64,64))*10,s,two=False)[0][0]
    np.testing.assert_equal(a.sigma,b.sigma)


@pytest.mark.parametrize("unit", ["2th_deg", "q_A^-1", "chi_rad"])
def test_coordinates_against_independent_geometry(engine, unit):
    # Do not compare two executions of the same pyFAI equation: both can be wrong.
    import copy
    shape = (64, 64)
    for ai in (engine.ai, copy.deepcopy(engine.ai)):
        pos = ai.position_array(shape)
        x, y, z = pos[..., 2], pos[..., 1], pos[..., 0]
        angle = np.arctan2(np.hypot(x, y), z)
        if unit == "2th_deg": expected = np.degrees(angle)
        elif unit == "q_A^-1": expected = 4*np.pi*np.sin(angle/2)/(ai.wavelength*1e10)
        else: expected = np.arctan2(y, x)
        np.testing.assert_allclose(ai.center_array(shape, unit), expected, rtol=1e-12, atol=1e-12)

def test_radial_extent_and_azimuth_coverage():
    from xrd_gui.processing import StableAzimuthalIntegrator
    ai = StableAzimuthalIntegrator(dist=1, pixel1=.0002, pixel2=.0002, poni1=.0064, poni2=.0064)
    result = ai.integrate2d_ng(np.ones((64,64)), 20, 36, unit="2th_deg", method=("no","histogram","cython"))
    assert result.radial.max() < 1
    assert np.count_nonzero(np.sum(result.count,axis=1)) == 36
