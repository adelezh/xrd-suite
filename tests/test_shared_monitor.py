import numpy as np
import pandas as pd
import pytest
from xrd_suite import peaks
from xrd_monitor import xrd_peak_workflow as monitor
from tests.fixtures import reference_peaks as reference

@pytest.mark.parametrize('method',['none','arpls','asls'])
def test_baseline_extraction_equivalent(method):
    x=np.linspace(2,4,301);y=peaks.pseudo_voigt(x,80,3,.12,.35)+8+.2*x
    for actual,expected in zip(peaks.baseline_correct_signal(x,y,method),reference.baseline_correct_signal(x,y,method)):
        np.testing.assert_array_equal(actual,expected)

def test_fit_extraction_equivalent():
    x=np.linspace(2,4,601);y=peaks.pseudo_voigt(x,80,3,.12,.35)+8
    options=dict(window=.4,center_bounds=(2.8,3.2),fit_bounds=(2.5,3.5))
    a=peaks.fit_pseudo_voigt_peak(x,y,300,**options);b=reference.fit_pseudo_voigt_peak(x,y,300,**options)
    for key in a:np.testing.assert_array_equal(a[key],b[key])
    assert monitor.fit_pseudo_voigt_peak is peaks.fit_pseudo_voigt_peak
    assert monitor.baseline_correct_signal is peaks.baseline_correct_signal

@pytest.fixture
def scans(tmp_path):
    paths=[]
    for i in (10,2,1):
        x=np.linspace(2,4,601);y=12+peaks.pseudo_voigt(x,80,3+i*.002,.12,.35)
        p=tmp_path/f'synthetic_primary-{i}_mean_tth.chi';np.savetxt(p,np.c_[x,y]);paths.append(str(p))
    return paths

def test_scan_identity_and_order_preserved(scans):
    assert monitor.ordered_files(scans)==reference.ordered_files(scans)
    np.testing.assert_array_equal(monitor.scan_axis_values(monitor.ordered_files(scans)),[1,2,10])
    duplicate=scans+[scans[0].replace('_tth','_q')]
    np.testing.assert_array_equal(monitor.scan_axis_values(duplicate),np.arange(4))

def test_tracking_equivalent(scans):
    kwargs=dict(initial_center=3.002,max_shift=.05,xmin=2.5,xmax=3.5,baseline_method='none')
    pd.testing.assert_frame_equal(monitor.track_peak_files(scans,**kwargs),reference.track_peak_files(scans,**kwargs))

def test_similarity_and_map_equivalent(scans):
    a=monitor.SimilarityConfiguration(scans[0],2.5,3.5).compare(scans)
    b=reference.SimilarityConfiguration(scans[0],2.5,3.5).compare(scans)
    pd.testing.assert_frame_equal(a,b)
    for actual,expected in zip(monitor.build_intensity_map(scans),reference.build_intensity_map(scans)):
        np.testing.assert_array_equal(actual,expected)

def test_detector_calibration_cache_and_rings(tmp_path):
    from xrd_suite.example import generate
    from xrd_monitor.xrd_detector_inspector import read_pair,matching_tiff
    from xrd_monitor.xrd_calibration import load_folder_calibration,GeometryCache,click_to_angle,angle_to_x
    folder=generate(tmp_path/'example with spaces');path=folder/'integration/synthetic_primary-1_mean_tth.chi'
    pair=read_pair(path);assert pair['scan']==1 and pair['image'].shape==(128,128)
    assert matching_tiff(path).name.endswith('00000.tiff')
    calibration=load_folder_calibration(folder/'integration');cache=GeometryCache()
    angles=cache.angles(calibration,(128,128));assert angles is cache.angles(calibration,(128,128))
    assert not angles.flags.writeable
    for kind in ('q','tth'):
        assert angle_to_x(click_to_angle(3,kind,1.),kind,1.)==pytest.approx(3)
    cache.clear();assert not cache.arrays

def test_cif_references(tmp_path):
    from pymatgen.core import Lattice,Structure
    from xrd_monitor.xrd_calculated_phases import CalculatedPhase,calculate_reflections,positions_for_dtype
    path=tmp_path/'synthetic silicon.cif'
    Structure(Lattice.cubic(5.43),['Si'],[[0,0,0]]).to(filename=path,fmt='cif')
    phase=CalculatedPhase(1,'Synthetic cubic',str(path),'blue')
    rows=calculate_reflections(phase,1.,0,dtype='tth',xmin=1,xmax=80)
    assert rows and phase._raw_cache
    np.testing.assert_allclose(positions_for_dtype(rows,'q'),[2*np.pi/r['d'] for r in rows])
