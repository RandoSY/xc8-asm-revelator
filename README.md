# XC8 ASM Revelator

XC8 ASM Revelator is a read-only inspection tool for Microchip XC8 / PIC-AS
compiler output. It parses `.lst`, `.s`, and `.asm` files and produces
programmer-focused Markdown, JSON, and optional annotated listing reports.

The tool is intended for firmware engineers who want to understand what XC8
emitted, spot common conservative code-generation patterns, and review timing or
flow-sensitive sections without rewriting compiler output automatically.

## Features

- Parses XC8/PIC-AS listing, assembly, and generated source files.
- Reports instruction mix, rough static cycle estimates, labels, branches,
  skips, calls, returns, and source-reference counts.
- Detects repeated bank selects, repeated literal loads, branch-to-next-label
  patterns, self branches, skip/double-goto structures, delay loops, and direct
  self-calls.
- Maps numeric SFR operands back to symbols when declarations are present in the
  input.
- Writes Markdown reports, optional JSON payloads, and optional annotated
  listings.
- Runs on Python 3.9+ with no third-party dependencies.

## Quick Start

```bash
python xc8_asm_revelator.py path/to/firmware.lst --annotate
```

By default this writes:

- `firmware.lst.programmer_review.md`
- `firmware.lst.annotated.lst` when `--annotate` is used

To also write JSON:

```bash
python xc8_asm_revelator.py path/to/firmware.lst --json review.json
```

## Command-Line Options

```text
usage: xc8_asm_revelator.py [-h] [--report REPORT] [--json JSON]
                            [--annotate]
                            [--annotated-output ANNOTATED_OUTPUT]
                            [--min-severity {INFO,WARN,STRONG}]
                            [--focus {program,maintext,all}]
                            input
```

- `input`: XC8/PIC-AS `.lst`, `.s`, or `.asm` file to inspect.
- `--report`: Markdown output path. Defaults to
  `<input>.programmer_review.md`.
- `--json`: Optional machine-readable JSON output path.
- `--annotate`: Write an annotated listing with review comments inserted before
  flagged lines.
- `--annotated-output`: Custom annotated listing output path.
- `--min-severity`: Minimum finding severity: `INFO`, `WARN`, or `STRONG`.
- `--focus`: Analysis scope: `program`, `maintext`, or `all`.

## Example Strict Review

```bash
python xc8_asm_revelator.py build/target.lst \
  --min-severity STRONG \
  --focus maintext \
  --json audit.json
```

## Documentation

See [docs/operators_guide.md](docs/operators_guide.md) for a deeper explanation
of the analysis pipeline, finding categories, and output formats.

## Notes

This is a static review helper. It does not prove runtime behavior, and its
cycle estimates are orientation metrics rather than complete timing analysis.
Always verify firmware changes against the target device, oscillator setup,
interrupt behavior, and compiler/linker settings.

## License

MIT. See [LICENSE](LICENSE).
