# GX Works2 Structured Ladder/FBD write-back validation

> Status: experimentally validated, deliberately narrow write path.
>
> Date: 2026-09-07
>
> Scope: FX3U / GX Works2 Structured Ladder/FBD controlled sample 48 only. This note records an observed write-back result; it does not claim a general-purpose `.gxw` writer yet.

## Purpose

The existing reverse-engineering work established a deterministic read path:

```text
GXW
  -> outer CFB
  -> nested `_hdb` CFB
  -> `projectdatalist.xml` logical-object resolution
  -> `*.Program.pou`
  -> Structured Ladder/FBD node/wire parser
```

The next unknown was whether GX Works2 would accept an externally modified Structured Ladder/FBD `Program.pou` after it was written back through both CFB layers.

This experiment tested the smallest possible mutation while keeping every stream and record size unchanged.

## Test case

Source project:

```text
48_STRUCT_X1_Y1.gxw
```

Original visible program:

```text
X1 -> Y1
```

Mutation:

```text
X1 -> X2
```

The target contact symbol is stored directly in the Structured Ladder node record as UTF-16LE text. Because `X1` and `X2` have the same encoded length, the test does not require any change to:

- node `record_length`;
- `symbol_char_count`;
- Program.pou body size;
- header fields at `0x37`, `0x3B`, or `0x47`;
- record count;
- nested `_hdb` stream length;
- outer `_hdb` stream length.

This isolates the question of whether the saved editor model can be externally modified and accepted by GX Works2 without another mandatory source-level integrity update.

## Write-back path

The tested path was:

```text
48_STRUCT_X1_Y1.gxw
  -> read outer CFB `_hdb` stream
  -> open `_hdb` as nested CFB
  -> resolve `1.Program.pou` through existing logical-object mapping
  -> parse Structured Ladder/FBD program
  -> locate the node whose symbol is `X1`
  -> replace only that node's UTF-16LE symbol bytes with `X2`
  -> write the unchanged-size Program.pou stream back into nested `_hdb`
  -> write the unchanged-size `_hdb` stream back into the copied outer GXW
  -> 48_STRUCT_X2_Y1_PATCHED.gxw
```

The mutation was node-targeted rather than a whole-file/global byte replacement.

## Observed GX Works2 result

The generated project was opened directly in GX Works2.

Observed behavior:

1. GX Works2 opened the patched `.gxw` successfully.
2. The Structured Ladder/FBD editor displayed `X2` in place of the original `X1`.
3. The project was saved successfully in GX Works2.
4. GX Works2 was closed.
5. The saved project was reopened successfully.
6. The editor still displayed `X2 -> Y1` after the save/close/reopen cycle.

The save/reopen result is important because GX Works2 itself accepted and reserialized the externally modified project rather than merely rendering it once.

## Established conclusion

For the tested sample and equal-length node-symbol mutation:

```text
external Program.pou mutation
  -> nested CFB write-back
  -> outer GXW write-back
  -> GX Works2 open
  -> GX Works2 save
  -> close
  -> reopen
```

is a valid path.

This is direct evidence that `*.Program.pou` is writable editor-source state for this Structured Ladder/FBD case, not merely a read-only cache or display artifact.

It also shows that no additional undiscovered project-level source checksum/hash update was required for GX Works2 to open, save, and reopen this specific unchanged-size mutation.

The conclusion must remain scope-limited. It does **not** yet prove that:

- variable-length Program.pou mutations are valid;
- records can be inserted or deleted safely;
- arbitrary node/wire graphs can be generated from scratch;
- nested or outer CFB streams can be resized without additional work;
- all GX Works2 versions or PLC families behave identically;
- compile-derived objects such as `MAIN.res` never require synchronization for later compile/runtime workflows.

## Milestone status

The Structured Ladder/FBD reverse-engineering status can now be separated into two capabilities:

```text
Read path: validated for the currently covered controlled samples

Write path: validated only for same-size node-symbol mutation
```

The project is therefore no longer strictly read-only at the research level, but the production implementation should still treat general `.gxw` writing as experimental until variable-size serialization and CFB resizing are validated.

## Next falsifiable write tests

The next experiments should increase one variable at a time.

### 1. Variable-length symbol

```text
X1 -> X100
```

This requires rebuilding at least:

```text
symbol_char_count
node record_length
Program.pou body_size
header[0x37]
header[0x3B]
header[0x47]
```

and then handling any required CFB stream resizing.

### 2. Record insertion

Starting from the simple contact/coil graph, insert one new contact and the required conductor records. This tests:

```text
record_count
record ordering
node construction
wire construction
geometry
```

### 3. Record deletion

Delete a known contact/wire set and verify that GX Works2 opens, saves, closes, and reopens the result.

### 4. General serializer round trip

For every supported controlled fixture:

```text
raw Program.pou
  -> parse
  -> serialize without semantic changes
  -> byte-for-byte identical Program.pou
```

Only after that should semantic mutation be layered on top of the serializer.

## Implementation implication

Keep the two writing problems separate:

```text
StructuredProgram serializer
    -> node/wire/header serialization

CFB writer
    -> nested Program.pou stream replacement/resizing
    -> outer `_hdb` stream replacement/resizing
```

The successful same-size experiment validates the boundary between these layers and provides a regression target for future general writer work.
