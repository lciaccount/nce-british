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
