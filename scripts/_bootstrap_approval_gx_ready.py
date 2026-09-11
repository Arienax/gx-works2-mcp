from pathlib import Path

path = Path("tests/test_approval_modes.py")
text = path.read_text(encoding="utf-8")
old = '''def setup_external(service, mode, monkeypatch):
    from test_application_persistence import _base
    pid = service.create_project(name='execution-spy')['id']
'''
new = '''def setup_external(service, mode, monkeypatch):
    from test_application_persistence import _base
    import application.execution
    monkeypatch.setattr(application.execution, 'read_gx_environment', lambda: {
        'status': 'ready', 'passed': True, 'desktop_execution_required': True,
        'gx_works2_running': True, 'project_open': True, 'message': 'GX Works2 已运行。',
    })
    pid = service.create_project(name='execution-spy')['id']
'''
if new in text:
    print("already applied")
elif text.count(old) == 1:
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print("patched approval GX fixture")
else:
    raise SystemExit(f"approval fixture preimage mismatch: {text.count(old)}")
