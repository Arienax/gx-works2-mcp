from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src/application/workbench.py"
text = path.read_text(encoding="utf-8")
old = '''        record_id(request_id, "request")\n        with self.lock.thread_lock:\n            if not self.jobs:\n                raise KeyError(job_id)\n            record = self.jobs._load(record_id(job_id, "job"))\n'''
new = '''        record_id(request_id)\n        with self.lock.thread_lock:\n            if not self.jobs:\n                raise KeyError(job_id)\n            record = self.jobs._load(record_id(job_id))\n'''
if text.count(old) != 1:
    raise SystemExit(f"repair id validation anchor mismatch: {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
print("fixed Workbench repair resource id validation")
