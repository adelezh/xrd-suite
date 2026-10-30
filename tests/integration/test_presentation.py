from types import SimpleNamespace
import numpy as np
import pytest
from xrd_gui.presentation import map_display, file_fields, curve_labels, effective_manipulation
from xrd_gui.files import Curve

def test_map_valid_zero_and_display_immutability():
    raw=np.array([[0.,2.,999.],[-1.,4.,np.nan]])
    r=SimpleNamespace(intensity=raw,count=np.array([[1,1,0],[1,1,0]]))
    before=raw.copy();data,norm,n=map_display(r,0,100)
    assert not data.mask[0,0] and data.mask[0,2]
    assert norm.vmin==-1 and norm.vmax==4
    data,norm,n=map_display(r,0,100,True)
    assert n==2 and data.mask[0,0] and data.mask[1,0]
    data[0,1]=1234
    np.testing.assert_array_equal(raw,before)

def test_map_normalization_fallback_and_bad_limits():
    r=SimpleNamespace(intensity=np.array([[0.,5.]]),sum_normalization=np.array([[1.,0.]]))
    data,_,_=map_display(r)
    assert not data.mask[0,0] and data.mask[0,1]
    with pytest.raises(ValueError):map_display(r,logarithmic=True)
    with pytest.raises(ValueError):map_display(r,limits=(4,1))

def test_labels_fallback_and_disambiguation():
    a='Sample_A_20260711-134044_fb35z4_primary-dk_sub_image-00001.tiff'
    b=a.replace('134044','134045')
    curves=[Curve(np.array([1]),np.array([1]),metadata={'source':p,'selection':'full'}) for p in (a,b)]
    labels=curve_labels(curves)
    assert labels[0]!=labels[1] and all('.tiff' not in label for label in labels)
    for i,c in enumerate(curves):c.metadata['source']='unrecognized_'+'long_prefix_'*5+str(i)+'.tiff'
    assert len(set(curve_labels(curves)))==2
    assert file_fields('unknown.tiff')==('unknown.tiff','Unrecognized','—')

def test_hidden_manipulation_options_do_not_leak():
    original=dict(operation='Average',naming='Custom',grouping='Sample',section='garbage',scale='invalid',extension='.chi')
    v,n,p,a=effective_manipulation(original,True,True,True,True)
    assert v['section']=='' and v['scale']==1 and not n and not p and not a
    assert original['section']=='garbage'
    original.update(operation='For TOPAS',naming='Keep original',extension='.xy',scale='2')
    v,n,p,a=effective_manipulation(original,True,True,True,True)
    assert v['extension']=='.xy' and v['section']=='' and not a and not n
    original['extension']='.xye'
    assert effective_manipulation(original,approximate=True,missing_sigma=False)[3] is False
    assert effective_manipulation(original,approximate=True,missing_sigma=True)[3] is True

def test_map_exports_unchanged_by_display(tmp_path):
    from xrd_gui.files import write_map
    r=SimpleNamespace(intensity=np.array([[0.,2.],[-1.,4.]]),count=np.ones((2,2)),radial=np.array([1.,2.]),azimuthal=np.array([-90.,90.]),sigma=np.ones((2,2)))
    write_map(tmp_path/'before.npz',r,{'unit':'2th_deg'})
    for log in (False,True):map_display(r,0,100,logarithmic=log)
    write_map(tmp_path/'after.npz',r,{'unit':'2th_deg'})
    with np.load(tmp_path/'before.npz') as a,np.load(tmp_path/'after.npz') as b:
        assert set(a.files)==set(b.files)
        for key in a.files:np.testing.assert_array_equal(a[key],b[key])
