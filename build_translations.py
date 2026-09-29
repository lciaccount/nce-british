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
    'b4-010-013': '他来自香港，已在台湾建厂，挑战日本对存储芯片市场的近乎垄断。',
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
    'b1-011-004': '不。',
    'b1-021-005': '不，不是那个。',
    'b1-039-009': '别把它掉下来！',
    'b1-061-012': '让我看看你的舌头。',
    'b1-081-003': '汤姆在哪里？',
    'b1-117-010': '“汤米怎么样了？”',
    'b2-060-012': '她不耐烦地问道。',
    'b2-061-002-p01': '哈勃望远镜于 4 月 20 日由美国国家航空航天局发射升空，',
    'b2-068-009': '“嗨，伊丽莎白，”奈杰尔回答道。',
    'b2-071-004-p01': '大本钟得名于本杰明·霍尔爵士，',
    'b2-085-005-p01': '所有为这份礼物出过力的人都会在一本大纪念册上签名，',
    'b2-089-010-p02': '“这里是 Poo and Ee Seed Bird Company。”（说话人口误，把公司名说乱了。）',
    'b3-004-003-p02': '因为他们上班通常穿着有领衬衫、打着领带。',
    'b3-012-013-p02': '又装上火柴和几罐啤酒，然后划船穿越加勒比海数英里，抵达一个小珊瑚岛。',
    'b3-014-012-p01': '他八十岁去世时，',
    'b3-014-012-p03': '这幅画是为了纪念“最英勇的战士、最杰出的领袖乔瓦尼·阿库托先生”。',
    'b3-035-011-p02': '这等于承认在特定情况下，正义已经自行得到伸张。',
    'b3-037-016-p02': '而只是以每小时三十英里的速度缓慢行驶。',
    'b3-043-004-p02': '或举办露天庆典，同样可以针对坏天气投保。',
    'b3-051-016-p02': '当时许多人都相信这种说法。',
    'b3-058-010-p02': '于是她坐下来喝了一杯浓茶，同时他打电话报了警。',
    'b3-059-006-p02': '前者是整理和丢弃物品所必需的；另一原因则是感情因素。',
    'b4-002-012-p01': '我们顶多只能大胆猜测它们究竟捕杀了多少猎物，',
    'b4-005-005-p02': '年轻人拥有光辉的未来，老人则拥有辉煌的过去：',
    'b4-006-006-p04': '一旦你觉得如果输了，自己和所属的群体都会蒙羞，',
    'b4-008-014-p01': '美国人很乐意先就医疗器械标准达成一项协议，再分别制定涵盖其他领域的协议，比如',
    'b4-023-012-p02': '而是属于天空；它往返于北方的筑巢地，可能要飞行六千英里，',
    'b4-029-004-p01': '其构想是用一个空气“垫”托起飞行器，',
    'b4-029-007-p02': '厚度不过一两英尺。',
    'b4-041-011-p01': '但这个年龄段的大象不容易顺从人类，',
    'b4-041-011-p02': '因此在驯养初期必须采取坚定的手段。',
    'b4-041-012-p01': '被圈养的大象仍拴在树上，每当有人靠近便挣扎、尖叫，',
    'b4-046-022-p01': '也可以说，理性、勤劳、',
    'b3-002-009': '“比尔，你在这上面干什么？”',
    'b3-004-005-p02': '阿尔弗雷德·布洛格斯的经历就是一例，他在埃尔斯米尔公司当清洁工。',
    'b3-010-005-p01': '但在当时，泰坦尼克号不仅是有史以来建造的最大轮船，',
    'b3-043-017-p01': '这个盘子的边缘十分光滑，',
    'b3-059-005-p02': '因为他们相信有朝一日会需要这些东西。',
    'b4-003-011-p02': '登山者只能四处寻找住处，有时借宿在和教区居民一样贫穷的当地牧师家中，',
    'b4-005-014-p02': '但我不会拿“尊老”之类乏味的陈词滥调来替自己辩护——仿佛年纪大本身就值得尊敬。',
    'b4-006-002-p02': '并认为，只要世界各国普通人能在足球或板球比赛中相遇，',
    'b4-007-002-p02': '看看蝙蝠回声定位这一非凡发现便知：声音也可以只起实用作用。',
    'b4-007-006-p03': '以及接收到回声之间的时间间隔，就能算出该处的海水深度。',
    'b4-008-006-p01': '符合欧盟安全标准的电动剃须刀，在美国销售前仍须经美国检测机构批准，',
    'b4-008-009-p02': '以免许多产品必须接受重复检测。',
    'b4-009-013-p02': '而他们的后勤补给毫无组织，只能依靠零星袭击。',
    'b4-010-012': '例如，亚历克斯·欧是一位斯坦福大学博士，',
    'b4-030-005-p01': '“豪猪号”被皇家学会用于多次航行，',
    'b4-031-011-p01': '他在脑海中清晰地想象出这个物体的立体形状，不管它有多大，',
    'b4-044-026-p01': '必须认识到，这些建立在同一观念基础上的制度，',
    'b4-046-018-p01': '邀请政治家、专业人士或商人去做这些事毫无意义，',
    'b4-046-018-p02': '他们已经连续六天忙于严肃事务或为其操心，周末不该再为琐事工作或操心。',
    'b4-046-031-p02': '最需要时不时把工作从脑海里放下。',
    'b4-047-002-p02': '或者租用设备，总费用都可能远低于住酒店。',
    'b4-047-018-p03': '或当地天气过于恶劣），逃离困境的办法就在帐篷外——甚至可能就是帐篷本身。',
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
