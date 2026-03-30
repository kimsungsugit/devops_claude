# /app/workflow/pipeline.py
# -*- coding: utf-8 -*-
# Integrated DevOps Pipeline
# v31.0: Step 踰덊샇 ?뺣━, Fuzz/QEMU strict ?듭뀡, AI 濡쒓렇 而⑦뀓?ㅽ듃/triage 諛섏쁺
import json
import os
import glob
import shutil
import subprocess
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any, Tuple
from xml.etree import ElementTree as ET

import config
import analysis_tools as tools
from utils.log import get_logger
from workflow.test_helpers import (
    strip_c_comments as _strip_c_comments_shared,
    param_placeholder as _param_placeholder_shared,
    parse_param_name as _parse_param_name_shared,
    alt_buffer as _alt_buffer_shared,
    build_call_variants as _build_call_variants_shared,
    is_simple_signature as _is_simple_signature_shared,
)

_logger = get_logger(__name__)
# ---------------------------------------------------------------------------
# Fuzz harness generator (minimal, compile-first)
# ---------------------------------------------------------------------------
def _write_fuzz_harness(dst: Path, target_c: Path) -> None:
    """LLVMFuzzerTestOneInput瑜??ы븿??fuzz harness ?앹꽦.
    ?寃??뚯뒪?먯꽌 ?좎뼵???⑥닔瑜?fuzzer ?낅젰?쇰줈 ?몄텧?쒕떎.
    """
    header_name = target_c.stem + ".h"
    stem = target_c.stem.lower()

    func_body = "    (void)Data; (void)Size;"
    if "e2e" in stem:
        func_body = """\
    if (Size < 1) return 0;
    E2E_Calculate_CRC8(Data, (uint8_t)(Size > 255 ? 255 : Size));"""
    elif "lin_protocol" in stem:
        func_body = """\
    if (Size < 5) return 0;
    generate_lin_ident(Data[0]);
    calculate_classic_lin_checksum(Data + 1, (uint8_t)(Size - 1 > 8 ? 8 : Size - 1));
    calculate_enhanced_lin_checksum(Data[0], Data + 1, (uint8_t)(Size - 1 > 8 ? 8 : Size - 1));"""
    elif "gateway" in stem:
        func_body = """\
    if (Size < 9) return 0;
    uint8_t buf[8];
    gateway_update_from_sbc_v1_1(Data[0], Data + 1);
    gateway_get_response_for_sbc_v1_1(0x02, buf);
    gateway_update_from_pdsm_v1_5(Data[0], Data + 1);
    gateway_get_publish_for_pdsm_v1_5(0x00, buf);"""
    elif "shared_data" in stem:
        func_body = """\
    if (Size < 8) return 0;
    shared_data_init();
    diag_queue_init();
    diag_enqueue(Data);
    uint8_t out[8];
    diag_dequeue(out);"""
    elif "lin_master" in stem or "lin_slave" in stem:
        func_body = "    (void)Data; (void)Size;"

    code = f"""// Auto-generated fuzz harness for {target_c.name}
#ifdef HOST_BUILD
#define UNIT_TEST 1
#endif

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "{header_name}"

int LLVMFuzzerTestOneInput(const uint8_t *Data, size_t Size) {{
{func_body}
    return 0;
}}
"""
    dst.write_text(code, encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "", encoding="utf-8")
    except Exception:
        pass


def _write_json(path: Path, obj: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _cmake_quote(s: str) -> str:
    """CMake 臾몄옄??由ы꽣?대줈 ?덉쟾?섍쾶 媛먯떥湲?(寃쎈줈??."""
    s = (s or "").replace("\\", "/")
    return f'"{s}"'


def _normalize_define(d: str) -> Optional[str]:
    """CLI/?섍꼍?먯꽌 ?ㅼ뼱??define??CMake target_compile_definitions ?낅젰 ?뺥깭濡??뺣━."""
    if not d:
        return None
    s = d.strip()
    if not s:
        return None
    if s.startswith("-D"):
        s = s[2:].strip()
    # 怨듬갚/?곗샂???ы븿 媛믪? 源⑥쭏 ???덉뼱 蹂댁닔?곸쑝濡??쒖쇅
    if any(ch.isspace() for ch in s):
        return None
    if any(ch in s for ch in ('"', "'")):
        return None
    return s


def _normalize_include_dir(project_root: Path, inc: str) -> Optional[str]:
    """include dir??CMake?먯꽌 ?????덇쾶 ?뺢퇋??

    - ?꾨줈?앺듃 ?대? 寃쎈줈硫?${PROJECT_SOURCE_DIR}/rel 濡?蹂??    - ?덈? 寃쎈줈/?몃? 寃쎈줈硫?洹몃?濡??ъ슜
    """
    if not inc:
        return None
    s = inc.strip().strip('"').strip("'")
    if not s:
        return None
    s = s.replace("\\", "/")

    try:
        p = Path(s)
    except Exception:
        return None

    # ?곷?寃쎈줈??project_root 湲곗??쇰줈 泥섎━
    if not p.is_absolute():
        rel = s.lstrip("./")
        return f"${{PROJECT_SOURCE_DIR}}/{rel}"

    # Absolute include path under project_root -> convert to PROJECT_SOURCE_DIR-relative form.
    try:
        relp = p.resolve().relative_to(project_root.resolve())
        # NOTE: avoid backslashes inside f-string expressions (SyntaxError on some Python versions)
        return f"${{PROJECT_SOURCE_DIR}}/{relp.as_posix()}"
    except Exception:
        return s


def _has_test_main_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return bool(re.search(r"\bmain\s*\(", text))


def _strip_c_comments(text: str) -> str:
    # Remove block and line comments to reduce false function matches.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*?$", "", text, flags=re.M)
    return text


def _param_placeholder(param: str) -> Tuple[Optional[str], Optional[str]]:
    p = (param or "").strip()
    if not p or p == "void":
        return None, None
    if "..." in p:
        return "0", None
    # drop default values
    p = p.split("=", 1)[0].strip()
    if "*" in p or "[" in p:
        if re.search(r"\b(uint8_t|char)\b", p):
            return "buf_u8a", "u8"
        if re.search(r"\b(uint16_t)\b", p):
            return "buf_u16a", "u16"
        if re.search(r"\b(uint32_t)\b", p):
            return "buf_u32a", "u32"
        if re.search(r"\b(uint64_t)\b", p):
            return "buf_u64a", "u64"
        if re.search(r"\b(int8_t|int16_t|int32_t|int|long)\b", p):
            return "buf_i32a", "i32"
        return "buf_u8a", "u8"
    if re.search(r"\b(bool)\b", p):
        return "false", None
    if re.search(r"\b(float|double)\b", p):
        return "0.0", None
    # integers/enums/size_t/uint/etc.
    return "0", None


def _parse_param_name(raw: str) -> str:
    ids = re.findall(r"[A-Za-z_]\w*", raw or "")
    if not ids:
        return ""
    return ids[-1]


def _alt_buffer(expr: str) -> str:
    return expr.replace("buf_u8a", "buf_u8b").replace("buf_u16a", "buf_u16b").replace("buf_u32a", "buf_u32b").replace("buf_u64a", "buf_u64b").replace("buf_i32a", "buf_i32b")


def _build_call_variants(func_name: str, params: List[str]) -> List[List[str]]:
    variants: List[List[str]] = []
    base_args: List[str] = []
    param_names: List[str] = []
    has_ptr = False
    first_scalar_idx: Optional[int] = None
    pid_idx: Optional[int] = None
    len_idx: Optional[int] = None

    for i, raw in enumerate(params):
        name = _parse_param_name(raw)
        param_names.append(name)
        expr, buf_kind = _param_placeholder(raw)
        if expr is None:
            expr = "0"
        base_args.append(expr)
        if buf_kind:
            has_ptr = True
        if first_scalar_idx is None and buf_kind is None:
            first_scalar_idx = i
        if name and "pid" in name.lower():
            pid_idx = i
        if name and any(k in name.lower() for k in ("len", "size", "count")):
            len_idx = i

    # base call
    variants.append(list(base_args))

    # pointer alternate buffer call
    if has_ptr:
        alt = [_alt_buffer(a) for a in base_args]
        if alt != base_args:
            variants.append(alt)

    # PID-specific variants
    if pid_idx is not None:
        for v in ("0x00", "0x01", "0x02", "0xFF"):
            args = list(base_args)
            args[pid_idx] = v
            variants.append(args)

    # length variants
    if len_idx is not None:
        for v in ("1", "4", "8", "16"):
            args = list(base_args)
            args[len_idx] = v
            variants.append(args)

    # scalar sweep for first scalar
    if first_scalar_idx is not None and pid_idx is None:
        for v in ("0", "1", "2", "3", "4", "7", "8", "9", "10", "11", "12", "13", "14", "15", "255"):
            args = list(base_args)
            args[first_scalar_idx] = v
            variants.append(args)

    # de-dup and cap
    uniq: List[List[str]] = []
    seen = set()
    for v in variants:
        key = "|".join(v)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(v)
        if len(uniq) >= 12:
            break
    return uniq


def _is_simple_signature(ret: str, params: str, *, header_found: bool) -> bool:
    if not ret:
        return False
    if "typedef" in ret or "struct" in ret or "enum" in ret:
        return False
    allowed = {
        "void",
        "int",
        "unsigned",
        "signed",
        "short",
        "long",
        "char",
        "float",
        "double",
        "bool",
        "size_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "uint",
        "uintptr_t",
        "intptr_t",
        "const",
        "volatile",
        "static",
        "inline",
    }

    def _check_tokens(tokens: List[str]) -> bool:
        for t in tokens:
            if t in allowed:
                continue
            if header_found and t.endswith("_t"):
                continue
            return False
        return True

    ret_tokens = re.findall(r"[A-Za-z_]\w*", ret)
    if not _check_tokens(ret_tokens):
        return False

    if params and params != "void":
        for raw in params.split(","):
            ids = re.findall(r"[A-Za-z_]\w*", raw)
            if not ids:
                continue
            # drop parameter name (last identifier)
            type_ids = ids[:-1] if len(ids) > 1 else ids
            if not _check_tokens(type_ids):
                return False
    return True


def _extract_stub_functions(src_text: str) -> List[Dict[str, str]]:
    funcs: List[Dict[str, str]] = []
    if not src_text:
        return funcs
    text = _strip_c_comments(src_text)
    func_re = re.compile(
        r"^\s*(?P<ret>[\w\s\*\(\),]+?)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^;{}]*)\)\s*\{",
        re.M,
    )
    skip_names = {
        "main",
        "core1_entry",
        "if",
        "for",
        "while",
        "switch",
        "case",
        "do",
    }
    skip_fragments = ("loop", "isr", "irq", "handler")
    for m in func_re.finditer(text):
        ret = (m.group("ret") or "").strip()
        name = (m.group("name") or "").strip()
        params = (m.group("params") or "").strip()
        if not ret:
            continue
        if not name or name in skip_names:
            continue
        if any(f in name.lower() for f in skip_fragments):
            continue
        if "typedef" in ret:
            # avoid file-local or typedef-like patterns
            continue
        funcs.append({"ret": ret, "name": name, "params": params})
    return funcs


def _build_stub_test_body(project_root: Path, rel_src: str, src_text: str) -> str:
    libs_dir = project_root / "libs"
    lib_sources = []
    if libs_dir.exists():
        lib_sources = sorted([p for p in libs_dir.glob("*.c") if p.is_file()])

    funcs = _extract_stub_functions(src_text)
    func_names = {f.get("name") for f in funcs}
    calls: List[str] = []
    buffers: Dict[str, str] = {}
    header_found = False
    for f in funcs:
        if not _is_simple_signature(f["ret"], f["params"], header_found=header_found):
            continue
        params = [p.strip() for p in f["params"].split(",")] if f["params"] and f["params"] != "void" else []
        for raw in params:
            _, buf = _param_placeholder(raw)
            if buf:
                buffers[buf] = buf
        for args in _build_call_variants(f["name"], params):
            calls.append(f"(void){f['name']}({', '.join(args)});")
            if len(calls) >= 12:
                break
        if len(calls) >= 12:
            break

    include_block = []
    for p in lib_sources:
        rel = p.relative_to(project_root).as_posix()
        include_block.append(f"#include \"{rel}\"")
    includes = "\n".join(include_block) + ("\n" if include_block else "")
    buf_decls = []
    if "u8" in buffers:
        buf_decls.append("uint8_t buf_u8a[16] = {0};")
        buf_decls.append("uint8_t buf_u8b[16] = {0};")
    if "u16" in buffers:
        buf_decls.append("uint16_t buf_u16a[8] = {0};")
        buf_decls.append("uint16_t buf_u16b[8] = {0};")
    if "u32" in buffers:
        buf_decls.append("uint32_t buf_u32a[4] = {0};")
        buf_decls.append("uint32_t buf_u32b[4] = {0};")
    if "u64" in buffers:
        buf_decls.append("uint64_t buf_u64a[2] = {0};")
        buf_decls.append("uint64_t buf_u64b[2] = {0};")
    if "i32" in buffers:
        buf_decls.append("int32_t buf_i32a[4] = {0};")
        buf_decls.append("int32_t buf_i32b[4] = {0};")
    buf_block = "\n    ".join(buf_decls) + ("\n" if buf_decls else "")
    init_lines: List[str] = []
    if "u8" in buffers:
        init_lines.append("for (int i = 0; i < 16; i++) { buf_u8a[i] = (uint8_t)i; buf_u8b[i] = (uint8_t)(0xFF - i); }")
    if "u16" in buffers:
        init_lines.append("for (int i = 0; i < 8; i++) { buf_u16a[i] = (uint16_t)(i * 3); buf_u16b[i] = (uint16_t)(0xFF - i); }")
    if "u32" in buffers:
        init_lines.append("for (int i = 0; i < 4; i++) { buf_u32a[i] = (uint32_t)(i * 7); buf_u32b[i] = (uint32_t)(0xFFFF - i); }")
    if "i32" in buffers:
        init_lines.append("for (int i = 0; i < 4; i++) { buf_i32a[i] = (int32_t)(i - 2); buf_i32b[i] = (int32_t)(2 - i); }")
    buf_init = "\n    ".join(init_lines) + ("\n" if init_lines else "")
    special: List[str] = []
    if "handle_lin1_slave_processing" in func_names:
        special.extend(
            [
                "uart_stub_reset();",
                "init_lin1_slave();",
                "uart_stub_set_readable_after(1);",
                "lin1_gpio_isr(LIN1_UART_RX_PIN, GPIO_IRQ_EDGE_FALL);",
                "uint8_t sbcm0[7] = {0x11,0x22,0x33,0x44,0x55,0x66,0x77};",
                "uint8_t cks0 = calculate_enhanced_lin_checksum(0x00, sbcm0, 7);",
                "uint8_t frame0[10] = {0x55, 0x00, sbcm0[0], sbcm0[1], sbcm0[2], sbcm0[3], sbcm0[4], sbcm0[5], sbcm0[6], cks0};",
                "uart_stub_push_bytes(frame0, 10);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t sbcm1[7] = {0x01,0x00,0x02,0x10,0x20,0x30,0x40};",
                "uint8_t cks1 = calculate_enhanced_lin_checksum(0x01, sbcm1, 7);",
                "uint8_t frame1[10] = {0x55, 0x01, sbcm1[0], sbcm1[1], sbcm1[2], sbcm1[3], sbcm1[4], sbcm1[5], sbcm1[6], cks1};",
                "uart_stub_push_bytes(frame1, 10);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t frame2[2] = {0x55, 0x02};",
                "uart_stub_push_bytes(frame2, 2);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t diag3c[8] = {0x10,0x01,0x02,0x03,0x04,0x05,0x06,0x07};",
                "uint8_t cks3c = calculate_classic_lin_checksum(diag3c, 8);",
                "uint8_t frame3c[11] = {0x55, 0x3C, diag3c[0], diag3c[1], diag3c[2], diag3c[3], diag3c[4], diag3c[5], diag3c[6], diag3c[7], cks3c};",
                "uart_stub_push_bytes(frame3c, 11);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t diag3c_short[4] = {0x10,0x01,0x02,0x03};",
                "uint8_t frame3c_short[6] = {0x55, 0x3C, diag3c_short[0], diag3c_short[1], diag3c_short[2], diag3c_short[3]};",
                "uart_stub_push_bytes(frame3c_short, 6);",
                "handle_lin1_slave_processing();",
                "LinDiagResponseTransaction* dr = get_diag_response_transaction();",
                "diag_response_lock();",
                "for (int i = 0; i < 8; i++) { dr->response_data[i] = (uint8_t)(i + 1); dr->last_valid_response_data[i] = (uint8_t)(0xA0 + i); }",
                "dr->response_ready = true; dr->has_ever_responded = true;",
                "diag_response_unlock();",
                "uint8_t frame3d[2] = {0x55, 0x3D};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame3d, 2);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t no_sync[3] = {0x00,0x01,0x02};",
                "uart_stub_push_bytes(no_sync, 3);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t only_sync[1] = {0x55};",
                "uart_stub_push_bytes(only_sync, 1);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t sbc_bad[7] = {0xFF,0xEE,0xDD,0xCC,0xBB,0xAA,0x99};",
                "uint8_t frame_bad[10] = {0x55, 0x00, sbc_bad[0], sbc_bad[1], sbc_bad[2], sbc_bad[3], sbc_bad[4], sbc_bad[5], sbc_bad[6], (uint8_t)0x00};",
                "uart_stub_push_bytes(frame_bad, 10);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t short_data[4] = {0x55, 0x00, 0x01, 0x02};",
                "uart_stub_push_bytes(short_data, 4);",
                "handle_lin1_slave_processing();",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t diag_bad[8] = {0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28};",
                "uint8_t frame3c_bad[11] = {0x55, 0x3C, diag_bad[0], diag_bad[1], diag_bad[2], diag_bad[3], diag_bad[4], diag_bad[5], diag_bad[6], diag_bad[7], (uint8_t)0x00};",
                "uart_stub_push_bytes(frame3c_bad, 11);",
                "handle_lin1_slave_processing();",
                "LinDiagResponseTransaction* dr2 = get_diag_response_transaction();",
                "diag_response_lock();",
                "dr2->response_ready = false; dr2->has_ever_responded = false;",
                "diag_response_unlock();",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame3d, 2);",
                "handle_lin1_slave_processing();",
                "diag_response_lock();",
                "for (int i = 0; i < 8; i++) { dr2->last_valid_response_data[i] = (uint8_t)(0xB0 + i); }",
                "dr2->response_ready = false; dr2->has_ever_responded = true;",
                "diag_response_unlock();",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame3d, 2);",
                "handle_lin1_slave_processing();",
            ]
        )

    if "lin_master_run_init_sequence" in func_names:
        special.extend(
            [
                "uart_stub_reset();",
                "init_lin2_master();",
                "uint8_t resp_init[4] = {0x12,0x34,0x56,0x78};",
                "uint8_t cks_init = calculate_enhanced_lin_checksum(generate_lin_ident(0x02), resp_init, 4);",
                "uint8_t frame_init[5] = {resp_init[0], resp_init[1], resp_init[2], resp_init[3], cks_init};",
                "uart_stub_push_bytes(frame_init, 5);",
                "(void)lin_master_run_init_sequence();",
                "uart_stub_reset();",
                "uint8_t frame_init_bad[5] = {0xAA,0xBB,0xCC,0xDD,0x00};",
                "uart_stub_push_bytes(frame_init_bad, 5);",
                "(void)lin_master_run_init_sequence();",
                "uart_stub_reset();",
                "(void)lin_master_run_init_sequence();",
                "uint8_t ru_buf[3] = {0};",
                "uart_stub_reset();",
                "uart_stub_set_readable_after(1);",
                "uint8_t ru_src[3] = {0x10,0x20,0x30};",
                "uart_stub_push_bytes(ru_src, 3);",
                "(void)read_uart_bytes(LIN2_UART_ID, ru_buf, 3, 1);",
                "print_byte_array(\"  L2M TEST: \", ru_buf, 3);",
            ]
        )

    if "handle_lin2_master_schedule" in func_names:
        special.extend(
            [
                "uart_stub_reset();",
                "uint8_t resp_req[4] = {0x9A,0xBC,0xDE,0xF0};",
                "uint8_t cks_req = calculate_enhanced_lin_checksum(generate_lin_ident(0x02), resp_req, 4);",
                "uint8_t frame_req[5] = {resp_req[0], resp_req[1], resp_req[2], resp_req[3], cks_req};",
                "uart_stub_push_bytes(frame_req, 5);",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "uart_stub_reset();",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "uart_stub_reset();",
                "handle_lin2_master_schedule();",
                "handle_lin2_master_schedule();",
                "uint8_t bad_resp[5] = {0x01,0x02,0x03,0x04,0x00};",
                "uart_stub_push_bytes(bad_resp, 5);",
                "handle_lin2_master_schedule();",
            ]
        )

    if "process_diag_request_and_get_response" in func_names:
        special.extend(
            [
                "uart_stub_reset();",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_req[8] = {0x01,0x10,0x22,0x33,0x44,0x55,0x66,0x77};",
                "(void)diag_enqueue(diag_req);",
                "uint8_t resp3d[8] = {0x10,0x02,0x03,0x04,0x05,0x06,0x07,0x08};",
                "uint8_t cks3d = calculate_classic_lin_checksum(resp3d, 8);",
                "uint8_t frame3d_resp[9] = {resp3d[0],resp3d[1],resp3d[2],resp3d[3],resp3d[4],resp3d[5],resp3d[6],resp3d[7],cks3d};",
                "uart_stub_set_readable_after(5);",
                "uart_stub_push_bytes(frame3d_resp, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_cf_unexp[8] = {0x01,0x20,0x02,0x03,0x04,0x05,0x06,0x07};",
                "(void)diag_enqueue(diag_cf_unexp);",
                "uint8_t resp_unexp[8] = {0x41,0x42,0x43,0x44,0x45,0x46,0x47,0x48};",
                "uint8_t cks_unexp = calculate_classic_lin_checksum(resp_unexp, 8);",
                "uint8_t frame_unexp[9] = {resp_unexp[0],resp_unexp[1],resp_unexp[2],resp_unexp[3],resp_unexp[4],resp_unexp[5],resp_unexp[6],resp_unexp[7],cks_unexp};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame_unexp, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_sf[8] = {0x01,0x00,0x02,0x03,0x04,0x05,0x06,0x07};",
                "(void)diag_enqueue(diag_sf);",
                "uint8_t resp_sf[8] = {0x20,0x21,0x22,0x23,0x24,0x25,0x26,0x27};",
                "uint8_t cks_sf = calculate_classic_lin_checksum(resp_sf, 8);",
                "uint8_t frame_sf[9] = {resp_sf[0],resp_sf[1],resp_sf[2],resp_sf[3],resp_sf[4],resp_sf[5],resp_sf[6],resp_sf[7],cks_sf};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame_sf, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_ff[8] = {0x01,0x10,0x20,0x30,0x40,0x50,0x60,0x70};",
                "(void)diag_enqueue(diag_ff);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_ff_small[8] = {0x01,0x10,0x08,0x11,0x22,0x33,0x44,0x55};",
                "(void)diag_enqueue(diag_ff_small);",
                "(void)process_diag_request_and_get_response();",
                "uint8_t diag_cf_last[8] = {0x01,0x20,0xAA,0xBB,0xCC,0xDD,0xEE,0xFF};",
                "(void)diag_enqueue(diag_cf_last);",
                "uint8_t resp_last[8] = {0x50,0x51,0x52,0x53,0x54,0x55,0x56,0x57};",
                "uint8_t cks_last = calculate_classic_lin_checksum(resp_last, 8);",
                "uint8_t frame_last[9] = {resp_last[0],resp_last[1],resp_last[2],resp_last[3],resp_last[4],resp_last[5],resp_last[6],resp_last[7],cks_last};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame_last, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_cf[8] = {0x01,0x20,0x02,0x03,0x04,0x05,0x06,0x07};",
                "(void)diag_enqueue(diag_cf);",
                "uint8_t resp_cf[8] = {0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37};",
                "uint8_t cks_cf = calculate_classic_lin_checksum(resp_cf, 8);",
                "uint8_t frame_cf[9] = {resp_cf[0],resp_cf[1],resp_cf[2],resp_cf[3],resp_cf[4],resp_cf[5],resp_cf[6],resp_cf[7],cks_cf};",
                "uart_stub_push_bytes(frame_cf, 9);",
                "(void)process_diag_request_and_get_response();",
                "uart_stub_reset();",
                "uint8_t diag_unk[8] = {0x01,0xF0,0x11,0x22,0x33,0x44,0x55,0x66};",
                "(void)diag_enqueue(diag_unk);",
                "uint8_t resp_bad[8] = {0x40,0x41,0x42,0x43,0x44,0x45,0x46,0x47};",
                "uint8_t frame_bad_resp[9] = {resp_bad[0],resp_bad[1],resp_bad[2],resp_bad[3],resp_bad[4],resp_bad[5],resp_bad[6],resp_bad[7],(uint8_t)0x00};",
                "uart_stub_set_readable_after(1);",
                "uart_stub_push_bytes(frame_bad_resp, 9);",
                "(void)process_diag_request_and_get_response();",
            ]
        )

    if "diag_enqueue" in func_names or "diag_dequeue" in func_names:
        special.extend(
            [
                "uint8_t diag_fill[8] = {0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08};",
                "(void)diag_enqueue(diag_fill);",
                "(void)diag_enqueue(diag_fill);",
                "(void)diag_enqueue(diag_fill);",
                "(void)diag_enqueue(diag_fill);",
                "(void)diag_enqueue(diag_fill);",
                "uint8_t diag_out[8] = {0};",
                "(void)diag_dequeue(diag_out);",
                "diag_queue_init();",
                "(void)diag_dequeue(diag_out);",
            ]
        )

    if "gateway_update_from_sbc_v1_1" in func_names or "gateway_get_publish_for_pdsm_v1_5" in func_names:
        special.extend(
            [
                "uint8_t sbc0_data[7] = {0xFF,0xAA,0x55,0x10,0x34,0x01,0xE0};",
                "gateway_update_from_sbc_v1_1(0x00, sbc0_data);",
                "uint8_t sbc1_data[7] = {0x11,0x22,0x33,0x44,0x55,0x66,0x77};",
                "gateway_update_from_sbc_v1_1(0x01, sbc1_data);",
                "uint8_t pdsm_data[4] = {0x80,0xAA,0x5F,0x9C};",
                "gateway_update_from_pdsm_v1_5(0x02, pdsm_data);",
                "gateway_update_from_pdsm_v1_5(0x03, pdsm_data);",
                "uint8_t pdsm_case6[4] = {0x00,0x00,0x60,0x00};",
                "gateway_update_from_pdsm_v1_5(0x02, pdsm_case6);",
                "uint8_t pdsm_case14[4] = {0x00,0x00,0xE0,0x00};",
                "gateway_update_from_pdsm_v1_5(0x02, pdsm_case14);",
                "uint8_t resp_buf[8] = {0};",
                "gateway_get_response_for_sbc_v1_1(0x02, resp_buf);",
                "gateway_get_response_for_sbc_v1_1(0x03, resp_buf);",
                "uint8_t pub_buf[8] = {0};",
                "gateway_get_publish_for_pdsm_v1_5(0x00, pub_buf);",
                "gateway_get_publish_for_pdsm_v1_5(0x01, pub_buf);",
                "gateway_get_publish_for_pdsm_v1_5(0x05, pub_buf);",
            ]
        )

    if "rotary_switch_update" in func_names or "rotary_switch_init" in func_names:
        special.extend(
            [
                "adc_stub_reset();",
                "rotary_switch_init();",
                "uint16_t slope_vals[5] = {3108, 3401, 3639, 3798, 3873};",
                "uint16_t temp_vals[4] = {3108, 3550, 3758, 3873};",
                "for (int i = 0; i < 5; i++) {",
                "  adc_stub_set_value(1, slope_vals[i]);",
                "  adc_stub_set_value(0, temp_vals[i < 4 ? i : 3]);",
                "  for (int j = 0; j < 3; j++) rotary_switch_update();",
                "}",
                "(void)get_adc_channel_from_gpio(25);",
                "(void)get_adc_channel_from_gpio(26);",
                "(void)get_closest_position(3108);",
                "(void)get_closest_position(3940);",
                "(void)get_slope_index_from_position(0);",
                "(void)get_slope_index_from_position(3);",
                "(void)get_slope_index_from_position(6);",
                "(void)get_slope_index_from_position(8);",
                "(void)get_slope_index_from_position(11);",
                "(void)get_temp_index_from_position(0);",
                "(void)get_temp_index_from_position(4);",
                "(void)get_temp_index_from_position(7);",
                "(void)get_temp_index_from_position(11);",
                "(void)read_adc_averaged(0);",
                "(void)read_adc_averaged(1);",
            ]
        )

    call_block = "\n    ".join(special + calls) if (special or calls) else "/* no callable functions found */"
    return (
        "#include <assert.h>\n"
        "#include <stdbool.h>\n"
        "#include <stddef.h>\n"
        "#include <stdint.h>\n"
        "#include \"pico/types.h\"\n"
        "#include \"hardware/uart.h\"\n"
        "#include \"hardware/gpio.h\"\n"
        "#include \"hardware/adc.h\"\n"
        "\n"
        "#define AI_UT_INCLUDE_SOURCES_ALL 1\n"
        f"{includes}"
        "int main(void) {\n"
        f"    {buf_block}"
        f"    {buf_init}"
        "    shared_data_init();\n"
        f"    {call_block}\n"
        "    return 0;\n"
        "}\n"
    )


