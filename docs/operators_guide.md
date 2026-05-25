# Microchip XC8 Assembly Revelator (v4.0)
## Advanced Static Analysis & Optimization Pipeline Operator's Guide

---

### 1. Executive Summary & Core Value Proposition

The **Microchip XC8 Assembly Revelator (v4.0)** is an enterprise-grade static analysis tool designed specifically for firmware engineers, safety-critical systems auditors, and performance engineers targeting Microchip PIC® enhanced midrange and baseline microcontrollers. 

Modern high-level C compilers like Microchip XC8 automate machine code generation but frequently emit defensive, deeply conservative assembly sequences. This artifact-bloat includes redundant bank selections (`movlb`), repetitive literal loading (`movlw`), and structurally heavy conditional branch matrices (skip-gated double `GOTO` chains). While executionally correct, these anti-patterns compromise strict timing budgets, bloat Flash memory utilization, and mask downstream logical anomalies.

```
       ┌─────────────────────────────────────────────────────────┐
       │   XC8 / PIC-AS Listing Stream (.lst / .s / .asm)        │
       └────────────────────────────┬────────────────────────────┘
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │     Two-Stage Context-Bounded Parsing Pipeline          │
       │   - Isolates Line Numbers, Addresses, & Opcode Hex      │
       │   - Discards Directives from Main Executable Streams    │
       └────────────────────────────┬────────────────────────────┘
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │        Control-Flow & Context Barrier Resolution        │
       │   Resets optimization matrices across jump boundaries    │
       └────────────────────────────┬────────────────────────────┘
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │     Multi-Pass Heuristic Analysis & Scoring Engine      │
       │   - Bank/Literal Redundancy  - Recursive Call Flags     │
       │   - Skip/Branch Traps        - Timing-Delay Signatures  │
       └────────────────────────────┬────────────────────────────┘
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │     Structured Machine Reports & In-Line Annotations    │
       │     (Markdown Reports, Standard JSON, Annotated LST)    │
       └─────────────────────────────────────────────────────────┘
```

The Assembly Revelator bridges this opacity gap. By ingesting `.lst` (compiler production listings), `.s` (assembly source), or `.asm` streams, it reconstructs tokenized basic blocks, maps numerical Special Function Register (SFR) dependencies to their absolute literal identifiers, and surfaces latent optimizations. It functions explicitly as a **read-only engineering oracle**—it does not alter structural firmware layouts; it arms the developer with exact, human-actionable optimization coordinates.

---

### 2. Architecture & Data Pipeline Breakdown

Version 4.0 replaces loose string-scanning mechanisms with a strict, state-isolated multi-stage ingestion pipeline.

```
+---------------------------------------------------------------------------------+
|                         STAGE 1: EXTENDED TWO-STAGE PARSER                      |
|                                                                                 |
|  [Raw Input String]                                                             |
|         │                                                                       |
|         ▼                                                                       |
|  (Regex Structural Bounds Extraction)                                           |
|         │                                                                       |
|         ├──► listing_line (int)                                                 |
|         ├──► absolute_address (hex -> int)                                      |
|         └──► operational_code_hex (hex bytes)                                   |
|                                                                                 |
|  [Clean Assembly Text Fragment]                                                 |
|         │                                                                       |
|         ▼                                                                       |
|  (Instruction / Label Labeler)                                                  |
|         │                                                                       |
|         ├──► label_context (identifier)                                         |
|         ├──► mnemonic_token (validated lower-case)                              |
|         └──► operand_arguments (comma-delimited sub-string)                     |
+---------------------------------------------------------------------------------+
                                    │
                                    ▼
+---------------------------------------------------------------------------------+
|                       STAGE 2: PROGRAM FLOW FOCUS FILTERS                       |
|                                                                                 |
|  Filters listing lines by compilation scope (psect blocks):                     |
|    - "program"   : Standard execution logic (omits static declaration noise)    |
|    - "maintext"  : Limits auditing to the primary target runtime boundary      |
|    - "all"       : Complete exhaustive raw analysis of the image footprint       |
+---------------------------------------------------------------------------------+
                                    │
                                    ▼
+---------------------------------------------------------------------------------+
|                       STAGE 3: STATE ISOLATION & AUDITING                       |
|                                                                                 |
|  Tracks registers using rolling contextual windows.                             |
|  CRITICAL CRITERIA: State metrics immediately cleared when crossing             |
|  Control Flow Barriers (e.g., GOTO, CALL, RETURN, PSECT, or Label Entry)        |
|  to eliminate false-positive redundancy flags.                                  |
+---------------------------------------------------------------------------------+
```

#### Special Function Register (SFR) Symbol Workspace
The engine reads absolute literal structures from `equ` and `set` directives within the file header to populate a bidirectionally mapped reference table:
* **`sfr_by_addr` (Dict[int, List[str]])**: Resolves raw compiled numbers back to names (e.g., mapping address `3` to `STATUS`).
* **`addr_by_sfr` (Dict[str, int])**: Validates human symbol requests back to memory ranges.

