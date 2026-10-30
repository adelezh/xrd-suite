"""Suite-only settings and user output locations."""
import os
from pathlib import Path

def settings_dir():
    configured = os.environ.get('XRD_SUITE_CONFIG_DIR')
    return Path(configured).expanduser() if configured else Path.home()/'.xrd-suite'

def data_dir():
    configured = os.environ.get('XRD_SUITE_DATA_DIR')
    return Path(configured).expanduser() if configured else Path.home()/'XRD Suite'

def default_workspace():
    p = data_dir()
    p.mkdir(parents=True, exist_ok=True)
    return str(p)
