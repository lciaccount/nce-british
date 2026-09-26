#!/usr/bin/env python3
"""Chromium smoke/regression tests under the same subpath as GitHub Pages."""
import json
import tempfile
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
PREFIX='/nce-british/'

class Handler(SimpleHTTPRequestHandler):
    delay=0
    fail=''
    def do_GET(self):
        if not self.path.startswith(PREFIX):self.send_error(404);return
        if self.path.endswith('.mp3'):
            time.sleep(type(self).delay)
            if type(self).fail and type(self).fail in self.path:
                self.send_error(503);return
        self.path='/'+self.path[len(PREFIX):]
        try:super().do_GET()
        except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self,*_):pass

def touch(page,start,end):
    cdp=page.context.new_cdp_session(page)
    cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':start[0],'y':start[1]}]})
    for i in range(1,8):
        cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':start[0]+(end[0]-start[0])*i/7,'y':start[1]+(end[1]-start[1])*i/7}]})
        page.wait_for_timeout(25)
    cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]});cdp.detach();page.wait_for_timeout(250)

def main():
    source=json.loads((ROOT/'content.js').read_text().removeprefix('window.NCE_DATA=').strip().removesuffix(';'))
    assert len(source['lessons'])==276
    assert all(l.get('aligned') for l in source['lessons'])
    assert sum(len(l['cues']) for l in source['lessons'])==4670
    assert any(c['text']=='Excuse me!' for c in source['lessons'][0]['cues'])
    assert len({c['id'] for l in source['lessons'] for c in l['cues']})==sum(len(l['cues']) for l in source['lessons'])
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    shots=Path(tempfile.mkdtemp(prefix='nce-browser-'))
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            context.add_init_script('Element.prototype.requestFullscreen=undefined; window.playEvents=[]; document.addEventListener("playing",e=>playEvents.push({time:e.target.currentTime,src:e.target.src}),true);')
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}{PREFIX}',wait_until='networkidle')
            assert page.locator('#books button').count()==4
            assert page.locator('#lessons button').count()==72
            page.locator('[data-book="4"]').click()
            assert page.locator('#lessons button').count()==48
            assert page.locator('#lessonLabel').inner_text().startswith('BOOK 4')
            page.locator('[data-book="1"]').click()
            assert page.locator('#speed option').count()==31
            page.locator('#search').fill('handbag')
            assert page.locator('#lessons button').count()>0
            page.locator('#search').fill('')
            page.locator('[data-cue="0"] [data-action="favorite"]').click()
            page.locator('#onlyFavorites').check()
            assert page.locator('#lessons button').count()==1
            page.locator('#onlyFavorites').uncheck()
            for width,height in [(320,568),(390,844),(844,390),(1280,900)]:
                page.set_viewport_size({'width':width,'height':height})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(shots/'normal.png'),full_page=True)
            page.locator('#openScreen').click()
            assert page.locator('#swipeIntro').is_visible()
            page.wait_for_function('document.querySelector("#audio").currentTime>0 && !document.querySelector("#audio").paused')
            page.wait_for_function('playEvents.length>0')
            assert page.evaluate('playEvents[0].time')>=source['lessons'][0]['cues'][0]['start']-.06
            page.wait_for_timeout(1600)
            assert page.locator('#swipeIntro').is_hidden()
            original=page.locator('#screenText').inner_text()
            page.screenshot(path=str(shots/'before-swipe.png'))
            touch(page,(190,440),(190,260))
            assert page.locator('#screenText').inner_text()!=original
            page.locator('#screenSpeed').select_option('0.75')
            assert page.evaluate('document.querySelector("#audio").playbackRate')==.75
            page.locator('#lock').click()
            assert page.locator('#exitScreen').is_hidden()
            locked=page.locator('#screenText').inner_text()
            touch(page,(190,440),(190,260))
            assert page.locator('#screenText').inner_text()!=locked
            page.keyboard.press('Escape')
            assert page.locator('#screen').is_visible()
            page.locator('#lock').click()
            page.locator('.screenSettings details').nth(1).evaluate('el=>el.open=true')
            page.locator('#fontSize').fill('150')
            page.locator('#hideText').check()
            assert page.locator('#screenText').is_hidden()
            page.locator('#reveal').click()
            assert page.locator('#screenText').is_visible()
            page.locator('#hideText').uncheck()
            for width,height in [(320,568),(390,844),(844,390),(1280,900)]:
                page.set_viewport_size({'width':width,'height':height})
                assert page.locator('#screen').evaluate('el=>el.scrollWidth<=el.clientWidth+1 && el.scrollHeight<=el.clientHeight+1'),(width,height)
            page.set_viewport_size({'width':390,'height':844})
            page.locator('.screenSettings details').nth(1).evaluate('el=>el.open=false')
            page.screenshot(path=str(shots/'screen.png'))
            page.locator('#screenPlayback').evaluate('el=>el.open=true')
            page.locator('#autoNext').check()
            page.locator('#screenRepeats').fill('2')
            page.locator('#rangeStart').fill('2')
            page.locator('#rangeEnd').fill('3')
            page.locator('#screenSpeed').select_option('2.00')
            page.locator('#screenForm button').click()
            page.wait_for_function('document.querySelector("#screenStatus").textContent.includes("本轮已完成")',timeout=30000)
            assert page.locator('#screenCounter').inner_text().startswith('3 /')
            page.locator('#exitScreen').click()
            assert page.locator('#screen').is_hidden()
            print('PASS: books/search/favorites, native MP3 sentence loop, touch, lock, speed/font, recall, auto range completion and layouts',flush=True)
            page.locator('[data-cue="0"] [data-action="timing"]').click()
            page.locator('#timingStart').fill('9999')
            page.locator('#timingForm button').first.click()
            assert page.locator('#timingError').inner_text()
            page.locator('#resetTiming').click()
            page.wait_for_function('navigator.serviceWorker.controller!==null')
            page.locator('#downloadForm').evaluate('el=>el.parentElement.open=true')
            page.locator('#downloadEnd').select_option('b1-003')
            page.locator('#download').click()
            page.wait_for_function('document.querySelector("#downloadStatus").textContent.includes("下载完成")',timeout=30000)
            assert page.evaluate('''async()=>{const c=await caches.open('nce-audio-v1');return !!(await c.match('./audio/b1/003.mp3'));}''')
            Handler.delay=.7
            page.locator('#downloadStart').select_option('b1-005')
            page.locator('#downloadEnd').select_option('b1-009')
            page.locator('#download').click()
            page.wait_for_function('document.querySelector("#downloadProgress").value>=1')
            page.locator('#cancelDownload').click()
            page.wait_for_function('document.querySelector("#downloadStatus").textContent.includes("已取消")')
            assert page.evaluate('''async()=>!!(await (await caches.open('nce-audio-v1')).match('./audio/b1/005.mp3'))''')
            Handler.delay=0;Handler.fail='/009.mp3'
            page.locator('#download').click()
            page.wait_for_function('document.querySelector("#downloadStatus").textContent.includes("下载未完成")')
            Handler.fail=''
            page.locator('#download').click()
            page.wait_for_function('document.querySelector("#downloadStatus").textContent.includes("下载完成")')
            print('PASS: cancellation preserves cached lessons; network failure stops honestly and retry fills missing audio',flush=True)
            context.set_offline(True)
            page.reload(wait_until='networkidle')
            assert page.locator('#fontSize').input_value()=='150'
            page.locator('#lessonPicker summary').click()
            page.locator('[data-lesson="b1-003"]').click()
            page.locator('[data-cue="0"] [data-action="play"]').click()
            page.wait_for_function('document.querySelector("#audio").currentTime>0&&!document.querySelector("#audio").paused',timeout=10000)
            result=page.evaluate('''async()=>{const r=await fetch('./audio/b1/003.mp3',{headers:{Range:'bytes=0-63'}});return [r.status,(await r.arrayBuffer()).byteLength];}''')
            assert result==[206,64],result
            assert not errors,errors
            print('PASS: calibration validation, exact lesson-range download, offline reload/playback, saved settings and byte ranges; no JS errors',flush=True)
            browser.close()
    finally:server.shutdown()
    print('Screenshots:',shots)

if __name__=='__main__':main()
