<p align="center">
  <img src="assets/logo.svg" alt="XC8 ASM Revelator logo" width="900">
</p>

# XC8 ASM Revelator

Current release: **v3.6**.

XC8 ASM Revelator is a read-only inspection tool for Microchip XC8 / PIC-AS
compiler output. It parses `.lst`, `.s`, and `.asm` files, can combine that
with optional `.map` linker output, and produces programmer-focused Markdown,
JSON, focused triage, and optional annotated listing reports.

Use it when you want to understand what XC8 emitted, identify which source
constructs are costing flash, separate normal PIC/GCBASIC structure from real
optimization targets, and review timing or flow-sensitive sections without
blindly rewriting compiler output.

## v3.6 Focus

Version 3.6 adds a GCBASIC-first interpretation layer and a triage workflow for
memory-tight PIC projects. The default `gcbasic` profile suppresses predictable
compiler/PIC scaffolding and promotes repeated source-level patterns that are
more likely to matter.

The recommended workflow is:

1. Run Revelator with both the listing and linker map.
2. Read the triage report first.
3. Use the full Markdown report for explanation and local context.
4. Keep the JSON output for audit, dashboards, and before/after comparisons.

## What It Finds

- Flash pressure estimated from XC8/PIC-AS linker `.map` output.
- String table burden from many emitted `STRINGTABLE` symbols and references.
- Serial print burden from repeated `HSERPRINT`/print-like helper calls.
- Large linear GCBASIC command dispatchers built from repeated
  `movlw` / `subwf` / `btfss` / `goto` chains.
- Feature-family call traffic such as USART/HSER, LED, ADC, 7SEG, NCO, and
  delay helpers.
- Structured GCBASIC control flow that appears as labels, skips, and GOTOs in
  generated PIC assembly.
- PIC skip-control idioms such as `btfss`, `btfsc`, and `decfsz`.
- `movf file,f` zero-test patterns.
- Bank/page scaffolding such as `movlb`, `banksel`, and `pagesel`.
- Map-symbol cross references that connect listing labels to linked addresses.
- Lower-level audit findings such as branch-to-next-label, delay loops,
  self-branches, self-calls, NOP/timing padding, and hot call targets.

## Requirements

- Python 3.9 or newer.
- No third-party Python packages.
- An XC8 / PIC-AS `.lst`, `.s`, or `.asm` file.
- An XC8 / PIC-AS `.map` file is strongly recommended for memory triage.

## Quick Start

Clone the repository:

```bash
git clone https://github.com/RandoSY/xc8-asm-revelator.git
cd xc8-asm-revelator
```

Run the normal v3.6 GCBASIC triage workflow:

```bash
python xc8_asm_revelator.py path/to/firmware.lst \
  --map path/to/firmware.map \
  --triage \
  --triage-report firmware_triage.md \
  --report firmware_full.md \
  --json firmware.json
```

Primary outputs:

- `firmware_triage.md`: read this first; ranked memory-reduction suspects.
- `firmware_full.md`: interpreted detailed report with grouped findings.
- `firmware.json`: complete structured audit trail.

Write an annotated listing as well:

```bash
python xc8_asm_revelator.py path/to/firmware.lst \
  --map path/to/firmware.map \
  --annotate \
  --annotated-output firmware.annotated.lst
```

Run a raw machine-level audit when you want every finding, including structural
noise normally suppressed by the GCBASIC profile:

```bash
python xc8_asm_revelator.py path/to/firmware.lst \
  --map path/to/firmware.map \
  --profile raw \
  --raw-findings \
  --report firmware_raw.md
```

## Command-Line Reference

```text
usage: xc8_asm_revelator.py [-h] [--map MAP] [--report REPORT] [--json JSON]
                            [--annotate]
                            [--annotated-output ANNOTATED_OUTPUT]
                            [--min-severity {INFO,WARN,STRONG}]
                            [--triage]
                            [--triage-report TRIAGE_REPORT]
                            [--triage-limit TRIAGE_LIMIT]
                            [--profile {raw,default,gcbasic}]
                            [--show-structural]
                            [--raw-findings]
                            input
```

| Argument | Description |
|---|---|
| `input` | XC8/PIC-AS `.lst`, `.s`, or `.asm` file to inspect. |
| `--map` | Optional XC8/PIC-AS linker `.map` file. Strongly recommended for v3.6 triage. |
| `--report` | Markdown output path. Defaults to `<input>.revelator_v3_6.md`. |
| `--json` | Optional machine-readable JSON output path. |
| `--annotate` | Writes an annotated listing with review comments inserted before flagged lines. |
| `--annotated-output` | Custom annotated listing output path. |
| `--min-severity` | Minimum finding severity: `INFO`, `WARN`, or `STRONG`. |
| `--triage` | Prints ranked memory-reduction suspects to the console. |
| `--triage-report` | Writes a focused triage Markdown report. |
| `--triage-limit` | Number of triage items to print to the console. Defaults to `12`. |
| `--profile` | Interpretation profile: `gcbasic` default, `default`, or `raw`. |
| `--show-structural` | Shows structural scaffolding findings normally hidden by the profile. |
| `--raw-findings` | Uses unfiltered raw findings in the full Markdown report. |

