#!/usr/bin/env python3
"""
xc8_asm_revelator_v3_4_mapaware.py

XC8 ASM Revelator v3.6-product

A conservative programmer-facing review tool for Microchip XC8 / PIC-AS listing
and map output.

Inputs:
    - XC8/PIC-AS .lst, .asm, or .s listing/assembly file
    - optional XC8 .map linker map file

Outputs:
    - Markdown programmer report
    - optional JSON report
    - optional annotated listing

Design goal:
    Reveal what the compiler and linker did.

The listing file answers:
    "What instructions were emitted?"

The map file answers:
    "Where did instructions, symbols, psects, and RAM objects land?"

This tool combines both when possible. It does NOT automatically rewrite code.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Developer-facing Markdown should emphasize grouped insight, not drown the
# programmer in thousands of repeated low-level lines. JSON still preserves
# the complete finding set for audit and dashboard work.
DEFAULT_MARKDOWN_FINDING_LIMIT = 250


@dataclasses.dataclass
class AsmLine:
    number: int
    raw: str
    cleaned: str
    address: Optional[int]
    address_text: Optional[str]
    opcode_text: Optional[str]
    code: str
    comment: str
    label: Optional[str]
    mnemonic: Optional[str]
    operands: str
    source_context: Optional[str] = None
    psect: Optional[str] = None

    @property
    def is_executable(self) -> bool:
        return self.mnemonic in EXEC_MNEMONICS


@dataclasses.dataclass
class Finding:
    severity: str
    category: str
    line: int
    message: str
    why: str
    suggestion: str
    raw: str
    cleaned: str = ""
    address_text: Optional[str] = None
    source_context: Optional[str] = None
    map_note: Optional[str] = None
    context: List[str] = dataclasses.field(default_factory=list)
    related_lines: List[int] = dataclasses.field(default_factory=list)

    # v3.6: interpretation-layer fields.
    compiler_reason: Optional[str] = None
    programmer_intent: Optional[str] = None
    actionability: str = "Review"
    fix_strategy: Optional[str] = None
    group_key: Optional[str] = None
    suppressed: bool = False
    suppression_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class PsectInfo:
    name: str
    start: Optional[int] = None
    end: Optional[int] = None
    size: Optional[int] = None
    raw_lines: List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class SymbolInfo:
    name: str
    address: Optional[int] = None
    raw: str = ""


@dataclasses.dataclass
class MapInfo:
    path: Optional[str] = None
    raw_line_count: int = 0
    memory_lines: List[str] = dataclasses.field(default_factory=list)
    psects: Dict[str, PsectInfo] = dataclasses.field(default_factory=dict)
    symbols: Dict[str, SymbolInfo] = dataclasses.field(default_factory=dict)
    call_graph_lines: List[str] = dataclasses.field(default_factory=list)
    data_usage_lines: List[str] = dataclasses.field(default_factory=list)
    program_usage_lines: List[str] = dataclasses.field(default_factory=list)
    warnings: List[str] = dataclasses.field(default_factory=list)
    section_hits: Dict[str, int] = dataclasses.field(default_factory=dict)


KNOWN_MNEMONICS = {
    "addlw", "addwf", "andlw", "andwf", "asrf", "bcf", "bra", "brw", "bsf",
    "btfsc", "btfss", "call", "clrf", "clrw", "clrwdt", "comf", "cpfseq",
    "cpfsgt", "cpfslt", "decf", "decfsz", "goto", "incf", "incfsz", "iorlw",
    "iorwf", "lslf", "lsrf", "movf", "movlb", "movlp", "movlw", "movwf",
    "nop", "option", "pagesel", "psect", "reset", "retfie", "retlw", "return",
    "rlf", "rrf", "sleep", "sublw", "subwf", "swapf", "tris", "xorlw", "xorwf",
    "processor", "pagewidth", "opt", "dabs", "equ", "global", "extrn", "org",
    "end", "config", "dw", "db", "de", "set", "space", "align", "fnconf",
    "signat", "file", "line",
}

EXEC_MNEMONICS = {
    "addlw", "addwf", "andlw", "andwf", "asrf", "bcf", "bra", "brw", "bsf",
    "btfsc", "btfss", "call", "clrf", "clrw", "clrwdt", "comf", "cpfseq",
    "cpfsgt", "cpfslt", "decf", "decfsz", "goto", "incf", "incfsz", "iorlw",
    "iorwf", "lslf", "lsrf", "movf", "movlb", "movlp", "movlw", "movwf",
    "nop", "retfie", "retlw", "return", "rlf", "rrf", "sleep", "sublw",
    "subwf", "swapf", "tris", "xorlw", "xorwf",
}

UNCONDITIONAL_BRANCHES = {"goto", "bra"}
RETURN_MNEMONICS = {"return", "retlw", "retfie"}
SKIP_MNEMONICS = {"btfsc", "btfss", "decfsz", "incfsz", "cpfseq", "cpfsgt", "cpfslt"}
BANK_SELECT_MNEMONICS = {"movlb", "banksel"}
FILE_REGISTER_OPS = {
    "clrf", "movwf", "movf", "bcf", "bsf", "btfsc", "btfss", "decf", "decfsz",
    "incf", "incfsz", "iorwf", "andwf", "xorwf", "subwf", "addwf", "rlf",
    "rrf", "swapf", "lslf", "lsrf", "asrf", "comf", "cpfseq", "cpfsgt", "cpfslt",
}
CONTROL_BARRIERS = {"call", "goto", "bra", "brw", "return", "retlw", "retfie", "psect", "global", "org", "end"}

ROUGH_CYCLES = {
    "nop": "1", "movlw": "1", "movwf": "1", "movf": "1", "movlb": "1",
    "clrf": "1", "bcf": "1", "bsf": "1", "goto": "2", "bra": "2",
    "call": "2", "return": "2", "retlw": "2", "retfie": "2",
    "btfsc": "1/2", "btfss": "1/2", "decfsz": "1/2", "incfsz": "1/2",
}


def parse_int_maybe(text: Optional[str]) -> Optional[int]:
    if text is None:
        return None
    s = text.strip().rstrip(",")
    if not s:
        return None
    try:
        if s.lower().startswith("0x"):
            return int(s, 16)
        if re.fullmatch(r"[0-9A-Fa-f]+", s) and re.search(r"[A-Fa-f]", s):
            return int(s, 16)
        return int(s, 10)
    except Exception:
        return None


def split_comment(line: str) -> Tuple[str, str]:
    if ";" in line:
        a, b = line.split(";", 1)
        return a.rstrip(), ";" + b.rstrip()
    return line.rstrip(), ""


def first_token(text: str) -> str:
    return text.strip().split(None, 1)[0].rstrip(":").lower() if text.strip() else ""


def first_operand(ops: str) -> str:
    return ops.split(",", 1)[0].strip() if ops else ""


def target_symbol(ops: str) -> str:
    return first_operand(ops).strip().lstrip("#")


def looks_like_asm_text(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    t = first_token(s)
    if t in KNOWN_MNEMONICS:
        return True
    if re.match(r"^[A-Za-z_.$?][\w.$?@#]*:\s*($|[A-Za-z_.$?])", s):
        return True
    parts = s.split()
    if len(parts) >= 2 and parts[1].lower() in KNOWN_MNEMONICS:
        return True
    return False


def strip_lst_line(raw: str) -> Tuple[str, Optional[str], Optional[int], Optional[str]]:
    line = raw.rstrip("\n")
    s = line.strip()
    if not s:
        return line, None, None, None
    if s.startswith("!"):
        return ";" + s, None, None, None

    # XC8 listing format observed in rotate.X.production.lst:
    #   1032     07DB  017E                movlb       62      ; select bank62
    m = re.match(
        r"^\s*(?P<listline>\d+)\s+"
        r"(?:(?P<addr>[0-9A-Fa-f]{4,6})\s+)?"
        r"(?:(?P<opcode>[0-9A-Fa-f]{4,6})\s+)?"
        r"(?P<body>.+?)\s*$",
        line,
    )
    if m:
        body = m.group("body").strip()
        addr_text = m.group("addr")
        opcode = m.group("opcode")
        if looks_like_asm_text(body):
            return body, addr_text, parse_int_maybe(addr_text), opcode
        if body:
            return ";" + body, addr_text, parse_int_maybe(addr_text), opcode

    # Address-colon form: 0x7DB: MOVLB 0x3E
    m = re.match(r"^\s*(?:0x)?(?P<addr>[0-9A-Fa-f]+):\s+(?P<body>.+)$", line)
    if m:
        body = m.group("body").strip()
        addr_text = m.group("addr")
        return (body if looks_like_asm_text(body) else ";" + body), addr_text, parse_int_maybe(addr_text), None

    return line, None, None, None


def parse_asm_line(number: int, raw: str, source_context: Optional[str], current_psect: Optional[str]) -> AsmLine:
    cleaned, addr_text, addr_int, opcode_text = strip_lst_line(raw)
    code, comment = split_comment(cleaned)
    stripped = code.strip()
    label = None
    mnemonic = None
    operands = ""

    if stripped:
        m = re.match(r"^([A-Za-z_.$?][\w.$?@#]*):\s*(.*)$", stripped)
        rest = stripped
        if m:
            label = m.group(1)
            rest = m.group(2).strip()
        if rest:
            parts = rest.split(None, 2)
            possible = parts[0].lower()
            if possible in KNOWN_MNEMONICS:
                mnemonic = possible
                operands = rest.split(None, 1)[1].strip() if len(rest.split(None, 1)) > 1 else ""
            elif len(parts) >= 2 and parts[1].lower() in KNOWN_MNEMONICS:
                label = parts[0]
                mnemonic = parts[1].lower()
                operands = parts[2].strip() if len(parts) > 2 else ""

    return AsmLine(number, raw.rstrip("\n"), cleaned.rstrip("\n"), addr_int, addr_text, opcode_text, code, comment, label, mnemonic, operands, source_context, current_psect)


def parse_listing_file(path: Path) -> List[AsmLine]:
    raw_lines = path.read_text(errors="replace").splitlines()
    out: List[AsmLine] = []
    source_context = None
    current_psect = None
    for i, raw in enumerate(raw_lines, 1):
        stripped = raw.strip()
        if stripped.startswith("!"):
            maybe = stripped.lstrip("!").strip()
            if maybe:
                source_context = maybe
        ln = parse_asm_line(i, raw, source_context, current_psect)
        if ln.mnemonic == "psect":
            current_psect = first_operand(ln.operands)
            ln.psect = current_psect
        out.append(ln)
    return out


MAP_SECTION_HINTS = {
    "program_memory": re.compile(r"(program\s+memory|memory\s+usage|rom\s+usage|class\s+CODE)", re.I),
    "data_memory": re.compile(r"(data\s+memory|ram\s+usage|class\s+COMMON|class\s+BANK|compiled\s+stack)", re.I),
    "psect": re.compile(r"(psect|section|class\s+address|name\s+link)", re.I),
    "symbol": re.compile(r"(symbol|global|external)", re.I),
    "call_graph": re.compile(r"(call\s+graph|callgraph|critical\s+path)", re.I),
}


def parse_map_file(path: Optional[Path]) -> MapInfo:
    info = MapInfo(path=str(path) if path else None)
    if path is None:
        return info
    if not path.exists():
        info.warnings.append(f"Map file not found: {path}")
        return info

    lines = path.read_text(errors="replace").splitlines()
    info.raw_line_count = len(lines)
    current_section = None

    for raw in lines:
        s = raw.rstrip("\n")
        for name, rx in MAP_SECTION_HINTS.items():
            if rx.search(s):
                current_section = name
                info.section_hits[name] = info.section_hits.get(name, 0) + 1
                break

        if current_section == "call_graph" and s.strip():
            info.call_graph_lines.append(s)
        if current_section == "data_memory" and s.strip():
            info.data_usage_lines.append(s)
        if current_section == "program_memory" and s.strip():
            info.program_usage_lines.append(s)

        if re.search(r"\b(ROM|RAM|program|data|memory|bytes|words|psect|class|CODE|COMMON|BANK|ABS|SPACE)\b", s, re.I):
            info.memory_lines.append(s)

        # Broad psect candidates: tries to detect lines containing psect-like names and address/size values.
        if any(key in s.lower() for key in ["psect", "class", "code", "common", "bank", "maintext", "cinit", "config"]):
            hexes = re.findall(r"0x[0-9A-Fa-f]+|\b[0-9A-Fa-f]{4,6}\b", s)
            names = re.findall(r"\b[A-Za-z_.$?][\w.$?@#]*\b", s)
            useful_names = [n for n in names if n.lower() not in {"class", "code", "space", "abs", "ovrld", "global", "delta", "psect"}]
            if useful_names:
                pname = useful_names[0]
                pi = info.psects.setdefault(pname, PsectInfo(name=pname))
                if hexes:
                    vals = [parse_int_maybe(h) for h in hexes]
                    vals = [v for v in vals if v is not None]
                    if vals and pi.start is None:
                        pi.start = vals[0]
                    if len(vals) >= 2 and pi.size is None:
                        pi.size = vals[1]
                    if pi.start is not None and pi.size is not None:
                        pi.end = pi.start + pi.size - 1
                pi.raw_lines.append(s)

        # Symbol candidates: address symbol OR symbol address.
        m1 = re.match(r"^\s*(?P<addr>0x[0-9A-Fa-f]+|[0-9A-Fa-f]{4,6})\s+(?P<name>[_A-Za-z.$?][\w.$?@#]*)\b", s)
        m2 = re.match(r"^\s*(?P<name>[_A-Za-z.$?][\w.$?@#]*)\s+(?P<addr>0x[0-9A-Fa-f]+|[0-9A-Fa-f]{4,6})\b", s)
        m = m1 or m2
        if m:
            name = m.group("name")
            addr = parse_int_maybe(m.group("addr"))
            if addr is not None and name.lower() not in KNOWN_MNEMONICS:
                info.symbols[name] = SymbolInfo(name=name, address=addr, raw=s)

    return info


def build_sfr_map(lines: List[AsmLine]) -> Dict[int, str]:
    sfr: Dict[int, str] = {}
    for ln in lines:
        if ln.mnemonic == "equ" and ln.label:
            num = parse_int_maybe(first_operand(ln.operands))
            if num is not None:
                old = sfr.get(num)
                if old is None or (ln.label.isupper() and not old.isupper()):
                    sfr[num] = ln.label
    return sfr


def build_label_map(lines: List[AsmLine]) -> Dict[str, int]:
    return {ln.label: i for i, ln in enumerate(lines) if ln.label}


def next_code_index(lines: List[AsmLine], start: int) -> Optional[int]:
    for i in range(start + 1, len(lines)):
        if lines[i].mnemonic or lines[i].label:
            return i
    return None


def previous_code_index(lines: List[AsmLine], start: int) -> Optional[int]:
    for i in range(start - 1, -1, -1):
        if lines[i].mnemonic or lines[i].label:
            return i
    return None


def line_context(lines: List[AsmLine], i: int, span: int = 4) -> List[str]:
    rows = []
    for j in range(max(0, i - span), min(len(lines), i + span + 1)):
        ln = lines[j]
        if ln.cleaned.strip():
            addr = f" addr={ln.address_text}" if ln.address_text else ""
            rows.append(f"{ln.number}{addr}: {ln.cleaned}")
    return rows


def map_note_for_line(ln: AsmLine, map_info: MapInfo) -> Optional[str]:
    if ln.address is None or not map_info.psects:
        return None
    for name, pi in map_info.psects.items():
        if pi.start is not None and pi.end is not None and pi.start <= ln.address <= pi.end:
            return f"Address {ln.address_text} appears within map psect `{name}` ({pi.start:04X}-{pi.end:04X})."
    return None


def function_regions(lines: List[AsmLine]) -> List[Dict[str, Any]]:
    labels = [(i, ln) for i, ln in enumerate(lines) if ln.label]
    regions = []
    for idx, (i, ln) in enumerate(labels):
        end_i = labels[idx + 1][0] if idx + 1 < len(labels) else len(lines)
        execs = [x for x in lines[i:end_i] if x.is_executable]
        if not execs:
            continue
        addrs = [x.address for x in execs if x.address is not None]
        regions.append({
            "label": ln.label,
            "line": ln.number,
            "start_address": min(addrs) if addrs else None,
            "end_address": max(addrs) if addrs else None,
            "instruction_count": len(execs),
            "psect": ln.psect,
            "source_context": ln.source_context,
        })
    return regions




def context(lines: List[AsmLine], i: int, span: int = 4) -> List[str]:
    """Compatibility wrapper for local context snippets used by v3.6 findings."""
    try:
        return local_context(lines, i, span=span)
    except NameError:
        a = max(0, i - span)
        b = min(len(lines), i + span + 1)
        rows: List[str] = []
        for j in range(a, b):
            ln = lines[j]
            if ln.cleaned.strip():
                addr = f" addr={ln.address_text}" if getattr(ln, "address_text", None) else ""
                rows.append(f"{ln.number}{addr}: {ln.cleaned}")
        return rows


# =============================================================================
# GCBASIC-aware interpretation and suppression layer
# =============================================================================

STRUCTURAL_CALL_NAMES = {"INITSYS", "INITUSART"}
STRUCTURAL_CALL_PREFIXES = ("INIT", "BASPROGRAM")
GCBASIC_COMPARE_PATTERN_CATEGORY = "GCBASIC_LINEAR_IF_CHAR_COMPARE"


@dataclasses.dataclass
class GroupedInsight:
    """Collapsed source-level explanation of many low-level findings."""

    category: str
    count: int
    severity: str
    title: str
    compiler_reason: str
    programmer_intent: str
    actionability: str
    fix_strategy: str
    representative_lines: List[int] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def call_target_from_text(text: str) -> str:
    m = re.search(r"\b(?:call|fcall)\s+([_A-Za-z.$?][\w.$?@#]*)", text, re.I)
    return m.group(1) if m else ""


def is_structural_call_target(name: str) -> bool:
    if not name:
        return False
    return name in STRUCTURAL_CALL_NAMES or any(name.startswith(prefix) for prefix in STRUCTURAL_CALL_PREFIXES)


def interpret_finding_for_gcbasic(f: Finding) -> Finding:
    """Attach GCBASIC-specific meaning and default suppression metadata."""
    if f.group_key is None:
        f.group_key = f.category

    raw_text = f.cleaned or f.raw
    call_target = call_target_from_text(raw_text)

    if call_target and is_structural_call_target(call_target):
        f.compiler_reason = "GCBASIC emitted standard startup or hardware-initialization scaffolding."
        f.programmer_intent = f"Initialize required runtime/hardware support via `{call_target}`."
        f.actionability = "Ignore"
        f.fix_strategy = "Do not optimize this line directly; remove the feature that requires the initializer if needed."
        f.suppressed = True
        f.suppression_reason = "Structural initialization call."
        f.group_key = "STRUCTURAL_INITIALIZATION"

    elif f.category == "PIC_SKIP_PATTERN":
        f.compiler_reason = "GCBASIC/PIC-AS commonly emits BTFSS/BTFSC-style skip tests for IF/THEN and loop logic."
        f.programmer_intent = "Implement a source-level conditional or loop test."
        f.actionability = "Low"
        f.fix_strategy = "Do not optimize individual skip instructions. Reduce repeated source-level condition patterns."
        f.group_key = "PIC_SKIP_CONTROL_FLOW"

    elif f.category == "GCBASIC_LINEAR_IF_CHAR_COMPARE":
        # Already created with rich fields; keep it.
        pass

    elif f.category == "REPEATED_MOVLW_SAME_LITERAL":
        f.compiler_reason = "GCBASIC may reload W conservatively around generated blocks, print setup, and branch targets."
        f.programmer_intent = "Prepare a literal for a comparison, assignment, or helper setup."
        f.actionability = "Low"
        f.fix_strategy = "Do not hand-edit individual reloads. Reduce repeated source constructs that cause them."
        f.group_key = "REPEATED_LITERAL_RELOADS"

    elif f.category == "SFR_ACCESS":
        f.compiler_reason = "GCBASIC emitted direct file-register access for hardware-facing code."
        f.programmer_intent = "Configure or drive PIC hardware."
        f.actionability = "Ignore"
        f.fix_strategy = "Do not remove hardware accesses unless removing the whole related feature."
        f.suppressed = True
        f.suppression_reason = "Expected hardware register access."
        f.group_key = "STRUCTURAL_SFR_ACCESS"

    elif f.category in {"BANK_SELECT", "MAP_SYMBOL_MATCH"}:
        f.compiler_reason = "This is structural PIC/linker scaffolding or cross-reference evidence."
        f.programmer_intent = "Support correct memory/register access or final linked placement."
        f.actionability = "Ignore"
        f.fix_strategy = "Use as evidence, not as a direct optimization target."
        f.suppressed = True
        f.suppression_reason = "Structural scaffolding/evidence."
        f.group_key = "STRUCTURAL_SCAFFOLDING"

    elif f.category == "REPEATED_BANK_SELECT":
        f.compiler_reason = "PIC bank selection is required, but repeated selects can indicate conservative generated code."
        f.programmer_intent = "Reach file registers/SFRs safely."
        f.actionability = "Low"
        f.fix_strategy = "Do not start here; remove whole source features or hot repeated blocks first."
        f.group_key = "BANK_SELECT_OVERHEAD"

    elif f.category in {"POSSIBLY_UNREACHABLE_CODE", "BRANCH_TO_NEXT_LABEL"}:
        f.compiler_reason = "GCBASIC emits explicit labels and GOTOs for structured IF/ELSE/ENDIF flow."
        f.programmer_intent = "Represent structured BASIC control flow in PIC assembly."
        f.actionability = "Medium"
        f.fix_strategy = "Simplify repeated source-level branches; do not hand-edit generated GOTOs."
        f.group_key = "GCBASIC_STRUCTURED_GOTO_FLOW"

    elif f.category in {"COUNTER_DELAY_LOOP", "DELAY_USAGE"}:
        f.compiler_reason = "GCBASIC emitted a delay helper or software timing loop."
        f.programmer_intent = "Wait for a human-visible/peripheral timing interval."
        f.actionability = "Low"
        f.fix_strategy = "In this CLI, strings and dispatch are higher-value targets than delay code."
        f.group_key = "DELAY_OR_TIMING"

    elif f.category == "COMPILER_TEMPORARY":
        f.compiler_reason = "GCBASIC/XC8 generated an internal temporary or helper symbol."
        f.programmer_intent = "Support an expression, helper routine, or generated storage convention."
        f.actionability = "Review"
        f.fix_strategy = "Use the map file to locate the symbol; reduce the source construct if it is large."
        f.group_key = "COMPILER_TEMPORARIES"

    elif f.category == "HOT_CALL_TARGET":
        target = call_target or "helper"
        f.compiler_reason = "The source or generated code repeatedly calls the same helper routine."
        f.programmer_intent = f"Reuse `{target}`."
        f.actionability = "Medium"
        f.fix_strategy = "If print-related, reduce repeated print sequences and long text before considering inlining."
        f.group_key = f"HOT_CALL_TARGET:{target}"

    elif f.category.startswith("NOP"):
        f.compiler_reason = "NOPs may be timing padding, skip padding, or generated filler."
        f.programmer_intent = "Timing, alignment, or safe skip target."
        f.actionability = "Low"
        f.fix_strategy = "Review only after larger source-level reductions."
        f.group_key = "NOP_OR_TIMING_PADDING"

    return f


def suppress_findings_for_profile(findings: List[Finding], profile: str, show_structural: bool = False) -> List[Finding]:
    """Return findings after applying profile-specific interpretation/suppression."""
    interpreted = [interpret_finding_for_gcbasic(f) for f in findings]
    if profile == "raw" or show_structural:
        return interpreted
    if profile in {"default", "gcbasic"}:
        return [f for f in interpreted if not f.suppressed]
    return interpreted


def detect_gcbasic_linear_compare_blocks(lines: List[AsmLine]) -> List[Finding]:
    """Detect repeated GCBASIC IF char = literal command-dispatch blocks."""
    findings: List[Finding] = []
    for i in range(len(lines) - 3):
        a, b, c, d = lines[i:i + 4]
        if (
            a.mnemonic == "movlw"
            and b.mnemonic == "subwf"
            and c.mnemonic == "btfss"
            and d.mnemonic in {"goto", "bra"}
        ):
            literal = a.operands.strip()
            findings.append(Finding(
                severity="INFO",
                category=GCBASIC_COMPARE_PATTERN_CATEGORY,
                line=a.number,
                message=f"GCBASIC linear character comparison block for literal `{literal}`.",
                why="This four-instruction sequence is the normal GCBASIC/PIC translation of IF char = literal THEN.",
                suggestion="Optimize the source-level dispatcher, not this individual block.",
                raw=a.raw,
                cleaned=a.cleaned,
                address_text=a.address_text,
                source_context=a.source_context,
                context=context(lines, i),
                related_lines=[a.number, b.number, c.number, d.number],
                compiler_reason="GCBASIC emitted literal-load, subtract, STATUS/Z skip, and branch for an IF equality test.",
                programmer_intent="Dispatch a one-character CLI command.",
                actionability="High",
                fix_strategy="Normalize input case once, remove duplicate upper/lower tests, or use grouped/table dispatch.",
                group_key="GCBASIC_LINEAR_COMPARE_CHAIN",
            ))
    return findings


def build_grouped_insights(findings: List[Finding]) -> List[GroupedInsight]:
    """Collapse repeated low-level findings into higher-level developer insights."""
    groups: Dict[str, List[Finding]] = defaultdict(list)
    for f in findings:
        groups[f.group_key or f.category].append(f)

    insights: List[GroupedInsight] = []
    for key, items in groups.items():
        count = len(items)
        reps = [f.line for f in items[:12]]
        first = items[0]

        if key == "GCBASIC_LINEAR_COMPARE_CHAIN":
            insights.append(GroupedInsight(
                category=key,
                count=count,
                severity="INFO",
                title=f"Linear GCBASIC command comparison chain ({count} blocks).",
                compiler_reason="GCBASIC translated repeated IF char = literal tests into movlw/subwf/btfss/goto blocks.",
                programmer_intent="Implement a one-character CLI dispatcher.",
                actionability="High",
                fix_strategy="Normalize command input to one case once; remove duplicate upper/lower tests; consider grouped/table dispatch.",
                representative_lines=reps,
            ))
        elif key == "REPEATED_LITERAL_RELOADS":
            insights.append(GroupedInsight(
                category=key,
                count=count,
                severity="WARN",
                title=f"Repeated literal reloads ({count} occurrences).",
                compiler_reason="GCBASIC conservatively reloads W around generated blocks and helper setup.",
                programmer_intent="Prepare literals for comparisons, print helpers, and assignments.",
                actionability="Low",
                fix_strategy="Do not hand-edit reloads. Reduce repeated source-level constructs that cause them.",
                representative_lines=reps,
            ))
        elif key == "GCBASIC_STRUCTURED_GOTO_FLOW":
            insights.append(GroupedInsight(
                category=key,
                count=count,
                severity="WARN",
                title=f"GCBASIC structured GOTO/label flow ({count} findings).",
                compiler_reason="GCBASIC emits explicit labels and GOTOs for IF/ELSE/ENDIF structure.",
                programmer_intent="Represent structured BASIC control flow in PIC assembly.",
                actionability="Medium",
                fix_strategy="Do not remove generated GOTOs directly; simplify repeated source-level branches.",
                representative_lines=reps,
            ))
        elif key.startswith("HOT_CALL_TARGET"):
            target = key.split(":", 1)[1] if ":" in key else "helper"
            insights.append(GroupedInsight(
                category=key,
                count=count,
                severity="INFO",
                title=f"Hot helper target `{target}` ({count} finding group).",
                compiler_reason="The generated code repeatedly calls the same helper.",
                programmer_intent=f"Reuse `{target}`.",
                actionability="Medium",
                fix_strategy="If print-related, reduce repeated print sequences and long text before considering inlining.",
                representative_lines=reps,
            ))
        elif count >= 5:
            insights.append(GroupedInsight(
                category=key,
                count=count,
                severity=first.severity,
                title=f"{key} ({count} occurrences).",
                compiler_reason=first.compiler_reason or first.why,
                programmer_intent=first.programmer_intent or "See representative lines.",
                actionability=first.actionability,
                fix_strategy=first.fix_strategy or first.suggestion,
                representative_lines=reps,
            ))

    action_rank = {"Critical": 0, "High": 1, "Medium": 2, "Review": 3, "Low": 4, "Ignore": 5}
    insights.sort(key=lambda gi: (action_rank.get(gi.actionability, 3), -gi.count, gi.category))
    return insights


class Analyzer:
    def __init__(self, lines: List[AsmLine], map_info: Optional[MapInfo] = None):
        self.lines = lines
        self.map_info = map_info or MapInfo()
        self.labels = build_label_map(lines)
        self.sfr = build_sfr_map(lines)
        self.findings: List[Finding] = []

    def add(self, severity: str, category: str, line_index: int, message: str, why: str, suggestion: str, related: Optional[List[int]] = None) -> None:
        ln = self.lines[line_index]
        self.findings.append(Finding(
            severity=severity,
            category=category,
            line=ln.number,
            message=message,
            why=why,
            suggestion=suggestion,
            raw=ln.raw,
            cleaned=ln.cleaned,
            address_text=ln.address_text,
            source_context=ln.source_context,
            map_note=map_note_for_line(ln, self.map_info),
            context=line_context(self.lines, line_index),
            related_lines=related or [],
        ))

    def analyze(self) -> List[Finding]:
        self.find_sfr_access()
        self.find_pic_skip_patterns()
        self.find_nops()
        self.find_bank_patterns()
        self.find_delay_loops()
        self.find_branch_to_next_label()
        self.find_movf_file_to_self()
        self.find_hot_call_targets()
        self.find_unreachable_after_unconditional()
        self.find_map_symbol_connections()
        return sorted(self.findings, key=lambda f: (f.line, f.category))

    def find_sfr_access(self) -> None:
        for i, ln in enumerate(self.lines):
            if ln.mnemonic not in FILE_REGISTER_OPS:
                continue
            num = parse_int_maybe(first_operand(ln.operands))
            if num is None:
                continue
            name = self.sfr.get(num)
            if name:
                self.add("INFO", "SFR_ACCESS", i,
                         f"{ln.mnemonic.upper()} touches file register {num} (`{name}`).",
                         "XC8 listings often show numeric file-register operands. Mapping the number back to the SFR name connects assembly to hardware behavior.",
                         "Use this as a register-level explanation; do not remove volatile SFR accesses merely because they look simple.")

    def find_pic_skip_patterns(self) -> None:
        for i, ln in enumerate(self.lines):
            if ln.mnemonic not in SKIP_MNEMONICS:
                continue
            ni = next_code_index(self.lines, i)
            next_text = self.lines[ni].cleaned if ni is not None else "(none)"
            self.add("INFO", "PIC_SKIP_PATTERN", i,
                     f"{ln.mnemonic.upper()} conditionally skips the next instruction.",
                     f"PIC skip instructions implement C if/loop logic by conditionally discarding exactly one following instruction. Next instruction: `{next_text}`.",
                     "Read this instruction together with the next line to understand branch polarity.",
                     related=[self.lines[ni].number] if ni is not None else [])

    def find_nops(self) -> None:
        for i, ln in enumerate(self.lines):
            if ln.mnemonic != "nop":
                continue
            pi = previous_code_index(self.lines, i)
            ni = next_code_index(self.lines, i)
            pm = self.lines[pi].mnemonic if pi is not None else None
            nm = self.lines[ni].mnemonic if ni is not None else None
            if pm in SKIP_MNEMONICS:
                self.add("INFO", "NOP_AFTER_SKIP", i, "NOP follows a skip-class instruction.",
                         "This can be intentional safe padding because PIC skip instructions discard the next instruction.",
                         "Keep unless the surrounding skip logic is proven safe without padding.", [self.lines[pi].number])
            elif pm in UNCONDITIONAL_BRANCHES or pm in RETURN_MNEMONICS:
                self.add("WARN", "NOP_AFTER_BRANCH_OR_RETURN", i, "NOP follows unconditional control transfer.",
                         "Execution usually cannot fall through to this instruction, so it may be dead padding or timing residue.",
                         "Review as a possible removal candidate, but verify timing/alignment and branch targets first.",
                         [self.lines[pi].number] if pi is not None else [])
            elif nm in RETURN_MNEMONICS:
                self.add("WARN", "NOP_BEFORE_RETURN", i, "NOP appears immediately before return.",
                         "This may waste a cycle unless inserted for timing.", "Review timing purpose before changing.",
                         [self.lines[ni].number] if ni is not None else [])
            else:
                self.add("INFO", "NOP_GENERAL", i, "NOP found.",
                         "NOP can be timing padding, delay-loop residue, or compiler filler.",
                         "Review only if optimizing cycle-level behavior.")

    def find_bank_patterns(self) -> None:
        last = None
        for i, ln in enumerate(self.lines):
            if not ln.mnemonic:
                continue
            if ln.label or ln.mnemonic in CONTROL_BARRIERS:
                last = None
            if ln.mnemonic in BANK_SELECT_MNEMONICS:
                op = first_operand(ln.operands)
                if last and last[0] == ln.mnemonic and last[1] == op:
                    self.add("WARN", "REPEATED_BANK_SELECT", i,
                             f"Repeated {ln.mnemonic.upper()} {op}.",
                             "Repeated bank selection can cost cycles if BSR was already known. Compilers are often conservative around bank state.",
                             "Remove only after proving no branch/call/label entry can require this bank setup.", [self.lines[last[2]].number])
                else:
                    self.add("INFO", "BANK_SELECT", i,
                             f"{ln.mnemonic.upper()} selects bank {op}.",
                             "PIC file-register access depends on bank selection. This explains why nearby numeric operands may refer to high-address SFRs or variables.",
                             "Use as context for following file-register instructions.")
                last = (ln.mnemonic, op, i)

    def find_delay_loops(self) -> None:
        for i, ln in enumerate(self.lines):
            if not ln.label:
                continue
            idx = []
            j = i
            for _ in range(12):
                j = next_code_index(self.lines, j)
                if j is None:
                    break
                idx.append(j)
            mn = [self.lines[k].mnemonic for k in idx]
            jumps_back = any(self.lines[k].mnemonic in UNCONDITIONAL_BRANCHES and target_symbol(self.lines[k].operands) == ln.label for k in idx)
            has_counter_skip = any(m in {"decfsz", "incfsz"} for m in mn)
            if jumps_back and has_counter_skip:
                self.add("INFO", "COUNTER_DELAY_LOOP", i,
                         f"Label `{ln.label}` looks like a counter/timing loop.",
                         "A backward GOTO plus DECFSZ/INCFSZ is a classic PIC software delay or counted-loop structure.",
                         "Estimate cycle cost before changing. It may implement __delay or a deliberate wait.",
                         [self.lines[k].number for k in idx])

    def find_branch_to_next_label(self) -> None:
        for i, ln in enumerate(self.lines):
            if ln.mnemonic not in UNCONDITIONAL_BRANCHES:
                continue
            t = target_symbol(ln.operands)
            if t not in self.labels:
                continue
            ni = next_code_index(self.lines, i)
            if ni is not None and self.lines[ni].label == t:
                self.add("WARN", "BRANCH_TO_NEXT_LABEL", i,
                         f"{ln.mnemonic.upper()} targets the next label `{t}`.",
                         "An unconditional branch to the next executable location usually changes nothing and costs cycles.",
                         "Review for removal or source-level simplification.", [self.lines[ni].number])

    def find_movf_file_to_self(self) -> None:
        for i, ln in enumerate(self.lines):
            if ln.mnemonic != "movf":
                continue
            ops = [x.strip().lower() for x in ln.operands.split(",")]
            if len(ops) >= 2 and ops[1] in {"f", "1"}:
                self.add("INFO", "MOVF_FILE_TO_SELF", i,
                         "MOVF f,F probably exists to set status flags.",
                         "This idiom updates flags, especially Z, without changing the register value.",
                         "Keep if followed by a STATUS/Z test or skip instruction.")

    def find_hot_call_targets(self) -> None:
        calls = []
        for i, ln in enumerate(self.lines):
            if ln.mnemonic == "call":
                t = target_symbol(ln.operands)
                if t:
                    calls.append((i, t))
        counts = Counter(t for _, t in calls)
        for t, n in counts.items():
            if n >= 3:
                firsts = [self.lines[i].number for i, x in calls if x == t][:10]
                self.findings.append(Finding("INFO", "HOT_CALL_TARGET", firsts[0],
                    f"Function `{t}` is called {n} times.",
                    "Frequent calls to tiny helpers can cost stack depth and call/return cycles on PIC devices.",
                    "Inspect size and purpose. Consider source-level restructuring or inlining only if the helper is truly small and hot.",
                    self.lines[calls[0][0]].raw, self.lines[calls[0][0]].cleaned, self.lines[calls[0][0]].address_text,
                    context=line_context(self.lines, calls[0][0]), related_lines=firsts))

    def find_unreachable_after_unconditional(self) -> None:
        for i, ln in enumerate(self.lines):
            if ln.mnemonic not in UNCONDITIONAL_BRANCHES and ln.mnemonic not in RETURN_MNEMONICS:
                continue
            ni = next_code_index(self.lines, i)
            if ni is None or self.lines[ni].label:
                continue
            self.add("WARN", "POSSIBLY_UNREACHABLE_CODE", ni,
                     "Instruction follows unconditional branch/return without an intervening label.",
                     "If execution cannot fall through, this may be unreachable.",
                     "Confirm no listing/psect/debug artifact explains it before changing source.", [ln.number])

    def find_map_symbol_connections(self) -> None:
        if not self.map_info.symbols:
            return
        for i, ln in enumerate(self.lines):
            if not ln.label:
                continue
            sym = self.map_info.symbols.get(ln.label)
            if sym:
                self.add("INFO", "MAP_SYMBOL_MATCH", i,
                         f"Map symbol `{sym.name}` appears at address 0x{sym.address:X}.",
                         "The listing label and linker-map symbol agree, connecting assembly labels to final linked addresses.",
                         "Use this to connect listing analysis to final firmware memory layout.")


def instruction_mix(lines: List[AsmLine]) -> Counter:
    return Counter(ln.mnemonic for ln in lines if ln.is_executable)


def address_summary(lines: List[AsmLine]) -> Dict[str, Any]:
    addrs = [ln.address for ln in lines if ln.is_executable and ln.address is not None]
    if not addrs:
        return {}
    return {"min_address": min(addrs), "max_address": max(addrs), "address_span_words_approx": max(addrs) - min(addrs) + 1, "executable_lines_with_addresses": len(addrs)}




def symbol_kind_from_listing_line(ln: AsmLine) -> str:
    """Classify listing symbols so SFR EQU names are not confused with code labels."""
    if not ln.label:
        return "none"
    if ln.mnemonic == "equ":
        if ln.label.isupper() or ln.label in {"STATUS", "WREG", "BSR", "PORTA", "PORTB", "PORTC", "TRISA", "TRISB", "TRISC", "LATA", "LATB", "LATC", "ANSELA", "ANSELB", "ANSELC"}:
            return "sfr_equ"
        return "equ_symbol"
    if ln.label.startswith("??"):
        return "compiler_temporary"
    if ln.label.startswith("?"):
        return "compiler_symbol"
    if ln.label.startswith("_") or re.match(r"^[lu]\d+$", ln.label):
        return "code_label"
    if ln.is_executable or ln.address is not None:
        return "code_label"
    return "other_label"


def classified_symbols(lines: List[AsmLine]) -> Dict[str, List[AsmLine]]:
    groups: Dict[str, List[AsmLine]] = defaultdict(list)
    for ln in lines:
        k = symbol_kind_from_listing_line(ln)
        if k != "none":
            groups[k].append(ln)
    return groups


def true_code_labels(lines: List[AsmLine]) -> List[AsmLine]:
    out = []
    for i, ln in enumerate(lines):
        if symbol_kind_from_listing_line(ln) == "code_label":
            out.append(ln)
            continue
        if ln.label and ln.mnemonic != "equ":
            j = next_code_index(lines, i)
            if j is not None and lines[j].is_executable:
                out.append(ln)
    # Deduplicate by line number.
    seen = set(); uniq = []
    for ln in out:
        if ln.number not in seen:
            seen.add(ln.number); uniq.append(ln)
    return uniq


def compiler_temporary_occurrences(lines: List[AsmLine]) -> Dict[str, AsmLine]:
    found: Dict[str, AsmLine] = {}
    for ln in lines:
        for t in re.findall(r"\?\?[_A-Za-z0-9.$?@#]+|\?[_A-Za-z0-9.$?@#]+", ln.cleaned):
            found.setdefault(t, ln)
    return found


def sfr_equ_definitions(lines: List[AsmLine]) -> List[AsmLine]:
    return [ln for ln in lines if symbol_kind_from_listing_line(ln) == "sfr_equ"]


def other_equ_definitions(lines: List[AsmLine]) -> List[AsmLine]:
    return [ln for ln in lines if symbol_kind_from_listing_line(ln) == "equ_symbol"]

def render_map_summary(map_info: MapInfo) -> List[str]:
    out = ["## Linker Map Summary", ""]
    if not map_info.path:
        out += ["No map file was supplied. Use `--map path/to/file.map` to add linker-memory analysis.", ""]
        return out
    out += [f"**Map file:** `{map_info.path}`", f"**Map physical lines:** {map_info.raw_line_count}", ""]
    if map_info.warnings:
        out += ["### Map Warnings", ""] + [f"- {w}" for w in map_info.warnings] + [""]
    out += ["### Detected Map Sections", ""]
    if map_info.section_hits:
        out += [f"- `{k}`: {v} hint(s)" for k, v in sorted(map_info.section_hits.items())]
    else:
        out.append("- No obvious map sections were recognized. The parser still captured broad memory/symbol lines where possible.")
    out.append("")
    if map_info.psects:
        out += ["### Psect / Section Candidates", "", "| Name | Start | End | Size | Notes |", "|---|---:|---:|---:|---|"]
        for name, pi in sorted(map_info.psects.items()):
            start = f"0x{pi.start:X}" if pi.start is not None else "-"
            end = f"0x{pi.end:X}" if pi.end is not None else "-"
            size = str(pi.size) if pi.size is not None else "-"
            notes = " / ".join(x.strip()[:80] for x in pi.raw_lines[:2]).replace("|", "\\|")
            out.append(f"| `{name}` | {start} | {end} | {size} | {notes} |")
        out.append("")
    if map_info.symbols:
        out += ["### Symbol Candidates", "", "| Symbol | Address | Raw map line |", "|---|---:|---|"]
        for name, sym in sorted(map_info.symbols.items())[:80]:
            addr = f"0x{sym.address:X}" if sym.address is not None else "-"
            raw = sym.raw.strip().replace("|", "\\|")[:100]
            out.append(f"| `{name}` | {addr} | {raw} |")
        if len(map_info.symbols) > 80:
            out.append(f"| ... | ... | {len(map_info.symbols) - 80} more symbols omitted |")
        out.append("")
    for title, rows in [("Program-Memory Related Lines", map_info.program_usage_lines), ("Data-Memory Related Lines", map_info.data_usage_lines), ("Call-Graph Related Lines", map_info.call_graph_lines)]:
        if rows:
            out += [f"### {title}", "", "```text"] + rows[:100]
            if len(rows) > 100:
                out.append(f"... {len(rows) - 100} more lines omitted ...")
            out += ["```", ""]
    return out


def render_markdown_report(path: Path, lines: List[AsmLine], findings: List[Finding], map_info: MapInfo) -> str:
    grouped_insights = build_grouped_insights(findings)
    execs = [ln for ln in lines if ln.is_executable]
    directives = [ln for ln in lines if ln.mnemonic and not ln.is_executable]
    labels_all = [ln for ln in lines if ln.label]
    code_labs = true_code_labels(lines)
    temp_occ = compiler_temporary_occurrences(lines)
    sfrs = sfr_equ_definitions(lines)
    other_equ = other_equ_definitions(lines)
    mix = instruction_mix(lines)
    sev = Counter(f.severity for f in findings)
    cats = Counter(f.category for f in findings)
    addrs = address_summary(lines)
    regions = function_regions(lines)
    out = [
        "# XC8 ASM Revelator v3.6 Triage Report", "",
        f"**Listing input:** `{path}`",
        f"**Physical listing lines:** {len(lines)}",
        f"**Executable instruction lines:** {len(execs)}",
        f"**Directive lines:** {len(directives)}",
        f"**All parsed labels/symbols:** {len(labels_all)}",
        f"**True code-label candidates:** {len(code_labs)}",
        f"**Compiler temporaries/symbols detected:** {len(temp_occ)}",
        f"**SFR/equ definitions:** {len(sfrs)}",
        f"**Other equ symbols:** {len(other_equ)}",
        f"**Findings:** {len(findings)}", ""
    ]
    if addrs:
        out += ["## Executable Address Orientation", "", f"- Lowest recognized executable address: `0x{addrs['min_address']:X}`", f"- Highest recognized executable address: `0x{addrs['max_address']:X}`", f"- Approximate executable address span: `{addrs['address_span_words_approx']}` words", f"- Executable lines with addresses: `{addrs['executable_lines_with_addresses']}`", "", "This is listing-derived orientation, not a complete linker memory-usage proof.", ""]
    out += ["## First Recognized Executable Lines", "", "```asm"]
    for ln in execs[:50]:
        out.append(f"{ln.number:>5} addr={ln.address_text or '-':>6} cyc={ROUGH_CYCLES.get(ln.mnemonic, '?'):<3} :: {ln.cleaned}")
    if len(execs) > 50:
        out.append(f"... {len(execs) - 50} additional executable lines omitted ...")
    out += ["```", ""]

    out += ["## Symbol Classification", "", "### Code Labels / Executable Regions", ""]
    if regions:
        out += ["| Label | Line | Start | End | Executable instructions | Psect |", "|---|---:|---:|---:|---:|---|"]
        for r in regions[:120]:
            start = f"0x{r['start_address']:X}" if r["start_address"] is not None else "-"
            end = f"0x{r['end_address']:X}" if r["end_address"] is not None else "-"
            out.append(f"| `{r['label']}` | {r['line']} | {start} | {end} | {r['instruction_count']} | `{r['psect'] or '-'}` |")
    else:
        out.append("No executable label regions were recognized.")
    out.append("")

    out += ["### Compiler Temporaries / Generated Symbols", ""]
    if temp_occ:
        out += ["| Symbol | First line | First context |", "|---|---:|---|"]
        for sym, ln in list(temp_occ.items())[:100]:
            out.append(f"| `{sym}` | {ln.number} | `{ln.cleaned.replace('|','\\|')}` |")
    else:
        out.append("No compiler temporary symbols were detected.")
    out.append("")

    out += ["### SFR / EQU Definitions", ""]
    out.append(f"{len(sfrs)} SFR/equ definitions detected. These are intentionally not counted as executable code labels.")
    if sfrs:
        out += ["", "| Name | Value | Line |", "|---|---:|---:|"]
        for ln in sfrs[:100]:
            out.append(f"| `{ln.label}` | `{first_operand(ln.operands)}` | {ln.number} |")
        if len(sfrs) > 100:
            out.append(f"| ... | ... | {len(sfrs)-100} more omitted |")
    out.append("")

    out += ["## Developer-Facing Grouped Insights", ""]
    if grouped_insights:
        out += ["These collapse repeated low-level assembly findings into source-level GCBASIC patterns.", ""]
        out += ["| Category | Count | Actionability | Interpretation | Fix strategy | Representative lines |", "|---|---:|---|---|---|---|"]
        for gi in grouped_insights:
            reps = ", ".join(str(x) for x in gi.representative_lines)
            out.append(f"| `{gi.category}` | {gi.count} | **{gi.actionability}** | {gi.title} | {gi.fix_strategy} | {reps} |")
        out.append("")
    else:
        out += ["No grouped insights were produced.", ""]

    out += ["## Severity Summary", ""] + [f"- **{s}:** {sev.get(s, 0)}" for s in ["STRONG", "WARN", "INFO"]]
    out += ["", "## Category Summary", ""]
    out += [f"- **{cat}:** {n}" for cat, n in cats.most_common()] if cats else ["- No findings."]
    out += ["", "## Instruction Mix", "", "| Mnemonic | Count | Rough cycle note |", "|---|---:|---|"]
    for k, v in mix.most_common():
        out.append(f"| `{k}` | {v} | `{ROUGH_CYCLES.get(k, '?')}` |")
    out.append("")
    out.extend(render_map_summary(map_info))
    out += ["## Programmer Findings", ""]
    if not findings:
        out += ["No findings were produced at the selected severity level.", ""]
    elif len(findings) > DEFAULT_MARKDOWN_FINDING_LIMIT:
        out += [
            f"Showing the first {DEFAULT_MARKDOWN_FINDING_LIMIT} line-level findings out of {len(findings)}.",
            "The JSON report preserves the complete finding set for audit/dashboard use.",
            "For machine-level auditing, rerun with `--profile raw` or `--show-structural`.",
            "",
        ]
    for f in findings[:DEFAULT_MARKDOWN_FINDING_LIMIT]:
        addr = f" addr={f.address_text}" if f.address_text else ""
        out += [f"### Line {f.line}{addr}: {f.category} [{f.severity}]", "", "```asm", f.cleaned or f.raw, "```"]
        if f.source_context:
            out += [f"**Source context:** `{f.source_context}`", ""]
        out += [f"**Meaning:** {f.message}", "", f"**Why it matters:** {f.why}", ""]
        if f.compiler_reason:
            out += [f"**Compiler/GCBASIC reason:** {f.compiler_reason}", ""]
        if f.programmer_intent:
            out += [f"**Likely programmer intent:** {f.programmer_intent}", ""]
        if f.actionability:
            out += [f"**Actionability:** `{f.actionability}`", ""]
        if f.fix_strategy:
            out += [f"**Fix strategy:** {f.fix_strategy}", ""]
        if f.map_note:
            out += [f"**Map cross-reference:** {f.map_note}", ""]
        out += [f"**Suggested action:** {f.suggestion}", ""]
        if f.context:
            out += ["Local context:", "```asm"] + f.context + ["```", ""]
    out += ["## Operator Notes", "", "- The listing file reveals instruction-level behavior.", "- The map file reveals linker-level placement and memory distribution.", "- SFR/equ definitions are now separated from true code labels.", "- Compiler temporaries are separately identified instead of being treated as ordinary labels.", "- A suspicious instruction is not automatically wrong.", "- Optimize source first. Hand-edit assembly only when purpose and timing are fully understood.", ""]
    return "\n".join(out)


def write_annotated_listing(lines: List[AsmLine], findings: List[Finding], outpath: Path) -> None:
    by_line: Dict[int, List[Finding]] = defaultdict(list)
    for f in findings:
        by_line[f.line].append(f)
    out = []
    for ln in lines:
        for f in by_line.get(ln.number, []):
            out.append("; -----------------------------------------------------------------------------")
            out.append(f"; REVELATOR {f.severity} {f.category}: {f.message}")
            out.append(f"; WHY: {f.why}")
            if f.map_note:
                out.append(f"; MAP: {f.map_note}")
            out.append(f"; DO: {f.suggestion}")
            out.append("; -----------------------------------------------------------------------------")
        out.append(ln.raw)
    outpath.write_text("\n".join(out) + "\n", encoding="utf-8")


def write_json_report(path: Path, lines: List[AsmLine], findings: List[Finding], map_info: MapInfo) -> None:
    payload = {
        "summary": {
            "physical_listing_lines": len(lines),
            "executable_instruction_lines": sum(1 for ln in lines if ln.is_executable),
            "directive_lines": sum(1 for ln in lines if ln.mnemonic and not ln.is_executable),
            "all_parsed_labels_symbols": sum(1 for ln in lines if ln.label),
            "true_code_labels": len(true_code_labels(lines)),
            "compiler_temporaries": len(compiler_temporary_occurrences(lines)),
            "sfr_equ_definitions": len(sfr_equ_definitions(lines)),
            "other_equ_definitions": len(other_equ_definitions(lines)),
            "findings": len(findings),
            "instruction_mix": dict(instruction_mix(lines)),
            "address_summary": address_summary(lines),
        },
        "symbol_classification": {
            "code_labels": [ln.label for ln in true_code_labels(lines)[:500]],
            "compiler_temporaries": list(compiler_temporary_occurrences(lines).keys())[:500],
            "sfr_equ_definitions": [{"name": ln.label, "value": first_operand(ln.operands), "line": ln.number} for ln in sfr_equ_definitions(lines)[:1000]],
        },
        "map": {
            "path": map_info.path,
            "raw_line_count": map_info.raw_line_count,
            "section_hits": map_info.section_hits,
            "psects": {k: dataclasses.asdict(v) for k, v in map_info.psects.items()},
            "symbol_count": len(map_info.symbols),
            "symbols": {k: dataclasses.asdict(v) for k, v in list(map_info.symbols.items())[:500]},
            "warnings": map_info.warnings,
        },
        "function_regions": function_regions(lines),
        "grouped_insights": [gi.to_dict() for gi in build_grouped_insights(findings)],
        "findings": [f.to_dict() for f in findings],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")



# =============================================================================
# Triage mode: ranked memory-reduction suspects
# =============================================================================

@dataclasses.dataclass
class TriageItem:
    rank: int
    category: str
    score: int
    title: str
    evidence: str
    recommendation: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def safe_int_hex(s: str) -> Optional[int]:
    try:
        return int(s, 16)
    except Exception:
        return None


def estimate_program_usage_from_map(map_info: MapInfo) -> Dict[str, Any]:
    """
    Estimate PIC program-memory usage from the XC8/PIC-AS map.

    The robust path is to reread the map file and look for the object-code
    placement table plus the UNUSED ADDRESS RANGES / CODE entry. This avoids
    undercounting when the generic map parser only captured one psect row.
    """
    result: Dict[str, Any] = {
        "used_words": None,
        "free_words": None,
        "total_words": None,
        "percent_used": None,
        "evidence": [],
    }

    if not map_info.path:
        return result

    try:
        raw_lines = Path(map_info.path).read_text(errors="replace").splitlines()
    except Exception:
        raw_lines = []

    used = 0
    seen = set()

    # Placement table rows, for example:
    #   PROGMEM1                            800      800      78F        0       0
    #   PROGMEM0                              0        0      7FF        0       0
    for line in raw_lines:
        m = re.search(r"^\s*(PROGMEM[01])\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\b", line)
        if m:
            key = (m.group(1), m.group(2), m.group(3), m.group(4))
            length = safe_int_hex(m.group(4))
            if length is not None and key not in seen:
                used += length
                seen.add(key)
                result["evidence"].append(line.strip())

    free = 0
    in_unused = False
    in_code = False

    for line in raw_lines:
        if "UNUSED ADDRESS RANGES" in line:
            in_unused = True
            continue

        if not in_unused:
            continue

        # Stop once we have clearly moved beyond CODE to COMMON or another region.
        region_match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s+", line)
        if region_match:
            region = region_match.group(1)
            in_code = (region == "CODE")
        elif not line.strip():
            continue

        if in_code:
            m = re.search(r"([0-9A-Fa-f]{4,6})-([0-9A-Fa-f]{4,6})\s+([0-9A-Fa-f]+)", line)
            if m:
                count = safe_int_hex(m.group(3))
                if count is not None:
                    free += count
                    result["evidence"].append(line.strip())

    if used:
        result["used_words"] = used
    if free:
        result["free_words"] = free

    # If both are present, infer total from placement + unused CODE holes.
    if used and free:
        result["total_words"] = used + free
        result["percent_used"] = 100.0 * used / (used + free)

    return result


def find_label_index(lines: List[AsmLine], label: str) -> Optional[int]:
    for i, ln in enumerate(lines):
        if ln.label == label:
            return i
    return None


def estimate_region_to_next_major_label(lines: List[AsmLine], start_label: str) -> Dict[str, Any]:
    start = find_label_index(lines, start_label)
    if start is None:
        return {"found": False}

    stop_labels = {"ENDIF4", "CLI_PRINTBANNER", "CLI_PRINTHELP", "CLI_PRINTIDENTITY", "CLI_PRINTSTATUS"}
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].label in stop_labels and lines[j].label != start_label:
            end = j
            break

    region = lines[start:end]
    execs = [ln for ln in region if ln.is_executable]
    calls = [ln for ln in execs if ln.mnemonic in {"call", "fcall"}]
    gotos = [ln for ln in execs if ln.mnemonic in {"goto", "bra"}]
    compares = [ln for ln in execs if ln.mnemonic == "subwf"]
    skips = [ln for ln in execs if ln.mnemonic in SKIP_MNEMONICS]
    addrs = [ln.address for ln in execs if ln.address is not None]

    return {
        "found": True,
        "start_line": lines[start].number,
        "end_line": lines[end - 1].number if end > start else lines[start].number,
        "start_address": min(addrs) if addrs else None,
        "end_address": max(addrs) if addrs else None,
        "instruction_count": len(execs),
        "call_count": len(calls),
        "goto_count": len(gotos),
        "compare_count": len(compares),
        "skip_count": len(skips),
        "span_words": (max(addrs) - min(addrs) + 1) if addrs else None,
    }


def collect_stringtable_stats(lines: List[AsmLine]) -> Dict[str, Any]:
    refs = Counter()
    definitions = set()
    for ln in lines:
        for name in re.findall(r"\bSTRINGTABLE\d+\b", ln.cleaned):
            refs[name] += 1
            if ln.label == name or ln.cleaned.strip().startswith(name):
                definitions.add(name)
    data_like = [ln for ln in lines if "STRINGTABLE" in ln.cleaned or "STRINGTABLE" in ln.raw]
    return {
        "unique_tables": len(refs),
        "references": sum(refs.values()),
        "definition_like": len(definitions),
        "top_refs": refs.most_common(12),
        "data_like_lines": len(data_like),
    }


def collect_call_stats(lines: List[AsmLine]) -> Dict[str, Any]:
    calls = Counter()
    for ln in lines:
        if ln.mnemonic in {"call", "fcall"}:
            tgt = target_symbol(ln.operands)
            if tgt:
                calls[tgt] += 1

    print_calls = {k: v for k, v in calls.items() if "HSERPRINT" in k or "PRINT" in k}
    feature_calls = {
        "CLI": sum(v for k, v in calls.items() if k.startswith("CLI_") or k.startswith("FN_CLI")),
        "ADC": sum(v for k, v in calls.items() if "ADC" in k),
        "LED": sum(v for k, v in calls.items() if "LED" in k),
        "7SEG": sum(v for k, v in calls.items() if "7SEG" in k),
        "NCO": sum(v for k, v in calls.items() if "NCO" in k),
        "USART/HSER": sum(v for k, v in calls.items() if "HSER" in k or "USART" in k),
        "DELAY": sum(v for k, v in calls.items() if "DELAY" in k),
    }
    return {
        "total_calls": sum(calls.values()),
        "unique_targets": len(calls),
        "top_calls": calls.most_common(20),
        "print_calls": sorted(print_calls.items(), key=lambda kv: kv[1], reverse=True),
        "feature_calls": feature_calls,
    }


def collect_branch_chain_stats(lines: List[AsmLine]) -> Dict[str, Any]:
    pattern_count = 0
    literals = []
    for i in range(len(lines) - 3):
        a, b, c, d = lines[i:i+4]
        if (
            a.mnemonic == "movlw"
            and b.mnemonic == "subwf"
            and c.mnemonic == "btfss"
            and d.mnemonic in {"goto", "bra"}
        ):
            pattern_count += 1
            literals.append(a.operands.strip())
    return {
        "command_compare_pattern_count": pattern_count,
        "literal_samples": literals[:40],
    }


def collect_delay_stats(lines: List[AsmLine]) -> Dict[str, Any]:
    delay_calls = [ln for ln in lines if ln.mnemonic in {"call", "fcall"} and "DELAY" in target_symbol(ln.operands)]
    delay_labels = [ln for ln in lines if ln.label and "DELAY" in ln.label.upper()]
    return {
        "delay_calls": len(delay_calls),
        "delay_targets": Counter(target_symbol(ln.operands) for ln in delay_calls).most_common(),
        "delay_label_count": len(delay_labels),
        "delay_labels": [ln.label for ln in delay_labels[:20]],
    }


def build_triage_items(lines: List[AsmLine], map_info: MapInfo) -> Tuple[List[TriageItem], Dict[str, Any]]:
    program_usage = estimate_program_usage_from_map(map_info)
    dispatcher = estimate_region_to_next_major_label(lines, "CLI_DISPATCHCOMMAND")
    strings = collect_stringtable_stats(lines)
    calls = collect_call_stats(lines)
    branches = collect_branch_chain_stats(lines)
    delays = collect_delay_stats(lines)

    items: List[TriageItem] = []

    def add(category: str, score: int, title: str, evidence: str, recommendation: str) -> None:
        items.append(TriageItem(
            rank=0,
            category=category,
            score=score,
            title=title,
            evidence=evidence,
            recommendation=recommendation,
        ))

    if program_usage.get("percent_used") is not None:
        pct = program_usage["percent_used"]
        free = program_usage.get("free_words")
        used = program_usage.get("used_words")
        add(
            "FLASH_PRESSURE",
            int(pct * 10),
            f"Program memory is critically full: about {pct:.1f}% used.",
            f"Estimated used={used} words, free={free} words from linker map.",
            "Treat this as a code-footprint emergency. Use feature profiles and remove nonessential monitor features from the default build.",
        )

    if dispatcher.get("found"):
        score = int(dispatcher.get("span_words") or dispatcher.get("instruction_count") or 0)
        add(
            "COMMAND_DISPATCHER",
            score,
            "CLI_DISPATCHCOMMAND is a major code-size structure.",
            (
                f"Approx span={dispatcher.get('span_words')} words, "
                f"instructions={dispatcher.get('instruction_count')}, "
                f"compares={dispatcher.get('compare_count')}, "
                f"skips={dispatcher.get('skip_count')}, "
                f"gotos={dispatcher.get('goto_count')}, calls={dispatcher.get('call_count')}."
            ),
            "Normalize input case once, reduce duplicate upper/lower command tests, and consider a compact command table or smaller command vocabulary.",
        )

    if branches["command_compare_pattern_count"]:
        add(
            "REPEATED_COMPARE_CHAIN",
            branches["command_compare_pattern_count"] * 12,
            "Dispatcher uses many repeated compare/skip/goto command tests.",
            f"Detected {branches['command_compare_pattern_count']} movlw/subwf/btfss/goto compare patterns.",
            "This is readable but expensive. First remove duplicate lower/upper tests by case-normalizing input; then consider a table-driven or grouped dispatch.",
        )

    if strings["unique_tables"]:
        add(
            "STRING_TABLE_BURDEN",
            strings["unique_tables"] * 20 + strings["references"],
            "String tables and serial text are a large footprint suspect.",
            f"Detected {strings['unique_tables']} unique STRINGTABLE symbols and {strings['references']} references.",
            "Shorten text, remove long help from the PIC, use terse tokens, or compile help/banner text only in FULL/DEBUG builds.",
        )

    print_total = sum(v for _, v in calls["print_calls"])
    if print_total:
        add(
            "SERIAL_PRINT_BURDEN",
            print_total * 10,
            "Serial print scaffolding is heavily used.",
            f"Detected {print_total} print-like calls; top print targets: {calls['print_calls'][:8]}.",
            "Replace verbose repeated print sequences with shorter shared helpers and compact status tokens.",
        )

    feature_calls = calls["feature_calls"]
    for feature, count in sorted(feature_calls.items(), key=lambda kv: kv[1], reverse=True):
        if count >= 5 and feature != "CLI":
            add(
                "FEATURE_FAMILY",
                count * 8,
                f"{feature} feature family contributes significant call traffic.",
                f"Detected {count} calls involving {feature}.",
                f"Create a build flag for {feature}; keep it in FULL monitor builds but remove it from CORE memory-tight builds.",
            )

    if delays["delay_calls"]:
        add(
            "DELAY_USAGE",
            delays["delay_calls"] * 5,
            "Delay calls are present but probably not the primary memory problem.",
            f"Detected {delays['delay_calls']} delay calls: {delays['delay_targets']}.",
            "Do not start here unless timing code is very large. The dispatcher, strings, and print text are likely higher-value targets.",
        )

    active_features = [k for k, v in feature_calls.items() if v > 0]
    if len(active_features) >= 4:
        add(
            "BUILD_PROFILES",
            999,
            "This monitor should be split into build profiles.",
            f"Active feature families detected: {', '.join(active_features)}.",
            "Define CORE, LED, 7SEG, NCO, ADC, and FULL profiles. Make FULL the demonstration build, not the default memory-tight build.",
        )

    items.sort(key=lambda x: x.score, reverse=True)
    for idx, item in enumerate(items, 1):
        item.rank = idx

    details = {
        "program_usage": program_usage,
        "dispatcher": dispatcher,
        "strings": strings,
        "calls": calls,
        "branches": branches,
        "delays": delays,
    }
    return items, details


def render_triage_markdown(lines: List[AsmLine], map_info: MapInfo) -> str:
    items, details = build_triage_items(lines, map_info)
    out: List[str] = []
    out.append("# XC8 ASM Revelator Triage Report")
    out.append("")
    out.append("This report condenses noisy line-by-line findings into ranked memory-reduction suspects.")
    out.append("")
    out.append("## Ranked suspects")
    out.append("")
    if not items:
        out.append("No triage items were produced.")
        out.append("")
    else:
        out.append("| Rank | Category | Score | Suspect | Evidence | Recommendation |")
        out.append("|---:|---|---:|---|---|---|")
        for item in items:
            out.append(
                f"| {item.rank} | `{item.category}` | {item.score} | "
                f"{item.title} | {item.evidence} | {item.recommendation} |"
            )
        out.append("")

    out.append("## Details")
    out.append("")
    out.append("```json")
    out.append(json.dumps(details, indent=2, default=str))
    out.append("```")
    out.append("")
    return "\n".join(out)


def render_triage_console(lines: List[AsmLine], map_info: MapInfo, limit: int = 12) -> str:
    items, details = build_triage_items(lines, map_info)
    out: List[str] = []
    out.append("Triage mode: ranked memory-reduction suspects")
    out.append("=" * 60)

    pgm = details.get("program_usage", {})
    if pgm.get("percent_used") is not None:
        out.append(
            f"Program memory estimate: {pgm['used_words']} used / "
            f"{pgm['total_words']} total words ({pgm['percent_used']:.1f}% used), "
            f"{pgm['free_words']} free words."
        )
    else:
        out.append("Program memory estimate: not available from parsed map.")

    disp = details.get("dispatcher", {})
    if disp.get("found"):
        out.append(
            f"CLI_DISPATCHCOMMAND: span={disp.get('span_words')} words, "
            f"instructions={disp.get('instruction_count')}, compares={disp.get('compare_count')}, "
            f"gotos={disp.get('goto_count')}, calls={disp.get('call_count')}."
        )

    strings = details.get("strings", {})
    out.append(
        f"String tables: {strings.get('unique_tables', 0)} unique, "
        f"{strings.get('references', 0)} references."
    )

    calls = details.get("calls", {})
    out.append(
        f"Calls: {calls.get('total_calls', 0)} total, "
        f"{calls.get('unique_targets', 0)} unique targets."
    )
    out.append("")

    if not items:
        out.append("No triage items generated.")
        return "\n".join(out)

    for item in items[:limit]:
        out.append(f"{item.rank}. [{item.category}] score={item.score}")
        out.append(f"   {item.title}")
        out.append(f"   Evidence: {item.evidence}")
        out.append(f"   Do: {item.recommendation}")
        out.append("")

    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="XC8 ASM Revelator v3.6: GCBASIC-aware, triage-enhanced XC8/PIC listing and linker-map review tool.")
    parser.add_argument("input", type=Path, help="Input .lst, .asm, or .s file")
    parser.add_argument("--map", type=Path, default=None, help="Optional XC8 linker .map file")
    parser.add_argument("--report", type=Path, default=None, help="Markdown report output path")
    parser.add_argument("--json", type=Path, default=None, help="JSON report output path")
    parser.add_argument("--annotate", action="store_true", help="Write annotated listing")
    parser.add_argument("--annotated-output", type=Path, default=None, help="Annotated listing output path")
    parser.add_argument("--min-severity", choices=["INFO", "WARN", "STRONG"], default="INFO")
    parser.add_argument("--triage", action="store_true", help="Print ranked memory-reduction suspects to console")
    parser.add_argument("--triage-report", type=Path, default=None, help="Write a focused triage Markdown report")
    parser.add_argument("--triage-limit", type=int, default=12, help="Number of triage items to print to console")
    parser.add_argument("--profile", choices=["raw", "default", "gcbasic"], default="gcbasic", help="Interpretation/suppression profile")
    parser.add_argument("--show-structural", action="store_true", help="Show structural scaffolding findings normally suppressed by profile")
    parser.add_argument("--raw-findings", action="store_true", help="Use unfiltered raw findings in the full report")
    args = parser.parse_args(argv)

    if not args.input.exists():
        raise SystemExit(f"Input listing/assembly file not found: {args.input}")
    rank = {"INFO": 0, "WARN": 1, "STRONG": 2}
    lines = parse_listing_file(args.input)
    map_info = parse_map_file(args.map)

    # Low-level analyzer output remains available as raw machine evidence.
    # v3.6 then adds GCBASIC-specific interpretation, optional suppression,
    # and high-level grouped insights.
    raw_findings = Analyzer(lines, map_info).analyze()
    raw_findings.extend(detect_gcbasic_linear_compare_blocks(lines))
    raw_findings = [interpret_finding_for_gcbasic(f) for f in raw_findings]

    if args.raw_findings:
        findings = raw_findings
    else:
        findings = suppress_findings_for_profile(
            raw_findings,
            args.profile,
            show_structural=args.show_structural,
        )

    findings = [f for f in findings if rank[f.severity] >= rank[args.min_severity]]
    grouped_insights = build_grouped_insights(findings)

    execs = [ln for ln in lines if ln.is_executable]
    directives = [ln for ln in lines if ln.mnemonic and not ln.is_executable]
    labels = [ln for ln in lines if ln.label]
    true_labels = true_code_labels(lines)
    temps = compiler_temporary_occurrences(lines)
    sfrs = sfr_equ_definitions(lines)
    sev = Counter(f.severity for f in findings)

    print(f"Input physical lines: {len(lines)}")
    print(f"Executable instruction lines: {len(execs)}")
    print(f"Directive lines: {len(directives)}")
    print(f"All parsed labels/symbols: {len(labels)}")
    print(f"True code-label candidates: {len(true_labels)}")
    print(f"Compiler temporaries/symbols: {len(temps)}")
    print(f"SFR/equ definitions: {len(sfrs)}")
    if args.map:
        print(f"Map file lines: {map_info.raw_line_count}")
        print(f"Map psect candidates: {len(map_info.psects)}")
        print(f"Map symbol candidates: {len(map_info.symbols)}")
    else:
        print("Map file: not supplied")
    print(f"Findings shown: {len(findings)}")
    try:
        print(f"Raw findings before profile filtering: {len(raw_findings)}")
        print(f"Profile: {args.profile}  show_structural={args.show_structural}  raw_findings={args.raw_findings}")
        print(f"Grouped insights: {len(grouped_insights)}")
    except NameError:
        pass
    for s in ["STRONG", "WARN", "INFO"]:
        print(f"  {s}: {sev.get(s, 0)}")
    try:
        if grouped_insights:
            print("Top grouped insights:")
            for gi in grouped_insights[:6]:
                print(f"  {gi.category}: {gi.count} occurrence(s), actionability={gi.actionability}")
    except NameError:
        pass
    print("First recognized executable lines:")
    for ln in execs[:20]:
        print(f"  {ln.number} addr={ln.address_text or '-'} :: {ln.cleaned}")

    if args.triage:
        print()
        print(render_triage_console(lines, map_info, limit=args.triage_limit))

    if args.triage_report:
        args.triage_report.write_text(render_triage_markdown(lines, map_info), encoding="utf-8")
        print(f"Triage report written: {args.triage_report}")

    report = args.report or args.input.with_suffix(args.input.suffix + ".revelator_v3_6.md")
    report.write_text(render_markdown_report(args.input, lines, findings, map_info), encoding="utf-8")
    print(f"Markdown report written: {report}")
    if args.json:
        write_json_report(args.json, lines, findings, map_info)
        print(f"JSON report written: {args.json}")
    if args.annotate or args.annotated_output:
        annotated = args.annotated_output or args.input.with_suffix(args.input.suffix + ".revelator_v3_4.annotated.lst")
        write_annotated_listing(lines, findings, annotated)
        print(f"Annotated listing written: {annotated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
