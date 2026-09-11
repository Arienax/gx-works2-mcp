"""Apply reviewed context hooks to one pinned source snapshot, fail closed."""
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

BASE = 'c6bc6ef7c8740d63bca1adb650e0264d0ffd8970'
ROOT = Path(__file__).resolve().parents[1]
HASHES = {
    'src/api.py': ('95c610ef768ee309e4c788a9540d63ab623002351656b8a6e5018796950873c7', '72066fb44c1a0cafad4edabe842fdbded15b1b9f8bab07dabf37c25cef18cb31'),
    'src/pattern_library.py': ('5bcf771da7e22d1924396d3d97b231dd7140cb7cc65ccc0a5230606d163cff58', '475eda11a6a73355fd96a0e6e09da16ff00d6a25e49225389a8b43660b6491ba'),
    'src/application/workbench.py': ('14c9855954a4917e8565ba45baeb36747619338d73c22dcc93bf2cf859ac7201', '3ad62061aeac5dc09e2c396d3ae5c6beb9273261572c7ccf316292c665e3fe14'),
    'src/knowledge_retriever.py': ('65ff1be1e0365755a240573afacc318f992de798cd9fecab262bba07025799d9', '5dcc28cf72f9484cfd2996199f8ea7033e5d158520d57fdb3ba050b0e43ebc09'),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    os.chdir(ROOT)
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], check=True)
    if git('status', '--porcelain', '--untracked-files=no').strip():
        raise RuntimeError('Build checkout must be clean before context preparation')
    edits = json.loads((ROOT / 'build_inputs/context_edits.json').read_text(encoding='utf-8-sig'))
    if len(edits) != 20 or {e['path'] for e in edits} != set(HASHES):
        raise RuntimeError('Unexpected hook scope')
    sources = {}
    for name, (before, _) in HASHES.items():
        text = (ROOT / name).read_text(encoding='utf-8')
        actual = digest(text.encode('utf-8'))
        if actual != before:
            raise RuntimeError(f'Pinned preimage changed: {name}: {actual}')
        sources[name] = text
    for edit in edits:
        name = edit['path']
        if sources[name].count(edit['before']) != 1:
            raise RuntimeError('Hook anchor missing or ambiguous: ' + edit['label'])
        sources[name] = sources[name].replace(edit['before'], edit['after'], 1)
    for name, text in sources.items():
        ast.parse(text, filename=name)
        actual = digest(text.encode('utf-8'))
        if actual != HASHES[name][1]:
            raise RuntimeError(f'Reviewed output mismatch: {name}: {actual}')
    policy = (ROOT / 'src/prompt_context_policy.py').read_text(encoding='utf-8')
    if digest(policy.encode()) != 'b3fac6bb30790a037a311e7b195c82ce5ea363e376df4a54ee33424f7e025b05':
        raise RuntimeError('Policy module differs from the reviewed module: ' + digest(policy.encode()))
    event_source = (ROOT / 'src/application/events.py').read_bytes()
    if digest(event_source) != '4dcfd9c5fd20225717c10ac483fc9d6edf3fda086e69d31440a98ef371c6e98f':
        raise RuntimeError('Context audit event projection changed')
    for name, text in sources.items():
        with (ROOT / name).open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
    modified = set(git('diff', '--name-only').decode().splitlines())
    if modified != set(HASHES):
        raise RuntimeError('Unexpected worktree changes: ' + repr(modified))
    changed_src = set(git('diff', '--name-only', BASE, '--', 'src').decode().splitlines())
    if changed_src != set(HASHES) | {'src/prompt_context_policy.py', 'src/application/events.py'}:
        raise RuntimeError('Upstream core changed outside the context hooks: ' + repr(changed_src))
    subprocess.run(['git', 'diff', '--check'], check=True)
    output = ROOT / 'build/context-test'
    output.mkdir(parents=True, exist_ok=False)
    patch = git('diff', '--binary', BASE, '--', 'src', 'scripts/web_entry.py',
                'scripts/start_context_test.ps1', 'tests/test_context_refresh_runtime.py',
                'tests/test_prompt_context_policy.py', 'tools/audit_prompt_context.py',
                'tools/context_audit_cases.jsonl', 'START_CONTEXT_TEST.cmd',
                'start-adaptive.cmd', 'start-legacy.cmd', 'CONTEXT_TEST_README.zh-CN.md')
    (output / 'context-changes.patch').write_bytes(patch)
    manifest = {'schema_version': 1, 'base_ref': 'fix/generation-result-refresh',
                'base_commit': BASE, 'build_input_commit': git('rev-parse', 'HEAD').decode().strip(),
                'hook_count': len(edits), 'runtime_patch_sha256': digest(patch),
                'runtime_hooks': {name: {'before_sha256': hashes[0], 'after_sha256': hashes[1]}
                                  for name, hashes in HASHES.items()},
                'context_policy_sha256': digest(policy.encode()),
                'typed_context_event_projection_sha256': digest(event_source),
                'production_core_changes_outside_context': [],
                'source_prepared': True}
    (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
