import json

from playwright.sync_api import sync_playwright

from mdlive.config import load, parser
from test_mdlive import serving


def test_mode_toggle_cycle_persistence_and_dynamic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'README.md').write_text('# Home\n\n[next](next.md)')
    (tmp_path / 'next.md').write_text('# Next')
    cfg = load(parser().parse_args(['--theme', 'basic-nav']))
    with serving(cfg) as (app, base):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(color_scheme='dark', viewport={'width': 375, 'height': 812})
            page = context.new_page()
            page.goto(base)
            control = page.locator('#mdlive-mode-toggle')
            assert control.inner_text() == 'Dynamic'
            assert control.evaluate('(el) => getComputedStyle(el).position') == 'fixed'
            def background(expected):
                page.wait_for_function('(value) => getComputedStyle(document.body).backgroundColor === value', arg=expected)
            background('rgb(23, 23, 23)')
            control.focus()
            assert control.evaluate('(el) => el.matches(":focus-visible") && getComputedStyle(el).outlineStyle === "solid"')
            page.keyboard.press('Enter')
            assert control.inner_text() == 'Light'
            background('rgb(255, 255, 255)')
            assert page.evaluate('localStorage.getItem("mdlive.color-mode")') == 'light'
            control.click()
            assert control.inner_text() == 'Dark'
            page.emulate_media(color_scheme='light')
            background('rgb(23, 23, 23)')
            page.locator('#mdlive-site-nav a[href="/next.md"]').click()
            page.wait_for_url(base + '/next.md')
            assert control.inner_text() == 'Dark'
            background('rgb(23, 23, 23)')
            control.click()
            assert control.inner_text() == 'Dynamic'
            background('rgb(255, 255, 255)')
            page.emulate_media(color_scheme='dark')
            background('rgb(23, 23, 23)')
            page.reload()
            assert control.inner_text() == 'Dynamic'
            background('rgb(23, 23, 23)')
            for _ in range(3):
                page.evaluate('window.dispatchEvent(new Event("mdlive:update"))')
            assert control.count() == 1
            assert control.get_attribute('aria-label') == 'Color mode: Dynamic. Switch to light.'
            assert control.bounding_box()['y'] + control.bounding_box()['height'] <= page.locator('#mdlive-site-nav a').first.bounding_box()['y']
            page.emulate_media(media='print')
            assert not control.is_visible()
            background('rgb(255, 255, 255)')
            browser.close()


def test_toggle_addon_composition_and_storage_failures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'README.md').write_text('# A custom theme')
    (tmp_path / 'config.json').write_text(json.dumps({
        'theme': 'custom', 'themes': {'custom': {'extends': ['basic', 'mode-toggle']}},
        'styles': [':root { --mdl-palette-link: var(--mdl-color-purple-40); }'],
    }))
    with serving(load(parser().parse_args([]))) as (app, base):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(color_scheme='light')
            # Both reading and writing storage may fail in a restricted browser.
            page.add_init_script('''
                Object.defineProperty(Storage.prototype, 'getItem', {value() { throw Error('blocked'); }});
                Object.defineProperty(Storage.prototype, 'setItem', {value() { throw Error('blocked'); }});
            ''')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base)
            control = page.locator('#mdlive-mode-toggle')
            assert control.inner_text() == 'Dynamic'
            control.click()
            control.click()
            assert control.inner_text() == 'Dark'
            assert page.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(23, 23, 23)'
            assert page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--mdl-palette-link").trim()') == '#d8b4fe'
            assert page.locator('#mdlive-site-nav').count() == 0
            assert not errors
            browser.close()
