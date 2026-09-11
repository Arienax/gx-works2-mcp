# Generation result delivery and manual preview refresh

The job terminal state records worker completion; it does not assert that an
approach-mismatched candidate is acceptable. Read the persisted job output to
resolve its proposal or explicitly blocked diagnostic result. No synthetic
approval, empty-program fallback, or second model call is used to show a diagram.

The toolbar button **刷新结果 / 重绘梯形图** reads the exact proposal/job/version
and invokes the existing Python validator, IR-to-ladder conversion and SVG
renderer in process. It does not execute user-selected Python files or shell
commands. For a proposal, the frozen private payload hash is checked first. For
blocked generation output and modern saved versions, the recorded IR hash is
checked. Every diagram is rendered after structural and IR consistency validation.

The response is a display-only projection (no-store HTTP), not a new saved
version. Normal proposal reads now re-render in memory rather than trusting a
possibly incomplete SVG cache. A missing saved SVG can be displayed again from
canonical IR without rewriting original project files. The current theme is
applied in memory. No API key, model call, native GX action or automatic acceptance
is involved. A blocked approach may be inspected in a clearly labelled diagnostic
view; it has no acceptance/import controls. Read-only browsing stays read-only.

The client keeps preview state across project metadata refreshes, reads results
when polling reports completion even if SSE is absent, tracks successful preview
loads instead of marking a failed request as shown, and exposes explicit retry.
Project and preview epochs reject stale responses. Accepted proposals follow
their saved version instead of reopening as pending candidates after a reload.

Validation uses the real HTTP app, job manager, proposal store, renderers and a
Chromium browser. Only model replies are deterministic fixtures. Scenarios cover
analysis/confirmation/generation, blocked approaches, delayed reads, failed reads,
SSE loss, visible SVG pixel decoding, explicit acceptance, reload, missing SVG
recovery and proof that manual refresh never calls the model or mutates a version.
This is not proof of arbitrary generated PLC logic or native GX/hardware safety.

For a separate, explicitly authorized live API exercise on a Windows development
machine, install `requirements/web.txt` and Playwright, build `web/dist` with
`build-web.bat`, then run:

    python scripts/web_generation_e2e.py --live

The API key is read from DEEPSEEK_API_KEY or a hidden prompt, never a CLI argument
or repository file. The script creates a temporary workspace, limits model
requests, records only safe outcome/token counts, and never operates GX or a PLC.
