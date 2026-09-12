"""Source Web entrypoint contract without running npm, pip, or GX software."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_build_web_prepares_python_runtime_by_default():
    text = (ROOT / "build-web.bat").read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "-m venv" in text
    assert "requirements\\web.txt" in text
    assert "pip install -r" in text
    assert "import fastapi, uvicorn, openai, numpy, mcp" in text
    assert "--frontend-only" in text
    assert "Source Web runtime is ready. You can now run start-web.cmd." in text


def test_start_web_resolves_source_or_locally_built_package():
    text = (ROOT / "scripts" / "start_web.ps1").read_text(encoding="utf-8-sig")
    assert '.venv\\Scripts\\python.exe' in text
    assert 'dist\\GXWorks-Agent-Web\\GXWorks-Agent-Web.exe' in text
    assert '$backendKind = "source"' in text
    assert '$backendKind = "built-package"' in text
    assert '请先运行根目录 build-web.bat' in text
