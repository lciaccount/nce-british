#!/usr/bin/env python3
"""Full six-voice coverage, ISO media integrity, sampled codec and unit checks."""
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_voices import corpus, batch_ranges, VOICES


def main():
    boundaries=[{'text':'Hello','offset':1000000,'duration':2000000},
                {'text':'world','offset':8000000,'duration':2000000}]
    assert len(batch_ranges(['Hello.','world!'],boundaries))==2
    for texts,metadata in [(['Hi','world'],boundaries),
                           (['Hello','world'],[{'text':'Hello world','offset':0,'duration':9000000}])]:
        try:batch_ranges(texts,metadata)
        except ValueError:pass
        else:raise AssertionError('Must reject mismatched or cross-sentence metadata')
    texts,cues=corpus()
    catalog=json.loads((ROOT/'voice-index.json').read_text())
    assert catalog['ready'], 'Incomplete build: do not publish six-voice availability'
    assert catalog['voices']==VOICES
    assert catalog['cues']==cues
    assert len(cues)==5395
    assert sum(v['locale']=='en-GB' for v in VOICES)==sum(v['locale']=='en-US' for v in VOICES)==3
    expected={f"{v['id']}/{k}" for v in VOICES for k in texts}
    assert set(catalog['assets'])==expected
    assert catalog['expectedAssets']==len(expected)
    total=0
    for key,(size,duration) in catalog['assets'].items():
        path=ROOT/'audio'/'tts'/f'{key}.m4a'
        assert path.stat().st_size==size and size>=600,(key,size)
        assert max(.1,len(texts[key.split('/')[1]].split())*.09)<duration<180,(key,duration)
        # Validate top-level ISO BMFF boxes all the way to EOF, not just suffix.
        boxes=[]
        with path.open('rb') as f:
            while f.tell()<size:
                start=f.tell();header=f.read(8);assert len(header)==8,key
                length,kind=struct.unpack('>I4s',header)
                if length==1:length=struct.unpack('>Q',f.read(8))[0]
                if length==0:length=size-start
                assert length>=8 and start+length<=size,key
                boxes.append(kind);f.seek(start+length)
        assert all(kind in boxes for kind in [b'ftyp',b'moov',b'mdat']),key
        total+=size
    assert total==catalog['totalBytes']
    # Stratified samples from each voice, spanning the corpus.
    keys=list(texts)
    for voice in VOICES:
        for key in keys[::max(1,len(keys)//8)]:
            path=ROOT/'audio'/'tts'/voice['id']/f'{key}.m4a'
            result=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
            stream=result['streams'][0]
            assert stream['codec_name']=='aac' and stream['channels']==1
            assert stream['sample_rate']=='24000'
            assert abs(float(result['format']['duration'])-catalog['assets'][f"{voice['id']}/{key}"][1])<.002
    first=next(iter(texts))
    assert len({hashlib.sha256((ROOT/'audio'/'tts'/v['id']/f'{first}.m4a').read_bytes()).hexdigest() for v in VOICES})==6
    listed=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    payload=sum((ROOT/f).stat().st_size for f in set(listed) if f and (ROOT/f).is_file())
    assert payload<1_000_000_000, f'Pages payload exceeds conservative 1 GB gate: {payload}'
    print(f'PASS: {len(cues)} items × six distinct voices, {len(expected)} deduplicated AAC assets; {total/1048576:.1f} MiB voices; total site payload {payload/1048576:.1f} MiB; metadata mapping rejects unsafe cuts')


if __name__=='__main__':main()
