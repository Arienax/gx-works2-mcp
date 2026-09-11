from __future__ import annotations

import runpy
import sys
from pathlib import Path

module = runpy.run_path("scripts/_bootstrap_gx_send_delete.py", run_name="bootstrap_gx_send_delete")
module["OPS"][:] = [item for item in module["OPS"] if item[0] != "app"]
sys.argv = ["_bootstrap_gx_send_delete.py", ".", "--no-tests"]
result = module["main"]()
if result:
    raise SystemExit(result)

path = Path("web/src/App.tsx")
text = path.read_text(encoding="utf-8")
old = '''  const displayedJobStatus = currentJob?.kind === "generation" && currentJob.status === "completed"
    ? generationResult.blocked ? "contract_mismatch"
      : generationResult.versionId ? "saved"
      : generationResult.proposalId ? "candidate_ready"
      : generationResult.loading ? "loading_result" : "result_unavailable"
    : currentJob?.status;
'''
new = '''  const displayedJobStatus = currentJob?.kind === "execution" && currentJob.status === "completed" &&
    ["failed", "interrupted", "conflict"].includes(String(currentJob.result?.status || ""))
    ? "failed"
    : currentJob?.kind === "generation" && currentJob.status === "completed"
      ? generationResult.blocked ? "contract_mismatch"
        : generationResult.versionId ? "saved"
        : generationResult.proposalId ? "candidate_ready"
        : generationResult.loading ? "loading_result" : "result_unavailable"
      : currentJob?.status;
'''
if new not in text:
    if text.count(old) != 1:
        raise RuntimeError("App.tsx displayedJobStatus preimage mismatch")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print("[ok]   app: execution failure overrides completed display status")
else:
    print("[skip] app status fix already applied")
