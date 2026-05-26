<p align="center">
  <img src="assets/logo.svg" alt="XC8 ASM Revelator logo" width="900">
</p>

# XC8 ASM Revelator

Current release: **v3.6**.

XC8 ASM Revelator is a read-only inspection tool for Microchip XC8 / PIC-AS
compiler output. It parses `.lst`, `.s`, and `.asm` files, can combine that
with optional `.map` linker output, and produces programmer-focused Markdown,
JSON, and optional annotated listing reports.

Use it when you want to understand what XC8 emitted, spot conservative
code-generation patterns, and review timing or flow-sensitive sections without
blindly rewriting compiler output.

## What It Finds

- Repeated bank selects such as redundant `movlb` or `banksel` sequences.
- Repeated literal loads into `W` with no intervening invalidation.
- Branches that jump to the next label.
- Self branches and direct self-calls.
- Skip plus double-`goto` compiler structures.
- Delay-loop signatures.
- Numeric SFR operands that can be mapped back to symbols from declarations in
  the listing.

## Requirements

- Python 3.9 or newer.
- No third-party Python packages.
- An XC8 / PIC-AS `.lst`, `.s`, or `.asm` file.

## Quick Start

Clone the repository:

```bash
git clone https://github.com/RandoSY/xc8-asm-revelator.git
cd xc8-asm-revelator
```

Run a standard review:

```bash
python xc8_asm_revelator.py path/to/firmware.lst --annotate
```

By default this writes:

- `firmware.lst.programmer_review.md`
- `firmware.lst.annotated.lst` when `--annotate` is used

Write JSON for automation:

```bash
python xc8_asm_revelator.py path/to/firmware.lst --json review.json
```

Run a stricter review focused on the main program section:

```bash
python xc8_asm_revelator.py build/target.lst \
  --min-severity STRONG \
  --focus maintext \
  --json audit.json
```

## Command-Line Reference

```text
usage: xc8_asm_revelator.py [-h] [--report REPORT] [--json JSON]
                            [--annotate]
                            [--annotated-output ANNOTATED_OUTPUT]
                            [--min-severity {INFO,WARN,STRONG}]
                            [--focus {program,maintext,all}]
                            input
```

| Argument | Description |
|---|---|
| `input` | XC8/PIC-AS `.lst`, `.s`, or `.asm` file to inspect. |
| `--report` | Markdown output path. Defaults to `<input>.programmer_review.md`. |
| `--json` | Optional machine-readable JSON output path. |
| `--annotate` | Writes an annotated listing with review comments inserted before flagged lines. |
| `--annotated-output` | Custom annotated listing output path. |
| `--min-severity` | Minimum finding severity: `INFO`, `WARN`, or `STRONG`. |
| `--focus` | Analysis scope: `program`, `maintext`, or `all`. |

## Outputs

### Markdown Review

The Markdown report is meant for human review. It includes:

- Executive summary.
- Instruction mix.
- Register/SFR interpretation.
- Source-line map when source references are available.
- Findings with local assembly context and suggested action.

### JSON Review

The JSON report is meant for CI, dashboards, or later tooling. It contains a
summary object and a list of structured findings.

```json
{
  "summary": {
    "physical_lines": 1442,
    "instruction_lines": 37,
    "rough_static_cycle_sum": 48.5
  },
  "findings": [
    {
      "severity": "WARN",
      "category": "REPEATED_BANK_SELECT",
      "line": 1024,
      "message": "Repeated MOVLB 2."
    }
  ]
}
```

### Annotated Listing

When `--annotate` is enabled, the tool writes a copy of the listing with review
comments inserted immediately before flagged lines.

```asm
; -----------------------------------------------------------------------------
; REVIEW WARN REPEATED_BANK_SELECT: Repeated MOVLB 2.
; SOURCE: ../rotate.c:89
; PARSED: movlb 2
; WHY: Repeated bank selects can be compiler conservatism, but are sometimes required after uncertain flow.
; DO: If no label/call/branch can enter between the two, the later bank select may be removable.
; -----------------------------------------------------------------------------
  1024     07E5  0182                  movlb   2
```

## Severity Levels

| Severity | Meaning |
|---|---|
| `INFO` | Useful context or a common compiler pattern to review. |
| `WARN` | Suspicious or potentially wasteful output that deserves human inspection. |
| `STRONG` | Higher-confidence issue that is more likely to justify source or assembly review. |

## Analysis Scope

| Focus | Meaning |
|---|---|
| `program` | Default review scope for normal program listing sections. |
| `maintext` | Narrows review to the primary main-text execution section. |
| `all` | Reviews all recognized sections, including configuration and support blocks. |

## Important Notes

XC8 ASM Revelator is a static review helper. It does not prove runtime behavior,
and its cycle estimates are orientation metrics rather than complete timing
analysis. Loops, interrupts, oscillator configuration, skip paths, and linker
layout all affect real execution.

The tool does not rewrite firmware. Treat every finding as a prompt for careful
review against the C source, generated assembly, datasheet, and target hardware.

## Documentation

See [docs/operators_guide.md](docs/operators_guide.md) for the v3.6 operator
guide, including parser architecture, finding categories, and output formats.

## Contributing

Issues and pull requests are welcome. Useful contributions include:

- Additional XC8/PIC-AS listing formats.
- New static-analysis heuristics with examples.
- Tests built from small, shareable listing snippets.
- Documentation for known compiler output patterns.

Generated `.lst`, `.hex`, `.elf`, review JSON, and annotated listing outputs are
ignored by default so public commits stay focused on source and documentation.

## License

MIT. See [LICENSE](LICENSE).
