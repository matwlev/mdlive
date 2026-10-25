import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from mdlive.config import load, parser
from mdlive.render import render, slug
from mdlive.server import App, make_server


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'README.md').write_text('# Hello\n\nWorld')
    return tmp_path


def config(*args):
    return load(parser().parse_args(list(args)))


@contextmanager
def serving(cfg, watcher=False):
    app = App(cfg)
    server = make_server(app, '127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    worker = threading.Thread(target=app.watch_loop, daemon=True)
    if watcher:
        worker.start()
        time.sleep(.3)
    try:
        yield app, f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        app.close()
        server.shutdown()
        server.server_close()
        thread.join(3)
        if watcher:
            worker.join(3)


def get(url):
    with urlopen(url, timeout=3) as response:
        return response.read().decode()


def test_help_version_skip_validation(project):
    (project / 'config.json').write_text('bad json')
    for option in ('-h', '--help', '--version'):
        executable = Path(sys.executable).parent / 'mdlive'
        result = subprocess.run([str(executable), 'missing.md', option], capture_output=True, text=True)
        assert result.returncode == 0
        assert 'mdlive 0.1.0' in result.stdout if option == '--version' else '--style-link' in result.stdout
    assert version('mdlive') == '0.1.0'


def test_config_precedence_and_paths(project):
    home = project / 'home/.mdlive'
    home.mkdir(parents=True)
    (home / 'config.json').write_text('{"port": 9000}')
    assert config().values['port'] == 9000
    (project / 'config.json').write_text('{"port": 9001, "styles": ["a"], "scripts": ["b"]}')
    c = config('--port', '9002', '--style', 'c', '--style', 'd')
    assert c.values['port'] == 9002
    assert c.values['styles'] == ['c', 'd']
    assert c.values['scripts'] == ['b']
    theme = project / 'theme'
    theme.mkdir()
    (theme / 'x.css').write_text('body{}')
    (theme / 'config.json').write_text('{"style_links": ["x.css"]}')
    assert config('--config', str(theme / 'config.json')).values['style_links'] == [str(theme / 'x.css')]
    with pytest.raises(FileNotFoundError):
        config('--config', 'missing.json')


@pytest.mark.parametrize('value', [{'port': True}, {'port': 0}, {'open': 'yes'}, {'styles': 'a'}, {'unknown': 1}])
def test_invalid_config(project, value):
    (project / 'config.json').write_text(json.dumps(value))
    with pytest.raises(ValueError):
        config()


def test_entries(project):
    (project / 'docs').mkdir()
    (project / 'docs/start.md').write_text('# Start')
    assert config('docs', '--index', 'start.md').entry == project / 'docs/start.md'
    with pytest.raises(ValueError):
        config('docs')
    with pytest.raises(ValueError):
        config('README.md', '--index', 'other.md')
    with pytest.raises(ValueError):
        config('--index', '../outside.md')


def test_rendering_headings_and_sanitization():
    output, headings = render('# Getting Started!\n\n## Héllo 世界\n\n## !!!\n\n# Same\n# Same\n\n'
                              '<h3>Raw <em>heading</em></h3><script>alert(1)</script>'
                              '<img src="x" onerror="evil()"><a href="javascript:evil()">bad</a>')
    assert [h['id'] for h in headings] == ['getting-started', 'héllo-世界', 'section', 'same', 'same-1', 'raw-heading']
    assert headings[-1] == dict(id='raw-heading', text='Raw heading', level=3)
    assert '<script' not in output and 'onerror' not in output and 'javascript:' not in output
    assert slug('  Lots \t of spaces ', 1) == 'lots-of-spaces'
    _, hs = render('<div id="hello">x</div>\n\n# Hello\n# mdlive content\n# Hello', lambda t, l: 'hello')
    assert [h['id'] for h in hs] == ['hello-1', 'hello-2', 'hello-3']


def test_custom_generator(project):
    (project / 'ids.py').write_text('def generate(text, level):\n    return text.lower().replace(" ", "_")\n')
    (project / 'config.json').write_text('{"heading_id_generator": "./ids.py:generate"}')
    c = config()
    assert render('# Hello World', c.generator)[1][0]['id'] == 'hello_world'
    for invalid in ('', 'has space', None, 3):
        with pytest.raises(ValueError):
            render('# A', lambda t, l: invalid)


def test_routes_assets_and_theme_order(project):
    (project / 'docs').mkdir()
    (project / 'docs/start.md').write_text('# Start\n\n![image](x.png)\n\n[next](next.md#section)')
    (project / 'docs/x.png').write_bytes(b'png')
    (project / 'theme.css').write_text('body{}')
    cfg = config('--index', 'docs/start.md', '--style-link', 'theme.css', '--style', '/* inline */',
                 '--script', '/* script */', '--script-link', 'https://example.test/theme.js')
    with serving(cfg) as (app, base):
        text = get(base + '/')
        assert '<base href="/docs/start.md">' in text
        assert 'href="next.md#section"' in text
        assert text.index('<link') < text.index('<style') < text.index('<main') < text.index('/* script */') < text.index('https://example.test/theme.js')
        assert get(base + '/docs/x.png') == 'png'
        assert get(base + '/__mdlive/assets/0') == 'body{}'
        assert 'EventSource' in get(base + '/__mdlive/client.js')
        state = json.loads(get(base + '/__mdlive/document?path=/docs/start.md'))
        assert state['data']['headings'][0]['id'] == 'start'
        with pytest.raises(HTTPError) as error:
            get(base + '/docs/')
        assert error.value.code == 404
        with pytest.raises(HTTPError) as error:
            get(base + '/%2e%2e/secret')
        assert error.value.code == 403
        outside = project.parent / 'outside.md'
        outside.write_text('secret')
        (project / 'escape.md').symlink_to(outside)
        assert '/escape.md' not in app.files()
        with pytest.raises(HTTPError) as error:
            get(base + '/escape.md')
        assert error.value.code == 403


def test_updates_and_config_recovery(project):
    cfgfile = project / 'config.json'
    cfgfile.write_text('{"styles": ["a"]}')
    app = App(config())
    (project / 'README.md').unlink()
    app.changed([project / 'README.md'])
    assert 'Document not found' in app.snapshot('/')['html']
    (project / 'README.md').write_text('# Back')
    app.changed([project / 'README.md'])
    assert app.snapshot('/')['data']['headings'][0]['id'] == 'back'
    old = app.reload_revision
    cfgfile.write_text('{"styles": ["b"], "port": 9000}')
    app.changed([cfgfile])
    assert app.config.values['styles'] == ['b'] and app.config.values['port'] == 8000
    assert old != app.reload_revision
    cfgfile.write_text('bad')
    app.changed([cfgfile])
    assert app.config.values['styles'] == ['b']


def test_real_watcher_and_multiple_sse_clients(project):
    with serving(config(), watcher=True) as (app, base):
        clients = [urlopen(base + '/__mdlive/events', timeout=4) for _ in range(2)]
        try:
            for client in clients:
                assert client.readline().startswith(b'data:')
                client.readline()
            (project / 'README.md').write_text('# Changed')
            deadline = time.monotonic() + 4
            while app.revision == 0 and time.monotonic() < deadline:
                time.sleep(.05)
            assert app.revision > 0
            assert app.snapshot('/')['data']['headings'][0]['id'] == 'changed'
            for client in clients:
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    line = client.readline()
                    if line.startswith(b'data:'):
                        assert json.loads(line[5:])['revision'] >= 1
                        break
                else:
                    pytest.fail('No update received over SSE')
        finally:
            for client in clients:
                client.close()


def test_generator_error_and_safe_metadata(project):
    app = App(config())
    app.config.generator = lambda text, level: ''
    assert 'Rendering error' in app.snapshot('/')['html']
    from mdlive.render import json_script
    assert '</script>' not in json_script({'text': '</script><script>alert(1)</script>'})


def test_external_theme_mapping_and_entry_symlink_swap(project):
    external = project.parent / 'external-theme.css'
    external.write_text('external{}')
    with serving(config('--style-link', str(external))) as (app, base):
        assert get(base + '/__mdlive/assets/0') == 'external{}'
        assert 'external-theme.css' not in get(base + '/')
        outside = project.parent / 'secret.md'
        outside.write_text('secret')
        (project / 'README.md').unlink()
        (project / 'README.md').symlink_to(outside)
        with pytest.raises(HTTPError) as error:
            get(base + '/')
        assert error.value.code == 403


def test_open_is_opt_in(project, monkeypatch):
    from mdlive import cli
    calls = []
    class Server:
        server_address = ('127.0.0.1', 8000)
        def serve_forever(self, **kwargs):
            raise KeyboardInterrupt
        def server_close(self):
            pass
    monkeypatch.setattr(cli, 'make_server', lambda *args: Server())
    monkeypatch.setattr(cli.App, 'watch_loop', lambda self: None)
    monkeypatch.setattr(cli.webbrowser, 'open', calls.append)
    monkeypatch.setattr(sys, 'argv', ['mdlive'])
    cli.main()
    assert not calls
    monkeypatch.setattr(sys, 'argv', ['mdlive', '--open'])
    cli.main()
    assert calls == ['http://127.0.0.1:8000/']


def test_directory_notifications_do_not_force_full_reload(project):
    app = App(config())
    old = app.reload_revision
    app.changed([project, project / 'README.md'])
    assert app.reload_revision == old
    assert app.revision == 1


def test_unreadable_sibling_directory_does_not_break_preview(project, monkeypatch):
    import errno
    import os

    broken = project / 'Before/Adoption/Charlotte/Matt Self Study.pages'
    broken.mkdir(parents=True)
    (project / 'guide.md').write_text('# Guide')
    original = os.scandir

    class UnreadableEntries:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            return self

        def __next__(self):
            raise OSError(errno.EDEADLK, 'Resource deadlock avoided', str(broken))

    def scandir(path):
        if Path(path) == broken:
            return UnreadableEntries()
        return original(path)

    monkeypatch.setattr(os, 'scandir', scandir)
    with serving(config('README.md')) as (app, base):
        assert '<h1 id="hello">Hello</h1>' in get(base + '/')
        state = json.loads(get(base + '/__mdlive/document?path=/'))
        assert state['data']['files'] == ['/README.md', '/guide.md']
        assert state['data']['headings'][0]['id'] == 'hello'


def test_unreadable_markdown_metadata_does_not_break_file_list(project, monkeypatch):
    import errno

    broken = project / 'unavailable.md'
    broken.write_text('# Unavailable')
    (project / 'loop.md').symlink_to('loop.md')
    original = Path.stat

    def stat(path, *args, **kwargs):
        if path == broken:
            raise OSError(errno.EDEADLK, 'Resource deadlock avoided', str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', stat)
    app = App(config('README.md'))
    assert app.files() == ['/README.md']
    assert app.snapshot('/')['data']['headings'][0]['id'] == 'hello'


def test_builtin_theme_selection_and_reload(project):
    assert config().values['theme'] == 'basic'
    selected = project / 'config.json'
    selected.write_text('{"theme": "none"}')
    assert config().values['theme'] == 'none'
    assert config('--theme', 'basic').values['theme'] == 'basic'
    selected.write_text('{"theme": "unknown"}')
    with pytest.raises(ValueError, match='theme'):
        config()
    with pytest.raises(ValueError, match='Unknown theme'):
        config('--theme', 'unknown')
    selected.write_text('{"theme": "basic"}')
    (project / 'override.css').write_text(':root { --mdl-palette-text: red; }')
    with serving(config('--style-link', 'override.css', '--style', '/* last */')) as (app, base):
        page = get(base + '/')
        assert page.index('/__mdlive/themes/basic.css') < page.index('/__mdlive/assets/0') < page.index('/* last */')
        with urlopen(base + '/__mdlive/themes/basic.css') as response:
            assert response.headers.get_content_type() == 'text/css'
            assert '--mdl-palette-primary-contrast' in response.read().decode()
        for route in ('/__mdlive/themes/config.py', '/__mdlive/themes/../config.py'):
            with pytest.raises(HTTPError) as error:
                get(base + route)
            assert error.value.code == 404
        before = app.reload_revision
        selected.write_text('{"theme": "none"}')
        app.changed([selected])
        assert app.reload_revision != before
        assert '/__mdlive/themes/basic.css' not in get(base + '/')
        selected.write_text('{"theme": "invalid"}')
        app.changed([selected])
        assert app.config.values['theme'] == 'none'


@pytest.mark.parametrize('name', ['basic-dark', 'basic-dynamic'])
def test_basic_variants_config_and_assets(project, name):
    selected = project / 'config.json'
    selected.write_text(json.dumps({'theme': name}))
    assert config().values['theme'] == name
    assert config('--theme', 'none').values['theme'] == 'none'
    with serving(config('--style', '/* override */')) as (app, base):
        page = get(base + '/')
        stylesheet = name + '.css'
        assert page.index('/__mdlive/themes/basic.css') < page.index('/__mdlive/themes/' + stylesheet) < page.index('/* override */')
        if name == 'basic-dynamic':
            assert '@import url("./basic-dark.css") (prefers-color-scheme: dark)' in get(base + '/__mdlive/themes/' + stylesheet)
        assert '--mdl-palette-background: var(--mdl-color-gray-90)' in get(base + '/__mdlive/themes/basic-dark.css')
        before = app.reload_revision
        selected.write_text('{"theme": "basic"}')
        app.changed([selected])
        assert app.reload_revision != before
        assert '/__mdlive/themes/basic-dark.css' not in get(base + '/')
