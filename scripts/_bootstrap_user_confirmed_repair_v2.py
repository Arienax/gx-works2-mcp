from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new, label):
    path = ROOT / path
    text = path.read_text(encoding="utf-8")
    if new in text:
        print("already applied:", label)
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print("applied:", label)


replace_once(
    "src/application/generation.py",
    '''class GenerationDependencies:\n    """Inject model calls or a provider snapshot; defaults use the accepted API."""\n    stream_response: Optional[Callable] = None\n    generate_json: Optional[Callable] = None\n    provider: object = None\n    check_cancelled: Optional[Callable] = None\n''',
    '''class GenerationDependencies:\n    """Inject model calls or a provider snapshot; defaults use the accepted API."""\n    stream_response: Optional[Callable] = None\n    generate_json: Optional[Callable] = None\n    provider: object = None\n    check_cancelled: Optional[Callable] = None\n    preserve_rejected_candidate: bool = False\n''',
    "add explicit rejected-candidate persistence dependency",
)

replace_once(
    "src/application/generation.py",
    '''            def persist_repair_candidate():\n                # Private staging only: never expose an invalid candidate as a project artifact.\n                if self.target_mode != "ladder" or not isinstance(json_str, str):\n                    return\n''',
    '''            def persist_repair_candidate():\n                # Private staging only: only the operator Workbench opts into this.\n                # Low-level workflows and explicit repair tools retain zero-artifact failure semantics.\n                if not self.dependencies.preserve_rejected_candidate:\n                    return\n                if self.target_mode != "ladder" or not isinstance(json_str, str):\n                    return\n''',
    "gate rejected-candidate persistence",
)

replace_once(
    "src/application/workbench.py",
    '''                metadata = GenerationWorkflow(request, out_dir, ctx.emit, GenerationDependencies(provider=provider, check_cancelled=ctx.checkpoint)).run()\n''',
    '''                metadata = GenerationWorkflow(request, out_dir, ctx.emit, GenerationDependencies(\n                    provider=provider, check_cancelled=ctx.checkpoint, preserve_rejected_candidate=True\n                )).run()\n''',
    "enable private rejected candidate only for Workbench generation",
)

replace_once(
    "src/integrations/web/responses.py",
    '''                    "invalid_shared_input", "invalid_ladder_structure", "repair_base_invalid",\n''',
    '''                    "invalid_shared_input", "invalid_ladder_structure", "field_too_long", "repair_base_invalid",\n''',
    "add field_too_long to HTTP response contract",
)
