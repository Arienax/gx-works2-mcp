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


def test_completed_generation_switches_to_its_new_version_id():
    sse = _between("stream.onmessage = (event) => {", "return () => {\n      stopped = true;\n      stream.close();")
    assert 'savedVersionId' in sse
    assert 'openSavedVersion(savedVersionId)' in sse
    saved_effect = _between('const saved = currentJob?.result?.version_id;', 'async function openGenerationResult(')
    assert 'currentJob?.kind === "generation"' not in saved_effect
    assert 'openSavedVersion(saved)' in saved_effect

def test_generation_result_fallback_yields_to_persisted_version_switch():
    auto = _between('useEffect(() => {\n    if (!session || busy || loading || specDirty.current ||', 'useEffect(() => {\n    const saved = currentJob?.result?.version_id;')
    assert 'typeof currentJob.result?.version_id === "string"' in auto