This mechanism intercepts standard instructions (e.g., `btfss 3,2`) and enriches report data to read explicitly as `btfss 3 (STATUS), 2`—instantly highlighting hardware state checks.

---

### 3. Comprehensive Metric Diagnostic Dictionary

The software executes seven decoupled heuristic analysis routines. Each pattern falls under an explicit classification framework.

#### 1. `REPEATED_BANK_SELECT` (Severity: `WARN`)
* **Trigger Condition:** An active bank selection instruction (`movlb` or `banksel`) targets a memory bank that exactly matches the current state register, without encountering an intermediate control-flow barrier or entry label.
* **Underlying Causality:** The compiler is generating defensive code-paths to guarantee bank alignment before performing localized register modifications, unaware that preceding linear execution has already stabilized the pointer.
* **Actionable Remediation:** In performance-critical loops, replace explicit multi-bank accesses with structured local variables optimized for allocation within a single common memory bank.

#### 2. `REPEATED_MOVLW` (Severity: `WARN`)
* **Trigger Condition:** The working register is loaded with a literal via `movlw` that matches the value already stored in it by an immediate predecessor, without any intervening working register operations (`addlw`, `andlw`, `xorlw`, etc.) to consume or invalidate the data.
* **Underlying Causality:** C structures evaluating multi-step logic or setting up flags often force variable assignments sequentially, resulting in repetitive structural loads to the working register (`W`).
* **Actionable Remediation:** Restructure internal conditional blocks or utilize specialized compound bitwise assignments in your source C code to compress state machine evaluations.

#### 3. `BRANCH_TO_NEXT_LABEL` (Severity: `STRONG`)
* **Trigger Condition:** An unconditional control branch (`goto`, `bra`, `ljmp`) targets an absolute code label whose executable index immediately follows the branch statement itself.
* **Underlying Causality:** This occurs when compilation logic encounters empty `else` blocks, structural switch statements, or linker artifacts that pass through to the next sequential instruction.
* **Actionable Remediation:** Refactor logical control flow to eliminate redundant default cases, or clean out abandoned conditional branches in source logic.

#### 4. `SELF_BRANCH` (Severity: `WARN`)
* **Trigger Condition:** A control branch explicitly references its own parent line index or entry label.
* **Underlying Causality:** This indicates a designed system trap loop (e.g., an unhandled exception handler, defensive watchdog trap, or infinite processing block).
* **Actionable Remediation:** Audit the code path to ensure this trap is intended behavior (such as a hardware panic loop) and not a logical deadlock artifact from macro expansions.

#### 5. `SKIP_WITH_DOUBLE_GOTO` (Severity: `INFO`)
* **Trigger Condition:** A conditional skip directive (`btfsc`, `btfss`, `decfsz`, `incfsz`) immediately feeds into two back-to-back unconditional branches (`goto`).
* **Underlying Causality:** This is the standard microcode sequence used by XC8 to implement `if-else` evaluations on limited PIC architectures.
* **Actionable Remediation:** While mathematically correct, check if inverted source conditions can let the code default directly into the most frequent path, which can save instruction cycles.

#### 6. `DELAY_LOOP` (Severity: `INFO`)
* **Trigger Condition:** A structural loop begins with a valid label, contains decrement/increment skip operations (`decfsz`, `incfsz`), and closes with a branch back to the starting label.
* **Underlying Causality:** This matches the microcode profile for blocking hardware delay cycles, such as `__delay_ms()` routines.
* **Actionable Remediation:** If blocking delay loops occur in critical sections, shift them to hardware peripheral timers or cooperative interrupt structures to regain CPU cycles.

#### 7. `SELF_CALL` (Severity: `WARN`)
* **Trigger Condition:** An active function execution identifier contains a direct internal call to its own operational address label.
* **Underlying Causality:** This flags a recursive execution routine.
* **Actionable Remediation:** **CRITICAL IN PIC TARGETS.** Midrange PIC architectures rely on a shallow, hardware-fixed hardware return stack (typically 8 to 16 levels deep). Recursion can trigger immediate stack overflow and cause undefined system resets. Convert recursive logic into iterative loop structures.

---

### 4. Command-Line Interface (CLI) Specification

Execute the engine using standard corporate automated automation runners or via a direct terminal shell interface.

```bash
python xc8_asm_revelator_v4_0.py <input_file_path> [options]
```

#### Positional Arguments
* `input_file_path` (Path, Required): The file path to the target file (`.lst`, `.s`, `.asm`).

#### Optional Configuration Flags
* `--report <path>`  
    Overrides the default Markdown review destination path. Defaults to `<input_name>.programmer_review.md`.
* `--json <path>`  
    Enables structured machine-readable logging output to the specified target path.
* `--annotate`  
    Enables in-line listing injection mode.
* `--annotated-output <path>`  
    Specifies the output file path for the annotated listing file. Defaults to `<input_name>.annotated.lst`.
