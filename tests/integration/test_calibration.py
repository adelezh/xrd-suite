"""The calibration button launches stock pyFAI without integration state."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock


def test_calibration_launches_stock_application(monkeypatch, tmp_path):
    from xrd_gui.gui import App
    import xrd_gui.gui as gui
    import importlib.util

    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: object())
    launch = Mock()
    monkeypatch.setattr(gui.subprocess, 'Popen', launch)
    monkeypatch.setattr(gui, '__file__', str(tmp_path/'xrd_gui'/'gui.py'))
    monkeypatch.setenv('OMP_NUM_THREADS', '8')
    # Deliberately no active image, PONI, mask, or engine attributes:
    # launching must not depend on or forward any integration state.
    app = SimpleNamespace(workspace=SimpleNamespace(get=lambda: str(tmp_path)),
                          status=Mock())
    App.calibrate(app)
    args, kwargs = launch.call_args
    assert args == ([sys.executable, '-s', '-u', '-X', 'faulthandler',
                     '-m', 'pyFAI.app.calib2', '--debug'],)
    assert kwargs['cwd'] == str(tmp_path)
    assert 'env' not in kwargs
    assert gui.os.environ['OMP_NUM_THREADS'] == '8'
    assert kwargs['stderr'] == gui.subprocess.STDOUT
    assert kwargs['stdout'].closed
    assert list((tmp_path/'.test-output'/'calibration').glob('pyfai-*.log'))
    app.status.set.assert_called_once()


def test_detector_angle_map_matches_planar_geometry():
    """Catch the MKL NumExpr strided-input error before plotting any rings."""
    import numpy as np
    from pyFAI.geometry import Geometry
    from pyFAI.detectors import Detector
    detector = Detector(pixel1=2e-4, pixel2=2e-4, max_shape=(128, 128))
    geometry = Geometry(dist=.3, poni1=.0128, poni2=.0128, detector=detector)
    rows, cols = np.indices(detector.shape)
    expected = np.arctan2(np.hypot((rows+.5)*2e-4-.0128,
                                  (cols+.5)*2e-4-.0128), .3)
    actual = geometry.center_array(unit='2th_rad', scale=False)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-14)


def test_stock_calibration_gui_finishes(tmp_path):
    """Test plotting as well as fitting, in a fresh Qt process with a timeout."""
    import os
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, '-s', '-m', 'tests.calibration_smoke'], cwd=root,
        env=dict(os.environ, QT_QPA_PLATFORM='offscreen', MPLCONFIGDIR=str(tmp_path/'mpl')),
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Stock pyFAI GUI fit completed' in result.stdout
