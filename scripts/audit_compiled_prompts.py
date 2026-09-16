"""Read explicitly selected task evidence; never mutate jobs or call providers."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.image_prompt_compiler import compile_task_prompt, PROMPT_CONTRACT_VERSION
from core.image_tasks import validate_image_task
from core.io import file_sha256, read_jsonl, write_json
from core.image_task_inputs import task_renderable_text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks', required=True, type=Path)
    parser.add_argument('--baseline-prompts', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    tasks = read_jsonl(args.tasks)
    for task in tasks:
        validate_image_task(task)
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = {(row['child'], row['role']): row for row in read_jsonl(args.baseline_prompts)}
    rows = []
    for task in tasks:
        if task.get('formation_status') != 'ready':
            continue
        prompt = compile_task_prompt(task=task)
        previous = baseline.get((task['child'], task['role']), {}).get('prompt', '')
        sections = {}
        section = 'header'
        for line in prompt.splitlines():
            if line.startswith('[') and line.endswith(']'):
                section = line[1:-1]
            else:
                sections[section] = sections.get(section, 0) + len(line) + 1
        repeats = [line for line, count in Counter(prompt.splitlines()).items() if count > 1 and line.strip()]
        path = args.output / f"{task['child']}_{task['role']}.txt"
        path.write_text(prompt, encoding='utf-8')
        rows.append({'child': task['child'], 'role': task['role'], 'before_chars': len(previous),
            'after_chars': len(prompt), 'section_chars': sections, 'repeated_exact_lines': repeats,
            'authored_copy': task_renderable_text(task),
            'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'prompt_path': path.name})
    sources = ['core/image_tasks.py', 'core/image_prompt_compiler.py', 'core/image_reference_context.py']
    write_json(args.output / 'audit.json', {'mode': 'offline_recompile_only_not_generation_input',
        'quality_verified': False, 'contract': PROMPT_CONTRACT_VERSION,
        'git_base': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_sha256': {path: file_sha256(ROOT / path) for path in sources},
        'tasks_sha256': file_sha256(args.tasks), 'baseline_sha256': file_sha256(args.baseline_prompts), 'rows': rows})
    print(json.dumps([{'role': r['role'], 'before': r['before_chars'], 'after': r['after_chars'],
                      'exact_repeat_count': len(r['repeated_exact_lines'])} for r in rows]))


if __name__ == '__main__':
    main()
