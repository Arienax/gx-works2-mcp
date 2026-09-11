from pathlib import Path

root = Path(__file__).resolve().parents[1]
api = root / "src/api.py"
text = api.read_text(encoding="utf-8")
start_marker = "def _build_knowledge_context(\n"
end_marker = "\ndef load_config():\n"
if text.count(start_marker) != 1 or text.count(end_marker) != 1:
    raise RuntimeError("knowledge context function markers changed")
start = text.index(start_marker)
end = text.index(end_marker, start)
block = text[start:end]
if "retrieval_query" in block:
    block = block.replace("retrieval_query", "query")
    text = text[:start] + block + text[end:]
    api.write_text(text, encoding="utf-8", newline="\n")
    print("applied: clear stale retrieval_query from analysis wrapper")
else:
    print("skip: analysis wrapper already uses canonical query")

verified = api.read_text(encoding="utf-8")[start:end]
if "retrieval_query" in verified:
    raise RuntimeError("stale retrieval_query remains in _build_knowledge_context")
