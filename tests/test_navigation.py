from urllib.parse import quote
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

from mdlive.config import load, parser
from test_mdlive import serving


def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    document = tmp_path / 'README.md'
    document.write_text('# Home\n\n' + '\n\n'.join('A readable paragraph.' for _ in range(150)))
    return document


def test_navigation_tree_labels_and_active_paths(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    files = ['README.md', 'readme.markdown', 'guide_folder/README.MD',
             'guide_folder/intro-page.md', 'guide_folder/deep_notes/setup.markdown',
             'folder-10/page.md', 'folder-2/page.md', 'page-10.md', 'page-2.md',
             'café & API.md', '<img src=x onerror=alert(1)>.md', '__proto__/safe.md']
    for name in files:
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        if not file.exists():
            file.write_text('# ' + file.stem)
    (tmp_path / 'empty-folder').mkdir()
    (tmp_path / 'ignore.txt').write_text('not Markdown')
    with serving(load(parser().parse_args(['--theme', 'basic-nav']))) as (app, base):
        for asset, mime in [('basic-nav.js', 'text/javascript'), ('basic-nav.css', 'text/css')]:
            with urlopen(base + '/__mdlive/themes/' + asset) as response:
                assert response.headers.get_content_type() == mime
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1400, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base)
            nav = page.locator('#mdlive-site-nav')
            assert nav.get_attribute('aria-label') == 'Site navigation'
            assert nav.locator(':scope > ul > li > :first-child').all_text_contents() == [
                'Home', 'Folder 2', 'Folder 10', 'Guide folder', 'Proto',
                '<img src=x onerror=alert(1)>', 'Café & API', 'Page 2', 'Page 10', 'Readme']
            assert nav.locator('a[aria-current="page"]').get_attribute('href') == '/README.md'
            guide = nav.locator('a[href="/guide_folder/README.MD"]')
            assert guide.count() == 1
            assert guide.inner_text() == 'Guide folder'
            assert guide.locator('..').locator(':scope > ul > li > :first-child').all_text_contents() == ['Deep notes', 'Intro page']
            assert nav.locator('img, button, details').count() == 0
            assert 'Empty folder' not in nav.inner_text()
            assert 'Ignore' not in nav.inner_text()
            assert nav.locator('ul').first.evaluate('(el) => getComputedStyle(el).listStyleType') == 'none'
            guide.click()
            page.wait_for_url(base + '/guide_folder/README.MD')
            assert page.locator('a[aria-current="page"]').inner_text() == 'Guide folder'
            page.locator('#mdlive-site-nav a[href="/guide_folder/deep_notes/setup.markdown"]').click()
            page.wait_for_url(base + '/guide_folder/deep_notes/setup.markdown')
            assert page.locator('a[aria-current="page"]').inner_text() == 'Setup'
            encoded = '/' + quote('café & API.md', safe='/')
            page.goto(base + encoded)
            assert page.locator('#mdlive-site-nav a[aria-current="page"]').get_attribute('href') == encoded
            assert page.locator('#mdlive-site-nav a[aria-current="page"]').inner_text() == 'Café & API'
            assert not errors
            browser.close()


def test_navigation_layout_updates_and_fallback(tmp_path, monkeypatch):
    document = setup(tmp_path, monkeypatch)
    folder = tmp_path / 'guides'
    folder.mkdir()
    for i in range(45):
        (folder / f'page-{i}.md').write_text(f'# Page {i}')
    (folder / ('long-label-' * 16 + '.md')).write_text('# Long label')
    cfg = load(parser().parse_args(['--theme', 'basic-nav']))
    with serving(cfg) as (app, base):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 800})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base)
            nav = page.locator('#mdlive-site-nav')
            assert nav.evaluate('(el) => el.scrollHeight > el.clientHeight')
            assert nav.evaluate('(el) => getComputedStyle(el).position') == 'sticky'
            assert nav.bounding_box()['x'] < page.locator('main').bounding_box()['x']
            page.keyboard.press('Tab')
            assert page.locator('#mdlive-site-nav a').first.evaluate('(el) => el.matches(":focus-visible") && getComputedStyle(el).outlineStyle === "solid"')
            target = nav.locator('a[href="/guides/page-20.md"]')
            target.focus()
            nav.evaluate('(el) => el.scrollTop = 300')
            saved_scroll = nav.evaluate('(el) => el.scrollTop')
            page.evaluate('window.savedLink = document.activeElement; window.savedNav = document.getElementById("mdlive-site-nav")')
            for _ in range(3):
                page.evaluate('window.dispatchEvent(new Event("mdlive:update"))')
            assert page.evaluate('document.activeElement === window.savedLink')
            document.write_text('# Updated\n\n' + 'Content\n\n' * 150)
            app.changed([document])
            page.wait_for_selector('#updated')
            assert page.evaluate('document.activeElement === window.savedLink')
            added = folder / 'zzz-added.md'
            added.write_text('# Added')
            app.changed([added])
            page.wait_for_selector('#mdlive-site-nav a[href="/guides/zzz-added.md"]')
            assert page.evaluate('document.activeElement.getAttribute("href")') == '/guides/page-20.md'
            assert nav.evaluate('(el) => el.scrollTop') == saved_scroll
            assert page.evaluate('document.getElementById("mdlive-site-nav") === window.savedNav')
            added.unlink()
            app.changed([added])
            page.wait_for_selector('#mdlive-site-nav a[href="/guides/zzz-added.md"]', state='detached')
            document.unlink()
            app.changed([document])
            page.wait_for_function('!document.querySelector("#mdlive-site-nav [aria-current]")')
            assert page.locator('main').inner_text().startswith('Document not found')
            document.write_text('# Restored')
            app.changed([document])
            page.wait_for_selector('#mdlive-site-nav a[aria-current="page"]')
            assert page.locator('#mdlive-site-nav').count() == 1
            assert page.locator('.mdlive-nav-layout').count() == 1
            for mode, expected in [('dark', 'rgb(23, 23, 23)'), ('light', 'rgb(255, 255, 255)')]:
                page.emulate_media(color_scheme=mode)
                page.wait_for_function('(value) => getComputedStyle(document.body).backgroundColor === value', arg=expected)
                active = nav.locator('a[aria-current="page"]')
                assert active.evaluate('(el) => getComputedStyle(el).backgroundColor') == ('rgb(147, 197, 253)' if mode == 'dark' else 'rgb(0, 95, 204)')
            for width in [1023, 375]:
                page.set_viewport_size({'width': width, 'height': 812})
                assert nav.evaluate('(el) => getComputedStyle(el).position') == 'static'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert nav.bounding_box()['y'] + nav.bounding_box()['height'] <= page.locator('main').bounding_box()['y']
            page.emulate_media(media='print')
            assert nav.evaluate('(el) => getComputedStyle(el).display') == 'none'
            assert page.locator('.mdlive-nav-layout').evaluate('(el) => getComputedStyle(el).display') == 'block'
            assert not errors
            no_js = browser.new_context(java_script_enabled=False)
            fallback = no_js.new_page()
            fallback.goto(base)
            assert fallback.locator('.mdlive-nav-layout, #mdlive-site-nav').count() == 0
            assert fallback.locator('main').is_visible()
            browser.close()
