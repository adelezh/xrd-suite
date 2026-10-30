import csv
import json
from dataclasses import replace
import numpy as np
import pytest
from xrd_gui.files import Curve, write_curve
from xrd_suite.analysis import (Collection, Snapshot, FitSettings, fit_snapshot, display_values, import_curve, export_fits)
from xrd_suite.peaks import pseudo_voigt

@pytest.fixture
def curve():
    x=np.linspace(2,4,601)
    return Curve(x,12+pseudo_voigt(x,80,3,.12,.35),np.ones(len(x)),
        {'source':'same source.tiff','unit':'2th_deg','wavelength_m':1e-10,'settings':{'method_1d':'average'},'calibration_sha256':'abc','mask_sha256':'def'})

def test_snapshots_are_independent_and_immutable(curve):
    collection=Collection();one,two=collection.add([curve,curve]);a=collection.entries[one].snapshot
    expected=a.intensity.copy()
    curve.intensity[:]=0;curve.x[:]=1;curve.sigma[:]=20;curve.metadata['settings']['method_1d']='percentile'
    np.testing.assert_array_equal(a.intensity,expected)
    assert a.metadata['settings']['method_1d']=='average'
    assert one!=two and collection.entries[one].label!=collection.entries[two].label
    with pytest.raises(ValueError):a.x[0]=1
    with pytest.raises(ValueError):a.x.setflags(write=True)
    meta=a.metadata;meta['settings']['method_1d']='changed'
    assert a.metadata['settings']['method_1d']=='average'
    collection.remove([one]);assert two in collection.entries

@pytest.mark.parametrize('ext',['xy','chi','xye'])
def test_import_metadata_and_uncertainties(tmp_path,curve,ext):
    path=tmp_path/f'with spaces.{ext}';write_curve(path,curve)
    read=import_curve(path)
    assert read.metadata['unit']=='2th_deg' and read.metadata['wavelength_m']==1e-10
    assert read.metadata['calibration_sha256']=='abc'
    assert read.metadata['import_path']==str(path.resolve())
    if ext=='xye':np.testing.assert_array_equal(read.sigma,curve.sigma)

def test_unknown_and_mixed_units_rejected(tmp_path,curve):
    p=tmp_path/'unknown.xy';np.savetxt(p,np.c_[curve.x,curve.intensity])
    c=Collection();unknown,known=c.add([import_curve(p),curve])
    with pytest.raises(ValueError,match='Assign units'):c.selected_snapshots([unknown,known])
    c.assign_unit([unknown],'q_A^-1')
    with pytest.raises(ValueError,match='same units'):c.selected_snapshots([unknown,known])
    with pytest.raises(ValueError,match='Only unknown'):c.assign_unit([known],'q_A^-1')
    assert c.entries[unknown].snapshot.metadata['unit_assignment'].startswith('explicit')

def test_chi_header_units_without_sidecar(tmp_path):
    p=tmp_path/'plain.chi';p.write_text('title\nq_A^-1\nIntensity\n3\n1 2\n2 3\n3 4\n')
    assert import_curve(p).metadata['unit']=='q_A^-1'

def test_display_never_changes_fitting_data(curve):
    snap=Snapshot.capture(curve);before=snap.intensity.copy()
    transformed,scale=display_values(snap,'max absolute',45)
    assert scale>1 and transformed.max()==46
    np.testing.assert_array_equal(snap.intensity,before)
    a=fit_snapshot(snap,FitSettings(2.5,3.5))
    display_values(snap,'none',1000)
    b=fit_snapshot(snap,FitSettings(2.5,3.5))
    assert a.parameters==b.parameters

@pytest.mark.parametrize('center,width,area,points',[(3.,.12,80,601),(3.1,.19,32,488),(2.9,.08,110,823)])
def test_independent_known_peaks(center,width,area,points):
    x=np.linspace(2,4,points);snap=Snapshot.capture(Curve(x,7+pseudo_voigt(x,area,center,width,.35),metadata={'unit':'2th_deg'}))
    fit=fit_snapshot(snap,FitSettings(2.5,3.5))
    assert fit.status=='ok',fit.detail
    for key,value in [('center',center),('fwhm',width),('area',area)]:assert fit.parameters[key]==pytest.approx(value,rel=2e-6)
    assert np.max(np.abs(fit.residual))<1e-5
    np.testing.assert_array_equal(fit.x,x[(x>=2.5)&(x<=3.5)])

@pytest.mark.parametrize('kind',['flat','multiple','short','unordered','nan'])
def test_explicit_failed_or_ambiguous_fits(curve,kind):
    if kind=='flat':curve.intensity[:]=3
    if kind=='multiple':curve.intensity+=pseudo_voigt(curve.x,80,3.3,.08,.3)
    if kind=='short':curve=Curve(curve.x[:4],curve.intensity[:4],metadata=curve.metadata)
    if kind=='unordered':curve.x=curve.x[::-1]
    if kind=='nan':curve.intensity[:]=np.nan
    fit=fit_snapshot(Snapshot.capture(curve),FitSettings(2.5,3.5))
    assert fit.status in ('failed','ambiguous') and fit.detail and not fit.parameters

def test_fit_invalidation_and_export(tmp_path,curve):
    c=Collection();key=c.add([curve])[0];entry=c.entries[key]
    entry.fit=fit_snapshot(entry.snapshot,FitSettings(2.5,3.5))
    p=tmp_path/'fit.csv';export_fits(p,c.entries.values());row=list(csv.DictReader(p.open()))[0]
    assert float(row['center'])==pytest.approx(3.)
    assert json.loads(row['fit_settings'])['baseline']=='none'
    assert json.loads(row['metadata'])['mask_sha256']=='def'
    c.invalidate_fits();export_fits(p,c.entries.values());row=list(csv.DictReader(p.open()))[0]
    assert row['center']=='' and row['status']=='not fitted'

def test_invalid_bins_do_not_enter_fit(curve):
    curve.metadata['invalid_bins']=[300];curve.intensity[300]=1e9
    fit=fit_snapshot(Snapshot.capture(curve),FitSettings(2.5,3.5))
    assert fit.status=='ok' and fit.parameters['center']==pytest.approx(3.)
    assert len(fit.x)==300


def test_import_nested_sidecar_units(tmp_path,curve):
    path=tmp_path/'nested.xy';np.savetxt(path,np.c_[curve.x,curve.intensity])
    Path = type(path)
    Path(str(path)+'.json').write_text(json.dumps({'settings':{'unit':'q_A^-1'},'source':'detector.tiff'}))
    assert import_curve(path).metadata['unit']=='q_A^-1'

def test_uncertainties_retained_without_reweighting(curve):
    a=Snapshot.capture(curve)
    curve.sigma=np.geomspace(.001,1e5,len(curve.x))
    b=Snapshot.capture(curve)
    assert not np.array_equal(a.sigma,b.sigma)
    assert fit_snapshot(a,FitSettings(2.5,3.5)).parameters==fit_snapshot(b,FitSettings(2.5,3.5)).parameters
