#!/usr/bin/env python3
"""Independent waveform screening of every still-flagged sentence boundary.

This cannot establish that every spoken word is present. It records objective
energy evidence so likely clipping can be prioritized for human listening.
"""
import json
from pathlib import Path

import numpy as np

from refine_alignment import ROOT, envelope


def payload():
    return json.loads((ROOT / 'content.js').read_text()
                      .removeprefix('window.NCE_DATA=').strip().removesuffix(';'))


def edge(energy, position, direction, scale):
    frame = round(position * 100)
    start, stop = ((frame - 15, frame) if direction == 'before'
                   else (frame, frame + 15))
    value = float(np.max(energy[max(0, start):min(len(energy), stop)]))
    return {'rms': round(value, 5), 'relativeToSpeech': round(value / scale, 3)}


def main():
    lessons = payload()['lessons']
    flagged = {row['id']: row for row in json.loads((ROOT / 'alignment-review.json').read_text())}
    rows = []
    for lesson in lessons:
        relevant = [cue for cue in lesson['cues'] if cue['id'] in flagged]
        if not relevant:
            continue
        energy = envelope(ROOT / lesson['audio'])
        for cue in relevant:
            start, end = round(cue['start'] * 100), round(cue['end'] * 100)
            inside = energy[min(start + 10, end - 1):max(start + 11, end - 10)]
            scale = max(.001, float(np.quantile(inside, .9)))
            rows.append({'id': cue['id'], 'lesson': lesson['id'],
                         'start': cue['start'], 'end': cue['end'],
                         'reasons': cue['reviewReasons'],
                         'beforeStart': edge(energy, cue['start'], 'before', scale),
                         'afterEnd': edge(energy, cue['end'], 'after', scale)})
    assert len(rows) == len(flagged)
    high = [row for row in rows if max(row['beforeStart']['relativeToSpeech'],
                                      row['afterEnd']['relativeToSpeech']) > .4]
    report = {'method': '10ms-rms-boundary-audit-v1', 'reviewedByEar': False,
              'note': 'Waveform energy is a screening signal, not proof of word completeness or human listening.',
              'flaggedSegments': len(rows), 'highEdgeEnergySegments': len(high), 'segments': rows}
    target = Path(ROOT / 'alignment-acoustic-audit.json')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'Waveform-screened {len(rows)} flagged segments; {len(high)} still have high energy near an outer edge.')


if __name__ == '__main__':
    main()
