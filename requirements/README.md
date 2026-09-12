# Optional dependency sets

The root `requirements.txt` remains the retained Qt desktop development environment.
Additional environments are kept here so the repository root stays focused on user-facing entry points and project metadata.

- `web.txt` — FastAPI/Web runtime used by the local Web workbench and Web packaging; it also includes the MCP SDK because the Windows Web release now builds `gxworks-agent-mcp.exe` beside the workbench.
- `mcp.txt` — minimal standalone/headless MCP SDK environment for source-only MCP use.
- `win7.txt` — retained Windows 7 / PyQt5 desktop compatibility environment.
- `gxw-test.txt` — optional independent MS-CFB reader used by GXW allocator regression tests.
