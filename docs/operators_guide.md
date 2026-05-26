# XC8 ASM Revelator v3.6 — GCBASIC Operator’s Manual

## 1. What Revelator Is For

XC8 ASM Revelator helps a GCBASIC/PIC developer understand what the compiler and linker actually produced.

It reads:

```text
.lst file  → generated assembly / instruction truth
.map file  → final memory layout / linker truth
```

It answers practical questions:

```text
Why is my program so large?
Which source constructs are costing flash?
Which patterns are normal GCBASIC output?
Which findings are structural noise?
What should I change in the .gcb source?
```

It is not an automatic optimizer. It is a diagnostic instrument.

---

## 2. Recommended Command

Use this command for normal GCBASIC work:

```powershell
python xc8_asm_revelator_v3_6_gcbasic.py nugget_cli_monitor.lst `
  --map nugget_cli_monitor.map `
  --triage `
  --triage-report nugget_cli_monitor_triage.md `
  --report nugget_cli_monitor_full.md `
  --json nugget_cli_monitor.json
```

Primary output files:

```text
nugget_cli_monitor_triage.md   ← read this first
nugget_cli_monitor_full.md     ← interpreted detailed report
nugget_cli_monitor.json        ← complete audit trail
```

The triage report is the practical memory-reduction guide. The full report is for deeper explanation. The JSON is for complete preservation and future dashboard/statistical work.

---

## 3. Important Options

### Default GCBASIC interpretation

```powershell
--profile gcbasic
```

This is the default. It suppresses predictable structural noise and adds GCBASIC-specific interpretation.

### Raw machine-level mode

```powershell
--profile raw
```

Use this when auditing everything the analyzer detects. This is intentionally noisy.

### Show structural findings

```powershell
--show-structural
```

Shows findings normally hidden because they are expected compiler/PIC structure.

### Raw findings in the full report

```powershell
--raw-findings
```

Bypasses profile filtering. Use only for deep audit.

### Severity filter

```powershell
--min-severity WARN
```

Shows only warnings and stronger findings.

---

## 4. First Thing to Read: Triage Output

Example:

```text
Program memory estimate: 3982 used / 4096 total words (97.2% used), 114 free words.
CLI_DISPATCHCOMMAND: span=587 words, instructions=333, compares=51, gotos=102, calls=0.
String tables: 60 unique, 258 references.
Calls: 84 total, 20 unique targets.
```

Interpretation:

```text
The program is critically close to full.
The CLI dispatcher is large.
Strings and serial output are major suspects.
The problem is source structure, not one bad instruction.
```

When flash is 97% used, do not start by chasing a single `NOP`, `MOVLW`, or `BANKSEL`. Start with the biggest structures.

---

## 5. Main GCBASIC Patterns

### A. Linear command comparison chain

Generated assembly pattern:

```asm
movlw   65
subwf   command_char,w
btfss   STATUS,Z
goto    ELSE_x
```

Likely GCBASIC source:

```basic
If command_char = "A" Then
```

Revelator category:

```text
GCBASIC_LINEAR_COMPARE_CHAIN
```

Meaning:

GCBASIC is translating each character test into a literal load, subtraction, zero-flag test, and branch.

If Revelator reports:

```text
GCBASIC_LINEAR_COMPARE_CHAIN: 109 occurrences
```

then the CLI command dispatcher is probably implemented as many repeated `IF char = "X"` tests.

Actionability: **High**

Best fixes:

```text
Normalize command input to uppercase once.
Remove duplicate upper/lower command tests.
Reduce the number of command letters.
Group related commands.
Consider a compact dispatch table if supported cleanly.
```

Avoid:

```text
Do not hand-edit each movlw/subwf/btfss/goto block.
```

---

### B. Repeated compare/skip/goto chain

Triage finding:

```text
REPEATED_COMPARE_CHAIN
Detected 109 movlw/subwf/btfss/goto compare patterns.
```

Meaning:

The command parser is readable at the GCBASIC source level, but it expands into a long linear assembly chain.

GCBASIC source example:

```basic
If cmd = "A" Then DoADC
If cmd = "a" Then DoADC
If cmd = "L" Then DoLED
If cmd = "l" Then DoLED
```

Better source-level direction:

```basic
' Convert once, near input handling
If cmd >= "a" And cmd <= "z" Then
    cmd = cmd - 32
