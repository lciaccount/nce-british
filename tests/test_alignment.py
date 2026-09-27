#!/usr/bin/env python3
"""Structural corpus checks and deterministic segmentation/edge unit tests."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from refine_alignment import split_words, quiet_edge, spoken_tokens


def words(text):
    return [{'text': word, 'start': i*.4, 'end': i*.4+.2, 'score': .95}
            for i, word in enumerate(text.split())]


def main():
    assert spoken_tokens("'Hello,' don't stop. 'I'm ready.'") == ['HELLO', "DON'T", 'STOP', "I'M", 'READY']
    assert spoken_tokens('1995?') == ['NINETEEN', 'NINETY', 'FIVE']
    assert split_words(words('This is a short sentence.')) == [(0, 5)]
    example = words('We followed the long road along the river until we reached the village; '
                    'then we stopped at a small hotel because we were all very tired.')
    ranges = split_words(example)
    assert len(ranges) >= 2
    assert ranges[0][0] == 0 and ranges[-1][1] == len(example)
    assert all(a[1] == b[0] for a, b in zip(ranges, ranges[1:]))
    assert all(b-a >= 5 for a, b in ranges)
    no_boundary = words(' '.join(['word']*30))
    assert split_words(no_boundary) == [(0, 30)], 'Do not force arbitrary splits'
    name = words('When the news got round that a comedy show would be presented at our local cinema by the P. and U. Bird Seed Company, we all rushed to see it.')
    assert all(name[a]['text'] != 'and' for a, b in split_words(name)), 'Do not split P. and U. inside a name'
    energy = np.ones(200)*.1
    energy[65:80] = 0
    assert .65 <= quiet_edge(energy, .9, .6, True) <= .8
    assert .65 <= quiet_edge(energy, .6, .9, False) <= .8
    assert quiet_edge(np.ones(100)*.1, .4, .6, False) == .6

    data = json.loads((ROOT/'content.js').read_text().removeprefix('window.NCE_DATA=').strip().removesuffix(';'))
    assert data['version'] == 3 and data['originalSentences'] == 4670
    seen, split_count, segment_count = set(), 0, 0
    for lesson in data['lessons']:
        original = json.loads((ROOT/'alignment'/f"{lesson['id']}.json").read_text())
        refined = json.loads((ROOT/'refined-alignment'/f"{lesson['id']}.json").read_text())
        assert hashlib.sha256((ROOT/lesson['audio']).read_bytes()).hexdigest() == lesson['sha256'] == refined['audioSha256']
        assert lesson['cues'] == refined['cues']
        assert len(original['cues']) == len(refined['words'])
        assert {c['sourceId'] for c in lesson['cues']} == {c['id'] for c in original['cues']}
        last_end = 0
        for c in lesson['cues']:
            assert c['id'] not in seen
            seen.add(c['id'])
            assert 0 <= last_end <= c['start'] < c['end'] <= lesson['duration']
            assert c['timingValid'] and c['needsReview'] == bool(c['reviewReasons'])
            last_end = c['end']
        for source_index, (source, aligned_words) in enumerate(zip(original['cues'], refined['words'])):
            parts = [c for c in lesson['cues'] if c['sourceId'] == source['id']]
            assert ' '.join(c['text'] for c in parts).split() == source['text'].split(), source['id']
            assert all(c['sourceIndex'] == source_index and c['parts'] == len(parts) for c in parts)
            assert [c['part'] for c in parts] == list(range(1, len(parts)+1))
            assert parts[0]['wordRange'][0] == 0 and parts[-1]['wordRange'][1] == len(aligned_words)
            for part in parts:
                lo, hi = part['wordRange']
                if part['wordModel'] != 'legacy-review' and 'boundary-conflict' not in part['reviewReasons']:
                    assert part['start'] <= aligned_words[lo]['start'] < aligned_words[hi-1]['end'] <= part['end']
            assert all(a['wordRange'][1] == b['wordRange'][0] for a, b in zip(parts, parts[1:]))
            if len(parts) > 1:
                split_count += 1
                assert all(c['id'].startswith(source['id']+'-p') for c in parts)
            else:
                assert parts[0]['id'] == source['id']
        segment_count += len(lesson['cues'])
    assert split_count > 0
    print(f'PASS: {len(data["lessons"])} unchanged recordings, 4670 lossless original sentences, '
          f'{split_count} split originals, {segment_count} ordered segments, unique IDs and word-edge coverage')


if __name__ == '__main__':
    main()
