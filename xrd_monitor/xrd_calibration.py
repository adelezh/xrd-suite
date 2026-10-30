"""Safe acquisition metadata extraction and optional calibrated detector geometry."""
from dataclasses import dataclass
from pathlib import Path
import json
import re

import numpy as np


@dataclass(frozen=True)
class Calibration:
    folder: str
    sources: tuple
    parameters_json: str

    @property
    def parameters(self):
        return json.loads(self.parameters_json)

    @property
    def wavelength_angstrom(self):
        return self.parameters['Wavelength'] * 1e10


def _plain(node, yaml, ancestors=()):
    """Convert only the required YAML subtree, never constructing tagged objects."""
    if id(node) in ancestors or len(ancestors) > 20:
        raise ValueError('Recursive or excessively nested calibration metadata')
    ancestors = (*ancestors, id(node))
    tag = node.tag
    if tag not in {'tag:yaml.org,2002:' + name for name in ('map', 'seq', 'str', 'int', 'float', 'null', 'bool')}:
        raise ValueError(f'Unsupported YAML tag in calibration_md: {tag}')
    if isinstance(node, yaml.MappingNode):
        result = {}
        for key_node, value in node.value:
            key = _plain(key_node, yaml, ancestors)
            if not isinstance(key, str) or key in result:
                raise ValueError('Calibration keys must be unique plain strings')
            result[key] = _plain(value, yaml, ancestors)
        return result
    if isinstance(node, yaml.SequenceNode):
        return [_plain(item, yaml, ancestors) for item in node.value]
    # SafeLoader scalar constructors are restricted to the standard tags above.
    loader = yaml.SafeLoader('')
    try:
        return loader.construct_object(node, deep=True)
    finally:
        loader.dispose()


def read_calibration_metadata(path):
    try:
        import yaml
    except ImportError as exc:
        raise ImportError('Calibration metadata requires PyYAML (python -m pip install pyyaml).') from exc
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Metadata exceeds the 16 MiB size limit')
    # compose parses nodes; it does not instantiate Python/NumPy YAML objects.
    root = yaml.compose(path.read_text(encoding='utf-8'), Loader=yaml.SafeLoader)
    if not isinstance(root, yaml.MappingNode) or root.tag != 'tag:yaml.org,2002:map':
        raise ValueError('Metadata must be a plain YAML mapping')
    matches = [value for key, value in root.value
               if key.tag == 'tag:yaml.org,2002:str' and key.value == 'calibration_md']
    if len(matches) != 1:
        raise ValueError('Expected exactly one calibration_md mapping')
    raw = _plain(matches[0], yaml)
    if not isinstance(raw, dict):
        raise ValueError('calibration_md must be a mapping')
    result = {}
    for key in ('Distance', 'Poni1', 'Poni2', 'Rot1', 'Rot2', 'Rot3', 'Wavelength'):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        if key in ('Distance', 'Wavelength') and value <= 0:
            raise ValueError(f'{key} must be positive')
        result[key] = float(value)
    detector = raw.get('Detector')
    config = raw.get('Detector_config')
    if not isinstance(detector, str) or not detector.strip() or not isinstance(config, dict):
        raise ValueError('Detector and a plain Detector_config mapping are required')
    if set(config) - {'pixel1', 'pixel2', 'max_shape', 'orientation'}:
        raise ValueError('Unsupported Detector_config fields: ' + ', '.join(sorted(set(config) - {'pixel1', 'pixel2', 'max_shape', 'orientation'})))
    for key in ('pixel1', 'pixel2'):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0:
            raise ValueError(f'Detector_config.{key} must be finite and positive (meters)')
    if 'max_shape' in config:
        shape = config['max_shape']
        if not isinstance(shape, list) or len(shape) != 2 or any(type(n) is not int or n <= 0 for n in shape):
            raise ValueError('Detector_config.max_shape must contain two positive integers')
    if 'orientation' in config and (type(config['orientation']) is not int or config['orientation'] not in (1, 2, 3, 4)):
        raise ValueError('Only detector orientations 1, 2, 3, 4 are supported')
    if raw.get('poni_version', 2) not in (2, 2.1):
        raise ValueError('Only PONI geometry version 2 or 2.1 is supported')
    result.update(Detector=detector, Detector_config=config)
    return result


