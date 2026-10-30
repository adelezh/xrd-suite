from pathlib import Path
from dataclasses import dataclass, field
import json, os, tempfile, shutil
import numpy as np

@dataclass
class Curve:
    x: np.ndarray
    intensity: np.ndarray
    sigma: np.ndarray | None = None
    metadata: dict = field(default_factory=dict)

def read_image(path):
    p = Path(path)
    if p.suffix.lower() == '.npy': data = np.load(p, allow_pickle=False)
    else:
        import fabio
        with fabio.open(str(p)) as f: data = f.data.copy()
    data = np.asarray(data, dtype=np.float64)
    if data.ndim != 2: raise ValueError(f'{p.name}: expected a single 2D detector image, got {data.shape}.')
    return data

def read_curve(path):
    rows = []; started = False
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        text = line.split('#')[0].strip()
        if not text: continue
        try: row = [float(t) for t in text.replace(',', ' ').split()]
        except ValueError:
            if started: raise ValueError(f'Malformed numeric row in {Path(path).name}: {line}')
            continue
        if len(row) not in (2,3):
            if started: raise ValueError('Expected two or three numeric columns.')
            continue
        started = True; rows.append(row)
    if not rows or len({len(r) for r in rows}) != 1: raise ValueError('No consistent two/three-column numeric data.')
    a = np.asarray(rows)
    if not np.isfinite(a).all(): raise ValueError('Input contains nonfinite numeric values.')
    meta = {'source':str(path), 'unit':'unknown (preserved)'}
    side = Path(str(path)+'.json')
    if side.exists(): meta.update(json.loads(side.read_text()))
    elif Path(path).stem.endswith('_q'): meta['unit'] = 'q_A^-1'
    elif Path(path).stem.endswith('_tth'): meta['unit'] = '2th_deg'
    return Curve(a[:,0],a[:,1],a[:,2] if a.shape[1]==3 else None,meta)

def validate_sigma(curve):
    if curve.metadata.get('xye_supported') is False:
        raise ValueError(curve.metadata.get('xye_reason','This result has no supported uncertainty for XYE. Choose XY/CHI.'))
    if curve.sigma is None: raise ValueError('XYE needs uncertainties. Select a pyFAI error model or supply variance; conversion offers an explicit approximation.')
    good = np.isfinite(curve.sigma) & (curve.sigma > 0) & np.isfinite(curve.intensity) & np.isfinite(curve.x)
    if not good.all(): raise ValueError(f'XYE contains {np.count_nonzero(~good)} invalid/empty bins. Reduce bins or restrict radial range; no fabricated uncertainties will be written.')

def scale_curve(c, factor=1., approximate=False):
    if not np.isfinite(factor): raise ValueError('Scale must be finite.')
    sigma = c.sigma
    meta = dict(c.metadata)
    if sigma is None and approximate:
        sigma = np.sqrt(np.maximum(c.intensity,1.)); meta['uncertainty'] = 'Approximate sqrt(max(original I,1)); not true counting uncertainty'
    return Curve(c.x.copy(),c.intensity*factor,None if sigma is None else sigma*abs(factor),meta)

def combine_curves(curves, average=False):
    first = curves[0]
    for c in curves:
        if c.x.shape != first.x.shape or not np.allclose(c.x,first.x,rtol=1e-10,atol=1e-12): raise ValueError('X-coordinate grids differ. Interpolation is not performed.')
        if c.metadata.get('unit') != first.metadata.get('unit'): raise ValueError('Input units differ.')
        if c.sigma is not None: validate_sigma(c)
    n = len(curves) if average else 1
    sigma = np.sqrt(sum(c.sigma**2 for c in curves))/n if all(c.sigma is not None for c in curves) else None
    return Curve(first.x.copy(),sum(c.intensity for c in curves)/n,sigma,{'unit':first.metadata.get('unit'), 'sources':[c.metadata for c in curves], 'operation':'average' if average else 'sum', 'uncertainty':'independent variance propagation' if sigma is not None else 'unavailable: at least one input lacks sigma'})

def resolve_output(path, policy='Skip'):
    path = Path(path)
    if not path.exists() and not Path(str(path)+'.json').exists(): return path
    if policy == 'Skip': return None
    if policy == 'Overwrite': return path
    i = 1
    while True:
        p = path.with_name(f'{path.stem}_{i}{path.suffix}')
        if not p.exists() and not Path(str(p)+'.json').exists(): return p
        i += 1

def atomic_write(path, writer, overwrite=False):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp = tempfile.mkstemp(prefix='.xrd-',suffix=path.suffix,dir=path.parent); os.close(fd)
    try:
        writer(Path(tmp))
        if overwrite: os.replace(tmp,path)
        else:
            # Windows rename refuses an existing destination; POSIX hard-link is exclusive.
            if os.name == 'nt': os.rename(tmp,path)
            else: os.link(tmp,path); os.unlink(tmp)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def write_curve(path, c, headerless=False, overwrite=False):
    path = Path(path); ext = path.suffix.lower()
    # Omit undefined integration bins without changing the in-memory result or grid.
    valid = np.isfinite(c.x) & np.isfinite(c.intensity)
    valid[np.asarray(c.metadata.get('invalid_bins', []), dtype=int)] = False
    omitted = np.flatnonzero(~valid)
    if not valid.any():
        raise ValueError('No finite populated bins to export. Adjust the range, mask, or bin count.')
    if omitted.size:
        meta = dict(c.metadata)
        meta['export_omitted_bins'] = omitted.tolist()
        meta['export_original_bin_count'] = len(c.x)
        meta['export_retained_bin_indices'] = np.flatnonzero(valid).tolist()
        meta['export_bin_policy'] = 'Undefined bins omitted; original coordinates retained; no interpolation or zero substitution.'
        meta['integration_invalid_bins'] = list(c.metadata.get('invalid_bins', []))
        meta['invalid_bins'] = []  # Exported rows are populated; old indices refer to the original grid.
        c = Curve(c.x[valid], c.intensity[valid], None if c.sigma is None else c.sigma[valid], meta)
    if ext == '.xye': validate_sigma(c)
    data = np.column_stack((c.x,c.intensity,c.sigma)) if ext == '.xye' else np.column_stack((c.x,c.intensity))
    header = ''
    if ext == '.chi' and not headerless:
        header = f"{path.stem}\n{c.metadata.get('unit','unknown')}\nIntensity\n{len(c.x)}"
    atomic_write(path, lambda p: np.savetxt(p,data,fmt='%.12g',header=header,comments=''),overwrite)
    atomic_write(str(path)+'.json',lambda p:p.write_text(json.dumps(c.metadata,indent=2,default=str)),overwrite)
    return int(omitted.size)

def write_map(path, result, metadata, overwrite=False):
    payload = dict(intensity=result.intensity,radial=result.radial,azimuth=result.azimuthal,metadata=json.dumps(metadata,default=str))
    if result.sigma is not None: payload['sigma'] = result.sigma
    atomic_write(path,lambda p: np.savez_compressed(p,**payload),overwrite)
