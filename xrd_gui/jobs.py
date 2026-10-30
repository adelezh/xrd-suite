from pathlib import Path
from dataclasses import replace, asdict
import shutil
import numpy as np
from .naming import output_name, check_collisions, group_files, add_method_tag
from .files import read_image, read_curve, combine_curves, scale_curve, write_curve, write_map, resolve_output, atomic_write


def batch_plan(files, folder, units, one, two, extension, naming, settings=None):
    if not files or not units or not (one or two): raise ValueError('Select input files, at least one unit and output product.')
    if not folder: raise ValueError('Choose an output folder.')
    plan = []
    for source in files:
        for unit in units:
            for dim,ext in [('1D',extension)]*bool(one) + [('2D','.npz')]*bool(two):
                name = output_name(source,naming,unit='tth' if unit=='2th_deg' else 'q',extension=ext,dimension='2d' if dim=='2D' else '')
                if dim=='1D' and settings is not None:name=add_method_tag(name,settings)
                plan.append((str(source),unit,dim,Path(folder)/name))
    check_collisions([p[3] for p in plan]); return plan


def run_batch(engine, settings, plan, policy, cancel, report):
    counts = dict(saved=0,skipped=0,failed=0)
    # One image and at most one result at a time; no batch-sized image cache.
    for index,(source,unit,dim,path) in enumerate(plan):
        if cancel.is_set(): break
        try:
            target = resolve_output(path,policy)
            if target is None: counts['skipped'] += 1; report(index+1,len(plan),f'Skipped: {path.name}'); continue
            if target.resolve() == Path(source).resolve(): raise ValueError('Output would overwrite an input.')
            s = replace(settings,unit=unit,compare_full=False,compare_average=False)
            if dim=='1D' and path.suffix.lower()=='.xye':s.validate_xye()
            curves,map_result,meta = engine.integrate(read_image(source),s,source,dim=='1D',dim=='2D')
            if cancel.is_set(): break
            omitted=0
            if dim=='1D': omitted=write_curve(target,curves[0],overwrite=policy=='Overwrite')
            else: write_map(target,map_result,meta,overwrite=policy=='Overwrite')
            counts['saved'] += 1; report(index+1,len(plan),f'Saved: {target.name}'+(f' ({omitted} undefined bins omitted)' if omitted else ''))
        except Exception as e:
            counts['failed'] += 1; report(index+1,len(plan),f'Failed {Path(source).name}: {e}')
    return dict(counts,cancelled=cancel.is_set())


def manipulation_plan(files,folder,operation,grouping,section,naming,prefix,suffix,numbered,extension,preserve_identifier=False):
    if not files or not folder: raise ValueError('Choose inputs and an output folder.')
    plan = []
    if operation in ('Sum','Average'):
        for key,members in group_files(files,grouping,section).items():
            image = Path(members[0]).suffix.lower() in ('.tif','.tiff')
            if any((Path(p).suffix.lower() in ('.tif','.tiff')) != image for p in members): raise ValueError('Do not mix detector images and 1D curves in one group.')
            name = prefix+key+suffix+('_sum' if operation=='Sum' else '_mean')+('.tiff' if image else extension)
            if any(c in name for c in '<>:"/\\|?*'): raise ValueError('Invalid group output name.')
            plan.append((members,Path(folder)/name))
    else:
        for i,p in enumerate(files,1):
            ext = extension if operation=='For TOPAS' else Path(p).suffix
            name = output_name(p,naming,extension=ext,prefix=prefix,suffix=suffix,section=section,number=i if numbered else None,preserve_identifier=preserve_identifier)
            plan.append(([str(p)],Path(folder)/name))
    check_collisions([p for _,p in plan])
    inputs = {str(Path(p).resolve()).casefold() for p in files}
    if any(str(p.resolve()).casefold() in inputs for _,p in plan): raise ValueError('Output would overwrite a source. Choose another folder or name.')
    return plan


def run_manipulation(plan,operation,policy,scale,approximate,cancel,report):
    counts = dict(saved=0,skipped=0,failed=0)
    for i,(members,path) in enumerate(plan):
        if cancel.is_set(): break
        try:
            target = resolve_output(path,policy)
            if target is None: counts['skipped']+=1; report(i+1,len(plan),f'Skipped: {path.name}'); continue
            overwrite = policy=='Overwrite'
            if operation=='Copy / Rename':
                atomic_write(target,lambda p:shutil.copyfile(members[0],p),overwrite)
                side = Path(members[0]+'.json')
                if side.exists(): atomic_write(str(target)+'.json',lambda p:shutil.copyfile(side,p),overwrite)
            elif operation=='For TOPAS':
                c = scale_curve(read_curve(members[0]),scale,approximate)
                write_curve(target,c,headerless=True,overwrite=overwrite)
            elif Path(members[0]).suffix.lower() in ('.tif','.tiff'):
                total = None
                for source in members:
                    if cancel.is_set(): return dict(counts,cancelled=True)
                    data = read_image(source)
                    if total is None: total = data
                    elif data.shape != total.shape: raise ValueError('Detector image dimensions differ.')
                    else: total += data
                if operation=='Average': total /= len(members)
                from fabio.tifimage import TifImage
                atomic_write(target,lambda p:TifImage(data=total).write(str(p)),overwrite)
            else:
                c = combine_curves([read_curve(p) for p in members],operation=='Average')
                write_curve(target,c,overwrite=overwrite)
            counts['saved']+=1; report(i+1,len(plan),f'Saved: {target.name}'+(f' ({omitted} undefined bins omitted)' if omitted else ''))
        except Exception as e:
            counts['failed']+=1; report(i+1,len(plan),f'Failed {path.name}: {e}')
    return dict(counts,cancelled=cancel.is_set())
