#!/usr/bin/env python3
"""Sentence segmentation + local acoustic forced alignment (no audio upload).

Dependencies: torch/torchaudio 2.4, nltk, num2words, ffmpeg. Model weights are
downloaded by TorchAudio. Sentence text is never replaced by ASR output.
"""
import argparse
import json
import re
import subprocess
import unicodedata
from pathlib import Path

import nltk
import numpy as np
import torch
import torchaudio
from num2words import num2words

ROOT=Path(__file__).resolve().parent

def normalize(text):
    text=unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode().upper()
    text=re.sub(r'\d[\d,]*(?:\.\d+)?',lambda m:num2words(m[0].replace(',','')).upper(),text)
    text=re.sub(r'\bMR\.', 'MISTER',text)
    text=re.sub(r'\bMRS\.', 'MISSES',text)
    text=re.sub(r'\bDR\.', 'DOCTOR',text)
    return re.sub(r"[^A-Z' ]",' ',text).split()

def sentences(lesson,tokenizer):
    lines=[]
    clean=lambda s:re.sub(r'[^a-z]','',s.lower())
    for index,cue in enumerate(lesson['cues']):
        text=cue['text'].strip()
        if index<2 and (re.match(r'^Lesson\s+\d+',text,re.I) or clean(text)==clean(lesson['title'])):
            continue
        if re.match(r'^Listen to the (?:tape|recording)',text,re.I):
            continue
        lines.append(text)
    return tokenizer.tokenize(' '.join(lines))

def emissions(model,path,device):
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-ac','1','-ar','16000','-'])
    wave=torch.from_numpy(np.frombuffer(raw,dtype=np.float32).copy())
    outputs,times=[],[]
    # Overlap protects phonemes at chunk boundaries, cropped to 20 ms frames.
    for begin in range(0,len(wave),20*16000):
        end=min(len(wave),begin+20*16000)
        left=max(0,begin-16000); right=min(len(wave),end+16000)
        with torch.inference_mode():
            output,_=model(wave[left:right].unsqueeze(0).to(device))
            output=output[0].log_softmax(-1).cpu()
        centers=left/16000+np.arange(len(output))*.02+.0125
        keep=(centers>=begin/16000)&(centers<end/16000)
        outputs.append(output[keep]); times.extend(centers[keep].tolist())
    return torch.cat(outputs),times

def align(lesson,model,labels,tokenizer,device):
    texts=sentences(lesson,tokenizer)
    emission,times=emissions(model,ROOT/lesson['audio'],device)
    vocab={c:i for i,c in enumerate(labels)}
    star=len(labels)
    emission=torch.cat([emission,torch.zeros((len(emission),1))],dim=1)
    tokens=[star]; slices=[]
    for text in texts:
        normalized='|'.join(normalize(text))
        first=len(tokens)
        tokens.extend(vocab[c] for c in normalized)
        slices.append((first,len(tokens)))
        tokens.append(vocab['|'])
    tokens[-1]=star
    path,scores=torchaudio.functional.forced_align(emission.unsqueeze(0),torch.tensor([tokens]),blank=0)
    spans=torchaudio.functional.merge_tokens(path[0],scores[0].exp(),blank=0)
    assert len(spans)==len(tokens),(len(spans),len(tokens))
    cues=[]
    for index,(text,(first,last)) in enumerate(zip(texts,slices)):
        selected=spans[first:last]
        assert selected,text
        start=max(0,times[selected[0].start]-.06)
        end=min(lesson['duration'],times[min(len(times)-1,selected[-1].end-1)]+.09)
        score=sum(s.score for s in selected)/len(selected)
        cues.append({'id':f"{lesson['id']}-{index+1:03}",'text':text,'start':round(start,3),'end':round(end,3),
                     'score':round(score,3),'timingValid':start<end,'needsReview':score<.8})
    # Do not allow neighbouring padding to cross a sentence boundary.
    for previous,current in zip(cues,cues[1:]):
        if previous['end']>current['start']:
            boundary=round((previous['end']+current['start'])/2,3)
            previous['end']=boundary;current['start']=boundary
    return cues

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int);parser.add_argument('--lesson');parser.add_argument('--force',action='store_true');args=parser.parse_args()
    torch.set_num_threads(4)
    try:nltk.data.find('tokenizers/punkt_tab/english/')
    except LookupError:nltk.download('punkt_tab',quiet=True,raise_on_error=True)
    tokenizer=nltk.data.load('tokenizers/punkt/english.pickle')
    bundle=torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    device='cuda' if torch.cuda.is_available() else 'cpu'
    model=bundle.get_model().to(device).eval()
    raw=(ROOT/'content.js').read_text(encoding='utf8')
    data=json.loads(raw.removeprefix('window.NCE_DATA=').strip().removesuffix(';'))
    if data.get('version') != 1:
        raise SystemExit('Run build_content.py first: alignment requires original LRC text, not already-published sentences.')
    out=ROOT/'alignment';out.mkdir(exist_ok=True)
    lessons=[l for l in data['lessons'] if not args.lesson or l['id']==args.lesson]
    for n,lesson in enumerate(lessons[:args.limit]):
        target=out/f"{lesson['id']}.json"
        if target.exists() and not args.force:continue
        cues=align(lesson,model,bundle.get_labels(),tokenizer,device)
        target.write_text(json.dumps({'audioSha256':lesson['sha256'],'method':'wav2vec2-base-960h-ctc-v1','cues':cues},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(f"{n+1}/{len(lessons)} {lesson['id']}: {len(cues)} sentences, {sum(c['needsReview'] for c in cues)} review",flush=True)

if __name__=='__main__':main()