End If

If cmd = "A" Then DoADC
If cmd = "L" Then DoLED
```

This reduces duplicate upper/lower command branches.

---

### C. String table burden

Triage finding:

```text
STRING_TABLE_BURDEN
Detected 60 unique STRINGTABLE symbols and 258 references.
```

Meaning:

GCBASIC has emitted many string constants and string-print references.

Source-level causes:

```basic
HSerPrint "NUGGET CLI MONITOR READY"
HSerPrint "Commands: A=ADC, L=LED, S=STATUS..."
HSerPrint "OK ADC STREAM ON"
HSerPrint "ERROR UNKNOWN COMMAND"
```

These are valuable for a friendly monitor, but expensive on a small PIC.

Actionability: **High**

Best fixes:

```text
Shorten messages.
Move long help to the teacher guide or PC dashboard.
Use terse protocol tokens.
Compile banner/help only in DEBUG or FULL builds.
```

Example:

```basic
' Friendly but expensive
HSerPrint "OK ADC STREAM ON"

' Smaller
HSerPrint "OK ADC ON"
```

Or even:

```basic
HSerPrint "OK A1"
```

Recommended policy:

```text
Verbose text belongs in the browser/dashboard/manual.
The PIC should emit compact, parseable tokens.
```

---

### D. Serial print burden

Triage finding:

```text
SERIAL_PRINT_BURDEN
Detected 60 print-like calls.
```

Meaning:

The program repeatedly calls serial print helpers such as `HSERPRINT...`.

This may be entirely correct, but the print system plus strings can dominate flash.

Actionability: **High to Medium**

Best fixes:

```text
Reduce repeated print sequences.
Use shorter text.
Create shared compact status emitters.
Avoid printing long prose from the PIC.
Gate help/banner text with compile-time flags.
```

Example source strategy:

```basic
' Instead of many unique text messages:
HSerPrint "ADC is now enabled"
HSerPrint "ADC is now disabled"

' Use compact command/status tokens:
HSerPrint "ADC=1"
HSerPrint "ADC=0"
```

---

### E. Structured GOTO / label flow

Grouped insight:

```text
GCBASIC_STRUCTURED_GOTO_FLOW
```

Meaning:

GCBASIC emits labels and GOTOs to implement structured BASIC control flow such as:

```basic
If ... Then
Else
End If

