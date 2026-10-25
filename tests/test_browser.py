"""Run with PLAYWRIGHT_BROWSERS_PATH set when using a custom browser cache."""
import json
import threading
import time

import pytest

from playwright.sync_api import sync_playwright

from mdlive.config import load, parser
from mdlive.server import App, make_server


def test_browser_theme_reload_fragments_and_reconnect(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'docs').mkdir()
    document = tmp_path / 'docs/start.md'
    source = '# Start\n\n' + '\n\n'.join(f'Paragraph {i}' for i in range(100)) + '\n\n## Target\n\nEnd'
    document.write_text(source)
    theme = tmp_path / 'theme.js'
    theme.write_text('''
      window.readyCount = 0; window.updateCount = 0;
      window.addEventListener('mdlive:ready', () => {
        window.readyCount++;
        const nav = document.createElement('nav'); nav.id = 'theme-nav';
        nav.textContent = window.mdlive.files.join(','); document.body.prepend(nav);
      });
      window.addEventListener('mdlive:update', () => {
        window.updateCount++; window.lastHeading = window.mdlive.headings.at(-1)?.id;
      });
    ''')
    configfile = tmp_path / 'config.json'
    configfile.write_text(json.dumps(dict(index='docs/start.md', script_links=['theme.js'])))
    app = App(load(parser().parse_args([])))
    server = make_server(app, '127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    worker = threading.Thread(target=app.watch_loop, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1000, 'height': 600})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#target')
            page.wait_for_function('window.readyCount === 1')
            assert page.locator('#target').evaluate('(el) => el.getBoundingClientRect().top') < 600
            assert page.evaluate('window.mdlive.currentPath') == '/docs/start.md'
            page.evaluate('window.navNode = document.getElementById("theme-nav"); scrollTo(0, 500)')
            before = page.evaluate('scrollY')
            document.write_text(source + '\n\n## Added')
            page.wait_for_function('window.lastHeading === "added"')
            assert page.evaluate('document.getElementById("theme-nav") === window.navNode')
            assert abs(page.evaluate('scrollY') - before) <= 1
            assert page.evaluate('window.readyCount') == 1
            (tmp_path / 'other.md').write_text('# Other')
            page.wait_for_function('window.mdlive.files.includes("/other.md")')
            document.unlink()
            page.wait_for_function('document.getElementById("mdlive-content").textContent.includes("Document not found")')
            document.write_text(source)
            page.wait_for_selector('#target')
            # Disconnect the browser while editing; SSE onopen must fetch current state.
            page.context.set_offline(True)
            document.write_text(source + '\n\n## Offline change')
            time.sleep(.5)
            page.context.set_offline(False)
            page.wait_for_function('window.lastHeading === "offline-change"', timeout=15000)
            # A theme edit forces a full page reload and initializes the theme again.
            theme.write_text(theme.read_text() + '\nwindow.themeRevision = 2;')
            page.wait_for_function('window.themeRevision === 2')
            assert page.evaluate('window.readyCount') == 1
            assert not errors
            browser.close()
    finally:
        app.close()
        server.shutdown()
        server.server_close()
        thread.join(3)
        worker.join(3)


