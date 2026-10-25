"""Run with PLAYWRIGHT_BROWSERS_PATH set when using a custom browser cache."""
import json
import threading
import time

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
    cfg = load(parser().parse_args([]))
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