def load_folder_calibration(folder):
    folder = Path(folder).expanduser().resolve()
    if folder.name.lower() != 'integration' or not folder.is_dir():
        raise ValueError('Select an integration folder to load calibration')
    pattern = re.compile(r'^(.+)_primary-[1-9]\d*_mean_(?:tth|q)\.chi$', re.I)
    prefixes = {match.group(1) for path in folder.iterdir()
                if path.is_file() and (match := pattern.fullmatch(path.name))}
    if not prefixes:
        raise ValueError('Calibration unavailable: no recognized integration files; use Load calibration to retry')
    sources = []
    metadata = folder.parent / 'meta'
    for prefix in sorted(prefixes):
        found = sorted(p for p in metadata.glob('*')
                       if p.is_file() and p.stem == prefix and p.suffix.lower() in ('.yaml', '.yml'))
        if not found:
            raise ValueError(f'Calibration unavailable: no exact metadata match for {prefix}; use Load calibration to retry')
        sources.extend(found)
    parameters = None
    for path in sources:
        try:
            current = read_calibration_metadata(path)
        except Exception as exc:
            raise ValueError(f'{path.name}: {exc}') from exc
        if parameters is not None and current != parameters:
            raise ValueError('Ambiguous calibration: conflicting matching metadata files: ' + ', '.join(p.name for p in sources))
        parameters = current
    return Calibration(str(folder), tuple(str(p.resolve()) for p in sources), json.dumps(parameters, sort_keys=True))


def geometry_backend():
    try:
        from pyFAI.detectors import detector_factory
        from pyFAI.geometry import Geometry
    except ImportError as exc:
        raise ImportError('Ring guide requires pyFAI (python -m pip install pyfai); ordinary viewer remains available.') from exc
    return detector_factory, Geometry


def make_geometry(calibration, shape=None):
    factory, Geometry = geometry_backend()
    p = calibration.parameters
    detector = factory(p['Detector'], p['Detector_config'])
    if not detector.IS_FLAT or not detector.uniform_pixel:
        raise ValueError('Ring guide supports flat uniform-pixel detectors only')
    for key in ('pixel1', 'pixel2'):
        if not np.isclose(getattr(detector, key), p['Detector_config'][key], rtol=1e-10, atol=0):
            raise ValueError('Detector model does not honor the calibrated pixel sizes')
    expected = detector.shape or detector.max_shape
    if shape is not None:
        if len(shape) != 2 or min(shape) < 2:
            raise ValueError('Ring guide requires a 2D image with at least two rows and columns')
        if expected is not None and tuple(shape) != tuple(expected):
            raise ValueError(f'Image shape {tuple(shape)} differs from calibrated detector shape {tuple(expected)}; no binning, crop, flip, or transpose is inferred')
        detector.shape = tuple(shape)
    return Geometry(dist=p['Distance'], poni1=p['Poni1'], poni2=p['Poni2'],
                    rot1=p['Rot1'], rot2=p['Rot2'], rot3=p['Rot3'],
                    wavelength=p['Wavelength'], detector=detector)


class GeometryCache:
    def __init__(self):
        self.arrays = {}

    def clear(self):
        self.arrays.clear()

    def angles(self, calibration, shape):
        key = (calibration.parameters_json, tuple(shape))
        if key not in self.arrays:
            geometry = make_geometry(calibration, shape)
            angles = np.asarray(geometry.twoThetaArray(shape))
            if angles.shape != tuple(shape) or not np.isfinite(angles).all():
                raise ValueError('Invalid per-pixel geometry array')
            angles.setflags(write=False)
            if len(self.arrays) >= 4:
                self.arrays.clear()
            self.arrays[key] = angles
        return self.arrays[key]


def click_to_angle(value, kind, wavelength):
    if not np.isfinite(value) or value < 0:
        raise ValueError('Click must be a finite nonnegative diffraction coordinate')
    if kind == 'tth':
        if value > 180:
            raise ValueError('2Theta must be between 0 and 180 degrees')
        return float(np.radians(value))
    if kind != 'q' or not np.isfinite(wavelength) or wavelength <= 0:
        raise ValueError('Invalid data type or calibration wavelength')
    argument = value * wavelength / (4 * np.pi)
    if not 0 <= argument <= 1:
        raise ValueError('q is outside the physical domain for the calibration wavelength')
    return float(2 * np.arcsin(argument))


def angle_to_x(angle, kind, wavelength):
    return float(np.degrees(angle)) if kind == 'tth' else float(4*np.pi*np.sin(angle/2)/wavelength)
