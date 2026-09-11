from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = [
    root / "tools/import_design_patterns.py",
    root / "tools/build_dense_embeddings.py",
]

for path in files:
    text = path.read_text(encoding="utf-8")
    old = '''    manifest_path.write_text(\n        json.dumps(manifest, ensure_ascii=False, indent=2) + "\\n",\n        encoding="utf-8",\n    )\n'''
    if old in text:
        new = '''    manifest_path.write_bytes(\n        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\\n").encode("utf-8")\n    )\n'''
        text = text.replace(old, new, 1)
    else:
        old_compact = '''    manifest_path.write_text(\n        json.dumps(manifest, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8"\n    )\n'''
        if old_compact not in text:
            raise RuntimeError(f"manifest writer anchor changed: {path}")
        new_compact = '''    manifest_path.write_bytes(\n        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\\n").encode("utf-8")\n    )\n'''
        text = text.replace(old_compact, new_compact, 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"applied: LF-stable manifest writer in {path.name}")