* `--min-severity {INFO, WARN, STRONG}`  
    Sets the minimum priority threshold for findings. Filtering out lower levels can help clear out noise during large file reviews. Default is `INFO`.
* `--focus {program, maintext, all}`  
    Configures parser focus constraints:
    * `program`: Filters out system macro tables; audits core code sections.
    * `maintext`: Focuses exclusively on the core `main` execution boundaries.
    * `all`: Runs a raw audit across all sections, including configuration blocks.

#### Typical Execution Patterns

1. **Standard Engineering Analysis Routine:**
   ```bash
   python xc8_asm_revelator_v4_0.py rotate.X.production.lst --annotate
   ```
   *Generates both the standard Markdown file report and a clean line-annotated code file for local review.*

2. **Strict Safety-Critical Automated CI Build Pipeline Audit:**
   ```bash
   python xc8_asm_revelator_v4_0.py target.lst --min-severity STRONG --focus maintext --json audit.json
   ```
   *Filters findings to isolate high-severity issues inside primary execution loops, outputting a machine-readable JSON summary.*

---

### 5. Production Output Formats

#### 1. Human-Readable Engineering Review (Markdown)
Designed for clear code reviews and documentation compliance, this output groups findings into a structured layout:
* **Executive Summary:** High-level metrics showing static code cycle estimates, instruction density, and issue severity tracking.
* **Instruction Mix Matrix:** Breakdowns of instruction usage paired with clear explanations of their hardware purpose.
* **Register/SFR Table:** Maps raw numeric references back to functional hardware names (e.g., absolute register address `26` mapped to `LATC`).
* **Contextual Diagnostic Cards:** Provides deep-dive views of each issue, showing surrounding instructions, source file references, and clear mitigation advice.

#### 2. Machine-Readable Automation Payload (JSON)
Perfect for integration into automated build steps or quality tracking dashboards.
```json
{
  "summary": {
    "physical_lines": 1442,
    "recognized_lines": 84,
    "instruction_lines": 37,
    "directive_lines": 23,
    "labels": 24,
    "rough_static_cycle_sum": 48.5,
    "mnemonics": { "goto": 6, "movlw": 5, "movlb": 4 },
    "psects": { "maintext": 33, "cinit": 2 },
    "bank_selects": 4,
    "branches": 8,
    "skips": 3,
    "calls": 2,
    "returns": 0,
    "source_refs": { "../rotate.c:95": 4 }
  },
  "findings": [
    {
      "severity": "WARN",
      "category": "REPEATED_BANK_SELECT",
      "line": 1024,
      "message": "Repeated MOVLB 2.",
      "why": "Repeated bank selects can be compiler conservatism...",
      "suggestion": "If no label/call/branch can enter between the two, the later bank select may be removable.",
      "raw": "  1024     07E5  0182              	movlb	2",
      "parsed": "movlb 2",
      "source_ref": "../rotate.c:89",
      "address": "07E5",
      "related_lines": [1012],
      "context": [
        "   1012: movlb	2",
        "=> 1024: movlb	2"
      ]
    }
  ]
}
```

#### 3. In-Line Annotated Listing File (`.lst`)
Injects warnings directly into the code stream using standard assembly comment tags (`;`), creating a seamless layout for developer tracking.
```asm
; -----------------------------------------------------------------------------
; REVIEW WARN REPEATED_BANK_SELECT: Repeated MOVLB 2.
; SOURCE: ../rotate.c:89
; PARSED: movlb 2
; WHY: Repeated bank selects can be compiler conservatism, but are sometimes required after uncertain flow.
; DO: If no label/call/branch can enter between the two, the later bank select may be removable.
; -----------------------------------------------------------------------------
  1024     07E5  0182              	movlb	2
```

---

### 6. Corporate Field Verification & Troubleshooting

#### High-Frequency Diagnostics Anomalies

##### Issue: Analyzer reports zero instructions parsed, but the file contains thousands of lines.
* **Root Cause:** The target file uses a non-standard compiler listing layout. The structural layout pattern `^\s*(\d+)\s+([0-9A-Fa-f]{4,6})?` expects line numbers to be clearly positioned ahead of addresses and opcode data.
* **Resolution:** Verify the input file isn't raw object code. Regenerate the listing through MPLAB® XC8 using the `-Wa,-a` command-line switch to ensure standard listing structures are embedded.

##### Issue: False-positive optimization warnings populate across long code sequences.
* **Root Cause:** The focus mode parameter is configured to `all`, which pulls macro assembly layout blocks into active processing memory without processing localized labels.
* **Resolution:** Switch execution profiles to use `--focus program`. This forces the system to respect control barriers and clear working registers across routine boundaries.

##### Issue: Missing C Source file link assignments inside finding blocks.
* **Root Cause:** The binary compilation was optimized for release, stripping out debug line markers.
* **Resolution:** Recompile the source project with debug line generation enabled (`-g` or `-g2` switches) to inject absolute C source file paths into the final listing.