def _generate_auto_generated_cmakelists(
    project_root: Path,
    reports: Path,
    tests_summary: Dict[str, Any],
    include_paths: List[str],
    defines: List[str],
    stubs_root: str,
) -> Dict[str, Any]:
    """AI媛 ?앹꽦??test_*.c/cpp瑜?CTest?먯꽌 ?ㅽ뻾 媛?ν븯?꾨줉
    reports/auto_generated/CMakeLists.txt瑜??먮룞 ?앹꽦.

    - _invalid/_archive ?쒖쇅
    - syntax_ok(=result.ok=True)留??ы븿
    - ?앹꽦??留ㅽ븨??manifest.json?쇰줈 ???    """
    out: Dict[str, Any] = {"generated": False, "count": 0, "path": None, "manifest": None, "prefix": None}

    tests_dir = reports / "auto_generated"
    tools.ensure_dir(tests_dir)

    results = (tests_summary or {}).get("results", [])
    if not isinstance(results, list):
        results = []

    # ?좏슚 ?뚯뒪???뚯뒪 ?섏쭛
    test_files: List[Path] = []
    for r in results:
        try:
            if not r.get("ok"):
                continue
            tf = r.get("test_file")
            if not tf:
                continue
            p = Path(tf)
            # _invalid / _archive 寃쎈줈 ?쒖쇅
            if "_invalid" in p.parts or "_archive" in p.parts:
                continue
            # auto_generated ?대뜑 ?덉そ留??덉슜
            try:
                p.resolve().relative_to(tests_dir.resolve())
            except Exception:
                continue
            if p.suffix.lower() not in (".c", ".cpp", ".cc", ".cxx"):
                continue
            if p.exists() and _has_test_main_file(p):
                test_files.append(p)
        except Exception:
            continue

    # test_*.c/cpp glob??蹂묓뻾 (寃곌낵 dict ?꾨씫 ?鍮?
    for p in list(tests_dir.glob("test_*.c")) + list(tests_dir.glob("test_*.cpp")):
        if "_invalid" in p.parts or "_archive" in p.parts:
            continue
        if not _has_test_main_file(p):
            continue
        if p not in test_files:
            test_files.append(p)

    # ?뺣젹(寃곗젙??
    test_files = sorted(test_files, key=lambda x: x.name)

    # If no valid tests, remove stale CMakeLists/manifest to avoid CMake configure failure
    if not test_files:
        stale_cmake = tests_dir / "CMakeLists.txt"
        stale_manifest = tests_dir / "manifest.json"
        for sp in (stale_cmake, stale_manifest):
            try:
                if sp.exists():
                    sp.unlink()
            except Exception:
                pass
        out["generated"] = False
        out["count"] = 0
        out["path"] = None
        out["manifest"] = None
        out["reason"] = "no_valid_tests"
        return out


    cmake_path = tests_dir / "CMakeLists.txt"
    manifest_path = tests_dir / "manifest.json"

    if not test_files:
        # stale ?뚯씪 ?쒓굅
        try:
            cmake_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
        try:
            manifest_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
        out.update({"generated": False, "count": 0, "path": None, "manifest": None, "reason": "no_valid_tests"})
        return out

    # include paths ?뺣━
    incs: List[str] = []
    # 湲곕낯 include (?꾨줈?앺듃 援ъ“ ?뚰듃)
    base_incs = [
        "${PROJECT_SOURCE_DIR}",
        "${PROJECT_SOURCE_DIR}/libs",
        "${PROJECT_SOURCE_DIR}/tests",
        f"${{PROJECT_SOURCE_DIR}}/{stubs_root.strip('/')}" if stubs_root else "${PROJECT_SOURCE_DIR}/tests/stubs",
    ]
    for b in base_incs:
        if b and b not in incs:
            incs.append(b)

    for inc in include_paths or []:
        ni = _normalize_include_dir(project_root, inc)
        if ni and ni not in incs:
            incs.append(ni)

    # define ?뺣━
    defs: List[str] = []
    for d in ["UNIT_TEST", "HOST_BUILD"] + list(defines or []):
        nd = _normalize_define(d)
        if nd and nd not in defs:
            defs.append(nd)

    # target/test name 留ㅽ븨 援ъ꽦
    prefix = "ai_ut_"
    out["prefix"] = prefix
    manifest: List[Dict[str, Any]] = []
    used: Dict[str, int] = {}

    def _includes_all_sources(p: Path) -> bool:
        try:
            return "AI_UT_INCLUDE_SOURCES_ALL" in p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False

    for p in test_files:
        stem = p.stem
        # test_foo -> foo
        if stem.startswith("test_"):
            stem = stem[len("test_") :]
        # CMake target name safe
        safe = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in stem)
        if not safe:
            safe = "test"
        name = f"{prefix}{safe}"
        n = used.get(name, 0)
        if n:
            name = f"{name}_{n+1}"
        used[name] = used.get(name, 0) + 1

        manifest.append(
            {
                "source": str(p.name),
                "target": name,
                "ctest_name": name,
                "language": "C++" if p.suffix.lower() in (".cpp", ".cc", ".cxx") else "C",
            }
        )

    # CMakeLists ?앹꽦
    lines: List[str] = []
    lines.append("# Auto-generated by workflow pipeline (P2.1)")
    lines.append("# Do NOT edit manually. This file is regenerated on each run.")
    lines.append("cmake_minimum_required(VERSION 3.15)")
    lines.append("include(CTest)")
    lines.append("enable_testing()")
    lines.append("")

    lines.append("set(_AI_AUTOGEN_TEST_SOURCES")
    for m in manifest:
        lines.append(f"  ${{CMAKE_CURRENT_LIST_DIR}}/{m['source']}")
    lines.append(")")
    lines.append("")

    # include dirs
    lines.append("set(_AI_AUTOGEN_TEST_INCLUDES")
    for inc in incs:
        lines.append(f"  {_cmake_quote(inc)}")
    lines.append(")")
    lines.append("")

    # compile defs
    lines.append("set(_AI_AUTOGEN_TEST_DEFS")
    for d in defs:
        lines.append(f"  {_cmake_quote(d)}")
    lines.append(")")
    lines.append("")

    # manifest-driven explicit targets (寃곗젙??+ 以묐났 泥섎━)
    for m in manifest:
        src = f"${{CMAKE_CURRENT_LIST_DIR}}/{m['source']}"
        tgt = m["target"]
        # Guard missing sources to avoid CMake configure failure
        lines.append(f"set(_AI_SRC_{tgt} {src})")
        lines.append(f"if(EXISTS ${{_AI_SRC_{tgt}}})")
        lines.append(f"  add_executable({tgt} ${{_AI_SRC_{tgt}}})")
        lines.append(f"  target_include_directories({tgt} PRIVATE ${{_AI_AUTOGEN_TEST_INCLUDES}})")
        lines.append(f"  target_compile_definitions({tgt} PRIVATE ${{_AI_AUTOGEN_TEST_DEFS}})")
        if not _includes_all_sources(p):
            lines.append(f"  if(TARGET lin_gateway_lib)")
            lines.append(f"    target_link_libraries({tgt} PRIVATE lin_gateway_lib)")
            lines.append("  endif()")
        lines.append(f"  add_test(NAME {tgt} COMMAND {tgt})")
        lines.append("else()")
        lines.append(f"  message(WARNING \"[auto_generated] missing source: ${{_AI_SRC_{tgt}}}, skipping {tgt}\")")
        lines.append("endif()")
        lines.append("")

    content = "\n".join(lines) + "\n"
    tmp = cmake_path.with_suffix(".txt.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(cmake_path)
        out["generated"] = True
        out["count"] = len(manifest)
        out["path"] = str(cmake_path)
    except Exception as e:
        out.update({"generated": False, "count": 0, "path": None, "reason": f"write_error: {e}"})
        return out

    # manifest write
    try:
        _write_json(manifest_path, {"generated_at": datetime.now().isoformat(), "prefix": prefix, "items": manifest})
        out["manifest"] = str(manifest_path)
    except Exception:
        out["manifest"] = None

    return out


def _generate_stub_tests(
    *,
    project_root: Path,
    reports: Path,
    targets: List[Path],
    excludes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    tests_dir = reports / "auto_generated"
    tools.ensure_dir(tests_dir)
    results: List[Dict[str, Any]] = []
    exclude_list = [str(x).strip().lower() for x in (excludes or []) if str(x).strip()]

    def _is_excluded(p: Path) -> bool:
        rel = p.as_posix().lower()
        name = p.name.lower()
        for ex in exclude_list:
            ex_norm = ex.replace("\\", "/")
            if "/" in ex_norm:
                if ex_norm in rel:
                    return True
            elif ex_norm == name:
                return True
        return False

    for src in targets:
        if exclude_list and _is_excluded(src):
            try:
                rel = src.relative_to(project_root)
            except Exception:
                rel = src
            stem = Path(str(rel)).stem
            try:
                (tests_dir / f"test_{stem}.c").unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": "excluded",
                    "plan_ok": False,
                }
            )
            continue
        try:
            rel = src.relative_to(project_root)
        except Exception:
            rel = src
        stem = Path(str(rel)).stem
        test_file = tests_dir / f"test_{stem}.c"
        try:
            src_text = src.read_text(encoding="utf-8", errors="ignore")
            test_body = _build_stub_test_body(project_root, str(rel), src_text)
            test_file.write_text(test_body, encoding="utf-8")
            results.append(
                {
                    "file": str(rel),
                    "ok": True,
                    "reason": "stub_only",
                    "test_file": str(test_file),
                    "plan_ok": False,
                }
            )
        except Exception as e:
            results.append(
                {
                    "file": str(rel),
                    "ok": False,
                    "reason": f"stub_write_failed:{e}",
                    "plan_ok": False,
                }
            )
    return {"enabled": True, "mode": "stub", "results": results}


