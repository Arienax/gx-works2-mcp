# Generation fast path: confirmed specification is the semantic authority

## Decision

For the direct Web/Qt generation flow, once the operator has confirmed the specification, the application does **not** reinterpret the request with a second set of heuristic semantic gates.

The direct generation critical path is:

1. confirmed specification and current project context,
2. one model generation (stream transport may fall back once to non-stream transport),
3. JSON/ST parsing and model-facing protocol normalization,
4. structural/processability validation,
5. deterministic PLC IR construction and IR consistency validation,
6. artifact rendering and local version save.

There is no automatic semantic re-generation loop after step 2.

## What can block direct generation

`generation_structural` validation is deliberately narrow. It can reject a candidate when the application cannot safely represent or process it, including:

- malformed JSON or wrong top-level response shape;
- unsupported ladder element encoding;
- invalid device/address syntax or out-of-range address;
- an instruction absent from the verified instruction registry, unsupported by the selected CPU, or encoded with invalid arity;
- writes to CPU-owned read-only targets;
- duplicate/invalid rung identifiers;
- an invalid partial-edit envelope or an explicit repair scope escape;
- internally stale/inconsistent PLC IR.

These are representation/tooling facts, not a second interpretation of user intent.

## What no longer blocks direct generation

The following remain useful for Review, diagnostics, simulator planning and GX/runtime evidence, but they do not reject a direct candidate after specification confirmation:

- `selected_approach.generation_contract` conformance;
- prose/regex-derived execution semantics;
- inferred edge/first-scan/cyclic intent;
- duplicate-coil style/ownership findings;
- timer-oscillation style rules;
- same-scan SET/RST toggle findings;
- M8029 topology preferences;
- confirmed hardware-family heuristics beyond the model-facing instruction/address contract.

The application still computes IR analysis metadata. It does not turn those findings into a hidden model retry.

## No hidden repair loop

A structurally invalid model response fails once with diagnostics. Direct generation does not call the model up to three additional times to satisfy local semantic validators.

A streaming transport failure may make one ordinary non-streaming request for the same candidate. This is a transport fallback, not a code/semantic repair.

Explicit Debug/patch/contract-repair tools keep their evidence and scope boundaries. They are separate workflows and do not silently run after normal generation.

## Validation profiles

- `generation_structural`: direct confirmed-spec generation. Persisted versions retain this profile so reload/preview verifies IR integrity without retroactively applying semantic gates.
- `strict`: existing Agent patch, Debug, review/execution-oriented validation unless that workflow explicitly chooses otherwise.

This prevents a version that was intentionally accepted through the direct generation fast path from becoming unreadable merely because a later load path invokes the historical strict validator.

## Product responsibility boundary

- Requirement meaning: model + operator during specification confirmation.
- Candidate implementation: model using the confirmed specification.
- Representation integrity: deterministic parser/schema/IR code.
- Engineering quality findings: optional Review/static analysis.
- Behavior correctness: simulator/Factory I/O/regression evidence.
- Native legality: GX/compiler/runtime evidence.

A review warning is not promoted to a generation failure merely because it can be expressed as a deterministic rule.
