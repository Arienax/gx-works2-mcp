# GXWorks Agent

[简体中文](README.zh-CN.md) | English

> **AI engineering agent for Mitsubishi MELSEC PLC programming, validation, project editing, simulation, diagnostics, and GX Works2 integration.**  
> Natural language → confirmed control specification → PLC IR → deterministic validation → GX Works2 / GXW → simulation evidence.

![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6.svg)
![PLC](https://img.shields.io/badge/demo-FX3U-orange.svg)
![Status](https://img.shields.io/badge/status-active%20development-yellow.svg)

<p align="center">
  <img src="resources/assets/demo.gif" alt="GXWorks Agent demo" width="1200">
</p>

**GXWorks Agent** is an experimental AI engineering workbench for Mitsubishi MELSEC PLC development.

It is designed around a simple rule: **LLM output is not treated as an engineering result by itself.** Natural-language requests are converted into structured specifications and PLC representations, checked by deterministic validators, reviewed as versioned candidates, and only then allowed to cross controlled boundaries into GX Works2 or GX Simulator2.

The current implementation is focused on **FX3U + GX Works2**. It supports the mature Ladder CSV workflow and an actively developed native **GXW / Structured Ladder / FBD** workflow.

---

## Quick start

### Windows Web workbench

For the packaged Windows release, extract the complete `GXWorks-Agent-Web` directory and double-click:

```text
start-web.cmd
```

Choose a workspace folder and then select:

- **Read-only** to inspect an existing workspace without creating or migrating versions.
- **Engineering edit** to create projects, confirm specifications, generate candidates, accept versions, and approve controlled GX operations.

The launcher opens a local browser session after the backend is ready. Keep the service window open while using the workbench and press `Ctrl+C` in that window to stop it.

The packaged Web release does not require a separate Python, Node.js, or Qt installation.

Starting the workbench does **not** automatically start GX Works2, GX Simulator2, a simulator gateway, or a physical PLC connection.

See [Web workbench guide](docs/integrations/web.md) for source installation, approval boundaries, workspace locking, MCP service mode, and Windows integration details.

### Source installation

```powershell
git clone https://github.com/Arienax/gxworks-agent.git
cd gxworks-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python src\main.py
```

For the Web source build:

```powershell
python -m pip install -r requirements-web.txt
Push-Location web
npm ci
npm run build
Pop-Location
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m integrations.web --workspace "D:\PLCWorkspaces\my-workspace" --port 8765 --open-browser
```

Run the test suite with:

```powershell
pytest -q
```

A Windows 7 compatibility dependency set is also retained:

```powershell
pip install -r requirements-win7.txt
```

API keys are stored in Windows Credential Manager rather than committed into repository configuration files.

---

## Current capability status

| Capability | Status |
| --- | --- |
| Natural-language requirement analysis | ✅ Available |
| Confirmed control specification workflow | ✅ Available |
| PLC Intermediate Representation (PLC IR) | ✅ Available |
| Deterministic PLC validation | ✅ Available |
| Ladder SVG preview | ✅ Available |
| Ladder CSV generation | ✅ Available |
| GX Works2 CSV import / export | ✅ Available |
| Program and device-comment synchronization | ✅ Available |
| Network-level Patch / Diff / versioning | ✅ Available |
| External-change detection and conflict protection | ✅ Available |
| FX3U manual / engineering knowledge retrieval | ✅ Available |
| Structured engineering Tool Runtime | ✅ Available |
| Local Web engineering workbench | ✅ Available |
| Persistent jobs, proposals, approvals, and recovery | ✅ Available |
| GXW project inspection and round-trip writing | 🧪 Experimental |
| Structured Ladder / FBD generation | 🧪 Experimental |
| Structured Ladder / FBD object, wire, and declaration editing | 🧪 Experimental |
| GXW import, preview, version acceptance, and download | 🧪 Experimental |
| GX Works2 opening of approved GXW copies | 🧪 Experimental |
| Structured Text generation | 🧪 Experimental |
| GX Simulator2 automated test planning / execution | 🧪 Experimental |
| Evidence-bound debug planning and local patch generation | 🧪 Experimental |
| Standalone MCP Server (stdio) | ✅ Available |
| MCP service bridge into the running Web workbench | ✅ Available |
| Native automated GXW compile command | 🚧 Not complete |
| FBD simulation / diagnostics | 🚧 Not complete |
| Full arbitrary GXW / IEC FBD support | 🚧 Not complete |
| GX Works3 adapter | 📋 Planned |
| Physical PLC write path | 📋 Not exposed by the current Web workflow |

> Status labels are intentionally conservative. “Experimental” means that a controlled implementation and test evidence exist, but the capability is not yet a universal production backend across arbitrary PLC programs, GX versions, or CPU models.

---

## Why GXWorks Agent exists

A conventional LLM workflow often stops here:

```text
Prompt
  ↓
LLM
  ↓
PLC code
```

GXWorks Agent instead maintains explicit engineering state:

```text
Natural-language requirement
          ↓
Requirement analysis
          ↓
Confirmed control specification
          ↓
PLC IR / structured program model
          ↓
Deterministic validation
          ↓
Versioned candidate + Diff
          ↓
Operator approval
          ↓
GX Works2 / GXW
          ↓
Simulation / evidence / diagnosis
```

This separation allows the system to reason with an LLM while keeping program state, validation, versioning, approvals, and external side effects under deterministic application control.

---

## Example

Describe the required machine behavior directly:

```text
X0 starts the motor.
X1 stops the motor.
Y0 drives the motor contactor.

The motor must latch after the start button is released.
Stop has priority over start.

When X2 detects a workpiece,
stop the motor after 3 seconds.

After power recovery, the motor must not restart automatically.
```

The analysis stage can turn that request into a **reviewable control specification** containing the selected programming approach, clarification questions, parameters, and I/O assignment.

The program is generated only after the specification is explicitly confirmed.

---

# Web engineering workbench

The current Web frontend is a local React/Vite interface backed by FastAPI. PLC semantics stay in the existing Python engineering core; the browser is an operator surface rather than a second implementation of PLC logic.

The workbench currently provides:

- project and version navigation
- Ladder, FBD, ST, diagnostics, review reports, and simulation views
- natural-language analysis / generation / agent tasks
- editable confirmed specifications
- persistent job progress and reconnectable event history
- candidate proposal review and Diff inspection
- explicit approval for local acceptance, GX import, simulation, and debug execution
- model configuration and connection testing
- GX environment observation
- GXW import and FBD editing
- local read-only mode for existing workspaces

Jobs continue in the backend if the browser is refreshed or closed. Their project, base version, confirmed specification, model settings, and response-language policy are frozen when submitted.

Proposal approval is version-bound and hash-bound. A stale browser tab cannot silently approve a candidate against a newer active version.

---

# Confirmed specification

GXWorks Agent does not assume that the first natural-language prompt is a complete PLC requirement.

The analysis workflow can produce a specification draft containing:

- requirement summary
- candidate programming approaches
- clarification questions and selectable answers
- parameters and suggested defaults
- I/O assignment
- user notes

The user confirms this specification before generation. Generated candidates are then bound to the confirmed specification hash and base version.

This is intended to reduce a common failure mode of AI-generated PLC programs: producing syntactically plausible logic for an underspecified control problem.

---

# PLC Intermediate Representation

The internal **PLC IR** is the semantic layer between model output and engineering operations.

```text
                    ┌─ Ladder CSV
                    ├─ Structured Text
AI → PLC IR ────────┼─ SVG preview
                    ├─ Validation
                    ├─ Static analysis
                    ├─ Diff / Patch
                    ├─ Test planning
                    └─ GX Works2 adapter
```

PLC IR represents engineering information such as:

- networks
- PLC instructions
- devices
- timers and counters
- reads and writes
- execution triggers
- revisions
- static findings
- I/O mapping
- semantic requirements
- deterministic rendering
- Diff and incremental Patch operations

The model therefore does not need to regenerate the entire program as free-form text for every change.

---

# Deterministic validation and review

The model is not trusted to declare its own PLC program correct.

Candidates can be checked by deterministic local code for issues such as:

- structural validity
- device and address legality
- PLC-specific instruction constraints
- timer / counter structure
- Network structure
- I/O references
- read / write dependencies
- confirmed-spec consistency
- multiple writers
- latch/reset ownership
- unreachable or dead-end state behavior
- timer completion paths
- common Ladder logic risks

The review pipeline runs local deterministic inspection first. A deeper AI review can optionally add specialist analysis, but local findings are preserved even if the model call is unavailable or fails.

```text
Candidate
   ↓
Local deterministic inspection
   ↓
Optional AI specialist review
   ↓
Merged evidence-backed report
```

Review output is version-bound and can include severity, evidence, affected addresses, rung/network locations, and suggested next actions.

---

# Incremental modification and versioning

Existing programs do not have to be regenerated from scratch.

```text
Current PLC IR
      ↓
Modification request
      ↓
Network Patch
      ↓
Candidate revision
      ↓
Validation
      ↓
Diff
      ↓
Operator approval
      ↓
Accepted version
```

For example:

```text
Make the stop logic stop-priority.
Do not modify any other Network.
```

The current Web workbench maintains explicit project versions. Candidate acceptance creates a new local version; it does **not** imply that the program has been imported, compiled, or simulated in GX Works2.

---

# GX Works2 Ladder integration

The most mature GX Works2 backend remains the **Ladder CSV import / export workflow**.

Current capabilities include:

- Ladder CSV generation
- device-comment CSV generation
- GX Works2 import / export
- program synchronization
- comment synchronization
- automatic backup before overwrite
- synchronization baselines
- detection of external manual edits
- conflict protection
- optional round-trip verification

If GXWorks Agent detects that a GX Works2 program was manually changed after the last synchronization baseline, it stops rather than silently overwriting the engineer’s changes.

Some GX Works2 operations still depend on GUI automation and therefore remain sensitive to GX version, language, desktop state, and Windows session conditions.

---

# Native GXW / Structured Ladder / FBD workflow

GXWorks Agent now contains an experimental native **GXW project pipeline** for GX Works2 Structured Ladder / FBD.

This work is based on reverse engineering with controlled GX Works2 compile / save / reopen experiments. It is intentionally limited to structures with evidence rather than assuming undocumented fields are understood.

The current pipeline can:

- inspect selected `Program.pou` records inside GXW projects
- preserve unrelated POU data, metadata, and unknown records
- generate an FX3U GXW project from supported Structured Ladder / FBD objects
- edit supported objects and orthogonal connections
- edit known local and global declarations
- keep FB instance declarations synchronized for supported FB calls
- preserve unsupported imported records instead of rewriting them blindly
- grow CFB MiniFAT / FAT / DIFAT allocation when modified streams expand
- update required GXW history size and MD5 metadata
- generate `fbd.json`, `fbd.svg`, GXW, and write reports
- import GXW files into the Web workbench
- preview the result as a proposal
- accept the candidate as a versioned local artifact
- download the accepted GXW
- open an approved copy in GX Works2 through the controlled execution queue

Supported generated templates currently include, among others:

- normally-open contact
- normally-closed contact
- coil
- input / output terminals
- `MOV`
- `TON`
- `TON_E`
- `CTU`
- `CTU_E`
- selected saved Function / Function Block ABI templates

Native controlled experiments currently include examples that compile and survive GX Works2 save / reopen round trips. A relay-parallel conversion example still retains a known `C2034` warning, and this is not hidden by the application.

Important limitations remain:

- arbitrary custom libraries, structures, and unknown FB ABIs are not generically synthesized
- imported GXW CPU identification is not complete
- arbitrary IEC FBD semantics are not implemented
- multiple independent Ladder-block encoding rules are not fully generalized
- native automatic compile invocation is not complete
- FBD simulation, diagnostics, and CSV synchronization are not yet connected

For the latest engineering evidence and boundaries, see:

- [`docs/research/gxw_declarations_allocation_web_fbd_20260910.md`](docs/research/gxw_declarations_allocation_web_fbd_20260910.md)
- [`docs/research/gxw_project_write_pipeline_20260910.md`](docs/research/gxw_project_write_pipeline_20260910.md)

---

# GX Simulator2 testing

GXWorks Agent can build version-bound simulator test plans from the current PLC program.

```text
PLC program
     ↓
AI test planning
     ↓
Deterministic Test DSL normalization
     ↓
Saved version-bound plan
     ↓
Operator approval
     ↓
GX Simulator2 execution
     ↓
Trace + assertions
     ↓
Saved evidence
```

The test planner can use:

- I/O mapping
- program devices
- Network instructions
- read / write dependencies
- execution triggers
- state machines
- semantic requirements
- selected static findings

The Test DSL can represent timed stimuli, expectations, waits, invariants, trace devices, and supported fault injections.

Simulation is still an **experimental capability**. Real GX Simulator2 execution requires the supported Windows environment and installed Mitsubishi software.

The simulator gateway is deliberately isolated from physical PLC access.

Current safety design includes:

- localhost-only communication
- per-process authentication
- fixed GX Simulator2 target
- controlled device writes
- no physical PLC connection path exposed through the simulator gateway

See [`simulator_gateway/README.md`](simulator_gateway/README.md).

---

# Evidence-bound debugging

Failed simulation runs can be turned into a version-bound debug plan.

The current debug workflow can:

1. load the exact PLC IR and saved failed simulation run
2. build failure evidence and reverse-dependency context
3. ask a diagnosis specialist to analyze the evidence
4. ask a patch specialist to propose a local Network patch
5. validate and persist the plan before any execution
6. require separate approval before running the debug action

This keeps diagnosis and modification tied to the exact program version and failure evidence rather than to a free-form chat description alone.

A fully automatic `compile → diagnose → repair → regression` loop is not yet complete.

---

# FX3U engineering knowledge retrieval

GXWorks Agent includes local retrieval over FX3U manuals and engineering knowledge.

It can support queries about:

- PLC instructions
- device constraints
- programming rules
- troubleshooting information

The repository contains a **220-case retrieval benchmark** in [`benchmarks/`](benchmarks/).

| Metric | Result |
| --- | ---: |
| Cases | 220 |
| Recall@1 | 86.27% |
| Recall@5 | 98.04% |
| Recall@10 | 100% |
| MRR | 0.9033 |
| Negative accuracy | 100% |
| Mean latency | 58.2 ms |

Current report:

[`benchmarks/fx3u_rag_benchmark_report.json`](benchmarks/fx3u_rag_benchmark_report.json)

> These are internal retrieval metrics. They do not represent end-to-end PLC program correctness or safety on real equipment.

---

# Engineering Agent and tool boundary

GXWorks Agent includes a tool-calling PLC engineering agent.

The agent receives structured engineering tools rather than unrestricted low-level computer control.

Representative tools include:

```text
get_current_project
get_current_program_info
read_network
search_plc_manual
get_diagnostics
validate_project
compile_project
patch_program
validate_current_program
import_current_program_to_gxworks2
```

The architecture is intentionally layered:

```text
AI Agent
   ↓
Engineering Tools
   ↓
Tool Runtime
   ↓
PLC Core
   ├─ PLC IR
   ├─ Validator
   ├─ Knowledge Retrieval
   ├─ Session / Version Store
   └─ GX Works2 adapters
```

Arbitrary mouse input, unrestricted file deletion, physical PLC writes, and unrestricted device forcing are not exposed as generic primitives to the model.

---

# MCP integration

**MCP is one external interface to GXWorks Agent, not the identity of the project itself.**

The standalone stdio MCP server exposes high-level engineering tools backed by the same `ToolRuntime` used by the built-in agent.

```text
Built-in Agent ↔ ModelProvider
      │
      └──────────────────────────┐
                                 ↓
External MCP Client → MCP Server → ToolRuntime → PLC Core
```

Two MCP modes are supported:

### Standalone workspace mode

The MCP server reads an explicitly selected workspace and exposes engineering tools without starting the desktop UI or model provider.

### Web service bridge mode

An external MCP client can connect to the running local Web service with a dedicated Agent token.

In this mode, an external agent can submit a candidate proposal into the Web workbench, but **cannot approve its own proposal or bypass operator-only routes**.

See [`docs/integrations/mcp.md`](docs/integrations/mcp.md) and [`docs/integrations/web.md`](docs/integrations/web.md).

---

# Model support

The built-in agent uses a provider-independent `ModelProvider` abstraction.

Current built-in configuration supports:

| Provider | Status |
| --- | --- |
| DeepSeek via OpenAI-compatible transport | ✅ |
| Zhipu GLM via OpenAI-compatible transport | ✅ |
| Custom OpenAI-compatible API | ✅ |
| Anthropic native API | 🚧 Planned |
| Gemini native API | 🚧 Planned |

External AI systems such as Codex-compatible or other MCP-capable clients can interact with GXWorks Agent through the MCP interface without being hard-wired into the PLC core.

Model providers are deliberately separated from engineering state. Program versions, validation, approvals, and GX operations therefore do not depend on one LLM vendor.

---

# Safety and approval model

GXWorks Agent separates local program acceptance from external execution.

| Approval action | What it authorizes | What it does **not** prove |
| --- | --- | --- |
| `accept_local` | Accept the frozen candidate as a local version | No GX import, compile, simulation, or PLC write |
| `gx_import` | Import Ladder CSV or open an approved GXW copy in GX Works2 | Import/open success is not native compile success |
| `simulation` | Run a saved version-bound test plan | Only saved execution evidence can be treated as a run result |
| `debug` | Execute a version/evidence-bound debug plan | Cannot bypass candidate hashes, version binding, or regression checks |

The Web backend serializes real GX desktop operations through a dedicated execution coordinator and cross-process desktop lock.

Interrupted external operations are marked as interrupted and require operator inspection. They are not automatically replayed after restart.

---

# Current validation boundary

The repository contains extensive automated regression coverage and controlled GXW reverse-engineering experiments, but several integration claims still require real Windows / Mitsubishi software validation.

Important remaining acceptance areas include:

- end-to-end GX Works2 import / read / synchronization on supported production setups
- real GX Simulator2 execution and saved evidence
- debug rollback and regression behavior
- lock-screen and RDP interruption cases
- ordinary-user packaged-launch interaction
- broader GXW / CPU / instruction coverage
- FBD simulation and diagnostics

Offline test success must not be interpreted as a substitute for those real-environment checks.

See [`docs/architecture/web-migration-checklist.md`](docs/architecture/web-migration-checklist.md) for the current acceptance matrix.

---

# Repository structure

```text
src/                         PLC core, workflows, adapters, application services
web/                         React/Vite Web workbench
simulator_gateway/           isolated GX Simulator2 gateway
benchmarks/                  retrieval and agent-routing benchmarks
docs/integrations/           Web, MCP, Codex and integration documentation
docs/architecture/           architecture and migration records
docs/research/               GXW reverse-engineering evidence and findings
research/                    controlled GXW models, results, and evidence helpers
tests/                       deterministic regression suite
tools/                       GXW and engineering utilities
```

---

# Development principles

The project currently follows several engineering rules:

1. **LLM reasoning is not the source of engineering truth.** Deterministic code owns validation and application state.
2. **Program changes are versioned candidates.** External side effects require explicit approval.
3. **Unknown GXW structures are preserved rather than guessed.** Native generation is limited to evidence-backed layouts and ABIs.
4. **Simulation evidence is kept separate from physical PLC access.** The simulator gateway has no physical PLC path.
5. **A successful import/open operation is not called a successful compile.** Status reporting keeps these stages separate.
6. **Unsupported programs fail explicitly.** The system does not silently relax validation just to keep an AI workflow running.

---

# Roadmap

Near-term work is concentrated on making the existing engineering loop more complete rather than simply adding more LLM output formats:

- richer interactive program inspection and dependency navigation
- stronger issue-to-network / issue-to-test traceability
- editable simulation plans and clearer trace visualization
- native GXW compile feedback and round-trip evidence capture
- broader evidence-backed Structured Ladder / FBD support
- FBD simulation and diagnostics
- safer real-device observation and future controlled PLC integration
- GX Works3 adapter

---

# License

This project is licensed under the [Apache License 2.0](LICENSE).

Mitsubishi Electric, MELSEC, GX Works2, GX Works3, GX Simulator2, and MX Component are trademarks or products of Mitsubishi Electric Corporation. This repository is not affiliated with or endorsed by Mitsubishi Electric and does not redistribute Mitsubishi proprietary software.
