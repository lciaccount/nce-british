#!/usr/bin/env python3
"""Replace imported LRC fragments with validated, acoustically aligned sentences."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
data=json.loads((ROOT/'content.js').read_text(encoding='utf8').removeprefix('window.NCE_DATA=').strip().removesuffix(';'))
if data.get('version') != 1:
    raise SystemExit('Already published. Run build_content.py before rebuilding/publishing alignment.')
review=[]
for lesson in data['lessons']:
    path=ROOT/'alignment'/f"{lesson['id']}.json"
    if not path.exists():raise SystemExit(f'Missing alignment: {lesson["id"]}')
    aligned=json.loads(path.read_text(encoding='utf8'))
    assert aligned['audioSha256']==lesson['sha256']
    last=0
    for cue in aligned['cues']:
        assert 0<=cue['start']<cue['end']<=lesson['duration'],cue
        assert cue['start']>=last-.001,cue
        last=cue['end']
        if cue['needsReview']:review.append({'lesson':lesson['id'],**cue})
    lesson['originalLrcWarnings']=lesson['timingWarnings']
    lesson['cues']=aligned['cues'];lesson['aligned']=True
    lesson['timingWarnings']=sum(c['needsReview'] for c in lesson['cues'])
data['version']=2
(ROOT/'content.js').write_text('window.NCE_DATA='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf8')
(ROOT/'alignment-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(f"Published {sum(len(l['cues']) for l in data['lessons'])} sentences, {len(review)} need review")
