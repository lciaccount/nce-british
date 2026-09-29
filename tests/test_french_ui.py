#!/usr/bin/env python3
"""Main-page visual/interaction regression for the french-4000-style layout."""
import os
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright

from test_app import Handler, PREFIX, ROOT


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    Thread(target=server.serve_forever, daemon=True).start()
    engine = os.environ.get('NCE_TEST_ENGINE', 'chromium')
    try:
        with sync_playwright() as playwright:
            options = {'headless': True}
            if engine == 'chromium':
                options['args'] = ['--no-sandbox']
            if engine == 'webkit' and os.environ.get('NCE_WEBKIT_EXECUTABLE'):
                options['executable_path'] = os.environ['NCE_WEBKIT_EXECUTABLE']
            browser = getattr(playwright, engine).launch(**options)
            page = browser.new_page(**playwright.devices['iPhone 13'])
            page.add_init_script('Element.prototype.requestFullscreen=undefined')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}{PREFIX}', wait_until='networkidle')

            assert page.locator('#mainControls').is_hidden()
            assert page.locator('#books button').count() == 4
            assert page.locator('#lessonPicker').get_attribute('open') is None
            assert page.evaluate('document.querySelector(".topbar").getBoundingClientRect().height < 250')
            assert page.evaluate('document.querySelector(".cue").getBoundingClientRect().top < innerHeight - document.querySelector("#playerBar").getBoundingClientRect().height')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('#pause').inner_text() == '▶ 播放'
            assert page.locator('#previousCue').is_disabled()

            page.locator('#mobileSettingsBtn').tap()
            assert page.locator('#mainControls').is_visible()
            assert page.locator('#mobileSettingsBtn').get_attribute('aria-expanded') == 'true'
            page.locator('#speed').select_option('1.25')
            page.locator('#mobileSettingsBtn').tap()
            assert page.locator('#mainControls').is_hidden()
            assert page.locator('#barSpeed').input_value() == '1.25'

            page.locator('#search').fill('handbag')
            assert page.locator('#lessonPicker').get_attribute('open') is not None
            page.locator('#clearSearch').tap()
            assert page.locator('#search').input_value() == ''
            page.locator('#lessonPicker summary').tap()
            page.locator('[data-cue="0"] [data-action="mastered"]').tap()
            assert page.locator('#progressCount').inner_text() == '1'
            page.locator('#nextCue').tap()
            assert page.locator('[data-cue="1"]').get_attribute('class').find('current') >= 0
            assert not page.locator('#previousCue').is_disabled()
            page.locator('#pause').tap()

            page.locator('#theme').tap()
            assert page.locator('body').get_attribute('class').find('dark') >= 0
            assert page.locator('#themeColorMeta').get_attribute('content') == '#111111'
            page.locator('#theme').tap()
            assert page.locator('#themeColorMeta').get_attribute('content') == '#f7f7f7'

            page.set_viewport_size({'width': 1280, 'height': 900})
            assert page.locator('#mainControls').is_visible()
            assert page.evaluate('document.querySelector(".workspace").getBoundingClientRect().width > document.querySelector(".lesson").getBoundingClientRect().width')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
    print(f'PASS {engine}: compact French-style layout, settings, search, progress, transport, theme and responsive widths')


if __name__ == '__main__':
    main()
