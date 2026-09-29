#!/usr/bin/env python3
"""Extract a small offline English-Chinese lexicon for the NCE corpus.

Input: ECDICT CSV pinned to a specific GitHub revision. Its complete dataset
stays outside the published site; only used words and attested phrases ship.
"""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from build_translations import corpus

ROOT = Path(__file__).resolve().parent
CSV = ROOT / '.bilingual-build' / 'ecdict.csv'
SOURCE_SHA256 = '1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf'
TOKEN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
# Only unambiguous source typos are normalized. The displayed English text is
# never changed; learners can still see exactly what the recording says.
TYPO_ALIASES = {
    'conditoned':'conditioned', 'differnce':'difference', 'dimensonal':'dimensional',
    'dinnner':'dinner', 'disover':'discover', 'essentialy':'essentially',
    'hosptial':'hospital', 'indulde':'indulge', 'industriallized':'industrialized',
    'lettters':'letters', 'metheods':'methods', 'rabit':'rabbit',
    'suffcient':'sufficient', 'towrds':'towards', 'widley':'widely',
    'greengroce\'s':'greengrocer',
}
EXTRA_GLOSSES = {
    'commercialization':'商业化', 'everpresent':'始终存在的',
    'humouredly':'以幽默的方式', 'internet':'互联网', 'listeria':'李斯特菌',
    'overindustrialized':'工业化过度的', 'strongminded':'意志坚定的',
    'strychnine':'士的宁；番木鳖碱', 'unpunctuality':'不守时', 'untreated':'未经处理的',
    'eu':'欧洲联盟（欧盟）', 'cm':'厘米', 'st':'街道（street 的缩写）',
    'hasn\'t':'没有（has not 的缩写）', 'haven\'t':'没有（have not 的缩写）',
    'what\'d':'what did / what would 的缩写', 'what\'ll':'what will 的缩写',
    'you\'d':'you had / you would 的缩写', 'you\'ll':'you will 的缩写',
    'de':'人名中的法语连接词，相当于“的”', 'la':'地名中的西班牙语冠词',
    'th':'英语序数词后缀（如 24th）',
}
SOURCE_ANOMALIES = {
    'againand', 'awave', 'cat\'only', 'islandscame', 'no\'illiterates',
    'visiblebreak',
}
PERSON_NAMES = set('acuto aleko alex au bagrit bellinsky benjamin bloggs brabante brinksley bussman dewey duamutef fratelli gamond guthrum haukodue hawkwood othmar sam shepenmut tazieff xiaohui'.split())
PLACE_NAMES = set('alice angouleme ayia beresovka escalopia ferngreen frinley gouffre irini kituro perachora pinhurst silbury skeppsbron wayle westhaven'.split())
OTHER_NAMES = set('anehin bellavista elkor endley lfz macintosh myrolite splendide'.split())
LETTER_TOKENS = set('b c d e f g h m n r s t y'.split())


def lemma_candidates(word):
    forms = []
    if word.endswith("'s"):
        forms.append(word[:-2])
    for suffix, endings in [('ies', ['y']), ('ing', ['', 'e']), ('ed', ['', 'e']),
                            ('es', ['']), ('s', ['']), ('est', ['', 'e']), ('er', ['', 'e'])]:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            stem = word[:-len(suffix)]
            forms.extend(stem + ending for ending in endings)
            if suffix in ('ing', 'ed') and len(stem) > 2 and stem[-1] == stem[-2]:
                forms.append(stem[:-1])
    return forms


def terms():
    words = set()
    phrases = set()
    for lesson in corpus():
        for cue in lesson['cues']:
            sequence = [word.lower().replace('’', "'") for word in TOKEN.findall(cue['text'])]
            words.update(sequence)
            for count in (2, 3, 4):
                phrases.update(' '.join(sequence[i:i + count]) for i in range(len(sequence) - count + 1))
    return words, phrases


