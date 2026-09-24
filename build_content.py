#!/usr/bin/env python3
"""Import user-supplied MP3/LRC without changing the originals or the recording."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAMP = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\]')

def read_lrc(path):
    raw = path.read_bytes()
    for encoding in ['utf-8-sig', 'gb18030']:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise ValueError(f'Unsupported encoding: {path}')

def import_lesson(pair):
    book, path = pair
    audio = next((p for p in path.parent.iterdir() if p.stem == path.stem and p.suffix.lower() == '.mp3'), None)
    if not audio:
        raise ValueError(f'Missing audio: {path}')
    duration = float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(audio)], text=True))
    source, encoding = read_lrc(path)
    number = int(re.match(r'\d+',path.name)[0])
    key = f'b{book}-{number:03}'
    title = re.search(r'\[ti:([^\]]+)\]', source)
    title = title[1].strip() if title else re.sub(r'^\d+(?:-\d+)?[－\- ]*','',path.stem)
    offset_match = re.search(r'\[offset:([+-]?\d+)\]',source)
    offset = int(offset_match[1])/1000 if offset_match else 0
    cues, removed = [], 0
    for line in source.splitlines():
        stamps = list(STAMP.finditer(line))
        if not stamps:
            continue
        text = STAMP.sub('',line).strip()
        if not text or 'http://' in text or 'https://' in text or '学习软件' in text:
            removed += 1
            continue
        for stamp in stamps:
            start = round(int(stamp[1])*60 + float(stamp[2]) + offset,3)
            cues.append({'start':start,'text':text})
    cues.sort(key=lambda c:c['start'])
    merged=[]
    for cue in cues:
        if merged and merged[-1]['start']==cue['start']:
            if cue['text'] != merged[-1]['text']:
                merged[-1]['text'] += ' ' + cue['text']
        else:
            merged.append(cue)
    for index,cue in enumerate(merged):
        cue['end'] = merged[index+1]['start'] if index+1<len(merged) else round(duration,3)
        cue['id'] = f'{key}-{index+1:03}'
        cue['timingValid'] = 0 <= cue['start'] < cue['end'] <= duration+.001
    if not merged:
        raise ValueError(f'No cues: {path}')
    target = ROOT/'audio'/f'b{book}'/f'{number:03}.mp3'
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists() or target.stat().st_size != audio.stat().st_size:
        shutil.copy2(audio,target)
    return {'id':key,'book':book,'number':number,'title':title,'audio':target.relative_to(ROOT).as_posix(),
            'bytes':audio.stat().st_size,'duration':round(duration,3),'cues':merged,
            'source':path.name,'encoding':encoding,'removedNonStudyLines':removed,
            'timingWarnings':sum(not c['timingValid'] for c in merged),
            'sha256':hashlib.sha256(audio.read_bytes()).hexdigest()}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=Path('/home/lc/nce/英音'))
    args=parser.parse_args()
    pairs=[]
    for folder in sorted(args.source.iterdir()):
        match=re.search(r'第([1-4])册',folder.name)
        if folder.is_dir() and match:
            pairs.extend((int(match[1]),p) for p in sorted(folder.iterdir()) if p.suffix.lower()=='.lrc')
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        lessons=list(pool.map(import_lesson,pairs))
    lessons.sort(key=lambda x:(x['book'],x['number']))
    assert len({x['id'] for x in lessons})==len(lessons)
    data={'version':1,'sourceLabel':'用户提供的“英音”目录','lessons':lessons}
    (ROOT/'audio-index.json').write_text(json.dumps({l['id']:{'path':l['audio'],'bytes':l['bytes']} for l in lessons},separators=(',',':'))+'\n',encoding='utf8')
    (ROOT/'content.js').write_text('window.NCE_DATA='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf8')
    report={'books':{str(b):sum(x['book']==b for x in lessons) for b in range(1,5)},'lessons':len(lessons),
            'cues':sum(len(x['cues']) for x in lessons),'audioBytes':sum(x['bytes'] for x in lessons),
            'timingWarnings': [{'id':x['id'],'count':x['timingWarnings']} for x in lessons if x['timingWarnings']],
            'note':'保留录音与英文原文；仅删除广告和空字幕。LRC 元信息存在美音标记，实际口音及逐条对齐需人工核对。'}
    (ROOT/'import-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