def test_unstyled_page_and_server_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    document = tmp_path / 'README.md'
    document.write_text('# Before restart')
    cfg = load(parser().parse_args(["--theme", "none"]))
    app = App(cfg)
    server = make_server(app, '127.0.0.1', 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{port}/')
            assert page.locator('style, link[rel="stylesheet"], nav').count() == 0
            page.wait_for_selector('#before-restart')
            app.close()
            server.shutdown()
            server.server_close()
            thread.join(3)
            document.write_text('# After restart')
            app = App(cfg)
            server = make_server(app, '127.0.0.1', port)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            page.wait_for_selector('#after-restart', timeout=15000)
            assert page.evaluate('window.mdlive.headings[0].id') == 'after-restart'
            browser.close()
    finally:
        app.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_basic_theme_readability_and_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    document = tmp_path / 'README.md'
    document.write_text('# Reading theme\n\n[Long link](#details) ' + 'https://example.test/' + 'a' * 180 +
                        '\n\n## Details\n\n> A readable quotation.\n\n- First\n- Second\n\n'
                        'Inline `code`.\n\n```\n' + 'long_code_' * 50 + '\n```\n\n'
                        '<table><tr><th>Heading</th><th>Other</th></tr><tr><td>' + 'cell ' * 80 +
                        '</td><td>Value</td></tr></table>\n\n'
                        '<img src="image.svg" alt="Example">')
    (tmp_path / 'image.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="100"><rect width="2000" height="100" fill="blue"/></svg>')
    app = App(load(parser().parse_args([])))
    server = make_server(app, '127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1100, 'height': 800}, color_scheme='dark')
            external = []
            page.on('request', lambda request: external.append(request.url) if not request.url.startswith(base) else None)
            page.goto(base + '/#details')
            assert page.locator('#details').evaluate('(el) => el.getBoundingClientRect().top') < 800
            assert page.locator('body').evaluate('(el) => getComputedStyle(el).fontSize') == '17px'
            assert page.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(255, 255, 255)'
            for width in (1100, 375):
                page.set_viewport_size({'width': width, 'height': 800})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.locator('pre').evaluate('(el) => el.scrollWidth > el.clientWidth')
                assert page.locator('img').evaluate('(el) => el.width <= document.getElementById("mdlive-content").clientWidth')
            page.goto(base + '/')
            page.keyboard.press('Tab')
            assert page.locator('a').evaluate('(el) => el.matches(":focus-visible") && getComputedStyle(el).outlineStyle === "solid"')
            assert page.locator('a').evaluate('(el) => getComputedStyle(el).textDecorationLine') == 'underline'
            # Check actual computed foreground/background pairs, including the accent pair.
            pairs = page.evaluate('''() => {
              const s = getComputedStyle(document.documentElement);
              return [['background', 'text'], ['surface', 'surface-contrast'], ['primary', 'primary-contrast'], ['background', 'link'], ['background', 'quote']]
                .map(pair => pair.map(name => s.getPropertyValue('--mdl-palette-' + name).trim()));
            }''')
            def luminance(color):
                channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
                linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
                return sum(a*b for a, b in zip(linear, (.2126, .7152, .0722)))
            for background, foreground in pairs:
                values = sorted([luminance(background), luminance(foreground)])
                assert (values[1] + .05) / (values[0] + .05) >= 4.5
            page.add_style_tag(content=':root { --mdl-palette-text: var(--mdl-color-purple-90); }')
            assert page.locator('body').evaluate('(el) => getComputedStyle(el).color') == 'rgb(59, 7, 100)'
            document.write_text(document.read_text() + '\n\n## Updated')
            app.changed([document])
            page.wait_for_selector('#updated')
            page.emulate_media(media='print')
            assert page.locator('pre').evaluate('(el) => getComputedStyle(el).whiteSpace') == 'pre-wrap'
            assert page.locator('table').evaluate('(el) => getComputedStyle(el).overflowX') == 'visible'
            assert not external
            browser.close()
    finally:
        app.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.mark.parametrize('theme', ['basic', 'basic-dark', 'basic-dynamic'])
def test_basic_color_modes(tmp_path, monkeypatch, theme):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'README.md').write_text('# Color modes\n\n[Link](#color-modes)\n\n> Quote\n\n```\nCode\n```')
    app = App(load(parser().parse_args(['--theme', theme])))
    server = make_server(app, '127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(color_scheme='light')
            external = []
            page.on('request', lambda request: external.append(request.url) if not request.url.startswith(base) else None)
            page.goto(base)
            page.evaluate('window.modeMarker = true')
            for mode in ('light', 'dark', 'light'):
                page.emulate_media(color_scheme=mode)
                dark = theme == 'basic-dark' or (theme == 'basic-dynamic' and mode == 'dark')
                expected = 'rgb(23, 23, 23)' if dark else 'rgb(255, 255, 255)'
                page.wait_for_function('(expected) => getComputedStyle(document.body).backgroundColor === expected', arg=expected)
                assert page.evaluate('window.modeMarker')
                assert page.locator('body').evaluate('(el) => getComputedStyle(el).fontSize') == '17px'
                assert page.locator('nav, button').count() == 0
                pairs = page.evaluate('''() => {
                  const s = getComputedStyle(document.documentElement);
                  return [['background', 'text'], ['surface', 'surface-contrast'],
                          ['primary', 'primary-contrast'], ['background', 'link'],
                          ['background', 'quote'], ['background', 'focus']]
                    .map(pair => pair.map(name => s.getPropertyValue('--mdl-palette-' + name).trim()));
                }''')
                def luminance(color):
                    channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
                    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
                    return sum(a*b for a, b in zip(linear, (.2126, .7152, .0722)))
                for background, foreground in pairs:
                    low, high = sorted([luminance(background), luminance(foreground)])
                    assert (high + .05) / (low + .05) >= 4.5
            page.emulate_media(media='print', color_scheme='dark')
            assert page.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(255, 255, 255)'
            page.emulate_media(media='screen', color_scheme='dark')
            page.add_style_tag(content=':root { --mdl-palette-text: var(--mdl-color-purple-40); }')
            assert page.locator('body').evaluate('(el) => getComputedStyle(el).color') == 'rgb(216, 180, 254)'
            assert not external
            browser.close()
    finally:
        app.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_composed_theme_script_order_and_live_reload(tmp_path, monkeypatch):
    from test_mdlive import serving

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    document = tmp_path / 'README.md'
    document.write_text('# Composed theme')
    parent_script = tmp_path / 'parent.js'
    parent_script.write_text('window.themeTrace.push("parent linked");')
    child_script = tmp_path / 'child.js'
    child_script.write_text('window.themeTrace.push("child linked");')
    settings = tmp_path / 'config.json'
    settings.write_text(json.dumps({
        'theme': 'child',
        'themes': {
            'parent': {
                'extends': ['basic-dark'],
                'styles': [':root { --mdl-palette-text: var(--mdl-color-purple-40); }'],
                'scripts': ['window.themeTrace = [window.mdlive.headings[0].text];'],
                'script_links': ['parent.js'],
            },
            'child': {
                'extends': ['parent'],
                'scripts': ['window.themeTrace.push("child inline");'],
                'script_links': ['child.js'],
            },
        },
        'scripts': ['window.themeTrace.push("top inline");'],
    }))
    with serving(load(parser().parse_args([])), watcher=True) as (app, base):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base)
            expected = ['Composed theme', 'parent linked', 'child inline', 'child linked', 'top inline']
            assert page.evaluate('window.themeTrace') == expected
            assert page.locator('body').evaluate('(el) => getComputedStyle(el).color') == 'rgb(216, 180, 254)'
            parent_script.write_text('window.themeTrace.push("parent updated");')
            page.wait_for_function('window.themeTrace?.includes("parent updated")')
            assert page.evaluate('window.themeTrace') == [expected[0], 'parent updated', *expected[2:]]
            document.write_text('# Updated document')
            page.wait_for_selector('#updated-document')
            assert page.evaluate('window.themeTrace[0]') == 'Composed theme'
            assert not errors
            browser.close()
