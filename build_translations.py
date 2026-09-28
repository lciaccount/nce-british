#!/usr/bin/env python3
"""Build offline Chinese cue translations from aligned bilingual subtitles.

The source is pinned so a rebuild never silently changes translations. Cues
that cannot be matched exactly are translated separately by a local model;
alignment never attaches a whole-sentence translation to only one fragment.
"""
import argparse
import concurrent.futures
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / '.bilingual-build'
SOURCE_REPO = 'byuc/NCE-Flow'
SOURCE_COMMIT = 'a9223062417396f23c829621bb5a9a82e46cc78c'
MODEL = 'Qwen/Qwen2.5-1.5B-Instruct'
MODEL_REVISION = '989aa7980e4cf806f80c7fef2b1adb7bc71aa306'
OVERRIDES = {
    "I-N-T-E-L-L-I-G-E-N-T. That's right.": 'I-N-T-E-L-L-I-G-E-N-T。对，拼对了。',
    '2.': '第二点：',
    '3.': '第三点：',
}
# Context-sensitive corrections for fragments whose isolated wording is
# ambiguous. Key by cue ID so identical English elsewhere remains untouched.
CUE_OVERRIDES = {
    'b2-041-012': '男人的领带永远不嫌多。',
    'b2-074-017': '“听着，警长，”罗克韦尔说，“别对我们太严厉。',
    'b2-026-021': '它确实挂反了！',
    'b3-004-003-p01': '办公室职员常被称为“白领”，原因很简单：',
    'b3-005-014-p03': '通向环绕总统府的十五英尺高围墙的 1084 级台阶。',
    'b3-007-013-p01': '约翰去找银行经理，经理把钱包的残骸',
    'b3-042-023-p02': '让水流把他们带到湖的另一边。',
    'b3-049-006-p02': '丈夫去世后很长时间，她仍坚持住在那里。',
    'b3-053-005-p01': '瑞典人最先意识到，公务员、警察等公职人员',
    'b4-010-013': '来自香港的斯坦福大学博士在台湾建厂，挑战日本在存储芯片市场近乎垄断的地位。',
    'b4-011-008-p01': '渐渐地，河面变宽，河岸向两侧退去，水流趋于平缓，最终，',
    'b4-013-010-p01': '一旦钻到石油层，',
    'b4-023-012-p03': '它一边飞行，一边喂养已经会飞的幼鸟，',
    'b4-025-016-p02': '但这确实意味着，与下面所说的情况相比，噪声的危害要小一些：',
    'b4-025-016-p03': '比如在孤儿院长大——那才是真正危害心理健康的事。',
    'b4-027-016-p01': '军械官下令把左舷的所有大炮移到右舷，以抵消船体的倾斜，',
    'b4-029-014-p04': '列车不接触轨道，时速可达 300 英里——前景似乎无限广阔。',
    'b4-031-006-p01': '后来，为了自身安全和实际需要，',
    'b4-032-008-p01': '然而，对证据进行更细致的研究，并更深入地理解那个时代，',
    'b4-033-018-p01': '由于无需离家谋生，孩子们不会因此受到冷落，',
    'b4-037-011-p02': '甚至宇宙本身，也必然会自然地“磨损殆尽”。',
    'b4-038-006-p02': '或选择知名品牌的瓶装、罐装饮料——装瓶厂通常遵循国际水处理标准。',
    'b4-044-026-p02': '比如以超自然观念为基础的制度，都必须放在一起考察，其中也包括我们自己的制度。',
    'b4-047-025-p02': '还有邀请“露营的朋友们”参加舞会或乘船游览的告示，不仅用法语、意大利语或西班牙语印制，',
    'b4-047-025-p03': '也用英语、德语和荷兰语印制。',
    'b4-047-031-p02': '他们留下多少垃圾；总之，他们是否会彻底惹恼土地所有者和乡村居民。',
    'b4-048-007': '这说明什么？',
    'b4-048-009-p03': '我们五位顾问中，没有一位会建议你把所有（甚至任何）资金都投进 Periwigs 这家公司。',
}


def corpus():
    return json.loads((ROOT / 'content.js').read_text().removeprefix('window.NCE_DATA=').strip().removesuffix(';'))['lessons']


def normalized(text):
    return re.sub('[^a-z0-9]', '', text.lower())


def fetch_source():
    CACHE.mkdir(exist_ok=True)
    tree_file = CACHE / f'{SOURCE_COMMIT}-tree.json'
    if not tree_file.exists():
        url = f'https://api.github.com/repos/{SOURCE_REPO}/git/trees/{SOURCE_COMMIT}?recursive=1'
        with urllib.request.urlopen(url, timeout=30) as response:
            tree_file.write_bytes(response.read())
    tree = json.loads(tree_file.read_text())
    assert not tree['truncated']
    paths = {}
    for node in tree['tree']:
        match = re.fullmatch(r'NCE([1-4])/(\d+)[^/]*\.lrc', node['path'])
        if match:
            key = f'b{match[1]}-{int(match[2]):03d}'
            assert key not in paths, key
            paths[key] = node['path']
    lessons = corpus()
    assert set(paths) == {lesson['id'] for lesson in lessons}, (len(paths), len(lessons))
    dest = CACHE / 'source'
    dest.mkdir(exist_ok=True)

    def one(item):
        key, path = item
        target = dest / f'{key}.lrc'
        if target.exists():
            return
        url = f'https://raw.githubusercontent.com/{SOURCE_REPO}/{SOURCE_COMMIT}/{urllib.parse.quote(path)}'
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    body = response.read()
                assert b'|' in body and len(body) > 100, key
                target.write_bytes(body)
                return
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, paths.items()))
    return {key: parse_lrc((dest / f'{key}.lrc').read_text(encoding='utf-8-sig')) for key in paths}


