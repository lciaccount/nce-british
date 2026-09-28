#!/usr/bin/env python3
"""Generate six local sentence voices, resumably; never replace source recordings.

Requires edge-tts and ffmpeg/ffprobe. Only the English text is sent to the speech
service; no original recording or learning record is uploaded.
"""
import argparse
import asyncio
import hashlib
import json
import random
import re
import subprocess
import time
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent
VOICES = [
    {'id':'gb-ryan','name':'Ryan','voice':'en-GB-RyanNeural','locale':'en-GB','label':'Ryan · 英音男声'},
    {'id':'gb-sonia','name':'Sonia','voice':'en-GB-SoniaNeural','locale':'en-GB','label':'Sonia · 英音女声'},
    {'id':'gb-libby','name':'Libby','voice':'en-GB-LibbyNeural','locale':'en-GB','label':'Libby · 英音女声'},
    {'id':'us-guy','name':'Guy','voice':'en-US-GuyNeural','locale':'en-US','label':'Guy · 美音男声'},
    {'id':'us-jenny','name':'Jenny','voice':'en-US-JennyNeural','locale':'en-US','label':'Jenny · 美音女声'},
    {'id':'us-aria','name':'Aria','voice':'en-US-AriaNeural','locale':'en-US','label':'Aria · 美音女声'},
]
VERSION = 'nce-six-aac24-v1'


def speech_text(text):
    text = re.sub(r'(?<=\d),\s+(?=\d{3}\b)', ',', text)
    text = re.sub(r'\b(Mr|Mrs|Ms|Dr)\.(?=[A-Z])', r'\1. ', text)
    return ' '.join(text.split())


def corpus():
    data = json.loads((ROOT/'content.js').read_text().removeprefix('window.NCE_DATA=').strip().removesuffix(';'))
    texts, cues = {}, {}
    for lesson in data['lessons']:
        for cue in lesson['cues']:
            text = speech_text(cue['text'])
            key = hashlib.sha256((VERSION+'\n'+text).encode()).hexdigest()[:24]
            assert key not in texts or texts[key] == text
            texts[key] = text
            cues[cue['id']] = key
    return texts, cues


def encode(raw, target, start=None, end=None):
    part = target.with_suffix('.tmp.m4a')
    # AAC is natively supported in iPhone Safari. Speech-sized mono files keep
    # all six voices plus the original MP3 recordings within Pages' site limit.
    seek=[] if start is None else ['-ss',str(start)]
    length=[] if end is None else ['-t',str(end-start)]
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y',*seek,'-i',str(raw),*length,'-af',
        'silenceremove=start_periods=1:start_duration=0.01:start_threshold=-50dB:start_silence=0.035,'
        'areverse,silenceremove=start_periods=1:start_duration=0.01:start_threshold=-50dB:start_silence=0.05,areverse',
        '-map_metadata','-1','-ac','1','-ar','24000','-c:a','aac','-b:a','24k','-movflags','+faststart',str(part)], check=True)
    duration = float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration',
        '-of','default=nw=1:nk=1',str(part)],text=True))
    if part.stat().st_size < 600 or not .1 < duration < 180:
        raise ValueError('Invalid synthesized audio')
    part.replace(target)
    return [target.stat().st_size, round(duration, 3)]


def normalized(text):
    return ''.join(c.lower() for c in text if c.isalnum())


def plausible_duration(text, duration):
    # Catch rare service timestamps that match the words but cut the audio to
    # a fraction of the utterance. This is a deliberately loose lower bound.
    return duration > max(.1, len(text.split()) * .09)


def batch_ranges(texts, boundaries):
    """Accept service timestamps only when every source character is accounted for.

    Metadata may group words (e.g. 'In 1995'). Never estimate a cut inside such
    a group or distribute duration by text length; fall back to separate calls.
    """
    expected=''.join(normalized(t) for t in texts)
    if ''.join(normalized(b['text']) for b in boundaries)!=expected:
        raise ValueError('Boundary metadata does not match source text')
    positions={0:0};cursor=0
    for i,b in enumerate(boundaries):
        cursor+=len(normalized(b['text']));positions[cursor]=i+1
    ranges=[];cursor=0
    for text in texts:
        first=positions[cursor];cursor+=len(normalized(text))
        if cursor not in positions:raise ValueError('A metadata word crosses a sentence boundary')
        last=positions[cursor]-1
        start=max(0,boundaries[first]['offset']/1e7-.08)
        end=(boundaries[last]['offset']+boundaries[last]['duration'])/1e7+.12
        if last+1<len(boundaries):end=min(end,(boundaries[last]['offset']+boundaries[last]['duration']+boundaries[last+1]['offset'])/2e7)
        if ranges and start<ranges[-1][1]:raise ValueError('Metadata ranges overlap')
        if end<=start:raise ValueError('Empty metadata range')
        ranges.append((start,end))
    return ranges


