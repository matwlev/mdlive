"""Exercise the real shell installer with isolated paths and a fake Python/pip."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / 'install.sh'
REMOTE = 'https://github.com/matwlev/mdlive/archive/refs/heads/main.tar.gz'


@pytest.fixture
def installer_env(tmp_path):
    fake = tmp_path / 'python3'
    fake.write_text('#!' + sys.executable + '\n' + '''
import os
from pathlib import Path
import shutil
import sys
args = sys.argv[1:]
if args[:1] == ['-c']:
    sys.exit(1 if os.environ.get('TEST_OLD_PYTHON') else 0)
if args[:2] == ['-m', 'venv']:
    if os.environ.get('TEST_NO_VENV'):
        sys.exit(1)
    target = Path(args[2]) / 'bin'
    target.mkdir(parents=True)
    shutil.copy2(__file__, target / 'python')
    sys.exit(0)
if args[:4] == ['-m', 'pip', 'install', '--upgrade']:
    if os.environ.get('TEST_PIP_FAILURE'):
        sys.exit(1)
    Path(os.environ['TEST_INSTALL_LOG']).write_text(args[4])
    command = Path(__file__).with_name('mdlive')
    command.write_text('#!/bin/sh\\necho "mdlive 0.1.0"\\n')
    command.chmod(0o755)
    sys.exit(0)
sys.exit(2)
''')
    fake.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith('MDLIVE_')}
    env.update(HOME=str(tmp_path / 'home'), SHELL='/bin/zsh',
               MDLIVE_PYTHON=str(fake), MDLIVE_INSTALL_DIR=str(tmp_path / 'app'),
               MDLIVE_BIN_DIR=str(tmp_path / 'commands'), TEST_INSTALL_LOG=str(tmp_path / 'installed-source'))
    return env


def run_installer(tmp_path, env, mode='pipe', options=('--no-modify-path',)):
    if mode == 'pipe':
        command = ['/bin/bash', '-s', '--', *options]
        source = INSTALLER.read_text()
    else:
        if mode == 'checkout':
            path = INSTALLER
        else:
            path = tmp_path / 'downloaded-install.sh'
            shutil.copy2(INSTALLER, path)
        command = ['/bin/bash', str(path), *options]
        source = None
    return subprocess.run(command, input=source, env=env, cwd=tmp_path, text=True, capture_output=True)


@pytest.mark.parametrize('mode', ['pipe', 'standalone', 'checkout'])
def test_installer_sources_and_isolation(tmp_path, installer_env, mode):
    result = run_installer(tmp_path, installer_env, mode)
    assert result.returncode == 0, result.stderr
    expected = str(INSTALLER.parent) if mode == 'checkout' else REMOTE
    assert Path(installer_env['TEST_INSTALL_LOG']).read_text() == expected
    link = Path(installer_env['MDLIVE_BIN_DIR']) / 'mdlive'
    assert link.is_symlink()
    assert link.resolve() == Path(installer_env['MDLIVE_INSTALL_DIR']) / 'venv/bin/mdlive'
    assert not (Path(installer_env['HOME']) / '.zshrc').exists()


@pytest.mark.parametrize('old_python', [False, True])
def test_installer_rejects_missing_or_old_python_before_install(tmp_path, installer_env, old_python):
    installer_env.pop('MDLIVE_PYTHON')
    if old_python:
        installer_env['PATH'] = str(tmp_path)
        installer_env['TEST_OLD_PYTHON'] = '1'
    else:
        installer_env['PATH'] = str(tmp_path / 'no-executables')
    result = run_installer(tmp_path, installer_env)
    assert result.returncode == 1
    assert 'Python 3.11+ was not found' in result.stderr
    assert not Path(installer_env['MDLIVE_INSTALL_DIR']).exists()
    assert not Path(installer_env['TEST_INSTALL_LOG']).exists()


def test_installer_detects_python_on_path(tmp_path, installer_env):
    installer_env.pop('MDLIVE_PYTHON')
    installer_env['PATH'] = str(tmp_path) + os.pathsep + '/usr/bin:/bin'
    result = run_installer(tmp_path, installer_env)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(('variable', 'message'), [('TEST_NO_VENV', 'venv support'), ('TEST_PIP_FAILURE', 'Installation failed')])
def test_installer_dependency_failures(tmp_path, installer_env, variable, message):
    installer_env[variable] = '1'
    result = run_installer(tmp_path, installer_env)
    assert result.returncode == 1
    assert message in result.stderr
    assert not (Path(installer_env['MDLIVE_BIN_DIR']) / 'mdlive').exists()


def test_installer_updates_and_path_are_idempotent(tmp_path, installer_env):
    for _ in range(2):
        result = run_installer(tmp_path, installer_env, options=())
        assert result.returncode == 0, result.stderr
    profile = Path(installer_env['HOME']) / '.zshrc'
    assert profile.read_text().count('# mdlive command') == 1


def test_installer_preserves_existing_command(tmp_path, installer_env):
    directory = Path(installer_env['MDLIVE_BIN_DIR'])
    directory.mkdir()
    command = directory / 'mdlive'
    command.write_text('leave this alone')
    result = run_installer(tmp_path, installer_env)
    assert result.returncode == 1
    assert 'Refusing to replace' in result.stderr
    assert command.read_text() == 'leave this alone'


def test_installer_help_needs_no_python(tmp_path, installer_env):
    installer_env['PATH'] = '/usr/bin:/bin'
    installer_env['MDLIVE_PYTHON'] = 'does-not-exist'
    result = run_installer(tmp_path, installer_env, options=('--help',))
    assert result.returncode == 0
    assert 'curl -fsSL' in result.stdout
    assert not Path(installer_env['MDLIVE_INSTALL_DIR']).exists()
