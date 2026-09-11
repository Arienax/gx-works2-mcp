# Workbench approvals and automatic saving

Web user requests to generate or edit programs, import a GXW, convert to FBD or
read a GX program now save a validated program immediately. The existing
transaction service still checks candidate hashes, the confirmed specification,
base-version binding and artifacts before activating an immutable version.
There is no second "accept local version" interaction in the normal flow.
Internal transaction records remain for audit, replay protection and recovery;
old pending drafts can still be opened and saved explicitly. Failed validation
and approach conflicts never become saved/active programs in any mode.

The workspace settings screen exposes three execution-consent modes:

- `ask` (default): explicit review of GX import, simulation and debug execution.
- `auto`: deterministic delegation of version-bound simulation/debug plans;
  standalone GX import still requires user review. It is not a second AI judge.
- `full`: delegate all three existing external actions, after a specific settings
  confirmation. It does not introduce arbitrary shell, file or real PLC writes.

Direct UI local saves are independent of these external-action approvals.
Connected HTTP Agent clients keep manual candidate approval under `ask`; under
`auto`/`full` the user delegates those existing local tools as well. Standalone
MCP retains its original tool registry and confirmation boundaries.

Policy changes use an expected revision, are written per workspace and cannot
be changed by an Agent credential. Changes do not execute previously pending
requests. A queued delegated action rechecks its policy revision and frozen
proposal inputs before any external effect. Downgrading prevents an unstarted
automatic action; it cannot undo an operation already in progress. No permission
mode skips PLC validators, immutable input checks, model response validation or
exclusive workspace/desktop locks.

Normal Windows startup selects only a workspace. The legacy `--read-only` /
`-ReadOnly` flag remains an explicitly requested recovery mechanism, not a role
picker. A random loopback session link opens automatically; Host/Origin/CSRF and
cross-site request protections remain. These prevent unrelated websites from
calling local APIs; they are not an operating-system security boundary against
a process already running as the same Windows user.

The project toolbar groups file exports, GX read/send, and utilities. CSV,
comments, SVG, IR, JSON, ST and supported GXW artifacts use their actual manifest,
not a claim that every mode can export every format. Exports are visible at the
top and require no GX connection. One refresh icon also rebuilds ladder previews.
Import/conversion/synchronization and history activation live in More. The
header shows the current approval mode; only Settings can change it. Responsive
controls wrap instead of being cropped by the side panels.
