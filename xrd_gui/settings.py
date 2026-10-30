from dataclasses import dataclass, asdict
from pathlib import Path
import json
import math

@dataclass(frozen=True)
class Settings:
    unit: str = '2th_deg'
    radial_bins: int = 5000
    azimuth_bins: int = 360
    radial_range: tuple | None = None
    sector: bool = False
    start: float = 100.
    end: float = 180.
    solid_angle: bool = True
    polarization: float = .99
    error_model: str = 'none'
    variance: str = ''
    compare_full: bool = False

    method_1d: str = 'average'
    sigma_threshold: float = 5.0
    sigma_iterations: int = 5
    clipping_model: str = 'azimuthal'
    percentile_low: float = 25.0
    percentile_high: float = 75.0
    compare_average: bool = False

    def validate(self):
        if self.unit not in ('2th_deg', 'q_A^-1'): raise ValueError('Choose 2theta or q units.')
        if not 1 <= self.radial_bins <= 100000 or not 1 <= self.azimuth_bins <= 10000:
            raise ValueError('Radial bins must be 1–100000; azimuth bins 1–10000.')
        if self.radial_bins * self.azimuth_bins > 20000000: raise ValueError('Reduce bins: maximum 20 million map cells.')
        if self.radial_range and (not all(math.isfinite(x) for x in self.radial_range) or not 0 <= self.radial_range[0] < self.radial_range[1]):
            raise ValueError('Radial range needs finite 0 <= minimum < maximum.')
        if not all(math.isfinite(x) for x in (self.start,self.end,self.polarization)): raise ValueError('Angles and polarization must be finite.')
        if not -1 <= self.polarization <= 1: raise ValueError('Polarization must be between -1 and 1.')
        if self.sector and (not -180 <= self.start <= 180 or not -180 <= self.end <= 180 or self.start == self.end):
            raise ValueError('Sector angles must be different, within -180 to 180 degrees.')
        if self.error_model not in ('none','poisson','supplied'): raise ValueError('Unsupported uncertainty model.')
        if self.error_model == 'supplied' and not self.variance: raise ValueError('Choose a variance image (variance, not sigma).')
        if self.method_1d not in ('average','sigma_clip','percentile'):
            raise ValueError('Choose Average, Sigma-clipping, or Percentile filtering.')
        if self.method_1d == 'sigma_clip':
            if not math.isfinite(self.sigma_threshold) or self.sigma_threshold <= 0:
                raise ValueError('Sigma threshold must be positive and finite.')
            if isinstance(self.sigma_iterations,bool) or not isinstance(self.sigma_iterations,int) or self.sigma_iterations < 1:
                raise ValueError('Maximum iterations must be a positive integer.')
            if self.clipping_model not in ('azimuthal','poisson','supplied'):
                raise ValueError('Choose azimuthal, Poisson, or supplied variance for clipping.')
            if self.clipping_model == 'supplied' and not self.variance:
                raise ValueError('Supplied-variance clipping requires a variance image.')
        if self.method_1d == 'percentile':
            if not all(math.isfinite(x) for x in (self.percentile_low,self.percentile_high)) or not 0 <= self.percentile_low <= self.percentile_high <= 100:
                raise ValueError('Percentiles must be finite, with 0 <= lower <= upper <= 100 (installed Cython API).')
        return self

    @property
    def percentile_argument(self):
        return self.percentile_low if self.percentile_low == self.percentile_high else (self.percentile_low,self.percentile_high)

    def validate_xye(self):
        if self.method_1d == 'percentile' and self.percentile_low == self.percentile_high:
            raise ValueError('Median/single-quantile XYE is unavailable: pyFAI returns selected-pixel propagation, not a characterized quantile uncertainty. Choose XY or CHI.')
        if self.method_1d != 'sigma_clip' and self.error_model == 'none':
            raise ValueError('XYE needs a supported uncertainty model. Choose Poisson/supplied variance or export XY/CHI.')

class Preferences:
    def __init__(self, path=None):
        from xrd_suite.paths import settings_dir
        self.path = Path(path) if path is not None else settings_dir() / 'integration.json'
        try: self.data = json.loads(self.path.read_text())
        except (OSError, ValueError): self.data = {}
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))
    def remember(self, key, path):
        self.data[key] = str(path)
        if key == 'workspace':
            self.data['recent'] = list(dict.fromkeys([str(path)] + self.data.get('recent', [])))[:10]
        self.save()


METHOD_DEFAULTS = {k:asdict(Settings())[k] for k in (
    'method_1d','sigma_threshold','sigma_iterations','clipping_model',
    'percentile_low','percentile_high','compare_average')}

def restore_method_preferences(data):
    """Old or malformed preferences cannot prevent startup."""
    raw=data.get('integration_methods',{})
    if not isinstance(raw,dict):raw={}
    values=dict(METHOD_DEFAULTS)
    for key,value in raw.items():
        if key not in values:continue
        try:
            if key in ('sigma_threshold','percentile_low','percentile_high'):value=float(value)
            if key=='sigma_iterations':
                number=float(value)
                if not number.is_integer():continue
                value=int(number)
            if key=='compare_average' and not isinstance(value,bool):continue
            values[key]=value
        except (TypeError,ValueError,OverflowError):pass
    if values['method_1d'] not in ('average','sigma_clip','percentile'):values['method_1d']='average'
    if values['clipping_model'] not in ('azimuthal','poisson','supplied'):values['clipping_model']='azimuthal'
    if not math.isfinite(values['sigma_threshold']) or values['sigma_threshold']<=0:values['sigma_threshold']=5.
    if values['sigma_iterations']<1:values['sigma_iterations']=5
    if not all(math.isfinite(values[k]) for k in ('percentile_low','percentile_high')) or not 0<=values['percentile_low']<=values['percentile_high']<=100:
        values['percentile_low'],values['percentile_high']=25.,75.
    return values