Do
Loop
```

Generated assembly may contain many labels and branches.

Actionability: **Medium**

Important interpretation:

```text
This is not automatically bad.
It is how structured GCBASIC becomes PIC assembly.
```

Fix strategy:

```text
Simplify repeated source-level branches.
Do not hand-edit generated GOTOs.
```

If this appears inside a long CLI dispatch chain, reduce the dispatcher. If it appears in ordinary control flow, leave it alone.

---

### F. PIC skip control flow

Grouped insight:

```text
PIC_SKIP_CONTROL_FLOW
```

Typical instructions:

```asm
btfss   STATUS,Z
btfsc   flags,0
decfsz  counter,f
```

Meaning:

PIC skip instructions conditionally skip the next instruction. GCBASIC uses them to implement `IF`, `LOOP`, and equality tests.

How to read:

```asm
btfss STATUS,Z
goto  ELSE_x
```

Plain English:

```text
If the Z flag is set, skip the goto.
If the Z flag is not set, execute the goto.
```

Actionability: **Low**

Do not optimize individual skip instructions. They are normal PIC idiom.

---

### G. MOVF file-to-self

Finding:

```text
MOVF_FILE_TO_SELF
```

Assembly:

```asm
movf some_register,f
```

Meaning:

This may look useless, but on PIC it commonly updates the Z flag without changing the register.

Likely purpose:

```text
Test whether a value is zero.
```

Actionability: **Review**

Usually keep it unless you prove the following status test is unnecessary.

---

### H. BANKSEL / MOVLB / page scaffolding

Typical instructions:

```asm
movlb   0
banksel SOME_REGISTER
pagesel SOME_ROUTINE
```

Meaning:

PIC memory is banked and paged. The compiler must select the correct bank/page before some accesses or calls.

In GCBASIC profile, normal bank/page scaffolding is treated as structural.

Actionability: **Usually Ignore**

Do not chase ordinary `MOVLB` or `BANKSEL` first. If memory is tight, remove source features, strings, command branches, or helper calls first.

---

### I. Initialization routines

Examples:

```asm
call INITSYS
call INITUSART
```

Meaning:

These are predictable startup/hardware initialization calls.

Actionability: **Ignore unless removing a whole subsystem**

If you remove serial support, then `INITUSART` may disappear. But do not treat the individual call as an optimization target.

---

### J. Delay loops

Finding:

```text
DELAY_OR_TIMING
```

Typical generated structure:

```asm
decfsz  counter,f
goto    loop
```

Meaning:

Software timing loop or delay helper.

Actionability: **Low**

In the CLI monitor, delay code is not the first target. Strings and dispatch are larger. Only optimize delay code if the report shows it is a major footprint or timing problem.

---

## 6. How to Interpret Actionability

### Critical

Memory pressure or failure condition. Act immediately.

Example:

```text
97.2% flash used, 114 words free
```

### High

Likely source-level optimization target.

Examples:

```text
STRING_TABLE_BURDEN
GCBASIC_LINEAR_COMPARE_CHAIN
SERIAL_PRINT_BURDEN
```

### Medium

May matter, especially inside repeated structures.

Examples:

```text
GCBASIC_STRUCTURED_GOTO_FLOW
HOT_CALL_TARGET
```

### Low

Usually normal compiler/PIC output.

Examples:

```text
PIC_SKIP_CONTROL_FLOW
DELAY_OR_TIMING
NOP_OR_TIMING_PADDING
```

### Ignore

Expected structural evidence.

Examples:

```text
ordinary SFR access
startup calls
map-symbol matches
ordinary bank selection
```

---

## 7. Recommended Memory-Reduction Order for a GCBASIC CLI

Use this order:

```text
1. Read triage report.
2. Confirm flash/RAM pressure from the map.
3. Shorten or remove help/banner text.
4. Replace verbose serial output with terse tokens.
5. Normalize command input case once.
6. Remove duplicate upper/lower command branches.
7. Split features into build profiles.
8. Remove unused command families from CORE builds.
9. Rebuild.
10. Re-run Revelator and compare.
```

Do not begin with:

```text
single NOPs
single MOVLW reloads
single BANKSEL/MOVLB instructions
ordinary SFR writes
startup calls
```

Those are usually not where the large savings are.

---

## 8. Build Profile Strategy

For a tight PIC CLI, one build should not carry every demonstration feature.

Recommended profiles:

```text
CORE      minimal command loop, identity, status
LED       CORE + LED commands
ADC       CORE + ADC commands
7SEG      CORE + seven-segment display commands
NCO       CORE + NCO commands
FULL      everything, for demonstration only
```

The FULL monitor is valuable, but it should not be the default memory-tight build.

Example concept:

```basic
#define PROFILE_CORE
' #define PROFILE_7SEG
' #define PROFILE_NCO
' #define PROFILE_FULL
```

Then conditionally compile command handlers and help text.

---

## 9. Practical Example: Unknown Command Text

Verbose:

```basic
HSerPrint "ERROR: UNKNOWN COMMAND. TYPE H FOR HELP."
```

Compact:

```basic
HSerPrint "ERR CMD"
```

Even better for dashboard parsing:

```basic
HSerPrint "E:CMD"
```

Interpretation:

```text
The student/manual/dashboard can explain the error.
The PIC only needs to transmit a compact signal.
```

---

## 10. Practical Example: Help Text

Verbose embedded help is expensive:

```basic
HSerPrint "A = ADC stream on/off"
HSerPrint "L = LED test"
HSerPrint "N = NCO test"
HSerPrint "S = status"
```

Better:

```basic
#ifdef FULL_HELP
    HSerPrint "A ADC"
    HSerPrint "L LED"
    HSerPrint "N NCO"
    HSerPrint "S STAT"