def clean_senses(raw):
    lines = re.split(r'\\n|\n|\r', raw or '')
    kept = []
    for line in lines:
        line = re.sub(r'\s+', ' ', line).strip(' ;；')
        if not line or line.startswith(('[网络]', '[医]', '[经]', '[计]', '[化]', '[例句]')):
            continue
        if not re.search('[\u3400-\u9fff]', line):
            continue
        if len(line) > 220:
            line = line[:220].rstrip('，；; ')
        if line not in kept:
            kept.append(line)
        if len(kept) >= 5:
            break
    return kept


def scan(targets):
    result = {}
    with CSV.open(encoding='utf-8-sig', newline='') as source:
        for row in csv.DictReader(source):
            word = row['word'].lower().replace('’', "'").strip()
            if word not in targets:
                continue
            senses = clean_senses(row['translation'])
            if not senses:
                continue
            lemma = re.search(r'(?:^|/)0:([^/]+)', row['exchange'] or '')
            lemma = lemma[1].lower() if lemma else ''
            entry = [(row['phonetic'] or '').strip()[:65], senses, lemma if lemma != word else '']
            if word not in result or sum(map(len, senses)) > sum(map(len, result[word][1])):
                result[word] = entry
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    assert CSV.is_file(), f'Download pinned ECDICT CSV to {CSV}'
    assert hashlib.sha256(CSV.read_bytes()).hexdigest() == SOURCE_SHA256, 'ECDICT CSV checksum changed'
    words, phrases = terms()
    entries = scan(words | phrases)
    lemmas = {entry[2] for word, entry in entries.items() if word in words and entry[2] and entry[2] not in entries}
    entries.update(scan(lemmas))
    missing = words - entries.keys()
    candidates = {form for word in missing for form in lemma_candidates(word)} | set(TYPO_ALIASES.values())
    entries.update(scan(candidates - entries.keys()))
    for word in sorted(missing):
        if word in entries:
            continue
        base = next((form for form in lemma_candidates(word) if form in entries), None)
        if base:
            source = entries[base]
            entries[word] = [source[0], source[1], base]
        elif word in TYPO_ALIASES and TYPO_ALIASES[word] in entries:
            base = TYPO_ALIASES[word]
            source = entries[base]
            entries[word] = [source[0], [f'原文疑似拼写错误；参见 {base}', *source[1][:2]], base]
        elif word in EXTRA_GLOSSES:
            entries[word] = ['', [EXTRA_GLOSSES[word]], '']
        elif word in PERSON_NAMES or word.removesuffix("'s") in PERSON_NAMES:
            entries[word] = ['', ['专有名词：人名'], '']
        elif word in PLACE_NAMES:
            entries[word] = ['', ['专有名词：地名'], '']
        elif word in OTHER_NAMES:
            entries[word] = ['', ['专有名词：作品、机构或事物名称'], '']
        elif word in LETTER_TOKENS:
            entries[word] = ['', ['字母或缩写中的字符；请结合原句判断'], '']
        elif word in SOURCE_ANOMALIES:
            entries[word] = ['', ['原文疑似排版或拼写错误；请结合整句理解'], '']
    covered = sum(word in entries or word in {'mr', 'mrs', 'ms', 'dr'} for word in words)
    phrase_count = sum(phrase in entries for phrase in phrases)
    print(f'Corpus words {len(words)}; covered {covered} ({covered / len(words):.1%}); corpus phrases {phrase_count}; entries {len(entries)}')
    print('Uncovered sample:', ', '.join(sorted(words - entries.keys())[:80]))
    for sample in ['handbag', 'cats', 'cat', 'went', 'go', 'take off', 'investment', 'tipsters']:
        print(sample, entries.get(sample))
    if args.audit:
        return
    dest = ROOT / 'dictionary-data.js'
    dest.write_text('window.NCE_DICTIONARY=' + json.dumps(entries, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print(f'Published {dest.stat().st_size} bytes to {dest}')


if __name__ == '__main__':
    main()
