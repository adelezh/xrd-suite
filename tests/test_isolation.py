import ast
from pathlib import Path
import os
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]

def test_production_has_no_original_path_dependencies():
    for package in ('xrd_gui','xrd_suite','xrd_monitor'):
        for path in (ROOT/package).glob('*.py'):
            source=path.read_text(encoding='utf-8')
            assert 'sys.path' not in source
            assert 'C:\\PythonProject' not in source
            assert not path.is_symlink()

def test_preferences_are_suite_specific(tmp_path,monkeypatch):
    from xrd_gui.settings import Preferences
    monkeypatch.setenv('XRD_SUITE_CONFIG_DIR',str(tmp_path/'config'))
    prefs=Preferences();prefs.remember('workspace',str(tmp_path))
    assert prefs.path==tmp_path/'config/integration.json'
    assert prefs.path.exists()

@pytest.mark.parametrize('module',['xrd_gui','xrd_monitor'])
def test_launcher_without_original_code(tmp_path,module):
    # Only the suite is copied into this temporary source tree. Block any attempt
    # to open original project code using Python's audit hook in the child.
    import shutil
    isolated=tmp_path/'source with spaces';isolated.mkdir()
    for name in ('xrd_gui','xrd_suite','xrd_monitor'):
        shutil.copytree(ROOT/name,isolated/name,ignore=shutil.ignore_patterns('__pycache__'))
    script=isolated/'check.py'
    script.write_text("""import sys, runpy
from pathlib import Path
def guard(event,args):
    if event=='open' and isinstance(args[0],(str,bytes)):
        name=str(args[0]).replace(chr(92),'/').lower()
        if '/pythonproject/integration_gui/' in name or '/pythonproject/xrd_inline_monitor/' in name:
            raise RuntimeError('Original project access forbidden')
sys.addaudithook(guard)
module=sys.argv.pop(1)
sys.argv=[module,'--smoke-check']
runpy.run_module(module,run_name='__main__')
""")
    env=dict(os.environ,XRD_SUITE_CONFIG_DIR=str(tmp_path/'config'),XRD_SUITE_DATA_DIR=str(tmp_path/'data'),MPLCONFIGDIR=str(tmp_path/'mpl'),PYTHONDONTWRITEBYTECODE='1')
    result=subprocess.run([sys.executable,str(script),module],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
