#!/usr/bin/env python3
"""Offline Chinese translation/dictionary coverage and mobile UI regression."""
import json
import os
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright

from test_app import Handler, PREFIX, ROOT


def payload(name, global_name):
    raw = (ROOT / name).read_text()
    return json.loads(raw.removeprefix(f'window.{global_name}=').strip().removesuffix(';'))


def main():
    lessons = payload('content.js', 'NCE_DATA')['lessons']
    translations = payload('translations.js', 'NCE_TRANSLATIONS')
    dictionary = payload('dictionary-data.js', 'NCE_DICTIONARY')
    ids = {cue['id'] for lesson in lessons for cue in lesson['cues']}
    assert len(ids) == 5395 and ids == translations.keys()
    assert sum(value[1] for value in translations.values()) == 775
    assert all(isinstance(value[0], str) and any('\u3400' <= c <= '\u9fff' for c in value[0]) for value in translations.values())
    assert all(isinstance(value, list) and len(value) == 3 and value[1] for value in dictionary.values())
    assert 'handbag' in dictionary and 'take off' in dictionary
    assert translations['b3-042-023-p02'][0] == '让水流把他们带到湖的另一边。'

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
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
            context = browser.new_context(**p.devices['iPhone 13'])
            context.add_init_script('Element.prototype.requestFullscreen=undefined')
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}{PREFIX}', wait_until='networkidle')
            assert page.locator('#showTranslations').is_checked()
            assert page.locator('[data-cue="0"] .cueZh').is_visible()
            assert page.locator('[data-cue="0"] .cueZh').inner_text() == translations[lessons[0]['cues'][0]['id']][0]
            page.locator('#showTranslations').uncheck()
            assert page.locator('[data-cue="0"] .cueZh').is_hidden()
            page.locator('#showTranslations').check()
            page.locator('[data-cue="0"] .wordToken').first.tap()
            assert page.locator('#wordDialog').is_visible()
            assert page.locator('#wordMeanings li').count() > 0
            assert page.locator('#wordContextEnglish').inner_text() == lessons[0]['cues'][0]['text']
            page.locator('#wordSearch').fill('take off')
            page.locator('#wordSearchForm button').tap()
            assert page.locator('#wordMeanings li').count() > 0
            page.locator('#wordSearch').fill('zzzyyyunknownword')
            page.locator('#wordSearchForm button').tap()
            assert '尚未收录' in page.locator('#wordMeanings').inner_text()
            page.locator('#wordClose').tap()
            assert page.locator('#wordDialog').is_hidden()

            page.locator('#openScreen').tap()
            page.locator('#hideTranslation').check()
            assert page.locator('#screenTranslation').is_hidden()
            page.locator('#detailsToggle').tap()
            assert page.locator('#screenContext').is_visible()
            assert page.locator('#screenContext [lang="zh-CN"]').first.is_hidden()
            page.locator('#translationReveal').tap()
            assert page.locator('#screenTranslation').is_visible()
            assert page.locator('#screenContext [lang="zh-CN"]').first.is_visible()
            page.locator('#screenText .wordToken').first.tap()
            assert page.locator('#wordDialog').is_visible()
            assert page.locator('#wordDialog').evaluate('el=>el.parentElement.id') == 'screen'
            page.locator('#wordClose').tap()
            page.locator('#lock').tap()
            assert page.locator('#screenText .wordToken').first.evaluate('el=>getComputedStyle(el).pointerEvents') == 'none'
            page.locator('#lock').tap()
            page.locator('#exitScreen').tap()
            page.wait_for_function('navigator.serviceWorker.controller !== null')
            page.reload(wait_until='networkidle')
            assert page.locator('[data-cue="0"] .cueZh').is_visible()
            assert page.evaluate("async()=>{const c=await caches.open('nce-shell-v7-bilingual-context-20260928');return !!(await c.match('./translations.js'))&&!!(await c.match('./dictionary-data.js'));}")
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
    print(f'PASS: {len(ids)} translations, {len(dictionary)} dictionary entries, {engine} mobile lookup/reveal/lock/offline cache')


if __name__ == '__main__':
    main()