#endif
```

Best for tiny builds:

```basic
HSerPrint "CMDS: A L N S"
```

Or omit help entirely and place it in the PC/dashboard/manual.

---

## 11. Practical Example: Duplicate Case Handling

Expensive pattern:

```basic
If cmd = "A" Then DoADC
If cmd = "a" Then DoADC
If cmd = "L" Then DoLED
If cmd = "l" Then DoLED
```

Better:

```basic
If cmd >= "a" And cmd <= "z" Then
    cmd = cmd - 32
End If

If cmd = "A" Then DoADC
If cmd = "L" Then DoLED
```

Expected Revelator improvement:

```text
fewer GCBASIC_LINEAR_COMPARE_CHAIN blocks
smaller CLI_DISPATCHCOMMAND span
fewer gotos and skip tests
```

---

## 12. How to Use Before/After Reports

After making a source change:

```powershell
python xc8_asm_revelator_v3_6_gcbasic.py new_build.lst `
  --map new_build.map `
  --triage `
  --triage-report new_triage.md `
  --report new_full.md `
  --json new.json
```

Compare:

```text
program words used
free words
STRINGTABLE count
STRINGTABLE references
CLI_DISPATCHCOMMAND span
compare-chain count
print-like call count
feature-family calls
```

A good change should reduce at least one of these major metrics.

---

## 13. Reading a Finding Correctly

Each interpreted finding may include:

```text
Compiler/GCBASIC reason
Likely programmer intent
Actionability
Fix strategy
```

Example:

```text
Compiler/GCBASIC reason:
GCBASIC emitted literal-load, subtract, STATUS/Z skip, and branch for an IF equality test.

Likely programmer intent:
Dispatch a one-character CLI command.

Actionability:
High

Fix strategy:
Normalize command input case once and reduce duplicate upper/lower command branches.
```

This is the correct interpretation level. The fix belongs in the `.gcb` source, not in the generated assembly.

---

## 14. What Not to Do

Do not:

```text
blindly remove NOPs
hand-delete MOVLB/BANKSEL
hand-edit generated GOTOs
remove volatile-looking SFR access
optimize individual MOVLW reloads first
judge GCBASIC output as bad because it is verbose
```

Do:

```text
shorten strings
reduce command count
remove duplicate tests
split build profiles
remove unused features
measure before/after with map files
```

---

## 15. Operator’s Rule of Thumb

If Revelator points to one assembly instruction, be cautious.

If Revelator points to a repeated pattern hundreds of times, pay attention.

If triage says strings, dispatcher, print scaffolding, and build profiles are the top suspects, start there.

---

## 16. Recommended Interpretation for the Nugget CLI Case

For the current Nugget CLI monitor, the tool’s practical diagnosis is:

```text
The program is nearly full because it is a rich monitor.
The largest savings are likely in:
  string/help/banner text
  serial print sequences
  linear command dispatch
  duplicate upper/lower command tests
  too many feature families in one build
```

The best next engineering step is not instruction-level cleanup. It is source-level profiling:

```text
CORE build
CORE + LED
CORE + ADC
CORE + 7SEG
FULL build
```

Then compare map/revelator output for each profile.

---

## 17. Final Principle

The Revelator’s job is to reveal the machine.

The programmer’s job is to simplify the source.

For GCBASIC, that usually means:

```text
less prose in the PIC
fewer duplicate command tests
smaller command vocabulary
profiled feature builds
compact protocol tokens
```

That is how a 97% full CLI becomes manageable again.