def parse_lrc(source):
    lines = []
    for line in source.splitlines():
        if not re.match(r'^\[\d+:\d+(?:\.\d+)?\]', line):
            continue
        body = re.sub(r'^\[[^]]+\]', '', line).strip()
        if '|' not in body:
            continue
        english, chinese = (part.strip() for part in body.split('|', 1))
        if normalized(english) and re.search('[\u3400-\u9fff]', chinese):
            lines.append((english, chinese))
    return lines


def align(lessons, bilingual):
    matched = {}
    misses = []
    counts = {}
    for lesson in lessons:
        rows = bilingual[lesson['id']]
        keys = [normalized(english) for english, _ in rows]
        pointer = 0
        good = 0
        for cue in lesson['cues']:
            target = normalized(cue['text'])
            found = None
            # Skip titles/instructions or a source line that groups multiple
            # cues; never use a fuzzy match to claim the wrong Chinese text.
            for start in range(pointer, min(len(rows), pointer + 10)):
                joined = ''
                for end in range(start, min(len(rows), start + 10)):
                    joined += keys[end]
                    if joined == target:
                        found = (start, end)
                        break
                    if len(joined) >= len(target):
                        break
                if found:
                    break
            if found:
                start, end = found
                matched[cue['id']] = ''.join(zh for _, zh in rows[start:end + 1])
                pointer = end + 1
                good += 1
            else:
                misses.append(cue)
        counts[lesson['book']] = counts.get(lesson['book'], 0) + good
    return matched, misses, counts


def translate_missing(misses):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    journal = CACHE / 'qwen.jsonl'
    translations = {}
    if journal.exists():
        for line in journal.read_text().splitlines():
            try:
                key, text, chinese = json.loads(line)
                if hashlib.sha256(text.encode()).hexdigest() == key and re.search('[\u3400-\u9fff]', chinese):
                    translations[key] = chinese
            except (ValueError, TypeError):
                continue
    distinct = {hashlib.sha256(cue['text'].encode()).hexdigest(): cue['text'] for cue in misses}
    translations.update({hashlib.sha256(text.encode()).hexdigest(): chinese for text, chinese in OVERRIDES.items()})
    pending = [(key, text) for key, text in distinct.items() if key not in translations]
    if pending:
        print(f'Local translation model: {len(pending)} new / {len(distinct)} distinct fragments', flush=True)
        tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=MODEL_REVISION)
        tokenizer.padding_side = 'left'
        model = AutoModelForCausalLM.from_pretrained(MODEL, revision=MODEL_REVISION, torch_dtype=torch.bfloat16).cuda().eval()
        problems = []
        for i in range(0, len(pending), 8):
            batch = pending[i:i + 8]
            prompts = [tokenizer.apply_chat_template([{'role':'user','content':'将下面英语片段准确译为简体中文。只输出片段译文，不增补上下文或解释：\n' + text}], tokenize=False, add_generation_prompt=True) for _, text in batch]
            encoded = tokenizer(prompts, padding=True, return_tensors='pt')
            assert encoded['input_ids'].shape[1] <= 1024, batch[0]
            with torch.inference_mode():
                output = model.generate(**encoded.to('cuda'), max_new_tokens=120, do_sample=False, temperature=None, top_p=None, top_k=None)
            results = tokenizer.batch_decode(output[:, encoded['input_ids'].shape[1]:], skip_special_tokens=True)
            with journal.open('a') as file:
                for (key, text), chinese in zip(batch, results):
                    chinese = re.sub(r'^译文[：:]\s*', '', chinese.strip()).strip('“”')
                    if not re.search('[\u3400-\u9fff]', chinese) or len(chinese) > 400 or '\n' in chinese:
                        problems.append((text, chinese))
                        continue
                    translations[key] = chinese
                    file.write(json.dumps([key, text, chinese], ensure_ascii=False) + '\n')
            if i % 80 == 0 or i + 8 >= len(pending):
                print(f'Translated {min(i + 8, len(pending))} / {len(pending)}', flush=True)
        if problems:
            for text, chinese in problems:
                print(f'Unusable machine translation: {text!r} => {chinese!r}', flush=True)
            raise ValueError(f'{len(problems)} machine translations need explicit correction')
    return {cue['id']: translations[hashlib.sha256(cue['text'].encode()).hexdigest()] for cue in misses}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    lessons = corpus()
    matched, misses, counts = align(lessons, fetch_source())
    print(f'Matched {len(matched)} / {len(matched) + len(misses)} cues, by book {counts}; missing {len(misses)}', flush=True)
    for cue in misses[:15]:
        print(cue['id'], cue['text'], flush=True)
    if args.audit:
        return
    generated = translate_missing(misses)
    records = {}
    for lesson in lessons:
        for cue in lesson['cues']:
            key = cue['id']
            if key in matched:
                records[key] = [matched[key], 0]
            else:
                records[key] = [CUE_OVERRIDES.get(key, generated[key]), 1]
    assert set(CUE_OVERRIDES) <= records.keys()
    assert len(records) == 5395 and all(re.search('[\u3400-\u9fff]', item[0]) for item in records.values())
    output = ROOT / 'translations.js'
    output.write_text('window.NCE_TRANSLATIONS=' + json.dumps(records, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print(f'Published {len(records)} translations ({len(generated)} locally generated), {output.stat().st_size} bytes', flush=True)


if __name__ == '__main__':
    main()
