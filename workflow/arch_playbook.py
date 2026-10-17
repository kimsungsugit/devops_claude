"""개선 후보 → **실행 가능한 상세 개선안**(플레이북).

`arch_improvement.build_candidates`가 내는 후보는 "무엇을"까지만 말한다:

    split_god_file · Ap_DoorPreCtrl_PDS.c · "호출 이웃이 몰린 축을 기준으로 파일을 분할한다"

134개 함수를 **어느 선으로** 자르라는 건지가 없어 실행이 안 된다. 이 모듈은 파서가 이미
만들고 버리던 실측 재료(`arch.playbook_inputs`)를 써서 그 빈칸을 채운다:

    ① 순환 끊기   → 그 간선을 만드는 **실제 함수 호출 쌍**(Cpu_IllegalOpcode → Cpu_OnIllegalOpcode)
    ② 파일 분할   → 내부 콜 연결성분 / 이름 접두사 중 실용적인 **분할 축과 군집별 함수 목록**
    ③ 스텁 시임   → **실제 함수포인터 심볼**(pfn_SafetyCheck · s_uds_wdbi_did_tbl[].pf_Handler)

## 정직성 (이 모듈의 존재 이유이자 한계)

- **코드는 스케치다.** 파서는 함수 시그니처(반환형·인자)를 주지 않으므로 타입 자리는 주석
  플레이스홀더로 둔다. 그럴듯한 타입을 지어내면 복사해 쓴 사람이 컴파일 에러를 만난다.
- **분할 축이 없으면 만들지 않는다.** 실측 8개 god_file 중 6개는 최대 덩어리가 91~97%라
  기계적 분할선이 없었다. 그때는 "축 없음 + 왜"를 말한다 — 억지 군집은 근거 없는 지시다.
- **생성 코드는 손대라고 하지 않는다.** Generated_Code 경로는 리팩터링 대상이 아니라
  래핑 대상이다(생성기가 덮어쓴다).
- 재료가 없으면 `detail`을 통째로 생략한다. 빈 껍데기 절차는 정보가 아니라 소음이다.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PLAYBOOK_VERSION = 1

# 자동 생성 코드 — 리팩터링하면 다음 생성 때 사라진다. 경로 토큰으로만 판정(내용 추정 금지).
GENERATED_MARKERS = ("generated_code", "generated", "/gen/", "_gen/", "autosar", "rte_")

SKETCH_NOTE = "타입·인자는 파서가 주지 않아 주석으로 비워 둔 스케치다 — 그대로 컴파일되지 않는다."

# 파일명에서 걸러낼 헝가리안/스코프 접두사 — 이게 남으면 Sys_UDS_LinComp_PDS_s_UDS_WDBI.c 가 된다.
_NAME_NOISE = {"s", "g", "u8", "u16", "u32", "s8", "s16", "s32",
               "u8s", "u16s", "u32s", "s8s", "s16s", "s32s", "st", "b", "t"}
# 이보다 작은 덩어리는 별도 파일로 제안하지 않는다 — 함수 1개짜리 .c 는 분할이 아니라 소음이다.
MIN_SPLIT_GROUP = 3


def _is_generated(path: str) -> bool:
    p = str(path or "").replace("\\", "/").lower()
    return any(m in p for m in GENERATED_MARKERS)


def _basename(path: str) -> str:
    return os.path.basename(str(path or "").replace("\\", "/"))


def _stem(path: str) -> str:
    b = _basename(path)
    return b[:-2] if b.lower().endswith(".c") else b


def _common_prefix_label(functions: List[str]) -> Optional[str]:
    """군집 이름 짓기 — 공통 토큰이 2개 이상일 때만(한 토큰은 s_/g_ 라 의미가 없다).

    ⚠ 함수가 1개면 '공통' 접두사가 그 함수 이름 전체가 된다 — 실측에서
    `Ap_DoorPreCtrl_PDS_g_Ap_DoorPreCtrl_GetActiveHoldingTm.c` 라는 파일명이 나왔다.
    """
    if len(functions) < 2:
        return None
    parts = [str(f).split("_") for f in functions]
    common: List[str] = []
    for i in range(min(len(p) for p in parts)):
        tok = parts[0][i]
        if all(p[i] == tok for p in parts):
            common.append(tok)
        else:
            break
    return "_".join(common) if len(common) >= 2 else None


def _file_suffix(label: Optional[str], stem: str, fallback: str) -> str:
    """군집 라벨 → 새 파일명 꼬리. 파일명에 이미 있는 토큰과 스코프 접두사는 뺀다.

    실측: label `s_UDS_WDBI` + stem `Sys_UDS_LinComp_PDS` 를 그대로 붙이면
    `Sys_UDS_LinComp_PDS_s_UDS_WDBI.c` 가 된다 — 원하는 건 `..._WDBI.c` 다.
    """
    if not label:
        return fallback
    stem_tokens = {t.lower() for t in str(stem).split("_") if t}
    toks = [t for t in str(label).split("_")
            if t and t.lower() not in stem_tokens and t.lower() not in _NAME_NOISE]
    return "_".join(toks) or fallback


def _edge_functions(arch: Dict[str, Any], from_file: str, to_file: str) -> List[Dict[str, str]]:
    pb = arch.get("playbook_inputs") or {}
    return list((pb.get("cycle_edge_functions") or {}).get(f"{from_file}|{to_file}") or [])


def _split_axis(arch: Dict[str, Any], file: str) -> Dict[str, Any]:
    pb = arch.get("playbook_inputs") or {}
    return dict((pb.get("split_axis") or {}).get(file) or {})


# ── 종류별 플레이북 ─────────────────────────────────────────────────────────────

def _pb_break_cycle(c: Dict[str, Any], arch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    target = str(c.get("target") or "")
    if "→" not in target:
        return None
    from_file, to_file = (s.strip() for s in target.split("→", 1))
    pairs = _edge_functions(arch, from_file, to_file)
    if not pairs:
        return None
    caller, callee = pairs[0]["caller"], pairs[0]["callee"]
    hdr = f"{_stem(from_file)}_Cb.h"
    cb_type = f"{_stem(from_file)}_{callee}_Cb_t"
    slot = f"s_cb_{callee}"
    return {
        "summary": (f"{_basename(from_file)}가 {_basename(to_file)}의 {callee}()를 직접 부르는 "
                    f"바람에 순환이 생긴다. 이 한 곳을 콜백으로 뒤집으면 고리가 끊긴다."),
        "steps": [
            f"{hdr}에 콜백 타입 {cb_type}과 등록 함수를 선언한다(이 헤더는 {_basename(to_file)}를 include 하지 않는다).",
            f"{_basename(from_file)}에 슬롯 {slot}과 등록 함수를 정의한다.",
            f"{caller}() 안의 {callee}() 직접 호출을 슬롯 호출로 바꾼다(NULL 가드 포함).",
            f"{_basename(to_file)}의 초기화에서 {callee}를 등록한다 — 의존 방향이 to→from 한쪽으로 정리된다.",
        ],
        "sketch": {
            "lang": "c",
            "before": (f"/* {_basename(from_file)} */\n"
                       f"#include \"{_stem(to_file)}.h\"   /* ← 이 include 가 순환의 실체 */\n\n"
                       f"void {caller}(void)\n{{\n"
                       f"    {callee}(/* ... */);\n"
                       f"}}"),
            "after": (f"/* {hdr} */\n"
                      f"typedef void (*{cb_type})(/* 원래 인자 */);\n"
                      f"void {_stem(from_file)}_Register_{callee}({cb_type} cb);\n\n"
                      f"/* {_basename(from_file)} */\n"
                      f"static {cb_type} {slot} = NULL;\n\n"
                      f"void {_stem(from_file)}_Register_{callee}({cb_type} cb)\n{{\n"
                      f"    {slot} = cb;\n}}\n\n"
                      f"void {caller}(void)\n{{\n"
                      f"    if ({slot} != NULL) {{ {slot}(/* ... */); }}\n"
                      f"}}\n\n"
                      f"/* {_basename(to_file)} 초기화 */\n"
                      f"{_stem(from_file)}_Register_{callee}(&{callee});"),
            "note": SKETCH_NOTE,
        },
        "stub_plan": {
            "what": [f"테스트가 {slot}에 자기 스텁을 등록한다 — {_basename(to_file)} 링크 불필요"],
            "gain": (f"지금은 {caller}() 단위시험에 {_basename(to_file)}가 통째로 딸려온다. "
                     f"콜백이 되면 스텁 함수 1개로 대체되고 호출 여부·인자를 테스트가 직접 검증할 수 있다."),
        },
        "impact": {
            "files_in_cycle": len(c.get("files") or []),
            "edge_call_sites": len(pairs),
            "other_pairs": [f"{p['caller']} → {p['callee']}" for p in pairs[1:]],
        },
        "caveats": ([f"{_basename(from_file)}는 자동 생성 코드다 — 수정하면 재생성 시 사라진다. "
                     f"생성기 설정이나 래퍼 계층에서 처리할 것."]
                    if _is_generated(from_file) else []),
    }


def _pb_layer_violation(c: Dict[str, Any], arch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fns = [f for f in (c.get("functions") or []) if f]
    if len(fns) < 2:
        return None
    caller, callee = str(fns[0]), str(fns[1])
    files = list(c.get("files") or [])
    caller_file = files[0] if files else ""
    return {
        "summary": (f"하위 계층의 {caller}()가 상위 계층 {callee}()를 직접 부른다. "
                    f"상위가 아래로 등록하는 방향으로 뒤집으면 계층이 한 방향이 된다."),
        "steps": [
            f"{callee}()의 역할을 이벤트 하나로 정의한다(예: '{callee.split('_')[-1]}' 알림).",
            "하위 계층에 이벤트 슬롯과 등록 API를 둔다 — 하위는 상위 헤더를 include 하지 않는다.",
            f"{caller}() 안의 직접 호출을 슬롯 호출로 교체한다.",
            f"상위 계층 초기화에서 {callee}를 등록한다.",
        ],
        "sketch": {
            "lang": "c",
            "before": f"/* 하위 계층 */\nvoid {caller}(void)\n{{\n    {callee}(/* ... */);   /* ← 상위를 직접 호출 */\n}}",
            "after": ("/* 하위 계층 헤더 */\n"
                      "typedef void (*EventSink_t)(/* ... */);\n"
                      "void RegisterEventSink(EventSink_t cb);\n\n"
                      "/* 하위 계층 */\n"
                      "static EventSink_t s_sink = NULL;\n"
                      f"void {caller}(void)\n{{\n"
                      "    if (s_sink != NULL) { s_sink(/* ... */); }\n}\n\n"
                      f"/* 상위 계층 초기화 */\nRegisterEventSink(&{callee});"),
            "note": SKETCH_NOTE,
        },
        "stub_plan": {
            "what": [f"{caller}() 시험은 스텁 sink 를 등록해 호출 여부만 확인한다"],
            "gain": "하위 계층 단위시험이 상위 계층 없이 독립적으로 돈다.",
        },
        "impact": {"reverse_pairs_total": c.get("basis"), "caller_file": caller_file},
        "caveats": ["계층은 함수명 휴리스틱 추정값이라 오탐이 섞일 수 있다 — 실제 소속을 먼저 확인할 것."],
    }


def _pb_split_god_file(c: Dict[str, Any], arch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    file = str(c.get("target") or (c.get("files") or [""])[0])
    axis = _split_axis(arch, file)
    if not axis:
        return None
    stem = _stem(file)
    if not axis.get("available"):
        share = axis.get("largest_component_share")
        pct = f"{float(share) * 100:.0f}%" if isinstance(share, (int, float)) else "대부분"
        return {
            "summary": (f"이 파일은 **기계적 분할선이 없다** — 함수 {pct}가 서로 호출로 한 덩어리다. "
                        f"자동 제안 대신 도메인 기준으로 사람이 갈라야 한다."),
            "steps": [
                "기능(도메인) 단위로 먼저 나눈다 — 상태 관리 / 판정 로직 / 하드웨어 접근처럼 책임이 다른 축.",
                "가장 안쪽 leaf 함수부터 별도 파일로 옮기고 헤더로 노출한다(호출 방향이 한쪽이라 안전하다).",
                "옮길 때마다 빌드·시험을 돌려 회귀를 확인한 뒤 다음 덩어리로 넘어간다.",
            ],
            "sketch": None,
            "stub_plan": None,
            "impact": {"functions": c.get("functions"), "components": axis.get("components"),
                       "largest_component_share": share},
            "caveats": ["연결성분·이름 접두사 두 축 모두 임계 미달이라 자동 군집을 제시하지 않는다."]
            + ([f"{_basename(file)}는 자동 생성 코드다 — 분할 대상이 아니다."] if _is_generated(file) else []),
        }

    groups = list(axis.get("groups") or [])
    axis_ko = "파일 내부 호출 덩어리" if axis.get("axis") == "call_component" else "함수명 접두사"
    # 함수 1~2개짜리는 별도 .c 로 떼면 파일만 늘고 얻는 게 없다 — 잔여로 묶어 따로 고지한다.
    big = [g for g in groups if int(g.get("size") or 0) >= MIN_SPLIT_GROUP]
    small = [g for g in groups if int(g.get("size") or 0) < MIN_SPLIT_GROUP]
    if len(big) < 2:            # 큰 덩어리가 하나뿐이면 원래 군집을 그대로 보여주는 편이 낫다
        big, small = groups, []
    proposal, steps = [], []
    for i, g in enumerate(big):
        label = g.get("label") or _common_prefix_label(list(g.get("functions") or []))
        new_file = f"{stem}_{_file_suffix(label, stem, f'part{i + 1}')}.c"
        proposal.append({
            "file": new_file, "size": g.get("size"),
            "label": label, "functions": list(g.get("functions") or [])[:12],
        })
    for p in proposal[:4]:
        steps.append(f"{p['file']} — 함수 {p['size']}개 (예: {', '.join(p['functions'][:3])})")
    if small:
        steps.append(f"나머지 {sum(int(g.get('size') or 0) for g in small)}개 함수"
                     f"({len(small)}덩어리)는 파일을 새로 만들 만큼이 아니다 — 원래 파일에 두거나 "
                     f"관련 있는 덩어리에 합친다.")
    cut = int(axis.get("cut_calls") or 0)
    steps.append("공통 헤더에 파일 간 노출이 필요한 함수만 선언한다 — 나머지는 static 으로 내린다."
                 if cut == 0 else
                 f"군집 간 호출 {cut}곳은 새 파일 사이의 의존이 되므로 헤더로 노출한다.")
    return {
        "summary": (f"{axis_ko} 기준으로 {axis.get('n_groups')}덩어리로 갈린다"
                    f"{' — 덩어리 사이 호출이 0이라 그대로 잘라도 파일 간 의존이 생기지 않는다' if cut == 0 else ''}."),
        "steps": steps,
        "split_proposal": proposal,
        "sketch": None,
        "stub_plan": {
            "what": [f"{p['file']} 단위시험" for p in proposal[:3]],
            "gain": (f"지금은 함수 {c.get('functions')}개가 한 파일이라 어느 시험이든 전체를 링크한다. "
                     f"나누면 덩어리별로 스텁 범위가 좁아진다."),
        },
        "impact": {"functions": c.get("functions"), "axis": axis.get("axis"),
                   "groups": axis.get("n_groups"), "cut_calls": cut,
                   "max_share": axis.get("max_share"), "cover": axis.get("cover")},
        "caveats": ([f"{_basename(file)}는 자동 생성 코드다 — 분할 대상이 아니다."]
                    if _is_generated(file) else []),
    }


def _pb_extract_pure(c: Dict[str, Any], arch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fn = str(c.get("target") or "")
    files = list(c.get("files") or [])
    file = str(files[0]) if files else ""
    if not fn:
        return None
    generated = _is_generated(file)
    return {
        "summary": (f"{fn}()는 복잡도 대비 커버리지가 낮다 — 판정 로직만 인자→반환값 함수로 떼어내면 "
                    f"하드웨어 없이 케이스를 붙일 수 있다."),
        "steps": (
            [f"{_basename(file)}는 생성 코드라 직접 수정하지 않는다 — 호출하는 응용 코드 쪽에 래퍼를 둔다.",
             "래퍼가 입력을 받아 판정만 하고, 생성 코드 호출은 래퍼 바깥에 남긴다.",
             "래퍼에 경계값·예외 케이스 시험을 붙인다."]
            if generated else
            [f"{fn}() 안에서 '값을 계산·판정하는 부분'과 '레지스터/전역을 쓰는 부분'을 나눈다.",
             "판정 부분을 입력 인자만 받아 결과를 반환하는 static 함수로 추출한다(부수효과 0).",
             f"{fn}()는 추출 함수를 부르고 그 결과로 부수효과만 수행하게 남긴다.",
             "추출 함수에 경계값·분기 케이스를 직접 넣어 시험한다 — 스텁이 필요 없다."]
        ),
        "sketch": {
            "lang": "c",
            "before": (f"void {fn}(void)\n{{\n"
                       "    /* 판정과 부수효과가 한 몸 — 시험하려면 하드웨어/전역을 흉내내야 한다 */\n"
                       "    if (/* 조건 */) { /* 레지스터 쓰기 */ }\n}"),
            "after": ("/* 순수: 입력만으로 결정 — 스텁 없이 시험된다 */\n"
                      f"static /* 반환형 */ {fn}_Decide(/* 입력 */)\n{{\n"
                      "    /* 분기 로직만 */\n}\n\n"
                      f"void {fn}(void)\n{{\n"
                      f"    /* 결과 */ = {fn}_Decide(/* 현재 상태 */);\n"
                      "    /* 결과에 따른 부수효과만 */\n}"),
            "note": SKETCH_NOTE,
        },
        "stub_plan": {
            "what": [f"{fn}_Decide() 는 스텁 0개로 시험 — 입력을 직접 넣는다"],
            "gain": "미커버 분기가 하드웨어 상태 재현 없이 도달 가능해진다.",
        },
        "impact": {"basis": c.get("basis"), "file": file},
        "caveats": ([f"{_basename(file)}는 자동 생성 코드다 — 원본 수정 금지, 래퍼로 감쌀 것."]
                    if generated else []),
    }


def _pb_inject_global(c: Dict[str, Any], arch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    g = str(c.get("target") or "")
    fns = [str(f) for f in (c.get("functions") or []) if f]
    if not g:
        return None
    return {
        "summary": (f"전역 {g}를 여러 모듈이 직접 읽고 쓴다 — 시험이 이 값을 고정하려면 "
                    f"링크 전역을 건드려야 하고, 케이스끼리 상태가 샌다."),
        "steps": [
            f"{g}를 읽는 함수의 시그니처에 값(또는 포인터)을 인자로 추가한다.",
            "호출부에서 전역을 넘겨준다 — 이 단계까지는 동작이 바뀌지 않는다.",
            "쓰기가 필요한 함수는 결과를 반환하고, 전역 갱신은 한 곳(소유 모듈)에서만 하게 모은다.",
            "시험은 인자로 상태를 직접 주입한다.",
        ],
        "sketch": {
            "lang": "c",
            "before": (f"void SomeFunc(void)\n{{\n    if ({g} > /* ... */) {{ /* ... */ }}\n}}"),
            "after": (f"void SomeFunc(/* 타입 */ {g.lstrip('gu_')}_in)\n{{\n"
                      f"    if ({g.lstrip('gu_')}_in > /* ... */) {{ /* ... */ }}\n}}\n\n"
                      f"/* 호출부 */\nSomeFunc({g});"),
            "note": SKETCH_NOTE,
        },
        "stub_plan": {
            "what": [f"{g} 전역 조작 대신 인자 주입"],
            "gain": "케이스 간 상태 누수가 사라져 시험 순서 의존이 없어진다.",
        },
        "impact": {"basis": c.get("basis"), "sample_functions": fns[:5]},
        "caveats": ["참조는 읽기/쓰기를 구분하지 않은 수치다 — 쓰기 지점을 먼저 확인할 것."],
    }


def _pb_seam_for_pointer(c: Dict[str, Any], arch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fn = str(c.get("target") or "")
    syms = [str(s) for s in (c.get("pointer_symbols") or [])]
    refs = [str(s) for s in (c.get("ref_functions") or [])]
    if not fn or not (syms or refs):
        return None
    if syms:
        sym = syms[0]
        table = "[" in sym          # s_uds_wdbi_did_tbl[i].pf_Handler 처럼 디스패치 테이블
        base = sym.split("[")[0]
        summary = (f"{fn}()는 {sym}로 간접 호출한다 — **이미 스텁을 끼울 수 있는 지점**이다. "
                   + ("테이블 엔트리를 시험용으로 교체하면 된다." if table
                      else "포인터를 시험에서 바꿔 끼우면 된다."))
        steps = ([f"{base} 테이블을 const 로 고정하지 말고 등록 API로 채우게 한다(이미 그렇다면 그대로 사용).",
                  "시험에서 해당 엔트리를 스텁 함수로 교체한다.",
                  "핸들러 호출 여부·인자·반환 처리 경로를 검증한다.",
                  "테이블 경계(빈 엔트리·NULL 핸들러) 케이스를 추가한다."]
                 if table else
                 [f"{base}를 설정하는 등록 함수를 헤더로 노출한다.",
                  "시험 setup 에서 스텁 함수를 등록한다.",
                  "호출 인자와 반환값 처리 경로를 검증한다.",
                  f"{base}가 NULL 인 경우의 방어 코드를 시험한다."])
        sketch_after = ("/* 시험 */\nstatic /* 반환형 */ Stub_Handler(/* 인자 */) { g_called = TRUE; return /* ... */; }\n\n"
                        "void setUp(void)\n{\n"
                        + (f"    {base}[0].pf_Handler = &Stub_Handler;\n" if table
                           else f"    Register_{base.lstrip('s_pfn')}(&Stub_Handler);\n")
                        + "}")
    else:
        sym = refs[0]
        summary = (f"{fn}()는 {sym} 등 함수 주소를 넘겨 쓴다 — 등록 지점을 헤더로 노출하면 "
                   f"시험에서 스텁으로 대체할 수 있다.")
        steps = [f"{sym}를 등록하는 경로를 등록 API 하나로 모은다.",
                 "시험 setup 에서 스텁을 등록한다.",
                 "등록/해제 순서와 NULL 방어를 시험한다."]
        sketch_after = (f"/* 시험 */\nstatic /* 반환형 */ Stub_{sym}(/* 인자 */) {{ return /* ... */; }}\n\n"
                        f"void setUp(void)\n{{\n    Register_{sym}(&Stub_{sym});\n}}")
    return {
        "summary": summary,
        "steps": steps,
        "sketch": {
            "lang": "c",
            "before": (f"/* {fn}() 안 */\n"
                       + (f"{sym}(/* ... */);   /* 간접 호출 — 무엇이 불릴지는 등록에 달렸다 */"
                          if syms else f"/* {sym} 의 주소를 등록해 사용 */")),
            "after": sketch_after,
            "note": SKETCH_NOTE,
        },
        "stub_plan": {
            "what": [f"{s} 를 스텁으로 교체" for s in (syms or refs)[:4]],
            "gain": ("실제 구현을 링크하지 않고 이 함수의 분기·에러 처리 경로를 직접 몰 수 있다. "
                     "간접 호출은 콜그래프에 안 잡혀 커버리지 도구가 놓치는 경로이기도 하다."),
        },
        "impact": {"pointer_symbols": syms, "ref_functions": refs, "basis": c.get("basis")},
        "caveats": [],
    }


_BUILDERS = {
    "break_cycle": _pb_break_cycle,
    "layer_violation": _pb_layer_violation,
    "split_god_file": _pb_split_god_file,
    "extract_pure": _pb_extract_pure,
    "inject_global": _pb_inject_global,
    "seam_for_pointer": _pb_seam_for_pointer,
}


def build_playbook(candidate: Dict[str, Any], arch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """후보 1건 → 상세 개선안. 재료가 없으면 None(빈 절차를 만들지 않는다)."""
    fn = _BUILDERS.get(str(candidate.get("kind") or ""))
    if fn is None:
        return None
    try:
        out = fn(candidate, arch or {})
    except Exception:  # noqa: BLE001 — 상세는 부가 정보다. 실패해도 후보 표는 살아야 한다.
        logger.warning("playbook 생성 실패 (kind=%s target=%s)",
                       candidate.get("kind"), candidate.get("target"), exc_info=True)
        return None
    if not out:
        return None
    return {**out, "version": PLAYBOOK_VERSION}


def attach_playbooks(candidates: List[Dict[str, Any]], arch: Dict[str, Any]) -> List[Dict[str, Any]]:
    """후보 목록에 `detail`을 붙여 반환(원본 미변경). 재료 없는 후보는 detail 키가 없다."""
    out: List[Dict[str, Any]] = []
    for c in candidates:
        pb = build_playbook(c, arch)
        out.append({**c, "detail": pb} if pb else dict(c))
    return out


def playbook_coverage(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """상세를 붙인 비율 — 낮으면 재료 부족을 프론트가 명시할 수 있게."""
    total = len(candidates)
    with_detail = sum(1 for c in candidates if c.get("detail"))
    return {"total": total, "with_detail": with_detail,
            "without_detail": total - with_detail}
