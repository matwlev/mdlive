import json

import pytest

from mdlive.server import App
from mdlive.theme import BUNDLED_ASSETS, resolve
from test_mdlive import config, get, project, serving


def test_inheritance_order_paths_and_cli(project):
    definitions = project / 'settings'
    definitions.mkdir()
    (definitions / 'parent.css').write_text('/* parent link */')
    (definitions / 'child.js').write_text('/* child link */')
    settings = definitions / 'config.json'
    settings.write_text(json.dumps({
        'theme': 'child',
        'themes': {
            'ancestor': {'styles': ['/* ancestor */']},
            'left': {'extends': ['ancestor'], 'style_links': ['parent.css'], 'styles': ['/* left */']},
            'right': {'extends': ['ancestor'], 'styles': ['/* right */']},
            'child': {'extends': ['left', 'right'], 'styles': ['/* child */'],
                      'scripts': ['/* child inline */'], 'script_links': ['child.js']},
            'unused': {'style_links': ['missing.css']},
        },
        'styles': ['/* top */'], 'scripts': ['/* top script */'],
    }))
    cfg = config('--config', str(settings), '--style', '/* CLI */')
    assert [layer['styles'] for layer in cfg.layers] == [
        ['/* ancestor */'], ['/* left */'], ['/* right */'], ['/* child */'], ['/* CLI */']]
    assert cfg.layers[1]['style_links'] == [str(definitions / 'parent.css')]
    assert config('--config', str(settings), '--theme', 'none').layers[:-1] == [
        {key: [] for key in ('styles', 'scripts', 'style_links', 'script_links')}]
    with serving(cfg) as (app, base):
        page = get(base + '/')
        markers = ['/* ancestor */', '/__mdlive/assets/0', '/* left */', '/* right */', '/* child */', '/* CLI */']
        assert [page.index(marker) for marker in markers] == sorted(page.index(marker) for marker in markers)
        assert page.count('/* ancestor */') == 1
        assert '/* top */' not in page
        assert page.index('window.mdlive=') < page.index('/* child inline */') < page.index('/__mdlive/assets/1') < page.index('/* top script */')
        assert get(base + '/__mdlive/assets/0') == '/* parent link */'
        assert str(definitions / 'missing.css') not in app.mapping


@pytest.mark.parametrize(('definitions', 'selected', 'message'), [
    ({'basic': {}}, 'basic', 'reserved: basic'),
    ({'none': {}}, 'none', 'reserved: none'),
    ({'custom': {'unknown': []}}, 'custom', 'definition: custom'),
    ({'custom': []}, 'custom', 'definition: custom'),
    ({'custom': {'extends': 'basic'}}, 'custom', 'custom: extends'),
    ({'custom': {'style_links': [{'href': 'style.css'}]}}, 'custom', 'custom: style_links'),
    ({'custom': {'scripts': [1]}}, 'custom', 'custom: scripts'),
    ({'custom': {'extends': ['missing']}}, 'custom', 'custom -> missing'),
    ({'a': {'extends': ['b']}, 'b': {'extends': ['a']}}, 'a', 'a -> b -> a'),
    ({'a': {'extends': ['a']}}, 'a', 'a -> a'),
    ({'': {}}, 'basic', 'nonempty'),
    ({}, 'missing', 'Unknown theme: missing'),
])
def test_invalid_theme_definitions(tmp_path, definitions, selected, message):
    with pytest.raises(ValueError, match=message):
        resolve(selected, definitions, tmp_path)


def test_missing_selected_asset_identifies_theme(tmp_path):
    with pytest.raises(ValueError, match='Theme custom: file does not exist'):
        resolve('custom', {'custom': {'style_links': ['missing.css']}}, tmp_path)
    layers = resolve('custom', {'custom': {'style_links': ['https://example.test/style.css']}}, tmp_path)
    assert layers[0]['style_links'] == ['https://example.test/style.css']


def test_inherited_assets_reload_and_config_recovery(project):
    outside = project.parent / (project.name + '-theme')
    outside.mkdir()
    parent = outside / 'parent.css'
    parent.write_text('/* before */')
    settings = project / 'config.json'
    raw = {'theme': 'child', 'themes': {'parent': {'style_links': [str(parent)]}, 'child': {'extends': ['parent']}}}
    settings.write_text(json.dumps(raw))
    with serving(config(), watcher=True) as (app, base):
        import time
        before = app.reload_revision
        parent.write_text('/* after */')
        deadline = time.monotonic() + 5
        while app.reload_revision == before and time.monotonic() < deadline:
            time.sleep(.05)
        assert app.reload_revision != before
        assert get(base + '/__mdlive/assets/0') == '/* after */'
        # Invalid definition edits keep the previous resolved layers and mapping.
        settings.write_text('{"theme": "child", "themes": {"child": {"extends": ["missing"]}}}')
        app.changed([settings])
        assert str(parent) in app.mapping
        raw['themes']['child'] = {'styles': ['/* replacement */']}
        settings.write_text(json.dumps(raw))
        app.changed([settings])
        assert str(parent) not in app.mapping
        assert '/* replacement */' in get(base + '/')


def test_dynamic_bundled_dependencies_are_watched(project):
    app = App(config('--theme', 'basic-dynamic'))
    assert set(app.mapping) == set(BUNDLED_ASSETS)
    dark = next(path for path in app.mapping if path.endswith('/basic-dark.css'))
    before = app.reload_revision
    app.changed([dark])
    assert app.reload_revision != before