## Outputs

### Triage Report

The triage report condenses noisy line-by-line findings into ranked,
source-level memory-reduction suspects. It is the first report to read when a
PIC build is close to full.

Typical high-value categories include:

- `FLASH_PRESSURE`
- `STRING_TABLE_BURDEN`
- `SERIAL_PRINT_BURDEN`
- `REPEATED_COMPARE_CHAIN`
- `COMMAND_DISPATCHER`
- `BUILD_PROFILES`
- `FEATURE_FAMILY`
- `DELAY_USAGE`

For a rich GCBASIC CLI monitor, the expected first fixes are usually source
changes: shorten strings, move long help text out of the PIC, use compact
protocol tokens, normalize command case once, remove duplicate command tests,
and split features into CORE/LED/ADC/7SEG/NCO/FULL build profiles.

### Markdown Review

The full Markdown report is meant for human review. It includes:

- Executive summary.
- Instruction mix.
- Linker map summary.
- Register/SFR interpretation.
- Source-line map when source references are available.
- Grouped GCBASIC/PIC insights.
- Findings with local assembly context and suggested action.

### JSON Review

The JSON report is meant for CI, dashboards, or later tooling. It contains
summary information, map-derived data, and structured findings.

```json
{
  "summary": {
    "physical_lines": 1442,
    "instruction_lines": 37
  },
  "map": {
    "path": "firmware.map",
    "symbol_count": 120
  },
  "findings": [
    {
      "severity": "WARN",
      "category": "GCBASIC_LINEAR_IF_CHAR_COMPARE",
      "line": 305,
      "message": "GCBASIC-style literal compare/skip/goto chain."
    }
  ]
}
```

### Annotated Listing

When `--annotate` is enabled, the tool writes a copy of the listing with review
comments inserted immediately before flagged lines.

```asm
; -----------------------------------------------------------------------------
; REVIEW WARN GCBASIC_LINEAR_IF_CHAR_COMPARE: GCBASIC-style literal compare/skip/goto chain.
; MAP: Address 005C appears within map psect `CODE`.
; WHY: GCBASIC emitted literal-load, subtract, STATUS/Z skip, and branch for an IF equality test.
; DO: Normalize command input case once and reduce duplicate upper/lower command branches.
; -----------------------------------------------------------------------------
  0305     005C  3061                  movlw   97
```

## Severity Levels

| Severity | Meaning |
|---|---|
| `INFO` | Useful context or a common compiler pattern to review. |
| `WARN` | Suspicious or potentially wasteful output that deserves human inspection. |
| `STRONG` | Higher-confidence issue that is more likely to justify source or assembly review. |

## Profiles

| Profile | Meaning |
|---|---|
| `gcbasic` | Default v3.6 mode. Suppresses predictable structural noise and adds GCBASIC-specific interpretation. |
| `default` | General interpreted review mode. |
| `raw` | Machine-level audit mode. Intentionally noisy. |

Use `--show-structural` when you want to see scaffolding hidden by the selected
profile. Use `--raw-findings` when the full report should include the raw
finding set.

## Important Notes

XC8 ASM Revelator is a static review helper. It does not prove runtime behavior,
and it does not rewrite firmware. Loops, interrupts, oscillator configuration,
skip paths, linker layout, and target hardware all affect real execution.

For GCBASIC, the highest-value fixes are usually in the `.gcb` source, not in
hand-edited generated assembly. Treat every finding as a prompt for careful
review against the source, generated listing, linker map, datasheet, and target
hardware.

## Documentation

See [docs/operators_guide.md](docs/operators_guide.md) for the v3.6 GCBASIC
operator guide, including the triage workflow, pattern interpretation, build
profile strategy, and before/after comparison guidance.

## Contributing

Issues and pull requests are welcome. Useful contributions include:

- Additional XC8/PIC-AS listing and map formats.
- New static-analysis heuristics with examples.
- Tests built from small, shareable listing snippets.
- Documentation for known compiler and GCBASIC output patterns.

Generated `.lst`, `.hex`, `.elf`, review JSON, triage reports, and annotated
listing outputs are ignored by default so public commits stay focused on source
and documentation.

## License

MIT. See [LICENSE](LICENSE).
