#!/usr/bin/env python3
"""Preserve learning records and old backups when sentences become fragments."""
from test_app import *


def main():
    data=json.loads((ROOT/'content.js').read_text().removeprefix('window.NCE_DATA=').strip().removesuffix(';'))
    lesson=next(l for l in data['lessons'] if any(c['parts']>1 for c in l['cues']))
    first=next(c for c in lesson['cues'] if c['parts']>1)
    parts=[c for c in lesson['cues'] if c['sourceId']==first['sourceId']]
    old={'lesson':lesson['id'],'index':first['sourceIndex'], 'speed':1.25,
         'favorites':[first['sourceId']], 'mastered':[first['sourceId']],
         'corrections':{first['sourceId']:{'start':first['start']+.1,'end':parts[-1]['end']-.1}}}
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':390,'height':844},has_touch=True,is_mobile=True)
            context.add_init_script('''if(!localStorage.getItem('nce-study-v1'))localStorage.setItem('nce-study-v1',%s)''' % json.dumps(json.dumps(old)))
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}{PREFIX}',wait_until='networkidle')
            row=page.locator('.cue.current')
            assert first['text'] in row.inner_text()
            assert '片段 1/' in row.inner_text()
            saved=page.evaluate("JSON.parse(localStorage.getItem('nce-study-v1'))")
            assert saved['cueId']==first['id'] and saved['dataVersion']==3
            assert saved['favorites']==saved['mastered']==[c['id'] for c in parts]
            assert saved['corrections']==old['corrections']
            assert page.locator('#barSpeed').input_value()=='1.25'
            row.locator('summary').tap()
            assert row.locator('details p').inner_text()==' '.join(c['text'] for c in parts)
            row.locator('[data-action="timing"]').tap()
            assert float(page.locator('#timingStart').input_value())==first['start'], 'Whole-sentence correction must not apply to fragment'
            page.locator('#closeTiming').tap()
            row.locator('[data-action="screen"]').tap()
            assert '片段 1/' in page.locator('#cueLabel').inner_text()
            page.locator('#detailsToggle').tap()
            assert ' '.join(c['text'] for c in parts) in page.locator('#screenContext').inner_text()
            page.wait_for_function('document.querySelector("#screenStatus").textContent.includes("循环中")')
            page.locator('#exitScreen').tap()
            page.reload(wait_until='networkidle')
            assert first['text'] in page.locator('.cue.current').inner_text()
            # Restoring an old export must perform the same ID migration.
            page.locator('#importProgress').set_input_files({'name':'old.json','mimeType':'application/json','buffer':json.dumps({'version':1,**old}).encode()})
            page.wait_for_function('document.querySelector("#backupStatus").textContent.includes("已恢复")')
            restored=page.evaluate("JSON.parse(localStorage.getItem('nce-study-v1'))")
            assert restored['favorites']==[c['id'] for c in parts]
            assert restored['corrections']==old['corrections']
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors,errors
            browser.close()
        print('PASS: original text expansion, segment playback/context, legacy favorite/mastery/index migration, old backup restore, calibration isolation and mobile layout')
    finally:server.shutdown()


if __name__=='__main__':main()
