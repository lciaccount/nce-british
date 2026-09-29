#!/usr/bin/env python3
"""Word alignment, conservative clause splitting and pause-aware boundaries.

Original alignment/ files remain the canonical complete sentences. All audio
stays byte-identical. Run with --publish only after reviewing generated output.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import torch
import torchaudio
from num2words import num2words
from align_sentences import emissions, normalize

ROOT = Path(__file__).resolve().parent
METHOD = 'dual-ctc-words-pauses-v7'
# Corrections supported by a 10 ms RMS waveform audit of flagged edges. These
# are not presented as listening certification: keep the review marker until
# someone listens to each original recording on real playback devices.
EDGE_CORRECTIONS = {
    'b1-005-019': {'start': 76.53},
    'b1-073-015': {'start': 72.66},
    'b1-073-016': {'start': 77.42},
    'b1-105-012': {'start': 41.70},
    'b1-123-013': {'start': 48.14, 'end': 49.25},
    'b2-066-001': {'end': 17.98},
    'b2-066-002': {'start': 18.70},
    'b2-095-006': {'end': 36.59},
    'b2-095-007': {'start': 37.83},
    'b3-002-015': {'end': 93.17},
    'b3-002-016': {'start': 93.85},
    'b3-026-023': {'end': 180.97},
    'b3-051-003-p02': {'end': 34.55},
    'b3-051-004': {'start': 35.48},
}
YEAR = re.compile(r'\b(?:1[6-9]\d{2}|20\d{2})\b')
CONNECTORS = {'and', 'but', 'because', 'although', 'though', 'whereas', 'while',
              'when', 'which', 'who', 'whose', 'unless', 'until', 'if', 'so', 'yet', 'that', 'or', 'nor'}


def spoken_tokens(text):
    # All ungrouped four-digit numbers in this corpus's 1600--2099 range
    # were checked in context: they denote years, not prices or quantities.
    # Align 1995 to "nineteen ninety-five", not "one thousand ...".
    text = YEAR.sub(lambda m: num2words(int(m[0]), to='year'), text)
    return [word.strip("'") for word in normalize(text) if word.strip("'")]


def split_words(words):
    """Return word ranges; never split inside a word or use proportional time."""
    def divide(lo, hi):
        duration = words[hi-1]['end'] - words[lo]['start']
        if hi-lo < 24 and duration < 12:
            return [(lo, hi)]
        choices = []
        for k in range(lo+5, hi-4):
            left, right = words[k-1], words[k]
            if re.fullmatch(r'(?:[A-Za-z]\.){1,4}|(?:Mr|Mrs|Ms|Dr|St|Prof|Capt)\.', left['text'].strip('"\'“”‘’')):
                continue
            punctuation = bool(re.search(r'[,;:!?][\"\'”’)]*$', left['text']))
            connector = right['text'].lower().strip('"\'“‘') in CONNECTORS
            if right['text'].lower() in {'and', 'or', 'nor'} and not punctuation:
                # A bare conjunction may join a name or noun phrase, not clauses.
                subject = words[k+1]['text'].lower().strip('"\'“‘')
                connector = subject in {'i', 'he', 'she', 'it', 'we', 'you', 'they', 'there',
                                        'this', 'that', 'the', 'a', 'an', 'my', 'his', 'her', 'our', 'their'}
            gap = right['start']-left['end']
            # Never strand "and," / "if," at the end of a fragment.
            if left['text'].lower().strip(',;:!?\"\'”’)') in CONNECTORS:
                continue
            # A few source subtitles omit a full stop before e.g. "It".
            # Preserve their spelling, but allow a clear recorded sentence gap.
            restart = gap >= .6 and right['text'].strip('"\'“‘') in {
                'It', 'He', 'She', 'They', 'We', 'You', 'There', 'This', 'That', 'The', 'A', 'An'}
            # A natural text boundary AND acoustic separation; do not break
            # a noun phrase just because there is a breath in the recording.
            if not (punctuation or (connector and gap >= .10) or restart):
                continue
            if min(left['score'], right['score']) < .55:
                continue
            balance = abs((k-lo)-(hi-k))/(hi-lo)
            strength = 1.1 if re.search(r'[;:!?][\"\'”’)]*$', left['text']) else .5 if punctuation else 0
            choices.append((balance-strength-min(max(gap, 0), .5), k))
        if not choices:
            return [(lo, hi)]
        _, k = min(choices)
        return divide(lo, k) + divide(k, hi)
    return divide(0, len(words))


def envelope(path):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                                   '-f', 'f32le', '-ac', '1', '-ar', '16000', '-'])
    wave = np.frombuffer(raw, dtype=np.float32)
    count = len(wave)//160
    return np.sqrt(np.mean(wave[:count*160].reshape(-1, 160)**2, axis=1))


def quiet_edge(energy, anchor, limit, before):
    """Find nearby >=30ms quiet run without crossing a neighbouring word.

    CTC character peaks are not phoneme boundaries. Keep a small guard around
    them; otherwise weak consonants can be clipped by trimming to peak frames.
    """
    a, b = sorted((anchor, limit))
    frames = np.arange(max(0, int(a/.01)), min(len(energy), int(b/.01)+1))
    if len(frames) < 3:
        return limit
    context = energy[max(0, int((anchor-.4)/.01)):min(len(energy), int((anchor+.4)/.01)+1)]
    threshold = max(.00015, min(float(np.quantile(context, .9))*.065,
                              float(np.quantile(context, .15))*2.0+.0001))
    quiet = energy[frames] <= threshold
    runs = [frames[i+1]*.01 for i in range(len(frames)-2) if quiet[i:i+3].all()]
    if runs:
        return max(runs) if before else min(runs)
    return limit


def align_words(lesson, originals, model, device, fallback=False):
    emission, times = emissions(model, ROOT/lesson['audio'], device, log_probs=not fallback)
    if fallback:
        vocab = {c:i for i,c in enumerate(torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.get_labels())}
        vocab['*'] = len(vocab)
        emission = torch.cat([emission, torch.zeros((len(emission), 1))], dim=1)
    else:
        vocab = torchaudio.pipelines.MMS_FA.get_dict()
    tokens = [vocab['*']]
    groups = []
    for cue in originals:
        group = []
        for match in re.finditer(r'\S+', cue['text']):
            # Quotes are not speech. Keep apostrophes inside contractions, but
            # never align the surrounding quote in 'Hello' as a spoken token.
            normalized = spoken_tokens(match[0])
            letters = '|'.join(normalized) if fallback else ''.join(normalized).lower()
            if not letters:
                # Punctuation-only tokens retain exact original text below.
                continue
            first = len(tokens)
            tokens.extend(vocab[c] for c in letters)
            group.append((match.start(), match.end(), first, len(tokens)))
            if fallback:
                tokens.append(vocab['|'])
        if not group:
            raise ValueError(f'No spoken text: {cue}')
        groups.append(group)
    if fallback:
        tokens[-1] = vocab['*']
    else:
        tokens.append(vocab['*'])
    path, scores = torchaudio.functional.forced_align(
        emission.unsqueeze(0), torch.tensor([tokens]), blank=0)
    spans = torchaudio.functional.merge_tokens(path[0], scores[0].exp(), blank=0)
    assert len(spans) == len(tokens)
    result = []
    for cue, group in zip(originals, groups):
        words = []
        for n, (begin, end, first, last) in enumerate(group):
            selected = spans[first:last]
            # Include punctuation-only tokens and preserve every original char.
            begin = 0 if n == 0 else begin
            end = group[n+1][0] if n+1 < len(group) else len(cue['text'])
            words.append({'text': cue['text'][begin:end].strip(), 'offset': begin,
                          'start': round(max(0, times[selected[0].start]-.01), 3),
                          'end': round(min(lesson['duration'], times[selected[-1].end-1]+.01), 3),
                          'score': round(float(np.mean([s.score for s in selected])), 3)})
        result.append(words)
    return result


def refine(lesson, originals, groups, methods):
    energy = envelope(ROOT/lesson['audio'])
    all_words = [w for group in groups for w in group]
    cursor, cues = 0, []
    for source_index, (original, words) in enumerate(zip(originals, groups)):
        if methods[source_index] == 'legacy-review':
            # Two uncertain alignments do not justify replacing a known range
            # or inventing internal cut points. Preserve it for listening review.
            cues.append({**original, 'sourceId': original['id'], 'sourceIndex': source_index,
                         'part': 1, 'parts': 1, 'wordRange': [0, len(words)],
                         'wordModel': 'legacy-review', 'needsReview': True,
                         'reviewReasons': ['unresolved-word-alignment']})
            cursor += len(words)
            continue
        ranges = split_words(words)
        for part, (lo, hi) in enumerate(ranges):
            first, last = words[lo], words[hi-1]
            previous = all_words[cursor+lo-1] if cursor+lo else None
            following = all_words[cursor+hi] if cursor+hi < len(all_words) else None
            # Never let an outward guard cross neighbouring word evidence.
            lower = max(0, first['start']-.24,
                        (previous['end']+first['start'])/2 if previous else 0)
            upper = min(lesson['duration'], last['end']+.32,
                        (last['end']+following['start'])/2 if following else lesson['duration'])
            start = quiet_edge(energy, max(lower, first['start']-.045), lower, True)
            end = quiet_edge(energy, min(upper, last['end']+.07), upper, False)
            score = round(float(np.mean([w['score'] for w in words[lo:hi]])), 3)
            reasons = []
            if score < .65 or min(w['score'] for w in words[lo:hi]) < .3:
                reasons.append('low-word-confidence')
            if ((lo == 0 and abs(start-original['start']) > .75) or
                    (hi == len(words) and abs(end-original['end']) > .75)):
                reasons.append('boundary-disagreement')
            if any(w['end']-w['start'] > max(1.5, len(w['text'])*.22) for w in words[lo:hi]):
                reasons.append('stretched-word')
            begin = words[lo]['offset']
            stop = words[hi]['offset'] if hi < len(words) else len(original['text'])
            cues.append({'id': original['id'] if len(ranges) == 1 else f"{original['id']}-p{part+1:02}",
                         'sourceId': original['id'], 'sourceIndex': source_index,
                         'part': part+1, 'parts': len(ranges),
                         'wordRange': [lo, hi],
                         'wordModel': methods[source_index],
                         'text': original['text'][begin:stop].strip(),
                         'start': round(start, 3), 'end': round(end, 3),
                         'score': score, 'timingValid': True,
                         'needsReview': bool(reasons), 'reviewReasons': reasons})
        cursor += len(words)
    for left, right in zip(cues, cues[1:]):
        if left['end'] > right['start']:
            boundary = round((left['end']+right['start'])/2, 3)
            left['end'] = right['start'] = boundary
            for cue in (left, right):
                cue['needsReview'] = True
                cue['reviewReasons'].append('boundary-conflict')
    for cue in cues:
        assert 0 <= cue['start'] < cue['end'] <= lesson['duration'], cue
    return apply_edge_corrections(cues)


def apply_edge_corrections(cues):
    for cue in cues:
        correction = EDGE_CORRECTIONS.get(cue['id'])
        if not correction:
            continue
        cue.update(correction)
        cue['reviewReasons'] = [reason for reason in cue['reviewReasons']
                                if reason != 'boundary-conflict']
        if 'waveform-corrected-needs-listening' not in cue['reviewReasons']:
            cue['reviewReasons'].append('waveform-corrected-needs-listening')
        cue['needsReview'] = True
    assert all(a['end'] <= b['start'] for a, b in zip(cues, cues[1:])), 'Corrected cues overlap'
    return cues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lesson')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    data = json.loads((ROOT/'content.js').read_text().removeprefix('window.NCE_DATA=').strip().removesuffix(';'))
    if data.get('version') not in (2, 3):
        raise SystemExit('Publish the complete sentences with publish_alignment.py first.')
    out = ROOT/'refined-alignment'
    out.mkdir(exist_ok=True)
    torch.set_num_threads(4)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model, fallback_model = None, None
    for number, lesson in enumerate(data['lessons']):
        if args.lesson and lesson['id'] != args.lesson:
            continue
        source = (ROOT/'alignment'/f"{lesson['id']}.json").read_bytes()
        original = json.loads(source)
        assert original['audioSha256'] == lesson['sha256']
        fingerprint = hashlib.sha256(source).hexdigest()
        target = out/f"{lesson['id']}.json"
        cached = None
        if target.exists() and not args.force:
            cached = json.loads(target.read_text())
            if cached.get('method') == METHOD and cached.get('sourceSha256') == fingerprint:
                continue
            if (cached.get('method') == 'dual-ctc-words-pauses-v6'
                    and cached.get('sourceSha256') == fingerprint and cached.get('audioSha256') == lesson['sha256']):
                # Only the lexical cut rules changed; reuse verified word audio
                # evidence and recompute the affected segment edges, not models.
                cached['cues'] = refine(lesson, original['cues'], cached['words'], cached['wordMethods'])
                cached['method'] = METHOD
                target.write_text(json.dumps(cached, ensure_ascii=False, separators=(',', ':'))+'\n')
                print(f"{number+1}/276 {lesson['id']}: resegmented verified words", flush=True)
                continue
            # Revalidate earlier cache only if neither changed normalization
            # rule applies to this lesson; acoustic evidence is then identical.
            outer_quotes = any(word != word.strip("'") for cue in original['cues']
                               for word in normalize(cue['text']))
            years = any(YEAR.search(cue['text']) for cue in original['cues'])
            unchanged = not years and (cached.get('method') == 'dual-ctc-words-pauses-v5' or
                        (cached.get('method') == 'dual-ctc-words-pauses-v4' and not outer_quotes))
            if (unchanged
                    and cached.get('sourceSha256') == fingerprint and cached.get('audioSha256') == lesson['sha256']):
                cached['cues'] = refine(lesson, original['cues'], cached['words'], cached['wordMethods'])
                cached['method'] = METHOD
                target.write_text(json.dumps(cached, ensure_ascii=False, separators=(',', ':'))+'\n')
                print(f"{number+1}/276 {lesson['id']}: validated unchanged word cache", flush=True)
                continue
        if model is None:
            model = torchaudio.pipelines.MMS_FA.get_model().to(device).eval()
        words = align_words(lesson, original['cues'], model, device)
        methods = ['mms-fa']*len(words)
        def suspect(group, cue):
            return (np.mean([w['score'] for w in group]) < .65 or
                    min(w['score'] for w in group) < .3 or
                    abs(group[0]['start']-cue['start']) > .75 or
                    abs(group[-1]['end']-cue['end']) > .75)
        checks = [suspect(group, cue) for group, cue in zip(words, original['cues'])]
        if any(checks):
            if fallback_model is None:
                fallback_model = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H.get_model().to(device).eval()
            alternative = align_words(lesson, original['cues'], fallback_model, device, fallback=True)
            for i, (check, group) in enumerate(zip(checks, alternative)):
                # Only use the English model where MMS is unreliable and the
                # second model has independently strong word evidence.
                if check and np.mean([w['score'] for w in group]) >= .8 and min(w['score'] for w in group) >= .5:
                    words[i] = group
                    methods[i] = 'english-ctc-fallback'
                elif check:
                    current, old = words[i], original['cues'][i]
                    if (np.mean([w['score'] for w in current]) < .85 or
                            abs(current[0]['start']-old['start']) > .75 or
                            abs(current[-1]['end']-old['end']) > .75):
                        methods[i] = 'legacy-review'
            # Never mix two alignments whose word intervals cross each other.
            if any(a[-1]['end'] > b[0]['start'] for a, b in zip(words, words[1:])):
                words = alternative
                methods = ['english-ctc-fallback']*len(words)
        cues = refine(lesson, original['cues'], words, methods)
        result = {'method': METHOD, 'audioSha256': lesson['sha256'],
                  'sourceSha256': fingerprint, 'wordMethods': methods, 'words': words, 'cues': cues}
        target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'))+'\n')
        print(f"{number+1}/276 {lesson['id']}: {len(original['cues'])} -> {len(cues)}, review {sum(c['needsReview'] for c in cues)}", flush=True)
    if args.publish:
        if args.lesson:
            raise SystemExit('Publish requires the complete corpus, not --lesson.')
        review, originals_all, boundary_shifts = [], [], []
        for lesson in data['lessons']:
            target = out/f"{lesson['id']}.json"
            result = json.loads(target.read_text())
            corrected = apply_edge_corrections(result['cues'])
            if corrected != json.loads(target.read_text())['cues']:
                result['cues'] = corrected
                target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'))+'\n')
            source = (ROOT/'alignment'/f"{lesson['id']}.json").read_bytes()
            assert result['method'] == METHOD
            assert result['audioSha256'] == lesson['sha256']
            assert result['sourceSha256'] == hashlib.sha256(source).hexdigest()
            originals = json.loads(source)['cues']
            originals_all.extend(originals)
            for original in originals:
                parts = [c for c in result['cues'] if c['sourceId'] == original['id']]
                assert ' '.join(c['text'] for c in parts).split() == original['text'].split()
                boundary_shifts.extend([abs(parts[0]['start']-original['start']),
                                        abs(parts[-1]['end']-original['end'])])
            lesson['cues'] = result['cues']
            lesson['alignmentMethod'] = METHOD
            lesson['timingWarnings'] = sum(c['needsReview'] for c in result['cues'])
            review.extend({'lesson': lesson['id'], **c} for c in result['cues'] if c['needsReview'])
        data['version'] = 3
        data['originalSentences'] = sum(len(json.loads(p.read_text())['cues']) for p in (ROOT/'alignment').glob('*.json'))
        (ROOT/'content.js').write_text('window.NCE_DATA='+json.dumps(data, ensure_ascii=False, separators=(',', ':'))+';\n')
        (ROOT/'alignment-review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2)+'\n')
        cues = [c for l in data['lessons'] for c in l['cues']]
        summary = {'method': METHOD, 'lessons': len(data['lessons']),
                   'originalSentences': len(originals_all), 'segments': len(cues),
                   'splitOriginals': len({c['sourceId'] for c in cues if c['parts'] > 1}),
                   'longBefore': sum(c['end']-c['start'] >= 12 for c in originals_all),
                   'longAfter': sum(c['end']-c['start'] >= 12 for c in cues),
                   'maxDurationBefore': round(max(c['end']-c['start'] for c in originals_all), 3),
                   'maxDurationAfter': round(max(c['end']-c['start'] for c in cues), 3),
                   'boundaryShiftMedian': round(float(np.median(boundary_shifts)), 3),
                   'reviewSegments': len(review),
                   'note': 'Automatic word alignment and pause-aware edges; 14 flagged edge corrections use 10ms waveform evidence. This is not human listening certification. Original audio and text preserved.'}
        (ROOT/'alignment-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
        print(f"Published {sum(len(l['cues']) for l in data['lessons'])} segments; review {len(review)}")


if __name__ == '__main__':
    main()