def _attach_ai_test_execution_to_summary(tests_summary: Dict[str, Any], b_res: Dict[str, Any]) -> None:
    """build.build_and_tests()??ctest_results瑜??댁슜??AI ?앹꽦 ?뚯뒪???ㅽ뻾 寃곌낵瑜?tests_summary??遺李?"""
    if not tests_summary or not tests_summary.get("enabled"):
        return

    cm = tests_summary.get("cmake") or {}
    prefix = cm.get("prefix") or "ai_ut_"
    ctest_results = (b_res or {}).get("data", {}).get("ctest_results", [])
    if not isinstance(ctest_results, list):
        ctest_results = []

    ai_runs: List[Dict[str, Any]] = []
    for r in ctest_results:
        try:
            name = r.get("name")
            if not name or not isinstance(name, str):
                continue
            if not name.startswith(prefix):
                continue
            ai_runs.append(
                {
                    "name": name,
                    "status": r.get("status"),
                    "exit_code": r.get("exit_code"),
                    "output": r.get("output"),
                }
            )
        except Exception:
            continue

    passed = sum(1 for x in ai_runs if x.get("status") == "pass")
    failed = sum(1 for x in ai_runs if x.get("status") != "pass")

    reason = "completed"
    if not (b_res or {}).get("ok") and (b_res or {}).get("reason") != "skipped":
        reason = "build_or_tests_failed"
    if cm.get("generated") and int(cm.get("count") or 0) > 0 and len(ai_runs) == 0:
        reason = "no_ai_tests_found_in_ctest"

    tests_summary["execution"] = {
        "enabled": True,
        "reason": reason,
        "count": len(ai_runs),
        "passed": passed,
        "failed": failed,
        "ok": (failed == 0),
        "results": ai_runs,
        "note": "AI auto-generated tests executed via CTest",
    }


def _detect_clang_info() -> Dict[str, str]:
    info: Dict[str, str] = {}
    try:
        v = subprocess.check_output(["clang", "--version"], text=True, stderr=subprocess.STDOUT).strip()
        info["clang_version"] = v.splitlines()[0] if v else ""
    except Exception:
        info["clang_version"] = ""
    try:
        r = subprocess.check_output(["clang", "-print-resource-dir"], text=True, stderr=subprocess.STDOUT).strip()
        info["clang_resource_dir"] = r
    except Exception:
        info["clang_resource_dir"] = ""
    return info

# NOTE:
# - This module is normally imported as a package member (workflow.pipeline).
# - When opened/executed as a standalone file (e.g., some IDE tools), relative
#   imports may fail. Keep a small absolute-import fallback for developer UX.

try:
    from . import common, static, build, ai, rag
    from .domain_test_panel import run_domain_test_panel, DomainTestConfig
except ImportError:  # pragma: no cover
    if __package__:
        raise
    import common, static, build, ai, rag  # type: ignore
    from domain_test_panel import run_domain_test_panel, DomainTestConfig  # type: ignore


def _csv_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        out = []
        for x in v:
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    s = str(v).strip()
    if not s:
        return []
    parts = re.split(r"[,\n]+", s)
    return [p.strip() for p in parts if p.strip()]


