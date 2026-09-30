#!/usr/bin/env python3
"""Conservative contextual hinting and the human listening review queue."""
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(ROOT)))
    Thread(target=server.serve_forever, daemon=True).start()
    engine = os.environ.get('NCE_TEST_ENGINE', 'chromium')
    try:
        with sync_playwright() as p:
            options = {'headless': True}
            if engine == 'chromium':
                options['args'] = ['--no-sandbox']
            if engine == 'webkit' and os.environ.get('NCE_WEBKIT_EXECUTABLE'):
                options['executable_path'] = os.environ['NCE_WEBKIT_EXECUTABLE']
            browser = getattr(p, engine).launch(**options)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            url = f'http://127.0.0.1:{server.server_port}'
            page.goto(url + '/alignment-review.html', wait_until='domcontentloaded')
            page.wait_for_function("document.querySelectorAll('.item').length === 21")
            assert '245' in page.locator('#count').inner_text()
            assert page.locator('.item.high').count() == 21
            page.locator('#filter').select_option('all')
            assert page.locator('.item').count() == 245
            page.locator('#filter').select_option('high')
            first = page.locator('.item').first
            first.locator('[data-action="play"]').click()
            assert '#t=' in page.locator('#audio').get_attribute('src')
            page.on('dialog', lambda dialog: dialog.accept('首尾已试听，测试记录'))
            first.locator('[data-action="accept"]').click()
            assert page.locator('.item').count() == 20
            page.locator('#filter').select_option('done')
            assert page.locator('.item').count() == 1
            assert '测试记录' in page.locator('.item .state').inner_text()
            page.goto(url + '/translation-review.html', wait_until='domcontentloaded')
            page.wait_for_function("document.querySelectorAll('.item').length === 25")
            assert '775' in page.locator('#count').inner_text()
            page.locator('#search').fill('b3-030-013-p02')
            assert '完整原句' in page.locator('#queue').inner_text()
            page.locator('#search').fill('')
            page.locator('.item').first.locator('textarea').fill('测试校对译文。')
            page.locator('.item').first.locator('[data-action="save"]').click()
            page.locator('#filter').select_option('done')
            assert page.locator('.item').count() == 1
            assert page.locator('.item textarea').input_value() == '测试校对译文。'
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
    print(f'PASS {engine}: 245 audio and 775 translation review queues with local decision recording')


if __name__ == '__main__':
    main()
