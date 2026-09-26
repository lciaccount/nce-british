#!/usr/bin/env python3
"""Regression checks for gesture-authorized audio and delayed/missing seek events.

These controlled cases exercise Safari-like failure paths, not a physical iPhone.
"""
from test_app import *

MEDIA_EDGE_CASES = r'''
Element.prototype.requestFullscreen=undefined;
window.attempts=[];window.seeks=[];window.denyNext=false;
window.dropAllSeeks=false;window.pendingPlay=false;
const play=HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play=function(){
  attempts.push({src:this.src,muted:this.muted});
  if(this.muted||window.denyNext){window.denyNext=false;return Promise.reject(new DOMException('Gesture needed','NotAllowedError'));}
  if(window.pendingPlay)return new Promise(()=>{});
  return play.call(this);
};
const clock=Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,'currentTime');
const firstSeek=new Set();
Object.defineProperty(HTMLMediaElement.prototype,'currentTime',{
  configurable:true,get(){return clock.get.call(this);},set(value){
    seeks.push({src:this.src,value});
    if(window.dropAllSeeks)return;
    if(!firstSeek.has(this.src)){firstSeek.add(this.src);return;}
    clock.set.call(this,value);
  }
});
// Some seek transitions do not dispatch the events that the old player awaited.
for(const type of ['loadedmetadata','seeked'])document.addEventListener(type,e=>e.stopImmediatePropagation(),true);
// Only accelerate the player's watchdog, not successful audio or repeat timing.
const timeout=window.setTimeout;
window.setTimeout=(fn,ms,...args)=>timeout(fn,ms===25000?2000:ms,...args);
'''


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    shots=Path(tempfile.mkdtemp(prefix='nce-safari-controls-'))
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            context.add_init_script(MEDIA_EDGE_CASES)
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}{PREFIX}',wait_until='networkidle')
            assert page.locator('#lessons').is_hidden()
            assert page.locator('#books button').first.bounding_box()['height']<=40
            page.locator('#lessonPicker summary').click()
            assert page.locator('#lessons').is_visible()
            page.locator('[data-lesson="b1-003"]').click()
            assert page.locator('#lessons').is_hidden()
            assert 'Lesson 3' in page.locator('#lessonChoice').inner_text()
            page.locator('#search').fill('coat')
            assert page.locator('#lessons').is_visible()
            page.locator('#search').fill('')
            page.locator('#lessonPicker summary').click()
            for id in ['speed','barSpeed','screenSpeed']:
                assert page.locator('#'+id+' option').count()==31
            page.locator('#barSpeed').select_option('0.85')
            assert page.locator('#speed').input_value()=='0.85'
            page.locator('[data-cue="0"] [data-action="play"]').click()
            page.wait_for_function('document.querySelector("#playStatus").textContent.includes("循环中")',timeout=6000)
            page.wait_for_function('document.querySelector("#audio").currentTime>=NCE_DATA.lessons[1].cues[0].start')
            assert page.evaluate('document.querySelector("#audio").playbackRate')==.85
            assert page.evaluate('seeks.length')>=2
            page.locator('#barSpeed').select_option('1.15')
            assert page.evaluate('document.querySelector("#audio").playbackRate')==1.15
            page.locator('#openScreen').click()
            assert page.locator('#screenSpeed').input_value()=='1.15'
            page.locator('#screenSpeed').select_option('1.30')
            assert page.locator('#barSpeed').input_value()=='1.30'
            page.wait_for_function('document.querySelector("#screenStatus").textContent.includes("循环中")')
            page.locator('#exitScreen').click()
            assert page.evaluate('attempts.every(x=>!x.muted)')
            print('PASS: all starts request audible playback, ignored first seek and missing metadata/seeked events recover, main/fullscreen speeds synchronize',flush=True)

            page.evaluate('denyNext=true')
            page.locator('[data-cue="0"] [data-action="play"]').click()
            page.wait_for_function('document.querySelector("#playStatus").textContent.includes("授权")')
            page.locator('#pause').click()
            page.wait_for_function('document.querySelector("#playStatus").textContent.includes("循环中")')
            page.locator('#pause').click()
            page.evaluate('dropAllSeeks=true')
            page.locator('[data-cue="6"] [data-action="play"]').click()
            page.wait_for_function('document.querySelector("#playStatus").textContent.includes("加载失败")',timeout=5000)
            assert page.evaluate('document.querySelector("#audio").paused')
            page.evaluate('dropAllSeeks=false;pendingPlay=true')
            page.locator('[data-cue="6"] [data-action="play"]').click()
            page.wait_for_function('document.querySelector("#playStatus").textContent.includes("加载失败")',timeout=5000)
            page.locator('[data-cue="6"] [data-action="play"]').click()
            page.locator('#pause').click()
            page.wait_for_timeout(2200)
            assert page.locator('#playStatus').inner_text()=='已暂停'
            page.evaluate('pendingPlay=false')
            page.locator('[data-book="4"]').click()
            page.locator('[data-cue="0"] [data-action="play"]').click()
            page.locator('[data-book="1"]').click()
            page.locator('[data-cue="0"] [data-action="play"]').click()
            page.wait_for_function('document.querySelector("#playStatus").textContent.includes("循环中")',timeout=6000)
            assert '/b1/001.mp3' in page.evaluate('document.querySelector("#audio").src')
            page.locator('#pause').click()
            print('PASS: permission errors allow retry; ignored seeks and pending play time out; stop/switch cancel stale callbacks',flush=True)
            for width,height in [(320,568),(390,844),(844,390),(1280,900)]:
                page.set_viewport_size({'width':width,'height':height})
                for expanded in [False,True]:
                    page.locator('#lessonPicker').evaluate('(el,open)=>el.open=open',expanded)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,height,expanded)
                    bar=page.locator('#barSpeed').bounding_box()
                    assert bar['x']>=0 and bar['x']+bar['width']<=width and bar['y']+bar['height']<=height,(width,bar)
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#lessonPicker').evaluate('el=>el.open=false')
            page.evaluate('scrollTo(0,0)')
            page.screenshot(path=str(shots/'collapsed.png'))
            page.locator('#lessonPicker summary').click()
            page.screenshot(path=str(shots/'expanded.png'))
            page.reload(wait_until='networkidle')
            assert page.locator('#barSpeed').input_value()=='1.30'
            assert page.locator('#lessons').is_hidden()
            assert not errors,errors
            print('PASS: compact tabs, collapse/select/search, 31 speeds, persisted rate and all mobile/desktop widths',flush=True)
            browser.close()
    finally:server.shutdown()
    print('Screenshots:',shots)

if __name__=='__main__':main()
