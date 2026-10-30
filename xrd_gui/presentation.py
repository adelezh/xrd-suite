"""Display-only transformations and compact labels, independent of Tk."""
from pathlib import Path
from collections import Counter
import numpy as np
from matplotlib.colors import Normalize, LogNorm
from .naming import parse

UNIT_LABELS={'2th_deg':'2θ (°)','q_A^-1':'q (Å⁻¹)'}
def file_fields(path):
    try:
        d=parse(path); return d['sample'],d['stamp'],d['identifier']
    except ValueError: return Path(path).name,'Unrecognized','—'

def short_source(path):
    sample,stamp,frame=file_fields(path)
    if stamp=='Unrecognized': return sample if len(sample)<=36 else sample[:33]+'…'
    return f'{sample} · Frame {frame}'

def method_label(s):
    method=s.get('method_1d','average')
    if method=='sigma_clip':return f"Sigma-clipping {s.get('sigma_threshold',5):g} sigma"
    if method=='percentile':return f"Percentile {s.get('percentile_low',25):g}-{s.get('percentile_high',75):g}"
    return 'Average'

def curve_labels(curves):
    sources=list(dict.fromkeys(c.metadata.get('source','') for c in curves))
    counts=Counter(short_source(p) for p in sources)
    labels=[]
    for c in curves:
        p=c.metadata.get('source',''); label=short_source(p)
        if counts[label]>1:
            stamp=file_fields(p)[1];label+=f' · {stamp}'
            if stamp=='Unrecognized' or sum(file_fields(q)==file_fields(p) for q in sources)>1: label+=f' · #{sources.index(p)+1}'
        s=c.metadata.get('settings',{}); selection=c.metadata.get('selection','full')
        label+=' · '+(f"Sector {s.get('start','?'):g}°–{s.get('end','?'):g}°" if selection=='sector' and isinstance(s.get('start'),(float,int)) else 'Full azimuth')
        label+=' | '+method_label(s)+(' (reference)' if c.metadata.get('comparison') else '')
        labels.append(label)
    return labels

def map_display(result, low=1., high=99., logarithmic=False, limits=None):
    """Return independent masked view and normalization, never mutate result arrays."""
    data=np.asarray(result.intensity)
    valid=np.isfinite(data)
    count=getattr(result,'count',None)
    norm=getattr(result,'sum_normalization',None)
    if count is not None: valid &= np.asarray(count)>0
    elif norm is not None: valid &= np.isfinite(norm) & (np.asarray(norm)>0)
    nonpositive=int(np.count_nonzero(valid & (data<=0))) if logarithmic else 0
    if logarithmic:valid &= data>0
    values=data[valid]
    if not values.size:raise ValueError('No positive populated bins for log display.' if logarithmic else 'No finite populated bins to display.')
    if limits is None:
        if not 0<=low<high<=100:raise ValueError('Contrast percentiles need 0 ≤ low < high ≤ 100.')
        vmin,vmax=np.percentile(values,[low,high])
        if vmin==vmax:
            if logarithmic:vmin,vmax=vmin*.9,vmax*1.1
            else:delta=max(abs(vmin)*.01,1.);vmin-=delta;vmax+=delta
    else:
        vmin,vmax=limits
        if not np.isfinite([vmin,vmax]).all() or vmin>=vmax:raise ValueError('Display minimum must be finite and below maximum.')
        if logarithmic and vmin<=0:raise ValueError('Log display needs a positive minimum.')
    return np.ma.array(data,mask=~valid,copy=True),(LogNorm(vmin,vmax) if logarithmic else Normalize(vmin,vmax)),nonpositive

def effective_manipulation(values, numbered=False, preserve=False, approximate=False, missing_sigma=False):
    """Drop irrelevant form values without erasing the user's saved choices."""
    v=dict(values); op=v['operation']; grouping=op in ('Sum','Average')
    custom=not grouping and v['naming']=='Custom'
    if not grouping:v['grouping']='All selected'
    if not (custom or grouping and v['grouping']=='Custom section'):v['section']=''
    if grouping:v['naming']='Keep original'
    if op=='Copy / Rename':v['extension']='.xy' # planner preserves source suffix
    if op=='For TOPAS' and v['extension'] not in ('.xy','.xye'):v['extension']='.xy'
    v['scale']=float(v['scale']) if op=='For TOPAS' else 1.
    return v, numbered and custom, preserve and custom, approximate and op=='For TOPAS' and v['extension']=='.xye' and missing_sigma
