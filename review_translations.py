#!/usr/bin/env python3
"""Generate reproducible, context-aware candidates for every machine cue.

Candidates are deliberately kept out of published translations until checked;
the model is an audit aid, not a claim of human proofreading.
"""
import argparse
import json
import re

from build_translations import (CACHE, CUE_OVERRIDES, MODEL, MODEL_REVISION,
                                corpus, fetch_source, normalized)


def records():
    current = json.loads((CACHE.parent / 'translations.js').read_text()
                         .removeprefix('window.NCE_TRANSLATIONS=').strip().removesuffix(';'))
    bilingual = fetch_source()
    for lesson in corpus():
        groups = {}
        for cue in lesson['cues']:
            groups.setdefault(cue['sourceId'], []).append(cue)
        source_chinese = {normalized(en): zh for en, zh in bilingual[lesson['id']]}
        for group in groups.values():
            english = ' '.join(cue['text'] for cue in group)
            reference = source_chinese.get(normalized(english), '')
            for cue in group:
                if current[cue['id']][1] and cue['id'] not in CUE_OVERRIDES:
                    yield {'id': cue['id'], 'text': cue['text'], 'source': english,
                           'reference': reference, 'current': current[cue['id']][0]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    pending = list(records())
    if args.limit:
        pending = pending[:args.limit]
    journal = CACHE / 'context-review.jsonl'
    done = {}
    if journal.exists():
        for line in journal.read_text().splitlines():
            row = json.loads(line)
            done[row['id']] = row
    pending = [row for row in pending if row['id'] not in done]
    print(f'{len(pending)} context-aware candidates remaining', flush=True)
    if not pending:
        return

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=MODEL_REVISION)
    tokenizer.padding_side = 'left'
    model = AutoModelForCausalLM.from_pretrained(MODEL, revision=MODEL_REVISION,
                                                torch_dtype=torch.bfloat16).cuda().eval()
    for i in range(0, len(pending), 8):
        batch = pending[i:i + 8]
        prompts = []
        for row in batch:
            task = (f'完整英文原句：{row["source"]}\n'
                    f'只翻译这个英语片段：{row["text"]}\n')
            if row['reference']:
                task += f'整句中文参考（只供理解语境，不可照搬成片段译文）：{row["reference"]}\n'
            task += '准确译为简体中文，只输出这个片段对应的译文；保留与前后片段衔接的语气，不增补片段外的信息。'
            prompts.append(tokenizer.apply_chat_template(
                [{'role': 'user', 'content': task}], tokenize=False, add_generation_prompt=True))
        encoded = tokenizer(prompts, padding=True, return_tensors='pt').to('cuda')
        with torch.inference_mode():
            output = model.generate(**encoded, max_new_tokens=150, do_sample=False,
                                    temperature=None, top_p=None, top_k=None)
        results = tokenizer.batch_decode(output[:, encoded['input_ids'].shape[1]:],
                                         skip_special_tokens=True)
        with journal.open('a') as file:
            for row, candidate in zip(batch, results):
                candidate = re.sub(r'^译文[：:]\s*', '', candidate.strip()).strip('“”')
                row['candidate'] = candidate
                file.write(json.dumps(row, ensure_ascii=False) + '\n')
        if i % 80 == 0 or i + 8 >= len(pending):
            print(f'{min(i + 8, len(pending))}/{len(pending)}', flush=True)


if __name__ == '__main__':
    main()
