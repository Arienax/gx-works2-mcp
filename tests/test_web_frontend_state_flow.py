from pathlib import Path

APP = (Path(__file__).parents[1] / "web" / "src" / "App.tsx").read_text(encoding="utf-8")

def _between(start: str, end: str) -> str:
    return APP.split(start, 1)[1].split(end, 1)[0]

def test_existing_confirmed_project_defaults_to_generation_edit_mode():
    assert "composerProjectRef.current !== value.id" in APP
    assert "value.confirmed_spec && (value.versions?.length || 0) > 0" in APP

def test_job_completion_is_silent():
    sse = _between("stream.onmessage = (event) => {", "return () => {\n      stopped = true;\n      stream.close();")
    assert "reloadProjectSilently(value.project_id)" in sse
    assert "setRefresh(" not in sse

def test_submit_generation_does_not_force_global_refresh():
    submit = _between("async function submitJob(", "async function saveSpec(")
    assert "kind === \"generation\" && !canGenerate" not in submit
    assert "refreshAll()" not in submit

def test_confirmed_analysis_continues_to_generation_without_global_refresh():
    save = _between("async function saveSpec(", "async function showProposal(")
    assert "generateAfterSave" in save
    assert "await submitJob(\"generation\")" in save
    assert "refreshAll()" not in save

def test_silent_reload_does_not_block_editor():
    silent = _between("async function reloadProjectSilently(", "async function refreshDrawing(")
    assert "setLoading(" not in silent
