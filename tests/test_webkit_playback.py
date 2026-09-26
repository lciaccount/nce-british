#!/usr/bin/env python3
"""Real WebKit playback with Playwright's iPhone profile (not iOS hardware)."""
import os
from test_app import *

class OfflineOrigin(Handler):
    unavailable=False
    blocked=[]
    def do_GET(self):
        if type(self).unavailable:
            type(self).blocked.append(self.path)
            self.send_error(503)
            return
        super().do_GET()


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(OfflineOrigin,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            options={'headless':True}
            if os.environ.get('NCE_WEBKIT_EXECUTABLE'):
                options['executable_path']=os.environ['NCE_WEBKIT_EXECUTABLE']
            browser=p.webkit.launch(**options)
            context=browser.new_context(**p.devices['iPhone 13'])
            context.add_init_script('''Element.prototype.requestFullscreen=undefined;window.playEvents=[];
              document.addEventListener("playing",e=>playEvents.push({time:e.target.currentTime,src:e.target.src}),true);
              window.loopBacks=0;let lastMediaTime=0;
              setInterval(()=>{const a=document.querySelector('#audio');if(a){if(a.currentTime<lastMediaTime-.5)loopBacks++;lastMediaTime=a.currentTime;}},50);
            ''')
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}{PREFIX}',wait_until='networkidle')
            page.locator('[data-cue="0"] [data-action="play"]').tap()
            # WebKit may emit playing only once while the actual media timeline loops.
            try:page.wait_for_function('loopBacks>=1 && document.querySelector("#audio").currentTime>NCE_DATA.lessons[0].cues[0].start+.15 && !document.querySelector("#audio").paused',timeout=20000)
            except Exception:
                print(page.evaluate('''()=>{const a=document.querySelector('#audio');return {status:document.querySelector('#playStatus').textContent,events:playEvents,time:a.currentTime,paused:a.paused,ready:a.readyState,seeking:a.seeking,error:a.error?.message,rate:a.playbackRate};}'''),flush=True)
                raise
            assert page.evaluate('playEvents[0].time>=NCE_DATA.lessons[0].cues[0].start-.06')
            assert not page.evaluate('document.querySelector("#audio").muted')
            page.locator('#barSpeed').select_option('1.25')
            page.locator('[data-cue="6"] [data-action="play"]').tap()
            page.wait_for_function('document.querySelector("#audio").currentTime>=NCE_DATA.lessons[0].cues[6].start && !document.querySelector("#audio").paused')
            assert page.evaluate('document.querySelector("#audio").playbackRate')==1.25
            page.locator('#openScreen').tap()
            page.locator('#screenPlayback').evaluate('el=>el.open=true')
            page.locator('#autoNext').check()
            page.locator('#screenRepeats').fill('2')
            page.locator('#rangeStart').fill('2')
            page.locator('#rangeEnd').fill('3')
            page.locator('#screenForm button').tap()
            page.wait_for_function('document.querySelector("#screenStatus").textContent.includes("本轮已完成")',timeout=20000)
            assert page.locator('#screenCounter').inner_text().startswith('3 /')
            page.locator('#exitScreen').tap()
            print('PASS WebKit iPhone profile: cold start at sentence boundary, audible loops, seeking, speed and full-screen two-repeat range',flush=True)
            page.wait_for_function('navigator.serviceWorker.controller!==null')
            page.locator('#downloadForm').evaluate('el=>el.parentElement.open=true')
            page.locator('#downloadEnd').select_option('b1-003')
            page.locator('#download').tap()
            page.wait_for_function('document.querySelector("#downloadStatus").textContent.includes("下载完成")')
            # WPE's set_offline() produced internal navigation errors here.
            # Use an unavailable origin and require resources from SW cache.
            OfflineOrigin.unavailable=True
            page.reload(wait_until='networkidle')
            page.locator('#lessonPicker summary').tap()
            page.locator('[data-lesson="b1-003"]').tap()
            page.locator('[data-cue="0"] [data-action="play"]').tap()
            try:page.wait_for_function('document.querySelector("#playStatus").textContent.includes("循环中")',timeout=15000)
            except Exception:
                print('Unavailable origin requests:',OfflineOrigin.blocked,flush=True)
                print(page.locator('#playStatus').inner_text(),flush=True)
                raise
            response=page.evaluate('''async()=>{const r=await fetch('./audio/b1/003.mp3',{headers:{Range:'bytes=0-63'}});return [r.status,(await r.arrayBuffer()).byteLength];}''')
            assert response==[206,64],response
            assert not errors,errors
            print('PASS WebKit: unavailable-origin reload and cached cold sentence playback; MP3 range response',flush=True)
            browser.close()
    finally:server.shutdown()

if __name__=='__main__':main()
