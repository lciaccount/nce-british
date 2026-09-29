#!/usr/bin/env python3
"""Real generated audio in a complete two-lesson fixture, in Chromium or WebKit.

The fixture allows UI/playback regression while the rest of the catalog builds.
It does NOT certify full-corpus coverage; test_voice_assets.py does that separately.
"""
import os
from test_app import *


class VoiceFixture(Handler):
    catalog=None
    delay_audio=0
    fail_audio=False
    def do_GET(self):
        if self.path==PREFIX+'voice-index.json':
            body=json.dumps(self.catalog,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        if self.path.endswith('.m4a'):
            if self.fail_audio:self.send_error(503);return
            time.sleep(self.delay_audio)
        super().do_GET()


def main():
    source=json.loads((ROOT/'content.js').read_text().removeprefix('window.NCE_DATA=').strip().removesuffix(';'))
    catalog=json.loads((ROOT/'voice-index.json').read_text())
    ids=[c['id'] for l in source['lessons'][:2] for c in l['cues']]
    keys={f"{v['id']}/{catalog['cues'][id]}" for id in ids for v in catalog['voices']}
    assert all(k in catalog['assets'] and (ROOT/'audio'/'tts'/f'{k}.m4a').is_file() for k in keys), 'Generate six voices for the first two lessons before running this fixture'
    VoiceFixture.catalog={**catalog,'ready':True,'cues':{id:catalog['cues'][id] for id in ids},'assets':{k:catalog['assets'][k] for k in keys},'expectedAssets':len(keys)}
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(VoiceFixture,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    shots=Path(tempfile.mkdtemp(prefix='nce-six-voices-ui-'))
    engine=os.environ.get('NCE_TEST_ENGINE','chromium')
    try:
        with sync_playwright() as p:
            options={'headless':True}
            if engine=='webkit' and os.environ.get('NCE_WEBKIT_EXECUTABLE'):options['executable_path']=os.environ['NCE_WEBKIT_EXECUTABLE']
            if engine=='chromium':options['args']=['--no-sandbox']
            browser=getattr(p,engine).launch(**options)
            context=browser.new_context(**p.devices['iPhone 13'])
            context.add_init_script('Element.prototype.requestFullscreen=undefined;window.started=[];document.addEventListener("playing",e=>started.push(e.target.src),true);')
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}{PREFIX}',wait_until='networkidle')
            assert page.locator('#voiceMode option').count()==10
            for v in catalog['voices']:
                page.locator('#mobileSettingsBtn').tap()
                page.locator('#voiceMode').select_option(v['id'])
                page.locator('#mobileSettingsBtn').tap()
                page.locator('[data-cue="0"] [data-action="play"]').tap()
                try:page.wait_for_function('document.querySelector("#playStatus").textContent.includes("循环中")')
                except Exception:
                    print(page.evaluate('''()=>{const a=document.querySelector('#audio');return {status:document.querySelector('#playStatus').textContent,src:a.src,ready:a.readyState,time:a.currentTime,error:a.error?.message,codec:a.canPlayType('audio/mp4; codecs="mp4a.40.2"')};}'''),flush=True)
                    raise
                assert f"/tts/{v['id']}/" in page.locator('#audio').get_attribute('src')
                assert not page.evaluate('document.querySelector("#audio").muted')
                page.wait_for_function('document.querySelector("#audio").currentTime>.15')
                page.locator('#pause').tap()
            print('PASS: all six actual AAC voices play audibly',flush=True)
            page.locator('#mobileSettingsBtn').tap()
            page.locator('#voiceMode').select_option('gb-cycle')
            page.locator('#mobileSettingsBtn').tap()
            page.locator('#barSpeed').select_option('2.00')
            page.locator('#openScreen').tap()
            assert page.locator('#screenVoice').input_value()=='gb-cycle'
            page.wait_for_function('started.some(s=>s.includes("gb-libby")) && document.querySelector("#audio").src.includes("gb-libby")',timeout=20000)
            page.locator('#screenPause').tap()
            page.locator('#screenVoice').select_option('us-cycle')
            page.locator('#screenPause').tap()
            page.wait_for_function('document.querySelector("#audio").src.includes("us-aria") && !document.querySelector("#audio").paused',timeout=20000)
            page.locator('#screenPause').tap()
            page.locator('#screenPlayback').evaluate('el=>el.open=true')
            page.locator('#autoNext').check()
            page.locator('#screenRepeats').fill('2')
            page.locator('#rangeStart').fill('2')
            page.locator('#rangeEnd').fill('3')
            page.locator('#loopRange').uncheck()
            page.locator('#screenForm button').tap()
            page.wait_for_function('document.querySelector("#screenStatus").textContent.includes("本轮已完成")',timeout=30000)
            assert page.locator('#screenCounter').inner_text().startswith('3 /')
            assert page.evaluate('document.querySelector("#audio").paused')
            page.locator('#screenTools').evaluate('el=>el.open=true')
            page.locator('#contextFontSize').fill('135')
            page.locator('#fontReset').tap()
            assert page.locator('#fontSize').input_value()==page.locator('#contextFontSize').input_value()=='100'
            page.locator('#screenTools').evaluate('el=>el.open=false')
            page.locator('#lock').tap()
            assert page.locator('#screenVoice').is_hidden() and page.locator('#screenLessonSelect').is_hidden()
            assert page.locator('#exitScreen').is_hidden()
            page.locator('#lock').tap()
            page.locator('#screenLessonSelect').select_option('b1-003')
            page.wait_for_function('document.querySelector("#screenCounter").textContent.startsWith("1 /") && document.querySelector("#screenLesson").textContent.includes("Lesson 3")')
            page.locator('#screenLessonSelect').select_option('b1-001')
            page.wait_for_function('document.querySelector("#screenCounter").textContent.startsWith("1 /") && document.querySelector("#screenLesson").textContent.includes("Lesson 1")')
            for width,height in [(320,568),(390,844),(844,390),(1280,900)]:
                page.set_viewport_size({'width':width,'height':height})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,height)
                for id in ['lock','exitScreen','screenVoice','screenSpeed','screenPause','detailsToggle']:
                    box=page.locator('#'+id).bounding_box();assert box and box['y']>=0 and box['y']+box['height']<=height+1,(id,box,width,height)
                page.screenshot(path=str(shots/f'{engine}-{width}.png'))
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_function('navigator.serviceWorker.controller!==null')
            page.locator('#screenTools').evaluate('el=>el.open=true')
            page.locator('#voiceDownloadStart').fill('1');page.locator('#voiceDownloadEnd').fill('3')
            page.locator('#voiceDownloadPack').select_option('all')
            page.locator('#voiceDownload').tap()
            page.wait_for_function('document.querySelector("#voiceDownloadStatus").textContent.includes("下载完成")')
            assert '18/18' in page.locator('#voiceDownloadStatus').inner_text()
            page.locator('#screenTools').evaluate('el=>el.open=false')
            page.locator('#screenVoice').select_option('us-jenny')
            page.locator('#exitScreen').tap()
            # Linux WPE has an unreliable offline API; an unavailable audio
            # origin still proves that the real cached AAC and range path work.
            if engine=='chromium':context.set_offline(True)
            else:VoiceFixture.fail_audio=True
            page.reload(wait_until='networkidle')
            assert page.locator('#voiceMode').input_value()=='us-jenny'
            page.locator('[data-cue="2"] [data-action="play"]').tap()
            page.wait_for_function('document.querySelector("#playStatus").textContent.includes("循环中")')
            response=page.evaluate('''async()=>{const r=await fetch(document.querySelector('#audio').src,{headers:{Range:'bytes=0-63'}});return [r.status,(await r.arrayBuffer()).byteLength];}''')
            assert response==[206,64],response
            assert not errors,errors
            browser.close()
        print(f'PASS {engine}: GB/US cycling, synchronized controls, lock, viewport layouts, six-voice range download, cached reload and AAC byte ranges; screenshots {shots}')
    finally:server.shutdown()


if __name__=='__main__':main()