def _pick_best_rag_solution(past_solutions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not past_solutions:
        return None
    try:
        return sorted(past_solutions, key=lambda x: float(x.get("score", 0.0)), reverse=True)[0]
    except Exception:
        return past_solutions[0]


def _extract_search_replace_blocks_text(text: str, max_blocks: int = 3) -> Optional[str]:
    """
    RAG fix pattern?먯꽌 SEARCH/REPLACE 釉붾줉??理쒕? max_blocks媛쒓퉴吏 異붿텧??    ai.apply_patch()媛 泥섎━ 媛?ν븳 ?щ㎎?쇰줈 ?ш뎄??    """
    if not text or max_blocks <= 0:
        return None

    # ai._parse_search_replace_blocks? ?명솚?섎뒗 ?щ㎎
    pattern = re.compile(
        r"<<<<SEARCH_BLOCK\[(?P<file>[^\]]+)\]\s*\n(?P<search>.*?)\n<<<<REPLACE_BLOCK\[(?P=file)\]\s*\n(?P<replace>.*?)(?=\n<<<<SEARCH_BLOCK\[|\Z)",
        re.DOTALL,
    )

    blocks: List[str] = []
    for m in pattern.finditer(text):
        file = (m.group("file") or "").strip()
        search = (m.group("search") or "").rstrip("\n")
        repl = (m.group("replace") or "").rstrip("\n")
        if not file:
            continue
        blocks.append(f"<<<<SEARCH_BLOCK[{file}]\n{search}\n<<<<REPLACE_BLOCK[{file}]\n{repl}\n")
        if len(blocks) >= max_blocks:
            break

    if not blocks:
        return None
    return "\n".join(blocks).strip() + "\n"


def _llm_call_with_policy(
    cfg_primary: Dict[str, Any],
    cfg_fallbacks: List[Dict[str, Any]],
    messages: List[Dict[str, str]],
    log_dir: Path,
    *,
    total_attempts: int,
    fallback_models: List[str],
    fallback_config_paths: List[str],
    stage: Optional[str] = None,
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    - ?숈씪 ?붿껌 2???ъ떆??(primary 2??
    - ?댄썑 fallback 紐⑤뜽/?ㅼ젙?쇰줈 ?쒖감 ?쒕룄
    - 媛??쒕룄?????硫뷀?瑜?由ъ뒪?몃줈 諛섑솚
    """
    attempts_meta: List[Dict[str, Any]] = []

    candidates: List[tuple[str, Dict[str, Any]]] = [("primary", dict(cfg_primary))]
    # config list??2踰덉㎏~ ??ぉ?ㅻ룄 fallback ?꾨낫濡??ъ슜
    for i, c in enumerate(cfg_fallbacks or []):
        if isinstance(c, dict) and c:
            candidates.append((f"config_list[{i+1}]", dict(c)))

    for m in fallback_models:
        try:
            c = dict(cfg_primary)
            c["model"] = m
            candidates.append((f"fallback_model:{m}", c))
        except Exception:
            continue

    for p in fallback_config_paths:
        try:
            c2 = ai.load_oai_config(p)
            if isinstance(c2, dict) and c2:
                candidates.append((f"fallback_cfg:{p}", dict(c2)))
        except Exception:
            continue

    if total_attempts <= 0:
        total_attempts = 1

    schedule: List[tuple[str, Dict[str, Any]]] = []
    # 1) same request retry twice on primary
    schedule.append(candidates[0])
    if total_attempts >= 2:
        schedule.append(candidates[0])

    # 2) then try remaining candidates
    for cand in candidates[1:]:
        if len(schedule) >= total_attempts:
            break
        schedule.append(cand)

    # 3) pad if still short
    while len(schedule) < total_attempts:
        schedule.append(schedule[-1])

    reply: Optional[str] = None
    for idx, (label, cfg_use) in enumerate(schedule[:total_attempts], start=1):
        meta: Dict[str, Any] = {"policy_attempt": idx, "label": label}
        t0 = time.time()
        try:
            reply = ai.llm_call(cfg_use, messages, log_dir, meta_out=meta, stage=stage)
        except Exception as e:
            meta["error"] = str(e)
            reply = None
        meta["duration_sec"] = round(time.time() - t0, 3)
        attempts_meta.append(meta)
        if reply:
            break

    return reply, attempts_meta


def _resolve_patch_mode(patch_mode: Optional[str]) -> str:
    """
    AGENT ?⑥튂 紐⑤뱶 ?뺢퇋??    - ?곗꽑?쒖쐞: run_cli ?몄옄 > ?섍꼍蹂??AGENT_PATCH_MODE > config.AGENT_PATCH_MODE_DEFAULT > 'auto'
    - ?덉슜 媛? ['auto', 'review', 'off']
    """
    valid = getattr(config, "AGENT_PATCH_MODES", ["auto", "review", "off"])
    default = getattr(config, "AGENT_PATCH_MODE_DEFAULT", "auto")

    mode = patch_mode or os.environ.get("AGENT_PATCH_MODE") or default
    if not mode:
        return default

    mode = mode.lower()
    if mode not in valid:
        return default
    return mode


def _save_agent_patch(
    reports: Path,
    content: str,
    iteration: int,
    fix_mode: str,
) -> Path:
    """
    review 紐⑤뱶???⑥튂 ?쒖븞 ????ы띁
    - LLM??諭됱? SEARCH/REPLACE 釉붾줉 ?먮Ц??洹몃?濡??띿뒪?몃줈 ???    - ?ㅼ젣 肄붾뱶 ?섏젙? ?꾪? ?섏? ?딆쓬
    """
    patch_dir = reports / "agent_patches"
    tools.ensure_dir(patch_dir)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"agent_patch_iter{iteration}_{fix_mode}_{ts}.txt"
    path = patch_dir / name
    tmp = path.with_suffix(path.suffix + ".tmp")

    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        _logger.warning("Failed to save agent patch file: %s", e)

    return path


def _pick_runtime_targets(targets: List[Path], all_targets: List[Path]) -> List[Path]:
    return targets if targets else all_targets


def _has_libfuzzer_runtime() -> bool:
    """
    Fuzz ?ㅽ뻾 媛???щ? 泥댄겕.

    - Linux/Mac: clang resource-dir ?꾨옒 libclang_rt.fuzzer + asan 議댁옱 ?щ?
    - Windows/MinGW: clang留??덉쑝硫?dumb fuzzer(UBSan) ?泥?媛?ν븯誘濡?True
    """
    if not shutil.which("clang"):
        return False

    # MinGW clang? -fsanitize=fuzzer 誘몄??먯씠吏留?dumb fuzzer ?泥?媛??    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["clang", "--version"], text=True, stderr=subprocess.DEVNULL,
            ).lower()
            if "windows-gnu" in out:
                return True
        except Exception:
            pass

    resource_dir: Optional[str] = None
    try:
        resource_dir = subprocess.check_output(  # nosec - local tool call
            ["clang", "-print-resource-dir"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        resource_dir = None

    search_roots: List[Path] = []
    if resource_dir:
        rd = Path(resource_dir)
        lib_root = rd / "lib"
        if lib_root.is_dir():
            search_roots.append(lib_root)

    # fallback (resource-dir 議고쉶 ?ㅽ뙣 ?鍮?
    for p in (
        "/usr/lib/llvm-*/lib/clang/*/lib",
        "/usr/lib/clang/*/lib",
    ):
        for hit in glob.glob(p):
            try:
                hp = Path(hit)
                if hp.is_dir():
                    search_roots.append(hp)
            except Exception:
                pass

    if not search_roots:
        return os.name == "nt"

    def _glob_any(root: Path, pat: str) -> bool:
        try:
            return bool(list(root.glob(pat)))
        except Exception:
            return False

    fuzzer_patterns = ["**/libclang_rt.fuzzer*.a"]
    asan_patterns = ["**/libclang_rt.asan*.a"]
    if os.name == "nt":
        # LLVM Windows installs provide .lib, not .a
        fuzzer_patterns.append("**/libclang_rt.fuzzer*.lib")
        asan_patterns.append("**/libclang_rt.asan*.lib")

    has_fuzzer = any(
        _glob_any(r, pat) for r in search_roots for pat in fuzzer_patterns
    )
    has_asan = any(
        _glob_any(r, pat) for r in search_roots for pat in asan_patterns
    )

    if has_fuzzer and not has_asan and os.name == "nt":
        return True
    return bool(has_fuzzer and has_asan)


def _check_elf_arch(path: Path) -> Optional[str]:
    """Read ELF e_machine field to determine architecture. Returns 'ARM', 'x86', 'x86_64', or None."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != b"\x7fELF":
                return None
            f.seek(18)
            e_machine = int.from_bytes(f.read(2), byteorder="little")
            arch_map = {0x03: "x86", 0x3E: "x86_64", 0x28: "ARM", 0xB7: "AArch64"}
            return arch_map.get(e_machine, f"unknown({e_machine})")
    except Exception:
        return None


def _resolve_qemu_elf(proj: Path, build_dir: Optional[Path], target_arch: str = "cortex-m0plus") -> Optional[Path]:
    """
    QEMU ?ㅽ뻾???ъ슜??ARM ELF ?먯깋.
    Host 鍮뚮뱶(x86)濡??앹꽦??ELF/EXE???먮룞 ?쒖쇅.
    RP2040(Cortex-M0+) ?꾨줈?앺듃???щ줈??而댄뙆?쇰맂 ELF留??ъ슜 媛??
    """
    elf_name = os.environ.get("QEMU_ELF_NAME") or getattr(config, "QEMU_ELF_NAME", None)
    candidates = []
    if elf_name:
        candidates.append(elf_name)

    candidates += list(getattr(config, "QEMU_ELF_CANDIDATES", []))
    if not candidates:
        candidates = ["lin_gateway_rp2040.elf", "my_lin_gateway.elf"]

    uniq = []
    seen: set = set()
    for c in candidates:
        if c and c not in seen:
            uniq.append(c)
            seen.add(c)
    candidates = uniq

    search_roots: List[Path] = []
    if build_dir:
        search_roots.append(build_dir)
    search_roots.append(proj)
    if (proj / "build").exists():
        search_roots.append(proj / "build")
    if (proj / "reports").exists():
        search_roots.append(proj / "reports")

    def _is_arm_elf(p: Path) -> bool:
        arch = _check_elf_arch(p)
        return arch in ("ARM", "AArch64")

    for cand in candidates:
        for root in search_roots:
            if root and root.exists():
                hits = list(root.rglob(cand))
                for h in hits:
                    if _is_arm_elf(h):
                        return h

    for root in search_roots:
        if root and root.exists():
            elfs = list(root.rglob("*.elf"))
            for e in elfs:
                if _is_arm_elf(e):
                    return e

    return None



def _is_truthy(val: str) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _is_ci_env() -> bool:
    # Common CI markers
    if os.environ.get("JENKINS_URL") or os.environ.get("JENKINS_HOME"):
        return True
    for k in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "TF_BUILD"):
        if _is_truthy(os.environ.get(k, "")):
            return True
    return False


def _env_flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return _is_truthy(v)


def _read_text_safe(p: Path, limit_chars: int = 0) -> str:
    try:
        s = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if limit_chars and len(s) > limit_chars:
        return s[:limit_chars] + "\n... (truncated)\n"
    return s


def _extract_interesting_lines(text: str, max_lines: int = 140) -> str:
    """?먮윭 ?먯씤 ?뚯븙???꾩????섎뒗 ?쇱씤留?異붿텧"""
    if not text:
        return ""
    needles = (
        "error:",
        "fatal:",
        "undefined reference",
        "ld:",
        "collect2:",
        "Assertion",
        "assertion",
        "AddressSanitizer",
        "ThreadSanitizer",
        "runtime error",
        "SIGSEGV",
        "Segmentation fault",
        "Timeout",
        "TIMEOUT",
        "FAILED",
        "failed",
        "No such file or directory",
    )
    out: List[str] = []
    for ln in text.splitlines():
        if any(n in ln for n in needles):
            out.append(ln)
            if len(out) >= max_lines:
                break
    return "\n".join(out)


def _build_ai_context_for_build_failure(
    proj: Path,
    b_res: Dict[str, Any],
    max_chars: int = 12000,
) -> Dict[str, str]:
    """
    build/test ?ㅽ뙣 ??AI???섍만 ?꾨＼?꾪듃 而⑦뀓?ㅽ듃瑜?援ъ꽦
    - triage ?붿빟
    - ?ㅽ뙣 ?뚯뒪?몃퀎 異쒕젰 ?뚯씪 ?쇰?
    - ?먮윭 ?쇱씤 異붿텧 + 濡쒓렇 tail
    """
    data = b_res.get("data", {}) or {}
    triage = data.get("triage", {}) or {}
    failures = triage.get("failures", []) or []
    targets = triage.get("targets", []) or []
    timeout_tests = triage.get("timeout_tests", []) or []

    ctest_results = data.get("ctest_results", []) or []
    failing_tests = [
        r
        for r in ctest_results
        if int(r.get("exit_code", 0) or 0) != 0 and r.get("output")
    ][:6]

    build_ok = bool(data.get("build_ok", False))
    tests_ok = bool(data.get("tests_ok", True))
    reason = b_res.get("reason", "")

    mode = "build_compile"
    if build_ok and not tests_ok:
        mode = "unit_test_fail"
    elif reason == "config_fail":
        mode = "cmake_config_fail"

    # policy (prod-first)
    policy = (
        "Fix policy:\n"
        "- unit test ?ㅽ뙣?쇰㈃ 湲곕낯? ?꾨줈?뺤뀡 肄붾뱶(libs/) ?섏젙 ?곗꽑\n"
        "- ?뚯뒪???ㅽ뀅 ?섏젙? '?뚯뒪??肄붾뱶 ?먯껜??臾몃쾿/而댄뙆???ㅻ쪟' ?먮뒗 '?ㅽ뀅 ?꾨씫'??紐낅갚???뚮쭔\n"
        "- ?뚯뒪?몃? 鍮꾪솢?깊솕?섍굅??湲곕?媛믪쓣 ?쏀솕?쒗궎吏 留?寃?n"
        "- 異쒕젰? SEARCH/REPLACE 釉붾줉留?n"
    )

    triage_lines = []
    for f in failures[:6]:
        t = f.get("type", "")
        h = f.get("hint", "")
        if t or h:
            triage_lines.append(f"- {t}: {h}".strip())
    if timeout_tests:
        triage_lines.append(f"- timeout_tests: {', '.join(timeout_tests[:8])}")

    focus_files = []
    for t in targets[:8]:
        fp = (proj / t).resolve()
        if proj in fp.parents and fp.exists():
            focus_files.append(str(fp.relative_to(proj)))
    focus_files = focus_files[:8]

    header = (
        f"Build/Test Failure Mode: {mode}\n"
        f"Reason: {reason}\n"
        f"build_ok={build_ok}, tests_ok={tests_ok}\n"
        + ("\n[Triage]\n" + "\n".join(triage_lines) + "\n" if triage_lines else "")
        + ("\n[Suggested Focus Files]\n" + "\n".join(focus_files) + "\n" if focus_files else "")
        + "\n"
        + policy
    )

    # excerpts for suggested targets
    excerpts: Dict[str, str] = {}
    for rel in focus_files[:4]:
        excerpts[rel] = common.read_excerpt(proj / rel)

    log_text = data.get("log", "") or ""
    interesting = _extract_interesting_lines(log_text, max_lines=160)
    tail = log_text[-6000:] if len(log_text) > 6000 else log_text

    sections: List[str] = [header]
    if excerpts:
        sections.append("[Source Excerpts]\n" + json.dumps(excerpts, indent=2))

    # failing test outputs
    for r in failing_tests:
        name = r.get("name") or "__all__"
        outp = Path(str(r.get("output")))
        out_txt = _read_text_safe(outp, limit_chars=2500)
        sections.append(
            f"[CTest Output: {name} | status={r.get('status')} | exit={r.get('exit_code')}]\n{out_txt}"
        )

    if interesting:
        sections.append("[Interesting Log Lines]\n" + interesting)
    if tail:
        sections.append("[Build Log Tail]\n" + tail)

    # fit to budget while preserving header
    combined = sections[0]
    budget = max_chars - len(combined)
    for sec in sections[1:]:
        if budget <= 0:
            break
        if len(sec) + 2 <= budget:
            combined += "\n\n" + sec
            budget -= (len(sec) + 2)
        else:
            # partial append
            combined += "\n\n" + sec[: max(0, budget)]
            budget = 0
            break

    # rag key???덈Т 湲몄? ?딄쾶
    rag_key = ""
    if failures:
        rag_key = (failures[0].get("type", "") + " " + failures[0].get("hint", "")).strip()
    if not rag_key:
        rag_key = (interesting.splitlines()[0] if interesting else tail.splitlines()[-1] if tail else "")[:300]

    return {
        "context": combined,
        "rag_key": rag_key[:300],
        "mode": mode,
    }



def run_cli(
    project_root: str,
    report_dir: str = "reports",
    targets_glob: str = "libs/*.c",
    include_paths: Optional[List[str]] = None,
    suppressions_path: Optional[str] = None,
    # Flags
    do_cmake_analysis: bool = False,
    do_syntax_check: bool = True,
    do_build_and_test: bool = False,
    do_coverage: bool = False,
    static_only: bool = True,
    enable_agent: bool = False,
    max_iterations: int = 1,
    oai_config_path: Optional[str] = None,
    pico_sdk_path_override: Optional[str] = None,
    auto_guard: bool = False,
    guard_prefixes: Optional[List[str]] = None,
    stubs_root: str = "tests/stubs",
    dry_run_autoguard: bool = False,
    defines: Optional[List[str]] = None,
    full_analysis: bool = False,
    # Callbacks
    progress_callback: Optional[Callable] = None,
    log_callback: Optional[Callable] = None,
    # Configs
    target_arch: str = "cortex-m0plus",
    extra_defines: Optional[List[str]] = None,
    cppcheck_enable: Optional[List[str]] = None,
    enable_test_gen: bool = False,
    test_gen_stub_only: bool = False,
    test_gen_excludes: Optional[List[str]] = None,
    test_gen_timeout_sec: Optional[int] = None,
    do_clang_tidy: bool = False,
    clang_tidy_checks: Optional[List[str]] = None,
    # Static Analysis Preset / Semgrep
    quality_preset: Optional[str] = None,
    enable_semgrep: Optional[bool] = None,
    semgrep_config: Optional[str] = None,
    # Dynamic Analysis Flags
    do_asan: bool = False,
    do_fuzz: bool = False,
    do_qemu: bool = False,
    do_docs: bool = False,
    # Domain Test Options
    enable_domain_tests: bool = False,
    domain_tests_auto: Optional[bool] = None,
    domain_targets: Optional[List[str]] = None,
    # Agent patch mode (auto / review / off)
    patch_mode: Optional[str] = None,
    # Agent loop settings
    agent_roles: Optional[List[str]] = None,
    agent_review: Optional[bool] = None,
    agent_rag: Optional[bool] = None,
    agent_max_steps: Optional[int] = None,
    agent_run_mode: Optional[str] = None,
    agent_rag_top_k: Optional[int] = None,
    # [NEW] ?뺤쟻 遺꾩꽍 ?ㅽ뙣 臾댁떆 ?щ? (湲곕낯媛?False)
    ignore_static_failure: bool = False,
    ai_log_max_chars: int = 12000,
    fuzz_strict: Optional[bool] = None,
    qemu_strict: Optional[bool] = None,
    domain_tests_strict: Optional[bool] = None,
    build_dir_override: Optional[str] = None,
    # Auto-fix scope
    auto_fix_scope: Optional[List[str]] = None,
    auto_fix_on_fail: Optional[bool] = None,
    auto_fix_on_fail_stages: Optional[List[str]] = None,
    # Git base ref for incremental diff
    git_base_ref: Optional[str] = None,
    # SCM mode (auto/git/svn)
    scm_mode: Optional[str] = None,
    # SVN base ref for incremental diff
    svn_base_ref: Optional[str] = None,
    # RAG ingestion sources
    vc_reports_paths: Optional[List[str]] = None,
    uds_spec_paths: Optional[List[str]] = None,
    req_docs_paths: Optional[List[str]] = None,
    codebase_paths: Optional[List[str]] = None,
    rag_ingest_enable: Optional[bool] = None,
    auto_run_tests: Optional[bool] = None,
    # Control
    stop_check: Optional[Callable[[], None]] = None,
    fast_fail: bool = True,
) -> int:
    # 1. Setup & Initialization
    proj = Path(project_root).resolve()
    reports = (proj / report_dir).resolve()
    tools.ensure_dir(reports)
    tools.ensure_dir(reports / "agent_logs")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = reports / "pipeline.log"
    common.append_run_header(log_path, f"Run {run_id} | project={proj.name}")
    log_callback = common.make_tee_logger(log_callback, log_path)

    def _check_stop() -> None:
        common.check_stop(stop_check=stop_check, stop_flag=(reports / ".stop"))

    _check_stop()


    # strict mode defaults (CI?먯꽌??湲곕낯 strict)
    ci_env = _is_ci_env()
    if fuzz_strict is None:
        fuzz_strict = _env_flag("FUZZ_STRICT", default=ci_env)
    if qemu_strict is None:
        qemu_strict = _env_flag("QEMU_STRICT", default=False)
    if domain_tests_strict is None:
        domain_tests_strict = _env_flag("DOMAIN_TESTS_STRICT", default=False)
    if domain_tests_auto is None:
        domain_tests_auto = bool(getattr(config, "DOMAIN_TESTS_AUTO", True))

    # env override for AI log budget
    try:
        _env_ai = int(os.environ.get("AI_LOG_MAX_CHARS", "0") or 0)
        if _env_ai > 0:
            ai_log_max_chars = _env_ai
    except Exception:
        pass

    # AI 濡쒓렇 budget
    if ai_log_max_chars < 3000:
        ai_log_max_chars = 3000

    if pico_sdk_path_override:
        os.environ["PICO_SDK_PATH"] = pico_sdk_path_override

    # Coverage/ASan??耳쒕㈃ 鍮뚮뱶 ?④퀎 ?먮룞 ?쒖꽦??    if do_coverage or do_asan:
        do_build_and_test = True

    # AI ?뚯뒪???앹꽦 ???먮룞 ?ㅽ뻾 ?듭뀡
    if auto_run_tests is None:
        auto_run_tests = bool(getattr(config, "AUTO_RUN_TESTS", False))
    if enable_test_gen and auto_run_tests:
        do_build_and_test = True

    # ?먮룞 AI 蹂듦뎄(鍮뚮뱶/?뚯뒪??臾몃쾿 ?ㅽ뙣 ??
    explicit_agent = bool(enable_agent)
    if auto_fix_on_fail is None:
        auto_fix_on_fail = _env_flag("AUTO_FIX_ON_FAIL", default=getattr(config, "AUTO_FIX_ON_FAIL", False))
    if auto_fix_on_fail_stages is None:
        auto_fix_on_fail_stages = getattr(config, "AUTO_FIX_ON_FAIL_STAGES", ["build", "tests", "syntax"])
    allowed_fail_stages = {str(s).strip().lower() for s in (auto_fix_on_fail_stages or []) if str(s).strip()}
    agent_only_on_failure = False
    if bool(auto_fix_on_fail) and not explicit_agent:
        enable_agent = True
        agent_only_on_failure = True
        if not patch_mode:
            patch_mode = getattr(config, "AUTO_FIX_PATCH_MODE", "auto")
        if agent_run_mode is None:
            agent_run_mode = getattr(config, "AUTO_FIX_RUN_MODE", "auto")
        if auto_fix_scope is None:
            auto_fix_scope = list(allowed_fail_stages) or getattr(config, "AUTO_FIX_SCOPE_ON_FAIL", ["build", "tests", "syntax"])
        common.log_msg(
            log_callback,
            f"?쨼 Auto-fix on failure enabled (agent forced on): stages={sorted(list(allowed_fail_stages))}",
        )

    def _check_any(names: List[str]) -> str:
        for n in names:
            if tools.which(n):
                return n
        return ""

    def _build_preflight() -> Dict[str, Any]:
        preflight: Dict[str, Any] = {"tools": {}, "missing": [], "warnings": []}
        def _record(key: str, names: List[str], required: bool) -> None:
            found = _check_any(names)
            preflight["tools"][key] = found
            if required and not found:
                preflight["missing"].append(key)
        # Git (incremental 紐⑤뱶???뚮쭔 ?꾩닔)
        _record("git", ["git"], required=not full_analysis)
        # Build & Test
        if do_build_and_test:
            _record("cmake", ["cmake"], required=True)
            _record("build_tool", ["ninja", "make"], required=False)
            _record("cc", ["gcc", "clang", "arm-none-eabi-gcc"], required=False)
        # Static analysis
        if cppcheck_enable:
            _record("cppcheck", ["cppcheck"], required=True)
        if do_clang_tidy:
            _record("clang_tidy", ["clang-tidy"], required=True)
        if enable_semgrep:
            found = _check_any(["semgrep"])
            preflight["tools"]["semgrep"] = found
            if not found:
                preflight["warnings"].append("semgrep_missing_disabled")
        if do_syntax_check:
            _record("gcc_syntax", ["gcc", "clang", "arm-none-eabi-gcc"], required=False)
        # Dynamic / Docs
        if do_qemu:
            _record("qemu", ["qemu-system-arm", "qemu-system-aarch64"], required=False)
        if do_docs:
            _record("doxygen", ["doxygen"], required=False)
        if do_fuzz:
            _record("fuzzer", ["clang", "gcc"], required=False)
        if preflight["missing"]:
            preflight["warnings"].append("missing_required_tools")
        return preflight

    def _summarize_change_impact(files: List[Path]) -> Dict[str, Any]:
        impact: Dict[str, Any] = {
            "total": 0,
            "by_ext": {},
            "top_dirs": [],
            "has_tests": False,
            "has_configs": False,
            "has_build_files": False,
        }
        if not files:
            return impact
        ext_counts: Dict[str, int] = {}
        dir_counts: Dict[str, int] = {}
        test_markers = ("test", "tests", "unittest", "ut", "it")
        config_files = {"cmakelists.txt", "requirements.txt", "pyproject.toml", "package.json"}
        build_markers = ("cmake", "makefile", "dockerfile", ".yml", ".yaml")
        for p in files:
            try:
                rel = p.relative_to(proj)
            except Exception:
                rel = Path(str(p))
            rel_posix = str(rel).replace("\\", "/")
            ext = p.suffix.lower() if p.suffix else "<no_ext>"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            top_dir = rel_posix.split("/", 1)[0] if "/" in rel_posix else rel_posix
            if top_dir:
                dir_counts[top_dir] = dir_counts.get(top_dir, 0) + 1
            lower = rel_posix.lower()
            if any(f"/{m}/" in f"/{lower}/" for m in test_markers) or lower.startswith("tests/"):
                impact["has_tests"] = True
            if rel.name.lower() in config_files:
                impact["has_configs"] = True
            if rel.name.lower() in ("cmakelists.txt", "makefile", "dockerfile") or lower.endswith(build_markers):
                impact["has_build_files"] = True
        impact["total"] = len(files)
        impact["by_ext"] = dict(sorted(ext_counts.items(), key=lambda x: x[1], reverse=True))
        impact["top_dirs"] = [k for k, _ in sorted(dir_counts.items(), key=lambda x: x[1], reverse=True)[:6]]
        return impact

    def _validate_reports(
        coverage: Dict[str, Any],
        docs: Dict[str, Any],
        tests: Dict[str, Any],
        report_root: Path,
    ) -> Dict[str, Any]:
        health: Dict[str, Any] = {"missing": [], "warnings": [], "checks": {}}

        def _exists(path: Optional[str]) -> bool:
            if not path:
                return False
            try:
                return Path(str(path)).exists()
            except Exception:
                return False

        if coverage.get("enabled"):
            xml_ok = _exists(str(coverage.get("xml") or ""))
            html_ok = _exists(str(coverage.get("html") or ""))
            health["checks"]["coverage_xml"] = xml_ok
            health["checks"]["coverage_html"] = html_ok
            if not xml_ok:
                health["missing"].append("coverage_xml")
            if not html_ok:
                health["missing"].append("coverage_html")

        if docs.get("enabled"):
            docs_dir = report_root / "docs"
            docs_ok = docs_dir.exists()
            health["checks"]["docs_dir"] = docs_ok
            if not docs_ok:
                health["missing"].append("docs_dir")

        if tests.get("enabled"):
            auto_dir = report_root / "auto_generated"
            plan_ok = bool(list(auto_dir.glob("test_*.plan.json"))) if auto_dir.exists() else False
            health["checks"]["ai_test_plan"] = plan_ok
            if not plan_ok:
                health["warnings"].append("ai_test_plan_missing")

        return health

    # Initialize Knowledge Base (RAG)
    kb = rag.get_kb(reports)
    if rag_ingest_enable is None:
        rag_ingest_enable = bool(getattr(config, "RAG_INGEST_ON_PIPELINE", True))
    if rag_ingest_enable:
        try:
            ingest_cfg = {
                "vc_reports_paths": vc_reports_paths,
                "uds_spec_paths": uds_spec_paths,
                "req_docs_paths": req_docs_paths,
                "codebase_paths": codebase_paths or [str(proj)],
            }
            ingest_res = rag.ingest_external_sources(kb, cfg=ingest_cfg)
            common.log_msg(
                log_callback,
                f"?뱴 RAG ingest: updated={ingest_res.get('updated')}, skipped={ingest_res.get('skipped')}",
            )
        except Exception as e:
            common.log_msg(log_callback, f"?좑툘 RAG ingest failed: {e}")

    # Agent loop configuration
    roles = _csv_list(agent_roles) if agent_roles else []
    if not roles:
        roles = list(getattr(config, "AGENT_ROLES_DEFAULT", ["planner", "generator", "fixer", "reviewer"]))
    agent_settings: Dict[str, Any] = {
        "roles": roles,
        "max_steps": int(agent_max_steps or getattr(config, "AGENT_MAX_STEPS_DEFAULT", 3)),
        "review_enabled": bool(agent_review) if agent_review is not None else bool(getattr(config, "AGENT_REVIEW_ENABLED_DEFAULT", True)),
        "rag_enabled": bool(agent_rag) if agent_rag is not None else bool(getattr(config, "AGENT_RAG_ENABLED_DEFAULT", True)),
        "rag_top_k": int(agent_rag_top_k or getattr(config, "AGENT_RAG_TOP_K_DEFAULT", 3)),
        "run_mode": str(agent_run_mode or getattr(config, "AGENT_RUN_MODE_DEFAULT", "auto")),
    }

    llm_disabled_env = os.environ.get("LLM_DISABLE", "").strip().lower() in ("1", "true", "yes", "on")
    stub_only_env = os.environ.get("TEST_GEN_STUB_ONLY", "").strip().lower() in ("1", "true", "yes", "on")
    llm_disabled = llm_disabled_env or stub_only_env
    if llm_disabled:
        enable_agent = False
        auto_fix_on_fail = False
        enable_domain_tests = False
        agent_settings["run_mode"] = "off"
        common.log_msg(
            log_callback,
            "[LLM] disabled by env -> skipping agent/domain features.",
        )

    # Agent patch 紐⑤뱶 寃곗젙
    agent_enabled_effective = bool(enable_agent) and agent_settings.get("run_mode") != "off"
    effective_patch_mode = _resolve_patch_mode(patch_mode) if agent_enabled_effective else "off"
    if agent_settings.get("run_mode") == "review" and agent_enabled_effective:
        effective_patch_mode = "review"

    common.log_msg(log_callback, f"?? Analysis started for {proj.name}")
    if agent_enabled_effective:
        common.log_msg(
            log_callback,
            f"?㎥ Agent patch mode: {effective_patch_mode}",
        )

    # 0. [Step 0] Preflight Checks
    preflight = _build_preflight()
    if enable_semgrep and not preflight.get("tools", {}).get("semgrep"):
        enable_semgrep = False
        common.log_msg(log_callback, "?좑툘 [Step 0] Semgrep not found; semgrep disabled for this run.")
    if preflight.get("missing"):
        common.log_msg(
            log_callback,
            f"?좑툘 [Step 0] Preflight: missing tools -> {', '.join(preflight.get('missing') or [])}",
        )
    else:
        common.log_msg(log_callback, "??[Step 0] Preflight OK")

    # 2. Target Identification
    all_targets = common.list_targets(proj, targets_glob)
    targets = all_targets
    change_mode = "full"
    git_status = "unknown"
    svn_status = "unknown"
    scm_used = "none"
    used_base_ref = None
    used_svn_ref = None
    changed_files: List[Path] = []
    changed_items: List[Dict[str, str]] = []

    scm_mode = (scm_mode or "auto").strip().lower()
    if not full_analysis:
        if scm_mode in ("auto", "git"):
            changed_items, git_status, used_base_ref = common.get_git_changed_items(proj, base_ref=git_base_ref)
            changed_files, _, _ = common.get_git_changed_files(proj, base_ref=git_base_ref)
            if git_status == "git_ok":
                scm_used = "git"
        if scm_used != "git" and scm_mode in ("auto", "svn"):
            changed_items, svn_status, used_svn_ref = common.get_svn_changed_items(proj, base_ref=svn_base_ref)
            changed_files, _, _ = common.get_svn_changed_files(proj, base_ref=svn_base_ref)
            if svn_status == "svn_ok" or svn_status == "svn_base_ref_invalid":
                scm_used = "svn"

        if scm_used in ("git", "svn"):
            targets = [t for t in all_targets if t.resolve() in changed_files]
            change_mode = "incremental"
            common.log_msg(
                log_callback,
                f"?뱄툘 Incremental scan({scm_used}): {len(targets)} changed files.",
            )
        else:
            common.log_msg(
                log_callback,
                f"?좑툘 SCM unavailable (git={git_status}, svn={svn_status}), falling back to full scan.",
            )
            targets = all_targets
    else:
        # still capture git status for summary when available
        try:
            _, git_status, used_base_ref = common.get_git_changed_files(proj, base_ref=git_base_ref)
        except Exception:
            git_status = "unknown"

    git_meta = common.get_git_meta(proj)
    svn_meta = common.get_svn_meta(proj)
    # normalize changed items + list
    norm_items: List[Dict[str, str]] = []
    changed_list: List[str] = []
    for it in changed_items:
        path = str(it.get("path") or "").strip()
        if not path:
            continue
        try:
            rel = str((proj / path).resolve().relative_to(proj))
        except Exception:
            rel = path
        status = str(it.get("status") or "").strip().upper() or "M"
        norm_items.append({"path": rel, "status": status})
        changed_list.append(rel)
    if not norm_items:
        for p in changed_files:
            try:
                rel = str(p.relative_to(proj))
            except Exception:
                rel = str(p)
            norm_items.append({"path": rel, "status": "M"})
            changed_list.append(rel)

    git_changed_list = changed_list if scm_used == "git" else []
    svn_changed_list = changed_list if scm_used == "svn" else []
    git_changed_samples = git_changed_list[:50]

    # SVN: auto shrink analysis scope by changed extensions
    if scm_used == "svn" and not full_analysis and norm_items:
        exts = set()
        for it in norm_items:
            p = str(it.get("path") or "")
            ext = Path(p).suffix.lower()
            if ext:
                exts.add(ext)
        if exts:
            targets = [t for t in targets if t.suffix.lower() in exts]
            common.log_msg(
                log_callback,
                f"?뵊 SVN ext filter applied: {sorted(list(exts))}",
            )

    def _write_scm_change_summary(out_dir: Path) -> Dict[str, Any]:
        out_dir.mkdir(parents=True, exist_ok=True)
        ext_counts: Dict[str, int] = {}
        status_counts: Dict[str, int] = {}
        top_dirs: Dict[str, int] = {}
        for it in norm_items:
            p = str(it.get("path") or "")
            ext = (Path(p).suffix or "<no_ext>").lower()
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            stv = str(it.get("status") or "M").upper()
            status_counts[stv] = status_counts.get(stv, 0) + 1
            top = p.split("/", 1)[0] if "/" in p else p
            if top:
                top_dirs[top] = top_dirs.get(top, 0) + 1
        summary = {
            "scm": scm_used,
            "git_base_ref": used_base_ref,
            "svn_base_ref": used_svn_ref,
            "total": len(norm_items),
            "by_ext": dict(sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)),
            "by_status": dict(sorted(status_counts.items(), key=lambda x: x[1], reverse=True)),
            "top_dirs": [k for k, _ in sorted(top_dirs.items(), key=lambda x: x[1], reverse=True)[:10]],
            "items": norm_items,
        }
        json_path = out_dir / "scm_change_summary.json"
        md_path = out_dir / "scm_change_summary.md"
        try:
            json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        try:
            lines = [
                "# SCM Change Summary",
                f"- scm: {scm_used}",
                f"- total: {len(norm_items)}",
                f"- git_base_ref: {used_base_ref}",
                f"- svn_base_ref: {used_svn_ref}",
                "",
                "## By Extension",
            ]
            for k, v in summary.get("by_ext", {}).items():
                lines.append(f"- {k}: {v}")
            lines.append("")
            lines.append("## By Status")
            for k, v in summary.get("by_status", {}).items():
                lines.append(f"- {k}: {v}")
            lines.append("")
            lines.append("## Top Dirs")
            for d in summary.get("top_dirs", []):
                lines.append(f"- {d}")
            md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        except Exception:
            pass
        return {"json": str(json_path), "md": str(md_path)}

    scm_report_paths = _write_scm_change_summary(reports)

    # 2.5 [Step 2.5] Change Impact Summary
    change_impact = _summarize_change_impact(changed_files)
    if change_impact.get("total", 0) > 0:
        common.log_msg(
            log_callback,
            f"?㎛ [Step 2.5] Change impact: {change_impact.get('total')} files, top dirs={change_impact.get('top_dirs')}",
        )

    def _prioritize_targets_by_changes(all_targets: List[Path], changed: List[Path]) -> List[Path]:
        if not all_targets or not changed:
            return all_targets
        changed_set = {c.resolve() for c in changed if c}
        changed_stems = {c.stem.lower() for c in changed if c}
        def _score(p: Path) -> int:
            try:
                if p.resolve() in changed_set:
                    return 0
            except Exception:
                pass
            if p.stem.lower() in changed_stems:
                return 1
            return 2
        return sorted(list(all_targets), key=_score)

    targets = _prioritize_targets_by_changes(targets, changed_files)

    # ?뺤쟻 ?꾩슜 + 蹂寃??源??놁쓬 + ?고???湲곕뒫???놁쓬???뚮쭔 議곌린 醫낅즺
    if (
        not targets
        and static_only
        and not do_build_and_test
        and not do_fuzz
        and not do_qemu
        and not enable_domain_tests
    ):
        common.log_msg(log_callback, "??Nothing to analyze.")
        return 0

    # LLM config
    need_llm = (agent_enabled_effective or enable_test_gen or do_fuzz or enable_domain_tests) and not llm_disabled
    cfgs = ai.load_oai_configs(oai_config_path) if need_llm else []
    cfg = cfgs[0] if cfgs else None
    cfg_fallbacks = cfgs[1:] if len(cfgs) > 1 else []
    if cfg:
        common.log_msg(log_callback, f"?쨼 LLM: model={cfg.get('model')}, api_type={cfg.get('api_type')}")
    
    # 9. Static-Analysis Paths (Moved up for early usage)
    default_incs = getattr(config, "DEFAULT_INCLUDE_PATHS", [])
    inc_paths = list(include_paths or []) + list(default_incs)
    inc_paths += tools.get_arch_include_paths(target_arch, str(proj))
    all_defines = list(defines or []) + list(extra_defines or [])
    syn_incs = list(inc_paths or [])
    syn_defs = list(all_defines or [])
    # Prefer stubs for Pico headers during syntax check
    try:
        stubs_dir = (proj / stubs_root).resolve() if stubs_root else (proj / "tests" / "stubs").resolve()
        if stubs_dir.exists():
            proj_str = str(proj.resolve())
            syn_incs = [proj_str] + [p for p in syn_incs if str(p) != proj_str]
            stubs_str = str(stubs_dir)
            syn_incs = [stubs_str] + [p for p in syn_incs if str(p) != stubs_str]
            if "UNIT_TEST" not in syn_defs:
                syn_defs.append("UNIT_TEST")
            if "HOST_BUILD" not in syn_defs:
                syn_defs.append("HOST_BUILD")
    except Exception:
        pass

    # Quality preset ?곸슜 (custom? UI ?ㅼ젙 洹몃?濡??ъ슜)
    preset = str(quality_preset or getattr(config, "QUALITY_PRESET_DEFAULT", "high")).strip().lower()
    presets = getattr(config, "QUALITY_PRESETS", {}) or {}
    if preset not in presets:
        preset = str(getattr(config, "QUALITY_PRESET_DEFAULT", "high")).strip().lower()
    preset_cfg = presets.get(preset, {}) if isinstance(presets, dict) else {}

    if preset != "custom":
        do_clang_tidy = bool(preset_cfg.get("clang_tidy", False))
        enable_semgrep = bool(preset_cfg.get("semgrep", False))
        semgrep_config = str(preset_cfg.get("semgrep_config") or "p/default")
    else:
        enable_semgrep = bool(enable_semgrep) if enable_semgrep is not None else False
        semgrep_config = str(semgrep_config or "p/default")

    # 3. [Step 1] Auto Guard (Stub Injection)
    if auto_guard:
        common.log_msg(log_callback, "?썳截?[Step 1] Auto-Guarding Sources...")
        build.auto_guard_sources(
            proj,
            reports,
            targets,
            guard_prefixes or ["pico/", "hardware/"],
            stubs_root,
            dry_run_autoguard,
            progress_callback,
        )

    # [MOVED UP] 14. [Step 2] Unit Test Generation
    # 而ㅻ쾭由ъ? 痢≪젙 ???앹꽦???뚯뒪?몃? ?ы븿?섍린 ?꾪빐 鍮뚮뱶 ?④퀎 ?욎쑝濡??대룞
    tests_summary: Dict[str, Any] = {"enabled": False}
    if enable_test_gen:
        cfg_runtime = dict(cfg or {})
        if test_gen_excludes is not None:
            cfg_runtime["test_gen_excludes"] = test_gen_excludes
        if test_gen_timeout_sec is not None:
            cfg_runtime["test_gen_timeout_sec"] = int(test_gen_timeout_sec)
        env_stub = os.environ.get("TEST_GEN_STUB_ONLY", "").strip().lower()
        if env_stub in ("1", "true", "yes", "on"):
            test_gen_stub_only = True
        if not test_gen_stub_only and cfg:
            api_type = str(cfg.get("api_type") or "").lower()
            model_name = str(cfg.get("model") or "").lower()
            if (api_type == "google" or "gemini" in model_name) and (
                getattr(ai, "genai_new", None) is None and getattr(ai, "genai_legacy", None) is None
            ):
                test_gen_stub_only = True
                common.log_msg(
                    log_callback,
                    "[Step 2] Gemini SDK missing -> fallback to stub-only tests.",
                )
        if not cfg and not test_gen_stub_only:
            test_gen_stub_only = True
            common.log_msg(
                log_callback,
                "[Step 2] LLM config not found -> fallback to stub-only tests.",
            )
        cfg_runtime["test_gen_stub_only"] = bool(test_gen_stub_only)
        if test_gen_stub_only:
            common.log_msg(
                log_callback,
                "?㎦ [Step 2] Generating Stub Unit Tests (Pre-Build)...",
            )
            tests_summary = _generate_stub_tests(
                project_root=proj,
                reports=reports,
                targets=targets,
                excludes=test_gen_excludes,
            )
        else:
            common.log_msg(
                log_callback,
                "?㎦ [Step 2] Generating Unit Tests (Pre-Build)...",
            )
            tests_summary = ai.run_test_gen(
                project_root=proj,
                reports=reports,
                targets=targets,
                cfg=cfg_runtime,
                include_paths=inc_paths,
                defines=all_defines,
                progress_callback=progress_callback,
                agent_settings=agent_settings,
                rag_kb=kb,
            )
        if "enabled" not in tests_summary:
            tests_summary["enabled"] = True
        try:
            t_results = tests_summary.get("results", [])
            if isinstance(t_results, list):
                tests_summary["generated_count"] = len(t_results)
                tests_summary["ok_count"] = sum(1 for r in t_results if r.get("ok") is True)
                tests_summary["failed_count"] = sum(1 for r in t_results if r.get("ok") is False)
                tests_summary["compile_failed_count"] = sum(
                    1 for r in t_results if str(r.get("reason") or "") == "compile_failed"
                )
                tests_summary["syntax_failed_count"] = sum(
                    1 for r in t_results if str(r.get("reason") or "") == "syntax_failed"
                )
                tests_summary["missing_main_count"] = sum(
                    1 for r in t_results if str(r.get("reason") or "") == "missing_main"
                )
                tests_summary["invalid_output_count"] = sum(
                    1
                    for r in t_results
                    if str(r.get("reason") or "") == "invalid_llm_output_quarantined"
                )
                tests_summary["plan_ok_count"] = sum(
                    1 for r in t_results if r.get("plan_ok") is True
                )
        except Exception:
            pass

        # P2.1: AI ?앹꽦 ?뚯뒪?몃? CTest ?ㅽ뻾 ??곸쑝濡??먮룞 ?깅줉
        cm_info = {"generated": False, "reason": "review_mode"}
        if tests_summary.get("mode") != "review":
            cm_info = _generate_auto_generated_cmakelists(
                project_root=proj,
                reports=reports,
                tests_summary=tests_summary,
                include_paths=inc_paths,
                defines=all_defines,
                stubs_root=stubs_root,
            )
            # Ensure top-level CMakeLists includes reports/auto_generated
            try:
                build.ensure_auto_generated_subdir(proj, reports)
            except Exception:
                pass
        tests_summary["cmake"] = cm_info
        if not cm_info.get("generated") and isinstance(tests_summary.get("results"), list):
            fail_reasons = {str(r.get("reason") or "") for r in tests_summary.get("results") or []}
            if any("llm_error:network_denied" in r for r in fail_reasons):
                common.log_msg(
                    log_callback,
                    "?좑툘 LLM network access denied (WinError 10013). Check firewall/proxy/AV permissions for python.exe.",
                )
            if "no_llm_response" in fail_reasons:
                common.log_msg(
                    log_callback,
                    "?좑툘 AI test code generation failed (no LLM response). Check Gemini SDK/config.",
                )

    # 4. [Step 3] Build & Test
    b_res = common.standardize_result(False, "skipped")
    coverage_summary: Dict[str, Any] = {
        "enabled": False,
        "ok": False,
        "line_rate": None,
        "branch_rate": None,
        "function_rate": None,
        "functions_covered": None,
        "functions_total": None,
        "threshold": None,
        "below_threshold": False,
        "xml": None,
        "html": None,
    }

    if do_build_and_test or do_clang_tidy:
        asan_msg = " (with ASan)" if do_asan else ""
        coverage_msg = " (with Coverage)" if do_coverage else ""
        common.log_msg(log_callback, f"?룛截?[Step 3] CMake Build & Test{asan_msg}{coverage_msg}...")

        _check_stop()
        b_res = build.build_and_tests(
            proj,
            reports,
            do_coverage,
            do_asan,
            stability_gate=bool(getattr(config, "TEST_STABILITY_GATE", False)),
            build_dir_override=build_dir_override,
        )
        
        # 鍮뚮뱶 寃곌낵 利됱떆 濡쒓퉭
        b_data = b_res.get("data", {})
        build_ok = b_data.get("build_ok", b_res.get("ok", False))
        tests_ok = b_data.get("tests_ok", True)
        reason = b_res.get("reason", "unknown")
        
        if not build_ok:
            common.log_msg(log_callback, f"??[Step 3] Build failed: reason={reason}")
            if reason == "config_fail":
                common.log_msg(log_callback, f"   ??CMake configure failed. Check CMakeLists.txt and build logs.")
            elif reason == "build_fail":
                # 鍮뚮뱶 濡쒓렇?먯꽌 ASan 愿???먮윭 ?뺤씤
                build_log = b_data.get("log", "")
                is_asan_error = (
                    "cannot find -lasan" in build_log or
                    "libasan" in build_log.lower() or
                    ("-fsanitize=address" in build_log and "error" in build_log.lower())
                )
                if is_asan_error:
                    common.log_msg(log_callback, f"   ??ASan library not found. On Windows/MinGW, UBSan is used as fallback.")
                    common.log_msg(log_callback, f"   ??UBSan detects: signed overflow, shift errors, null deref, type mismatches.")
                else:
                    common.log_msg(log_callback, f"   ??Compilation failed. Check build errors above.")
            elif reason == "test_fail":
                common.log_msg(log_callback, f"   ??Tests failed (but build succeeded).")
        elif not tests_ok:
            common.log_msg(log_callback, f"?좑툘 [Step 3] Build succeeded but tests failed")
        else:
            common.log_msg(log_callback, f"??[Step 3] Build and tests succeeded")

        # Attach CTest execution summary to tests section.
        try:
            _attach_ai_test_execution_to_summary(tests_summary, b_res)
        except Exception:
            pass

        # Fast-fail: 鍮뚮뱶 ?ㅽ뙣 ???꾩냽 ?④퀎 ?⑥텞(?먯씠?꾪듃 誘몄궗?⑹씪 ??
        # 二쇱쓽: build_ok? tests_ok瑜?援щ텇?섏뿬, 鍮뚮뱶???깃났?덉?留??뚯뒪?멸? ?ㅽ뙣??寃쎌슦?먮룄 而ㅻ쾭由ъ? ?섏쭛 媛??        b_data = b_res.get("data", {})
        build_ok = b_data.get("build_ok", b_res.get("ok", False))
        tests_ok = b_data.get("tests_ok", True)  # 湲곕낯媛믪? True (?뚯뒪?멸? ?놁쓣 ?섎룄 ?덉쓬)
        
        if fast_fail and (not agent_enabled_effective) and (not build_ok):
            # 鍮뚮뱶 ?먯껜媛 ?ㅽ뙣??寃쎌슦?먮쭔 ?꾩냽 ?④퀎 ?⑥텞
            do_coverage = False
            do_fuzz = False
            do_qemu = False
            do_docs = False
            enable_domain_tests = False

        # Coverage report + threshold 怨꾩궛
        # 鍮뚮뱶媛 ?깃났?덉쑝硫??뚯뒪???ㅽ뙣 ?щ?? 愿怨꾩뾾??而ㅻ쾭由ъ? 由ы룷???앹꽦 ?쒕룄
        if do_coverage and build_ok:
            build_dir_path = Path(b_data.get("build_dir", ""))
            cov_res: Dict[str, Any] = {"ok": False, "reason": "not_run"}
            if not build_dir_path or not build_dir_path.exists():
                common.log_msg(log_callback, f"?좑툘 [Step 4] Coverage skipped: build_dir not found or invalid: {build_dir_path}")
                coverage_summary["enabled"] = True
                coverage_summary["ok"] = False
                coverage_summary["reason"] = "build_dir_invalid"
                cov_res = {"ok": False, "reason": "build_dir_invalid"}
            else:
                if not tests_ok:
                    common.log_msg(log_callback, f"?좑툘 [Step 4] Tests failed, but generating coverage report anyway (build succeeded)")
                common.log_msg(log_callback, f"?뱢 [Step 4] Generating Coverage Report (gcovr)...")
                common.log_msg(log_callback, f"   Build directory: {build_dir_path}")
                
                # CMake ?ㅼ젙 ?뺤씤
                cmake_cache = build_dir_path / "CMakeCache.txt"
                if cmake_cache.exists():
                    try:
                        cache_content = cmake_cache.read_text(encoding="utf-8", errors="ignore")
                        if "DEVOPS_COVERAGE:BOOL=ON" in cache_content:
                            common.log_msg(log_callback, f"   ??CMake configuration: DEVOPS_COVERAGE=ON")
                        elif "DEVOPS_COVERAGE:BOOL=OFF" in cache_content:
                            common.log_msg(log_callback, f"   ?좑툘 CMake configuration: DEVOPS_COVERAGE=OFF (coverage disabled in CMake)")
                        else:
                            common.log_msg(log_callback, f"   ?좑툘 CMake configuration: DEVOPS_COVERAGE not found in CMakeCache.txt")
                    except Exception as e:
                        common.log_msg(log_callback, f"   ?좑툘 Could not read CMakeCache.txt: {e}")
                else:
                    common.log_msg(log_callback, f"   ?좑툘 CMakeCache.txt not found (CMake may not have been configured)")
                
                try:
                    cov_res = tools.generate_coverage_report(
                        proj, reports, build_dir_path
                    )
                    # .gcda ?뚯씪 寃??寃곌낵 濡쒓퉭
                    if cov_res.get("reason") == "no_gcda":
                        gcda_files = cov_res.get("gcda_files", [])
                        if gcda_files:
                            common.log_msg(log_callback, f"   Found {len(gcda_files)} .gcda files")
                        else:
                            common.log_msg(log_callback, f"   ?좑툘 No .gcda files found in build directory")
                            build_log = b_data.get("log", "")
                            if "No tests were found" in build_log or "No tests discovered" in build_log:
                                common.log_msg(log_callback, f"   CTest found no tests. Ensure add_subdirectory(reports/auto_generated) in CMakeLists and valid test_*.c exist.")
                            common.log_msg(log_callback, f"   Possible causes:")
                            common.log_msg(log_callback, f"     - Tests were not executed (check CTest output, 'No tests were found')")
                            common.log_msg(log_callback, f"     - Coverage flags were not set correctly in CMake (apply CMakeLists.txt.fixed)")
                            common.log_msg(log_callback, f"     - Compiler flags (-fprofile-arcs -ftest-coverage) not applied")
                    elif cov_res.get("reason") == "gcovr_not_found":
                        common.log_msg(log_callback, f"   ??gcovr not found. Please install: pip install gcovr")
                    elif cov_res.get("ok"):
                        gcda_count = len(cov_res.get("gcda_files", []))
                        common.log_msg(log_callback, f"   ??Coverage report generated successfully ({gcda_count} .gcda files processed)")
                except Exception as e:
                    cov_res = {"ok": False, "reason": "coverage_exception", "error": str(e)}
                    common.log_msg(log_callback, f"   ??Coverage report generation failed: {e}")

            coverage_summary["enabled"] = True
            coverage_summary["ok"] = cov_res.get("ok", False)
            coverage_summary["xml"] = cov_res.get("xml")
            coverage_summary["html"] = cov_res.get("html")
            coverage_summary["reason"] = cov_res.get("reason")
            coverage_summary["error"] = cov_res.get("error")

            cov_threshold = getattr(config, "DEFAULT_COVERAGE_THRESHOLD", 0.0)
            env_thr = os.environ.get("COVERAGE_THRESHOLD")
            if env_thr is not None:
                try:
                    cov_threshold = float(env_thr)
                except ValueError:
                    pass
            elif tests_summary.get("mode") == "stub":
                # Stub-only tests often don't exercise code paths; avoid failing the pipeline on coverage.
                cov_threshold = 0.0
                common.log_msg(
                    log_callback,
                    "?뱄툘 Stub-only tests detected ??coverage threshold disabled for this run.",
                )
            coverage_summary["threshold"] = cov_threshold or 0.0

            if cov_res.get("ok") and cov_res.get("xml"):
                try:
                    tree = ET.parse(cov_res["xml"])
                    root = tree.getroot()
                    line_rate_attr = root.attrib.get("line-rate")
                    if line_rate_attr is not None:
                        line_rate = float(line_rate_attr)
                        coverage_summary["line_rate"] = line_rate
                        coverage_summary["line_rate_pct"] = line_rate * 100.0
                        if cov_threshold and line_rate < cov_threshold:
                            coverage_summary["below_threshold"] = True

                    branch_rate_attr = root.attrib.get("branch-rate")
                    if branch_rate_attr is not None:
                        branch_rate = float(branch_rate_attr)
                        coverage_summary["branch_rate"] = branch_rate
                        coverage_summary["branch_rate_pct"] = branch_rate * 100.0

                    func_covered = 0
                    func_total = 0
                    for pkg in root.findall(".//package"):
                        for cls in pkg.findall(".//class"):
                            for method in cls.findall("methods/method"):
                                func_total += 1
                                lines = method.findall("lines/line")
                                if any(int(l.attrib.get("hits", "0")) > 0 for l in lines):
                                    func_covered += 1
                    if func_total > 0:
                        func_rate = func_covered / func_total
                        coverage_summary["function_rate"] = func_rate
                        coverage_summary["function_rate_pct"] = func_rate * 100.0
                        coverage_summary["functions_covered"] = func_covered
                        coverage_summary["functions_total"] = func_total
                except Exception as e:
                    coverage_summary["parse_error"] = str(e)

    # 5. [Step 5] AI Fuzzing
    fuzz_res: Dict[str, Any] = {"enabled": False, "ok": True, "results": [], "reason": "skipped"}
    if do_fuzz and cfg:
        runtime_targets = _pick_runtime_targets(targets, all_targets)
        if not runtime_targets:
            fuzz_res = {"enabled": True, "ok": True, "results": [], "reason": "no_targets"}
        elif not _has_libfuzzer_runtime():
            # LibFuzzer??clang ?꾩슜?대?濡? gcc瑜??ъ슜?섎뒗 寃쎌슦 ?뺤긽?곸쑝濡?嫄대꼫?
            # ASan? gcc?먯꽌???묐룞?섎?濡?蹂꾨룄 臾몄젣 ?놁쓬
            if fuzz_strict:
                common.log_msg(
                    log_callback,
                    "??LibFuzzer clang runtime missing ??fuzzing requested but cannot run (strict mode).\n"
                    "   Note: LibFuzzer requires clang. ASan works with both gcc and clang.\n"
                    "   (clang / llvm / compiler-rt ?⑦궎吏 ?ㅼ튂 ?щ? ?먭? ?꾩슂)",
                )
                fuzz_res = {"enabled": True, "ok": False, "results": [], "reason": "libfuzzer_runtime_missing"}
            else:
                common.log_msg(
                    log_callback,
                    "?좑툘 LibFuzzer clang runtime missing ??skipping fuzzing step.\n"
                    "   Note: LibFuzzer requires clang. ASan works with both gcc and clang.\n"
                    "   (Fuzzing???ъ슜?섎젮硫?clang ?ㅼ튂 ?꾩슂, ASan? gcc?먯꽌???뺤긽 ?묐룞)",
                )
                fuzz_res = {"enabled": True, "ok": True, "results": [], "reason": "libfuzzer_runtime_missing"}
        else:
            common.log_msg(log_callback, "?뮗 [Step 5] Running AI Fuzzing...")

            fuzz_inc_paths = (
                inc_paths
                + tools.get_arch_include_paths(target_arch, str(proj))
                + [str(proj / "libs"), str(proj)]
            )

            def _fuzz_deps(target: Path) -> List[Path]:
                """Resolve source dependencies for fuzz compilation."""
                libs_dir = proj / "libs"
                dep_map = {
                    "gateway_logic": ["shared_data.c", "e2e.c"],
                    "lin_master": ["lin_protocol.c", "shared_data.c", "gateway_logic.c", "e2e.c"],
                    "lin_slave": ["lin_protocol.c", "shared_data.c"],
                    "rotary_switch": ["shared_data.c"],
                }
                deps: List[Path] = []
                stem = target.stem.lower()
                for key, files in dep_map.items():
                    if key in stem:
                        for f in files:
                            p = libs_dir / f
                            if p.exists() and p != target:
                                deps.append(p)
                return deps

            fuzz_default = getattr(config, "FUZZ_DEFAULT_DURATION", 10)
            fuzz_focus = getattr(
                config,
                "FUZZ_FOCUS_DURATION",
                max(fuzz_default, 30),
            )
            fuzz_keywords: List[str] = getattr(
                config,
                "FUZZ_FOCUS_KEYWORDS",
                ["e2e", "gateway", "protocol", "parser"],
            )
            max_focus = getattr(config, "FUZZ_MAX_FOCUS_TARGETS", 3)
            max_total = getattr(config, "FUZZ_MAX_TOTAL_TARGETS", len(runtime_targets))

            focus_candidates = [
                t for t in runtime_targets if any(k in t.name.lower() for k in fuzz_keywords)
            ]
            focus_targets = focus_candidates[:max_focus]

            remaining = [t for t in runtime_targets if t not in focus_targets]
            other_budget = max(0, max_total - len(focus_targets))
            other_targets = remaining[:other_budget]

            work_dir = reports / "fuzz"
            tools.ensure_dir(work_dir)

            total = len(focus_targets) + len(other_targets)
            idx = 0

            for t in focus_targets:
                if progress_callback:
                    progress_callback(idx, total, f"Fuzzing (focus) {t.name}")
                try:
                    harness = work_dir / f"fuzz_{t.stem}_harness.c"
                    _write_fuzz_harness(harness, t)
                    
                    stubs_dir = (proj / stubs_root).resolve() if stubs_root else (proj / "tests" / "stubs").resolve()
                    incs = [str(stubs_dir)] + [
                        str(Path(p).resolve())
                        for p in fuzz_inc_paths
                        if str(p).strip() and str(Path(p).resolve()) != str(stubs_dir)
                    ]
                    
                    dep_sources = _fuzz_deps(t)
                    res = tools.run_libfuzzer(
                        harness_path=harness,
                        source_files=[t] + dep_sources,
                        include_dirs=incs,
                        work_dir=work_dir,
                        duration_sec=fuzz_focus,
                        artifact_prefix=f"fuzz_{t.stem}",
                    )
                except Exception as e:
                    res = {"ok": False, "crash_found": False, "error": str(e)}

                res.update({"target": t.name, "focus": True, "duration": fuzz_focus})
                fuzz_res["results"].append(res)
                status = "ERROR" if not res.get("ok", True) else ("CRASH" if res.get("crash_found") else "PASS")
                common.log_msg(
                    log_callback,
                    f"   - Fuzz (focus) {t.name} [{fuzz_focus}s]: {status}",
                )
                idx += 1

            for t in other_targets:
                if progress_callback:
                    progress_callback(idx, total, f"Fuzzing {t.name}")
                try:
                    harness = work_dir / f"fuzz_{t.stem}_harness.c"
                    _write_fuzz_harness(harness, t)
                    
                    stubs_dir = (proj / stubs_root).resolve() if stubs_root else (proj / "tests" / "stubs").resolve()
                    incs = [str(stubs_dir)] + [
                        str(Path(p).resolve())
                        for p in fuzz_inc_paths
                        if str(p).strip() and str(Path(p).resolve()) != str(stubs_dir)
                    ]
                    
                    dep_sources = _fuzz_deps(t)
                    res = tools.run_libfuzzer(
                        harness_path=harness,
                        source_files=[t] + dep_sources,
                        include_dirs=incs,
                        work_dir=work_dir,
                        duration_sec=fuzz_default,
                        artifact_prefix=f"fuzz_{t.stem}",
                    )
                except Exception as e:
                    res = {"ok": False, "crash_found": False, "error": str(e)}

                res.update({"target": t.name, "focus": False, "duration": fuzz_default})
                fuzz_res["results"].append(res)
                status = "ERROR" if not res.get("ok", True) else ("CRASH" if res.get("crash_found") else "PASS")
                common.log_msg(
                    log_callback,
                    f"   - Fuzz {t.name} [{fuzz_default}s]: {status}",
                )
                idx += 1

            fuzz_res["enabled"] = True
            fuzz_res["reason"] = "completed"
            fuzz_res["focus_keywords"] = fuzz_keywords
            fuzz_res["focus_count"] = len(focus_targets)

            # overall fuzz status
            fuzz_ok = True
            for r in fuzz_res.get("results", []):
                if not r.get("ok", True) or r.get("crash_found"):
                    fuzz_ok = False
                    break
            fuzz_res["ok"] = fuzz_ok

    # 6. [Step 6] QEMU Smoke / Sanity Test
    qemu_res: Dict[str, Any] = {"enabled": False, "ok": False, "reason": "skipped"}
    if do_qemu:
        common.log_msg(log_callback, "?뼢截?[Step 6] Running QEMU Smoke Test...")
        qemu_env = tools.check_qemu_env(target_arch)
        if not qemu_env.get("ok"):
            common.log_msg(log_callback, "   - QEMU not found in PATH.")
            qemu_res = {
                "enabled": True,
                "ok": False,
                "effective_ok": False,
                "reason": "qemu_not_found",
                "env": qemu_env,
            }
            if qemu_strict:
                common.log_msg(log_callback, "   - QEMU strict mode: FAIL")
            else:
                common.log_msg(log_callback, "   - QEMU strict mode: WARN (skipped)")
        else:
            common.log_msg(
                log_callback,
                f"   - QEMU: {qemu_env.get('qemu_path')} 쨌 machine={qemu_env.get('selected')} 쨌 machines={len(qemu_env.get('machines') or [])}",
            )
            if qemu_env.get("recommended") and qemu_env.get("recommended") != qemu_env.get("selected"):
                common.log_msg(
                    log_callback,
                    f"   - QEMU 異붿쿇 癒몄떊: {qemu_env.get('recommended')} (reason={qemu_env.get('recommend_reason')})",
                )
            elif qemu_env.get("recommend_reason") == "rp2040_no_qemu_machine":
                common.log_msg(
                    log_callback,
                    "   - RP2040 怨꾩뿴? QEMU 吏?먯씠 ?쒗븳?곸엯?덈떎. ?꾩슂 ??QEMU瑜??꾧굅???ㅻⅨ 蹂대뱶 癒몄떊??吏?뺥븯?몄슂.",
                )

        if qemu_env.get("ok"):
            build_dir = None
            if b_res.get("ok") and b_res.get("data", {}).get("build_dir"):
                try:
                    build_dir = Path(b_res["data"]["build_dir"])
                except Exception:
                    build_dir = None

            elf = _resolve_qemu_elf(proj, build_dir, target_arch)
            is_rp2040_project = ("rp2040" in target_arch.lower()) or ("cortex-m0plus" in target_arch.lower())
            if is_rp2040_project and qemu_env.get("recommend_reason") == "rp2040_no_qemu_machine":
                common.log_msg(log_callback, "       - RP2040 target detected but installed QEMU has no compatible board model.")
                common.log_msg(log_callback, "       - Skipping incompatible fallback machine execution for this target.")
                qemu_res = {
                    "enabled": True,
                    "ok": False,
                    "effective_ok": True,
                    "reason": "rp2040_no_supported_qemu_machine",
                    "soft_fail": True,
                    "message": "RP2040 target detected but installed QEMU machine list has no compatible board model.",
                }
            elif elf:
                common.log_msg(log_callback, f"       ??Found ARM ELF: {elf.name} (arch={_check_elf_arch(elf)})")
                qemu_res = tools.run_qemu_smoke_test(
                    elf,
                    artifact_dir=reports / "qemu",
                    artifact_prefix="qemu_smoke",
                )
                qemu_res["enabled"] = True
                qemu_res["effective_ok"] = qemu_res.get("ok", True)
            elif is_rp2040_project:
                common.log_msg(log_callback, "       ??RP2040/Cortex-M0+ ?꾨줈?앺듃: Host 鍮뚮뱶(x86)留?議댁옱?섏뿬 QEMU ARM ?먮??덉씠??遺덇?.")
                common.log_msg(log_callback, "       ??ARM ?щ줈??而댄뙆?쇰윭(arm-none-eabi-gcc)濡?鍮뚮뱶??ELF媛 ?꾩슂?⑸땲??")
                common.log_msg(log_callback, "       ??QEMU??RP2040 癒몄떊 ??낆씠 ?놁뼱 蹂꾨룄 蹂대뱶 ?먮??덉씠???꾩슂.")
                qemu_res = {
                    "enabled": True, "ok": False, "effective_ok": True,
                    "reason": "rp2040_host_build_only",
                    "soft_fail": True,
                    "message": "RP2040 project: only host-built x86 binaries found, no ARM ELF available for QEMU",
                }
            else:
                common.log_msg(log_callback, "       ??No ARM ELF found in build output (only x86 binaries exist).")
                qemu_res = {"enabled": True, "ok": False, "effective_ok": False, "reason": "no_arm_elf_in_build"}

            log_text = qemu_res.get("log", "") or ""
            patterns: List[str] = getattr(
                config,
                "QEMU_LOG_ERROR_PATTERNS",
                ["HardFault", "ASSERT", "panic", "Segmentation fault"],
            )
            
            if log_text and any(p in log_text for p in patterns):
                qemu_res["ok"] = False
                qemu_res["reason"] = "runtime_error_pattern_in_log"
                qemu_res["effective_ok"] = False

            soft_fail = bool(
                is_rp2040_project
                and qemu_res.get("reason") in (
                    "runtime_error_pattern_in_log",
                    "rp2040_host_build_only",
                    "timeout",
                    "non_zero_exit",
                    "crash",
                )
            )
            if is_rp2040_project and not qemu_res.get("ok"):
                soft_fail = True
            if soft_fail:
                qemu_res["effective_ok"] = True
                qemu_res["soft_fail"] = True

            if not qemu_res.get("ok"):
                if soft_fail:
                    status = "WARN (RP2040 Soft-Fail)"
                    common.log_msg(log_callback, f"   ?좑툘 QEMU {status}")
                else:
                    status = "FAIL"
                    common.log_msg(log_callback, f"   - QEMU Emulation: {status}")
            else:
                status = "PASS"
                common.log_msg(log_callback, f"   - QEMU Emulation: {status}")
        else:
            common.log_msg(log_callback, "   - No ELF file found for QEMU.")
            qemu_res = {"enabled": True, "ok": False, "effective_ok": False, "reason": "no_elf"}

    if not do_qemu:
        common.log_msg(log_callback, "?뼢截?[Step 6] QEMU Smoke Test skipped (do_qemu=False).")

    # 7. [Step 7] Documentation
    docs_res: Dict[str, Any] = {"enabled": False, "ok": False, "reason": "skipped"}
    if do_docs:
        common.log_msg(
            log_callback,
            "?뱴 [Step 7] Generating Documentation (Doxygen)...",
        )
        try:
            docs_result = tools.run_doxygen(proj, reports / "docs")
            if docs_result.get("ok"):
                docs_res.update({"enabled": True, "ok": True, "reason": "completed"})
                common.log_msg(log_callback, f"   ??Documentation generated: {reports / 'docs'}")
            else:
                reason = docs_result.get("reason", "unknown")
                error_msg = docs_result.get("message") or docs_result.get("error") or str(reason)
                docs_res.update({"enabled": True, "ok": False, "reason": reason, "error": error_msg})
                if reason == "doxyfile_not_found":
                    common.log_msg(log_callback, f"   ?좑툘 Doxyfile not found. Creating default configuration...")
                elif reason == "doxygen_not_found":
                    common.log_msg(log_callback, f"   ?좑툘 Doxygen not found: {error_msg}")
                else:
                    common.log_msg(log_callback, f"   ?좑툘 Doxygen failed: {error_msg}")
        except Exception as e:
            docs_res.update({"enabled": True, "ok": False, "reason": f"doxygen_failed: {e}"})
            common.log_msg(log_callback, f"   ?좑툘 Doxygen failed: {e}")
    else:
        common.log_msg(log_callback, "?뱴 [Step 7] Documentation skipped (do_docs=False).")
        docs_res["reason"] = "disabled"

    # 8. [Step 8] Syntax Check
    syn_res = common.standardize_result(True, "skipped")
    if do_syntax_check and targets:
        common.log_msg(log_callback, "?뵇 [Step 8] Running Syntax Check...")
        _check_stop()
        syn_res = static.run_gcc_syntax(
            proj,
            reports,
            targets,
            syn_incs,
            syn_defs,
            progress_callback,
            target_arch,
        )
        # [NEW] Enhanced failure logging
        if not syn_res.get("ok"):
            common.log_msg(log_callback, "   ??Syntax Check Failed on specific files:")
            for r in syn_res.get("data", {}).get("results", []):
                if not r.get("ok"):
                    # 泥?以꾨쭔 ?섎씪??蹂댁뿬二쇨린
                    err_preview = (r.get("stderr", "") or "").strip().split("\n")[0][:100]
                    common.log_msg(log_callback, f"      - {r.get('file')}: {err_preview}")

    # 9. [Step 9] Static Analysis (Cppcheck)
    cpp_res = common.standardize_result(True, "skipped")
    if targets:
        common.log_msg(log_callback, "?뵊 [Step 9] Running Cppcheck...")
        cpp_res = static.run_cppcheck(
            proj,
            reports,
            targets,
            cppcheck_enable,
            inc_paths,
            suppressions_path,
            progress_callback,
            target_arch,
            all_defines,
        )

    # 9.5 [Step 9.5] Semgrep (optional)
    semgrep_res = common.standardize_result(True, "skipped")
    if enable_semgrep and targets:
        common.log_msg(log_callback, "?㎥ [Step 9.5] Running Semgrep...")
        semgrep_res = static.run_semgrep(
            proj,
            reports,
            targets,
            semgrep_config or "p/default",
            progress_callback,
        )

    # 10. [Step 10] Clang-Tidy
    tidy_res = common.standardize_result(True, "skipped")
    if do_clang_tidy and targets and b_res.get("ok"):
        common.log_msg(log_callback, "?㏏ [Step 10] Running Clang-Tidy...")
        tidy_res = static.run_clang_tidy(
            proj,
            targets,
            clang_tidy_checks or [],
            Path(b_res["data"]["build_dir"]),
            progress_callback,
        )

    # 11. [Step 11] Domain Test Panel
    def _infer_domain_targets_by_changes(changed: List[Path]) -> List[str]:
        if not changed:
            return []
        keywords = [str(k).lower() for k in getattr(config, "DOMAIN_TESTS_KEYWORDS", [])]
        exts = {str(e).lower() for e in getattr(config, "DOMAIN_TESTS_EXTS", [])}
        results: List[str] = []
        for p in changed:
            try:
                rel = p.relative_to(proj)
            except Exception:
                rel = p
            rel_str = str(rel)
            if exts and Path(rel_str).suffix.lower() not in exts:
                continue
            if keywords and not any(k in rel_str.lower() for k in keywords):
                continue
            if rel_str not in results:
                results.append(rel_str)
        return results

    auto_domain_targets = _infer_domain_targets_by_changes(changed_files) if domain_tests_auto else []
    enable_domain_tests_effective = bool(enable_domain_tests or (domain_tests_auto and auto_domain_targets))

    domain_tests_summary: Dict[str, Any] = {
        "enabled": False,
        "tests": [],
        "errors": [],
        "reason": "skipped",
        "auto": bool(domain_tests_auto),
        "auto_enabled": bool(not enable_domain_tests and enable_domain_tests_effective),
        "auto_targets": auto_domain_targets,
    }
    if enable_domain_tests_effective and cfg:
        common.log_msg(
            log_callback,
            "?㎦ [Step 11] Running Domain Test Panel...",
        )

        if domain_targets:
            dt_targets: List[str] = domain_targets
        elif auto_domain_targets:
            dt_targets = auto_domain_targets
        else:
            dt_targets = []
            source_targets = _pick_runtime_targets(targets, all_targets)

            for t in source_targets:
                name = t.name.lower()
                if any(key in name for key in ("e2e", "gateway", "protocol", "lin")):
                    try:
                        rel = t.relative_to(proj)
                        dt_targets.append(str(rel))
                    except ValueError:
                        dt_targets.append(str(t))

        if dt_targets:
            dt_cfg = DomainTestConfig(
                language="c",
                test_framework="assert",
                max_scenarios_per_file=8,
            )

            logs_dir = reports / "agent_logs" / "domain_tests"

            def _llm(messages: List[Dict[str, str]]) -> str:
                reply = ai.agent_call_text(
                    cfg,
                    messages,
                    logs_dir,
                    role="generator",
                    stage="domain_tests",
                    rag_kb=kb,
                    rag_query=(messages[-1].get("content", "") if messages else ""),
                    settings=agent_settings,
                )
                return reply or ""

            domain_res = run_domain_test_panel(
                project_root=proj,
                targets=dt_targets,
                llm_call=_llm,
                config=dt_cfg,
                output_dir=proj / "tests" / "domain",
                domain_notes=(
                    "Embedded C project. If this is an automotive LIN gateway, "
                    "focus on E2E counters, CRC, invalid frames, and timeout behavior."
                ),
            )
            domain_tests_summary = {**domain_res, "enabled": True, "reason": "completed"}
        else:
            common.log_msg(
                log_callback,
                "?뱄툘 Domain Test Panel: no matching targets, skipped.",
            )
            domain_tests_summary["reason"] = "no_matching_targets"

    elif enable_domain_tests_effective and not cfg:
        common.log_msg(
            log_callback,
            "?㎦ [Step 11] Domain Test Panel skipped (missing LLM config).",
        )
        domain_tests_summary["reason"] = "missing_llm_config"
    else:
        common.log_msg(
            log_callback,
            "?㎦ [Step 11] Domain Test Panel skipped (disabled or no matching changes).",
        )
        domain_tests_summary["reason"] = "disabled"

    # 12. [Step 12] AI Agent Loop
    def _normalize_fix_scope(scope: Optional[List[str]]) -> set[str]:
        if scope is None:
            scope = getattr(config, "AUTO_FIX_SCOPE_DEFAULT", ["static", "syntax", "build", "tests"])
        if isinstance(scope, str):
            scope = [s.strip() for s in scope.replace("\n", ",").split(",") if s.strip()]
        scopes = {str(s).strip().lower() for s in (scope or []) if str(s).strip()}
        if "all" in scopes:
            return {"static", "syntax", "build", "tests"}
        return scopes

    fix_scope = _normalize_fix_scope(auto_fix_scope)
    fix_kind = None
    if b_res.get("ok") is False and b_res.get("reason") != "skipped":
        b_reason = str(b_res.get("reason") or "")
        b_data = b_res.get("data", {}) if isinstance(b_res.get("data"), dict) else {}
        if b_reason == "test_fail" or (b_data.get("build_ok") and not b_data.get("tests_ok", True)):
            fix_kind = "tests"
        else:
            fix_kind = "build"
    elif syn_res and not syn_res.get("ok"):
        fix_kind = "syntax"
    else:
        static_issue_count = (
            len(cpp_res.get("data", {}).get("issues", []))
            + len(tidy_res.get("data", {}).get("issues", []))
            + len(semgrep_res.get("data", {}).get("issues", []))
        )
        if static_issue_count > 0:
            fix_kind = "static"
    agent_res: Dict[str, Any] = {
        "iterations": 0,
        "applied_changes": [],
        "stop_reason": "none",
        "history": [],
        "patch_mode": effective_patch_mode,
        "patch_files": [],
    }

    if agent_only_on_failure and not fix_kind:
        agent_res["stop_reason"] = "no_failure"
        common.log_msg(
            log_callback,
            "?쨼 [Step 12] Agent loop skipped (no build/test/syntax failure).",
        )
    elif agent_only_on_failure and fix_kind and allowed_fail_stages and fix_kind not in allowed_fail_stages:
        agent_res["stop_reason"] = "failure_stage_excluded"
        common.log_msg(
            log_callback,
            f"?쨼 [Step 12] Agent loop skipped (stage excluded: {fix_kind}).",
        )

    def _dedup_static_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set = set()
        out: List[Dict[str, Any]] = []
        for it in issues:
            key = (
                str(it.get("file", "")),
                int(it.get("line", 0)),
                str(it.get("message", ""))[:120],
            )
            if key not in seen:
                seen.add(key)
                out.append(it)
        return out

    def _build_rag_context_from_issues(items: List[Dict[str, Any]], limit: int = 6) -> str:
        lines: List[str] = []
        for it in items[:limit]:
            tool = str(it.get("tool") or it.get("id") or "").strip()
            file = str(it.get("file") or "").strip()
            msg = str(it.get("message") or it.get("stderr") or "").strip()
            if msg:
                msg = msg.replace("\n", " ").strip()
            line = " :: ".join([x for x in [tool, file, msg] if x])
            if line:
                lines.append(line)
        return "\n".join(lines).strip()

    def _build_rag_tags(items: List[Dict[str, Any]], fix_mode: str) -> List[str]:
        tags = [fix_mode]
        for it in items[:10]:
            tool = str(it.get("tool") or it.get("id") or "").strip().lower()
            if tool:
                tags.append(tool)
        # dedup ?좎?
        out: List[str] = []
        seen = set()
        for t in tags:
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out

    if (
        agent_enabled_effective
        and cfg
        and effective_patch_mode != "off"
        and (targets or not b_res.get("ok"))
        and not (agent_only_on_failure and not fix_kind)
        and not (agent_only_on_failure and fix_kind and allowed_fail_stages and fix_kind not in allowed_fail_stages)
    ):
        if fix_kind and fix_scope and (fix_kind not in fix_scope):
            agent_res["stop_reason"] = "scope_excluded"
            common.log_msg(
                log_callback,
                f"?쨼 [Step 12] Agent loop skipped (scope excludes {fix_kind}).",
            )
        else:
            common.log_msg(
                log_callback,
                "?쨼 [Step 12] Starting AI Self-Healing Loop...",
            )

            prev_issue_sig: Optional[str] = None
            for i in range(max_iterations):
                _check_stop()
                current_iter = i + 1
                issues: List[Dict[str, Any]] = []
                fix_mode = "static"
                prompt = ""
                error_context_for_rag = ""
                rag_tags: List[str] = []

                if b_res["reason"] != "skipped" and not b_res.get("ok"):
                    b_reason = str(b_res.get("reason") or "")
                    b_data = b_res.get("data", {}) if isinstance(b_res.get("data"), dict) else {}
                    if b_reason == "test_fail" or (b_data.get("build_ok") and not b_data.get("tests_ok", True)):
                        fix_mode = "tests_fix"
                    else:
                        fix_mode = "build_fix"
                    ctx = _build_ai_context_for_build_failure(proj, b_res, max_chars=ai_log_max_chars)
                    error_context_for_rag = ctx.get("rag_key", "")

                    issues = [{"file": "BUILD_LOG", "line": 0, "message": "Build/Test Failed", "id": "build_error"}]
                    prompt = (
                        "Build/Test failed. Use the context below to fix the root cause.\n"
                        "If unit tests failed, prioritize fixing production code first (libs/).\n"
                        "If host build is missing headers, prefer adding/adjusting stubs under tests/stubs or guarding includes properly.\n\n"
                        f"Build Context:\n{ctx.get('context', '')}\n"
                    )
                elif syn_res and not syn_res.get("ok"):
                    fix_mode = "syntax_fix"
                    fails = [r for r in syn_res["data"]["results"] if not r.get("ok", True)]
                    if fails:
                        error_context_for_rag = _build_rag_context_from_issues(
                            [{"file": r.get("file"), "stderr": r.get("stderr", "")} for r in fails],
                            limit=5,
                        )
                        issues = [{"file": r["file"], "line": 0, "message": r.get("stderr", "")} for r in fails]

                else:
                    cpp_issues = cpp_res.get("data", {}).get("issues", [])
                    tidy_issues = tidy_res.get("data", {}).get("issues", [])
                    sem_issues = semgrep_res.get("data", {}).get("issues", [])
                    issues = _dedup_static_issues(cpp_issues + tidy_issues + sem_issues)
                    if issues:
                        error_context_for_rag = _build_rag_context_from_issues(issues, limit=6)
                if issues and not error_context_for_rag:
                    error_context_for_rag = _build_rag_context_from_issues(issues, limit=3)
                if issues and not rag_tags:
                    rag_tags = _build_rag_tags(issues, fix_mode)

                if not issues:
                    agent_res["stop_reason"] = "clean"
                    common.log_msg(log_callback, "?럦 Code is clean! No issues to fix.")
                    break

                issue_sig = json.dumps(sorted(
                    (d.get("file", ""), d.get("line", 0), d.get("id", ""))
                    for d in issues
                ))
                if issue_sig == prev_issue_sig:
                    agent_res["stop_reason"] = "no_progress"
                    common.log_msg(log_callback, "?좑툘 Same issues detected as previous iteration ??stopping to avoid infinite loop.")
                    break
                prev_issue_sig = issue_sig

                common.log_msg(
                    log_callback,
                    f"   ??Iter {current_iter}: Fixing {len(issues)} issues [{fix_mode}]...",
                )

                roles_enabled = {str(r).lower() for r in (agent_settings.get("roles") or [])}

                past_solutions: List[Dict[str, Any]] = []
                rag_context = ""
                if agent_settings.get("rag_enabled"):
                    past_solutions = kb.search(
                        error_context_for_rag,
                        role="fixer",
                        stage=fix_mode,
                        tags=["fixer", fix_mode],
                    )
                    if past_solutions:
                        common.log_msg(
                            log_callback,
                            f"      ?뱴 Found {len(past_solutions)} RAG solutions!",
                        )
                        rag_context = "\n\n[?뱴 Knowledge Base - Past Successful Fixes]:\n"
                        for idx, sol in enumerate(past_solutions):
                            score = sol.get("score", 0.0)
                            rag_context += f"--- Example {idx + 1} (Score: {score:.2f}) ---\n"
                            rag_context += f"Error: {sol.get('error_clean', '')[:100]}...\n"
                            rag_context += "Fix Pattern:\n"
                            rag_context += f"{sol.get('fix', '')}\n"

                planner_notes = ""
                if "planner" in roles_enabled:
                    planner_prompt = (
                        "Create a short fix plan (bullets, max 6). "
                        "Focus on root cause and safest edits.\n\n"
                        f"Issues:\n{json.dumps(issues[:5], indent=2)}\n"
                    )
                    if prompt:
                        planner_prompt += f"\nContext:\n{prompt}\n"
                    planner_messages = [{"role": "user", "content": planner_prompt}]
                    planner_notes = ai.agent_call_text(
                        cfg,
                        planner_messages,
                        reports / "agent_logs",
                        role="planner",
                        stage=fix_mode,
                        task_id=f"planner_iter{current_iter}",
                        rag_kb=kb,
                        rag_query=error_context_for_rag,
                        settings=agent_settings,
                    ) or ""
                    if planner_notes:
                        prompt = f"{prompt}\n\nPlanner Notes:\n{planner_notes}\n"

                if fix_mode != "build_fix":
                    max_findings = getattr(config, "MAX_FINDINGS_FOR_PROMPT", 5)
                    top_issues = issues[:max_findings]
                    excerpts = {
                        item["file"]: common.read_excerpt(proj / item["file"])
                        for item in top_issues
                        if item.get("file")
                    }
                    prompt = (
                        "Fix these code issues:\n"
                        f"{json.dumps(top_issues, indent=2)}\n\n"
                        "Source Code Context:\n"
                        f"{json.dumps(excerpts, indent=2)}\n"
                    )

                full_prompt = (
                    f"{prompt}\n{rag_context}\n\n"
                    "Task: Output ONLY SEARCH/REPLACE blocks to fix these issues.\n"
                    "Format:\n"
                    "<<<<SEARCH_BLOCK[filename]...\n"
                    "<<<<REPLACE_BLOCK[filename]...\n\n"
                    "Do NOT include markdown, code fences, or explanations."
                )

                messages = [{"role": "user", "content": full_prompt}]

                def _validate_patch(reply_text: str) -> Tuple[bool, str]:
                    try:
                        blocks = ai._parse_search_replace_blocks(reply_text)
                        if blocks:
                            return True, ""
                        return False, "no_search_replace_blocks"
                    except Exception as e:
                        return False, f"parse_error: {e}"

                # P2.2: LLM ??? ?? ?? (???2?+ fallback + ?? ??)
                total_attempts = int(getattr(config, "AGENT_LLM_TOTAL_ATTEMPTS", 3))
                fallback_models = _csv_list(getattr(config, "AGENT_LLM_FALLBACK_MODELS", ""))
                fallback_cfg_paths = _csv_list(getattr(config, "AGENT_LLM_FALLBACK_CONFIGS", ""))
                llm_attempts: List[Dict[str, Any]] = []

                def _policy_call(
                    msgs: List[Dict[str, str]]
                ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
                    reply, attempts_meta = _llm_call_with_policy(
                        cfg_primary=cfg,
                        cfg_fallbacks=cfg_fallbacks,
                        messages=msgs,
                        log_dir=reports / "agent_logs",
                        total_attempts=total_attempts,
                        fallback_models=fallback_models,
                        fallback_config_paths=fallback_cfg_paths,
                        stage=fix_mode,
                    )
                    gemini_content = None
                    if isinstance(attempts_meta, list):
                        for ent in reversed(attempts_meta):
                            if isinstance(ent, dict) and "gemini_content" in ent:
                                gemini_content = ent.get("gemini_content")
                                break
                    if isinstance(attempts_meta, list):
                        for ent in attempts_meta:
                            if isinstance(ent, dict) and "gemini_content" in ent:
                                ent["gemini_content"] = True
                    llm_attempts[:] = attempts_meta or []
                    return reply, {"attempts": attempts_meta, "gemini_content": gemini_content}

                fixer_res = ai.agent_call(
                    cfg,
                    messages,
                    reports / "agent_logs",
                    role="fixer",
                    stage=fix_mode,
                    task_id=f"fixer_iter{current_iter}",
                    rag_kb=kb,
                    rag_query=error_context_for_rag,
                    settings=agent_settings,
                    validator=_validate_patch,
                    llm_call_fn=_policy_call,
                )
                reply = fixer_res.get("output")

                # Plan B: RAG ?? ???? LLM ????? RAG fix pattern?? ?? ??
                plan_b = None
                if not reply and past_solutions:
                    best = _pick_best_rag_solution(past_solutions)
                    max_blocks = int(getattr(config, "AGENT_RAG_PLANB_MAX_BLOCKS", 3))
                    plan_text = _extract_search_replace_blocks_text((best or {}).get("fix", ""), max_blocks)
                    if plan_text:
                        plan_b = {
                            "used": True,
                            "source": "rag",
                            "id": (best or {}).get("id"),
                            "score": (best or {}).get("score"),
                            "max_blocks": max_blocks,
                        }
                        reply = plan_text
                        common.log_msg(
                            log_callback, "?㎝ Plan B: Applying RAG-based rule patch (limited blocks)."
                        )

                agent_res.setdefault("history", []).append(
                    {
                        "iter": current_iter,
                        "fix_mode": fix_mode,
                        "issue_count": len(issues),
                        "planner": {"used": bool(planner_notes), "notes_preview": planner_notes[:500]},
                        "fixer": {
                            "final_ok": bool(reply),
                            "llm_attempts": llm_attempts,
                            "plan_b": plan_b,
                        },
                    }
                )

                if not reply:
                    agent_res["stop_reason"] = "no_llm_response"
                    common.log_msg(log_callback, "?좑툘 No response from AI (after retries/fallback).")
                    break

                if effective_patch_mode == "review":
                    patch_path = _save_agent_patch(
                        reports,
                        reply,
                        current_iter,
                        fix_mode,
                    )
                    agent_res["patch_files"].append(str(patch_path))
                    agent_res["iterations"] = current_iter
                    agent_res["stop_reason"] = "review_pending"
                    common.log_msg(
                        log_callback,
                        f"      ?뱷 Saved AI suggestions to {patch_path} (review mode, no code modified).",
                    )
                    break

                changes = ai.apply_search_replace(
                    proj,
                    reply,
                    reports / "agent_logs",
                )
                applied_patches = [c for c in changes if c.get("status") == "ok"]
                agent_res["applied_changes"].extend(applied_patches)
                agent_res["iterations"] = current_iter

                if not applied_patches:
                    agent_res["stop_reason"] = "patch_failed"
                    common.log_msg(
                        log_callback,
                        "?좑툘 AI suggested fixes could not be applied (Pattern mismatch).",
                    )
                    break

                for p in applied_patches:
                    common.log_msg(log_callback, f"      ??Patched: {p['file']}")

                success = False
                if fix_mode == "build_fix":
                    common.log_msg(
                        log_callback,
                        "      ?봽 Re-running Build to verify fix...",
                    )
                    b_res = build.build_and_tests(
                        proj,
                        reports,
                        do_coverage,
                        do_asan,
                        stability_gate=bool(getattr(config, "TEST_STABILITY_GATE", False)),
                    )
                    success = b_res.get("ok")

                elif fix_mode == "syntax_fix":
                    common.log_msg(
                        log_callback,
                        "      ?봽 Re-running Syntax Check...",
                    )
                    syn_res = static.run_gcc_syntax(
                        proj,
                        reports,
                        targets,
                        syn_incs,
                        syn_defs,
                        None,
                        target_arch,
                    )
                    success = syn_res.get("ok")

                else:
                    common.log_msg(
                        log_callback,
                        "      ?봽 Re-running Static Analysis...",
                    )
                    check_res = static.run_gcc_syntax(
                        proj,
                        reports,
                        targets,
                        syn_incs,
                        syn_defs,
                        None,
                        target_arch,
                    )
                    success = check_res.get("ok")
                    if success:
                        cpp_res = static.run_cppcheck(
                            proj,
                            reports,
                            targets,
                            cppcheck_enable,
                            inc_paths,
                            suppressions_path,
                            None,
                            target_arch,
                            all_defines,
                        )

                if success:
                    category = "general"
                    try:
                        cat_map = getattr(config, "RAG_CATEGORY_BY_STAGE", {})
                        if isinstance(cat_map, dict):
                            category = str(cat_map.get(fix_mode) or "general")
                    except Exception:
                        category = "general"
                    tags = rag_tags or [fix_mode]
                    if category and category not in tags:
                        tags = tags + [category]
                    kb.learn(
                        error_context_for_rag,
                        reply[:2000],
                        tags=tags,
                        role="fixer",
                        stage=fix_mode,
                        context=error_context_for_rag,
                        category=category,
                    project_root=str(proj),
                    )
                    common.log_msg(
                        log_callback,
                        "      ?쭬 Knowledge Base Updated: Solution learned!",
                    )
                else:
                    common.log_msg(
                        log_callback,
                        "      ??Fix did not resolve the issue fully.",
                    )

    elif enable_agent and effective_patch_mode == "off":
        agent_res["stop_reason"] = "patch_mode_off"
        common.log_msg(
            log_callback,
            "?쨼 Agent enabled but patch mode is 'off' ??skipping self-healing loop.",
        )

    else:
        if not enable_agent:
            agent_res["stop_reason"] = "agent_disabled"
            common.log_msg(
                log_callback,
                "?쨼 [Step 12] Agent loop skipped (enable_agent=False).",
            )
        elif not cfg:
            agent_res["stop_reason"] = "missing_llm_config"
            common.log_msg(
                log_callback,
                "?쨼 [Step 12] Agent loop skipped (missing LLM config).",
            )
        elif not (targets or not b_res.get("ok")):
            agent_res["stop_reason"] = "no_targets"
            common.log_msg(
                log_callback,
                "?쨼 [Step 12] Agent loop skipped (no targets and build OK).",
            )

    # 13. [Step 13] Report / Artifact Validation
    report_health = _validate_reports(coverage_summary, docs_res, tests_summary, reports)
    if report_health.get("missing"):
        common.log_msg(
            log_callback,
            f"?좑툘 [Step 13] Missing reports -> {', '.join(report_health.get('missing') or [])}",
        )
    elif report_health.get("warnings"):
        common.log_msg(
            log_callback,
            f"?뱄툘 [Step 13] Report warnings -> {', '.join(report_health.get('warnings') or [])}",
        )
    else:
        common.log_msg(log_callback, "??[Step 13] Reports OK")

    # 15. Final Summary & Exit Code
    exit_code = 0
    failure_stage = "none"

    static_issue_count = (
        len(cpp_res.get("data", {}).get("issues", []))
        + len(tidy_res.get("data", {}).get("issues", []))
        + len(semgrep_res.get("data", {}).get("issues", []))
    )

    coverage_below = (
        coverage_summary.get("enabled")
        and coverage_summary.get("below_threshold")
    )


    # strict gating for runtime steps (optional)
    fuzz_failed = bool(do_fuzz and fuzz_res.get("enabled") and (not fuzz_res.get("ok", True)) and bool(fuzz_strict))
    qemu_failed = bool(do_qemu and qemu_res.get("enabled") and (not qemu_res.get("effective_ok", qemu_res.get("ok", True))) and bool(qemu_strict))
    domain_failed = bool(
        enable_domain_tests
        and domain_tests_summary.get("enabled")
        and (not domain_tests_summary.get("ok", True))
        and bool(domain_tests_strict)
    )
    if not b_res.get("ok") and b_res["reason"] != "skipped":
        # Build ?④퀎 ?ㅽ뙣? Unit Test ?ㅽ뙣瑜?援щ텇
        b_reason = b_res.get("reason", "")
        b_data = b_res.get("data", {})
        if b_reason == "test_fail" or (b_data.get("build_ok") and not b_data.get("tests_ok", True)):
            exit_code = 2
            failure_stage = "unit_tests"
        else:
            exit_code = 2
            failure_stage = "build"
    elif not syn_res.get("ok"):
        exit_code = 3
        failure_stage = "syntax"
    elif static_issue_count > 0:
        if ignore_static_failure:
            exit_code = 0
            failure_stage = "static_issues_ignored"
        else:
            exit_code = 1
            failure_stage = "static_issues"
    elif coverage_below:
        exit_code = 1
        failure_stage = "coverage"

    elif static_issue_count == 0 and not coverage_below:
        if fuzz_failed:
            exit_code = 1
            failure_stage = "fuzz"
        elif qemu_failed:
            exit_code = 1
            failure_stage = "qemu"
        elif domain_failed:
            exit_code = 1
            failure_stage = "domain_tests"

    agent_runs: List[Dict[str, Any]] = []
    if isinstance(tests_summary, dict):
        ar = tests_summary.get("agent_runs")
        if isinstance(ar, list):
            agent_runs.extend(ar)

    summary: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "project_root": str(proj),
        "targets": [str(t) for t in targets],
        "preflight": preflight,
        "change_impact": change_impact,
        "static": {
            "cppcheck": cpp_res,
            "clang_tidy": tidy_res,
            "semgrep": semgrep_res,
        },
        "build": b_res,
        "syntax": syn_res,
        "agent": agent_res,
        "agent_config": agent_settings,
        "agent_runs": agent_runs,
        "tests": tests_summary,
        "fuzzing": fuzz_res,
        "qemu": qemu_res,
        "coverage": coverage_summary,
        "docs": docs_res,
        "domain_tests": domain_tests_summary,
        "report_health": report_health,
        "scm": {
            "mode": scm_used,
            "git_status": git_status,
            "svn_status": svn_status,
            "git_base_ref": used_base_ref,
            "svn_base_ref": used_svn_ref,
            "changed_files": len(changed_files),
            "changed_list": changed_list,
            "changed_items": norm_items,
            "changed_exts": sorted(list({Path(it.get("path") or "").suffix.lower() for it in norm_items if it.get("path")})),
        },
        "scm_change_report": scm_report_paths,
        "git": {
            "status": git_status,
            "changed_files": len(git_changed_list),
            "incremental": bool(not full_analysis),
            "branch": git_meta.get("branch"),
            "commit": git_meta.get("commit"),
            "dirty": git_meta.get("dirty"),
            "changed_sample": git_changed_samples,
            "changed_list": git_changed_list,
            "base_ref": used_base_ref,
            "author": git_meta.get("author"),
            "message": git_meta.get("message"),
        },
        "svn": {
            "status": svn_status,
            "url": svn_meta.get("url"),
            "revision": svn_meta.get("revision"),
            "author": svn_meta.get("author"),
            "date": svn_meta.get("date"),
            "dirty": svn_meta.get("dirty"),
            "changed_list": svn_changed_list,
            "base_ref": used_svn_ref,
        },
        "exit_code": exit_code,
        "failure_stage": failure_stage,
        "change_mode": change_mode,
        "engine_version": getattr(config, "ENGINE_VERSION", "unknown"),
        "quality_preset": preset,
        "auto_fix_scope": sorted(list(fix_scope)) if isinstance(fix_scope, set) else fix_scope,

        "strict": {
            "ci_env": ci_env,
            "fuzz_strict": bool(fuzz_strict),
            "qemu_strict": bool(qemu_strict),
            "domain_tests_strict": bool(domain_tests_strict),
        },
        "artifacts": {
            "summary_json": str(reports / "analysis_summary.json"),
            "summary_md": str(reports / "analysis_summary.md"),
            "findings_flat": str(reports / "findings_flat.json"),
            "pipeline_log": str(log_path),
        },
    }

    try:
        runtime_ingest = rag.ingest_runtime_summary(kb, summary, reports)
        summary["rag_runtime_ingest"] = runtime_ingest
    except Exception as e:
        summary["rag_runtime_ingest"] = {"ok": False, "error": str(e)}

    flat_issues = (
        cpp_res.get("data", {}).get("issues", [])
        + tidy_res.get("data", {}).get("issues", [])
        + semgrep_res.get("data", {}).get("issues", [])
    )
    summary["findings_total"] = len(flat_issues)

    sev_counts = {"error": 0, "warning": 0, "style": 0, "info": 0}
    for iss in flat_issues:
        s = str(iss.get("severity", "warning")).lower()
        if s in sev_counts:
            sev_counts[s] += 1
        else:
            sev_counts["warning"] += 1
    penalty = sev_counts["error"] * 15 + sev_counts["warning"] * 3
    if not b_res.get("ok"):
        penalty += 30
    if not syn_res.get("ok"):
        penalty += 20
    if not enable_test_gen:
        penalty += 5
    summary["risk_score"] = max(0, min(100, 100 - penalty))

    _write_json(reports / "analysis_summary.json", summary)
    _write_json(reports / "findings_flat.json", flat_issues)

    try:
        import report_generator
        report_generator.generate_markdown_summary(summary, str(reports / "analysis_summary.md"))
    except Exception as e:
        common.log_msg(log_callback, f"?좑툘 Failed to generate markdown summary: {e}")

    common.log_msg(log_callback, f"??Pipeline Finished. Exit Code: {exit_code}")
    return exit_code

