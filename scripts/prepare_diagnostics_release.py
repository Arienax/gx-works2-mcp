"""Apply observation-only hooks after the pinned context preparation."""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
NAMES={'src/model_provider.py','src/application/jobs.py','src/integrations/web/app.py'}
def sha(data):return hashlib.sha256(data).hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def main():
    config=json.loads((ROOT/'build_inputs/diagnostics.json').read_text(encoding='utf-8'))
    patch=ROOT/'build_inputs/diagnostics.patch'
    if config.get('schema_version')!=1 or {x['path'] for x in config['files']}!=NAMES:
        raise RuntimeError('Diagnostic scope mismatch')
    # Normalize only accidental diff-header indentation, then require the exact
    # previously reviewed patch checksum. Never normalize program whitespace.
    patch_bytes=patch.read_bytes().replace(b'\n diff --git ', b'\ndiff --git ')
    if sha(patch_bytes)!=config['patch_sha256']:
        raise RuntimeError('Diagnostic patch checksum mismatch')
    for item in config['files']:
        if sha((ROOT/item['path']).read_bytes())!=item['before_sha256']:
            raise RuntimeError('Diagnostic preimage mismatch: '+item['path'])
    subprocess.run(['git','apply','--check','-'],input=patch_bytes,cwd=ROOT,check=True)
    subprocess.run(['git','apply','-'],input=patch_bytes,cwd=ROOT,check=True)
    for item in config['files']:
        data=(ROOT/item['path']).read_bytes()
        if sha(data)!=item['after_sha256']:
            raise RuntimeError('Diagnostic output mismatch: '+item['path'])
        ast.parse(data,filename=item['path'])
    subprocess.run(['git','diff','--check'],cwd=ROOT,check=True)
    destination=ROOT/'build/context-test'
    manifest=json.loads((destination/'source-manifest.json').read_text(encoding='utf-8'))
    final_patch=git('diff','--binary',manifest['base_commit'],'--','src','web/src/features/JobFailure.tsx',
        'scripts','tests/test_runtime_diagnostics.py','tests/test_runtime_diagnostics_web.py',
        'tests/test_context_refresh_runtime.py','tests/test_prompt_context_policy.py',
        'tools/audit_prompt_context.py','tools/context_audit_cases.jsonl','START_CONTEXT_TEST.cmd',
        'start-adaptive.cmd','start-legacy.cmd','CONTEXT_TEST_README.zh-CN.md','DIAGNOSTICS_README.zh-CN.md')
    (destination/'context-changes.patch').write_bytes(final_patch)
    manifest.update(runtime_patch_sha256=sha(final_patch), diagnostic_version=1,
        diagnostic_hooks=config['files'], diagnostic_module_sha256=sha((ROOT/'src/runtime_diagnostics.py').read_bytes()),
        production_core_changes_outside_context=sorted(NAMES|{'src/runtime_diagnostics.py'}),
        diagnostics={'metadata_only':True,'raw_response_saved':False,'prompt_saved':False,
                     'acceptance_changed':False,'automatic_repair_changed':False})
    (destination/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