async def synth_batch(texts, voice, raw):
    sentences=[]
    for text in texts:
        text=text.strip().strip('"\'“”‘’').rstrip(',;: ')
        sentences.append(text if text.endswith(('.', '?', '!')) else text+'.')
    boundaries=[]
    with raw.open('wb') as f:
        async for chunk in edge_tts.Communicate('\n\n'.join(sentences),voice,boundary='WordBoundary').stream():
            if chunk['type']=='audio':f.write(chunk['data'])
            elif chunk['type']=='WordBoundary':boundaries.append(chunk)
    return batch_ranges(texts,boundaries)


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--batch-size',type=int,default=16)
    parser.add_argument('--limit',type=int,help='Generate at most this many missing assets; does not publish an incomplete catalog')
    parser.add_argument('--catalog-only',action='store_true')
    parser.add_argument('--preview',action='store_true',help='Write an explicitly incomplete catalog for local testing only')
    args=parser.parse_args()
    texts,cues=corpus()
    work=ROOT/'.voice-build';work.mkdir(exist_ok=True)
    journal=work/'completed.jsonl'
    assets={}
    if journal.exists():
        for line in journal.read_text().splitlines():
            try:
                key,value=json.loads(line)
                path=ROOT/'audio'/'tts'/f'{key}.m4a'
                if path.is_file() and path.stat().st_size==value[0] and plausible_duration(texts[key.split('/')[1]],value[1]):assets[key]=value
            except (ValueError,TypeError,OSError,KeyError):continue
    expected=[(voice,key) for key in texts for voice in VOICES]
    pending=[(v,k) for v,k in expected if f"{v['id']}/{k}" not in assets]
    for v in VOICES:(ROOT/'audio'/'tts'/v['id']).mkdir(parents=True,exist_ok=True)
    print(f'{len(cues)} items / {len(texts)} unique texts × 6 = {len(expected)} assets; cached {len(expected)-len(pending)}; missing {len(pending)}',flush=True)
    failures=[]
    if not args.catalog_only and pending:
        available={v['ShortName']:v for v in await edge_tts.list_voices()}
        assert all(available[v['voice']]['Locale']==v['locale'] for v in VOICES)
        queue=asyncio.Queue();chosen=pending[:args.limit]
        groups=[]
        for v in VOICES:
            keys=[k for voice,k in chosen if voice['id']==v['id']]
            size=max(1,min(args.batch_size,24))
            groups.append([(v,keys[i:i+size]) for i in range(0,len(keys),size)])
        # Interleave voices so completed lessons can be verified early.
        for i in range(max(map(len,groups),default=0)):
            for group in groups:
                if i<len(group):queue.put_nowait(group[i])
        total=len(chosen);done=0;started=time.monotonic()
        async def worker():
            nonlocal done
            while not queue.empty():
                try:v,keys=queue.get_nowait()
                except asyncio.QueueEmpty:return
                raw=work/f"{v['id']}-{keys[0]}-batch.mp3"
                for attempt in range(5):
                    try:
                        try:
                            ranges=await asyncio.wait_for(synth_batch([texts[k] for k in keys],v['voice'],raw),150)
                        except ValueError:
                            ranges=None
                        for i,k in enumerate(keys):
                            asset=f"{v['id']}/{k}"
                            if asset in assets:continue
                            target=ROOT/'audio'/'tts'/f'{asset}.m4a'
                            if ranges is None:
                                individual=work/f"{v['id']}-{k}.mp3"
                                await asyncio.wait_for(edge_tts.Communicate(texts[k],v['voice']).save(str(individual)),90)
                                value=await asyncio.to_thread(encode,individual,target)
                                individual.unlink(missing_ok=True)
                            else:
                                value=await asyncio.to_thread(encode,raw,target,*ranges[i])
                                if not plausible_duration(texts[k],value[1]):
                                    individual=work/f"{v['id']}-{k}.mp3"
                                    await asyncio.wait_for(edge_tts.Communicate(texts[k],v['voice']).save(str(individual)),90)
                                    value=await asyncio.to_thread(encode,individual,target)
                                    individual.unlink(missing_ok=True)
                            if not plausible_duration(texts[k],value[1]):
                                raise ValueError('Implausibly short synthesized cue')
                            with journal.open('a') as f:f.write(json.dumps([asset,value])+'\n')
                            assets[asset]=value
                        raw.unlink(missing_ok=True)
                        break
                    except Exception as error:
                        if attempt==4:
                            failures.append([v['id'],keys,str(error)])
                            print(f'FAILED {v["id"]} batch: {type(error).__name__}',flush=True)
                        else:await asyncio.sleep(min(60,2**(attempt+1))+random.random())
                done+=len(keys);queue.task_done()
                if done%96<len(keys) or done==total:
                    elapsed=time.monotonic()-started
                    print(f'{done}/{total} this run; ETA {(total-done)*elapsed/max(done,1)/60:.1f} min; failures {len(failures)}',flush=True)
                if len(failures)>=12:
                    return
        await asyncio.gather(*(worker() for _ in range(max(1,min(args.workers,12)))))
    selected={f"{v['id']}/{k}":assets[f"{v['id']}/{k}"] for v,k in expected if f"{v['id']}/{k}" in assets}
    ready=len(selected)==len(expected)
    catalog={'version':VERSION,'ready':ready,'voices':VOICES,'cues':cues,'assets':selected,
             'expectedAssets':len(expected),'totalBytes':sum(v[0] for v in selected.values()),
             'format':'AAC-LC 24 kbit/s, 24 kHz mono; original recordings unchanged'}
    if ready or args.preview:
        dest=ROOT/'voice-index.json';tmp=dest.with_suffix('.tmp.json')
        tmp.write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':'))+'\n');tmp.replace(dest)
        print(f'Catalog: ready={ready}, assets={len(selected)}, bytes={catalog["totalBytes"]}',flush=True)
    else:
        print(f'Not published: {len(expected)-len(selected)} missing. Rerun to resume.',flush=True)
    if failures:
        (work/'failures.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2))
        raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
