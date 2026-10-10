"""SwUDS 문서의 `Function Information` 표 → 함수별 **설계 ID**.

## 왜 별도 모듈인가

이 표 하나를 **두 소비처**가 읽는다:

1. 추적성 매트릭스 — `backend/routers/jenkins.py::_jenkins_uds_extract_mapping_impl`
   (설계ID → SDS → SRS 브리지의 좌측 끝)
2. STS 요구-함수 매핑 — `generators/sts.py::map_requirements_to_functions`

파싱 규약(값 셀 위치, echo 가드, `Related ID` 행 한정, `Sw[A-Za-z]{2,}_\\d+` 정규식)이
양쪽에 복제되면 한쪽만 고쳐진다. 이 저장소는 같은 복제로 이미 여러 번 당했다
(`scripts/_ratchet_core.py` 가 ruff/eslint ratchet 에서 같은 문제를 합친 선례).

## ⚠ 함수 **이름**으로만 이을 것 — `SwUFn_NNNN` 번호로 잇지 말 것

SwUDS 문서의 `SwUFn` 번호와 **소스 파서가 매기는 `SwUFn` 번호는 다른 체계**다.
실측(KJPDS02_PV, 2026-08-18): 한 표에 ID·이름이 하나씩만 있는 43건을 대조했더니
**35건이 불일치**했다::

    SwUFn_1416   SwUDS='s_DoorState_AutoClose'  소스='s_ProcessLatchStates'
    SwUFn_0301   SwUDS='g_ApiIn_LinRx_ReadData' 소스='g_Lib_SafeWriteQueue_EnqueueWrite'

번호로 조인하면 **조용한 오귀속**이 된다(같은 실측에서 ID 조인만이 만든 링크 276건).
그래서 이 모듈은 `id` 를 담되 **조인 키로 쓰지 말라**고 명시한다.
"""
from __future__ import annotations

import gc
import io
import re
from typing import Any, Dict, List, Optional

# 설계/요구 ID 토큰. ⚠ `[A-Za-z]` 여야 한다 — 예전의 `[A-Z]{2,}` 는 소문자가 섞인
# `SwFn`·`SwCom` 을 통째로 놓쳤다.
DESIGN_ID_TOKEN_RE = re.compile(r"Sw[A-Za-z]{2,}_\d+")

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def collect_docx_garbage() -> None:
    """(R75) python-docx 로 다 읽은 문서 그래프를 바로 거둔다 — 그 문서의 객체(문서 · 문단 · 표 · 셀)를 쥔 프레임이 끝난
    뒤에 부를 것(쥐고 있으면 거둘 수 없다).

    python-docx 의 `Document` 는 패키지와 파트가 서로를 가리키는 순환 참조라 참조 수로는 풀리지 않고 순환 가비지 수집을
    기다린다. 오래 사는 객체가 많은 생성 프로세스에서는 그 수집(2 세대)이 드물게 돌아, KJPDS02_PV SwUDS(48 MB)를 읽은
    판독기마다 1.2 GB 가 남아 쌓였다 — SUTS 생성 최대 RSS 4,079 MB 중 2.4 GB(R75 실측, 수집 뒤 70 MB).

    ⚠ 전체 수집이라 그동안 프로세스 전체(웹 백엔드의 다른 요청 · 이벤트 루프 포함)가 멈춘다 — 생성 중 힙에서 1 초 안팎,
    쉬는 백엔드에서 0.1 초(R75 실측). 문서 하나에 한 번만, 루프 안에서 부르지 말 것. 다른 스레드가 수집 중이면
    아무것도 하지 않는다(CPython) — 그 문서는 다음 자동 수집까지 남는 최선 노력이다.
    """
    gc.collect()


def _python_docx_tables(data: bytes) -> List[List[List[str]]]:
    """python-docx 로 읽은 표 — 문서 객체는 이 프레임의 지역으로만 둔다(반환하면 `collect_docx_garbage` 가 거둘 수 있다)."""
    import docx as _docx
    doc = _docx.Document(io.BytesIO(data))
    return [[[c.text for c in r.cells] for r in t.rows] for t in doc.tables]


def docx_tables_text(data: bytes) -> Optional[List[List[List[str]]]]:
    """docx bytes → tables[행[셀텍스트]]. 손상 docx 복구 fallback 포함.

    정상 파일은 python-docx로 읽는다. 임베디드 이미지 CRC 오류 등으로 python-docx가
    실패해도 추적성 매핑은 이미지와 무관한 '표'에서만 추출하므로, word/document.xml만
    직접 스트리밍 파싱해 표를 복구한다(손상 미디어 파트 우회). document.xml까지 손상돼
    파싱 불가하면 None.
    """
    # 1) 정상 경로 — python-docx
    tables: Optional[List[List[List[str]]]]
    try:
        tables = _python_docx_tables(data)
    except Exception:  # silent-ok — 손상 docx 는 아래 document.xml 직독으로 복구한다
        tables = None
    # (R75) python-docx 문서 그래프는 순환 참조라 반환해도 남는다 — 실패해 버린 그래프도 같다
    collect_docx_garbage()
    if tables is not None:
        return tables
    # 2) 손상 fallback — document.xml만 직접 파싱 (이미지 등 손상 파트 우회).
    #    document.xml은 수십 MB일 수 있어 iterparse + elem.clear()로 메모리 방어.
    try:
        import xml.etree.ElementTree as _ET
        import zipfile as _zip
        xml_tables: List[List[List[str]]] = []
        with _zip.ZipFile(io.BytesIO(data)) as zf:
            with zf.open("word/document.xml") as f:
                for _, elem in _ET.iterparse(f, events=("end",)):
                    if elem.tag != _W + "tbl":
                        continue
                    rows: List[List[str]] = []
                    for tr in elem.findall(_W + "tr"):
                        rows.append([
                            "".join(t.text or "" for t in tc.iter(_W + "t"))
                            for tc in tr.findall(_W + "tc")
                        ])
                    xml_tables.append(rows)
                    elem.clear()
        return xml_tables
    except Exception:
        # silent-ok — 두 경로 모두 실패 = "표를 못 읽었다". 호출부가 None 을 보고
        # 사용자에게 사유를 낸다(빈 리스트로 접으면 '표가 없는 문서'로 위장된다).
        return None


def extract_function_related_rows(
    tables_text: Optional[List[List[List[str]]]],
) -> List[Dict[str, Any]]:
    """`Function Information` 표들 → ``[{"id", "name", "design_ids"}]``.

    ``name`` 이 빈 표는 버린다(값 셀이 라벨을 echo 하는 템플릿/빈 표가 여기서 걸러진다).
    ``design_ids`` 는 정렬·중복제거되고 **자기 자신의 `id` 는 빠진다**.

    파싱 규약(둘 다 실측으로 굳은 것이라 임의로 바꾸지 말 것):

    · **값 셀 위치** — python-docx 는 병합셀을 grid 로 펼쳐 값이 ``cells[2]`` 에 오지만,
      document.xml 직접 파싱(손상 docx fallback)은 실제 ``w:tc`` 만 뽑아 ``cells[1]`` 에
      온다. 두 경우를 모두 커버한다.
    · **echo 가드** — 값 셀이 라벨을 그대로 되뇌는 표(``cells=['Name','Name',…]``)는 junk 다.
      이 echo 가 ``name='Name'``/``id='ID'`` 로 수확되면 설계-ID 브리지를 타고 요구
      추적성에 '함수'로 유입돼 over-trace 를 만든다(HDPDM01 실측 32/56 요구 오염).
    · **`Related ID` 행 한정** — 예전엔 모든 행의 모든 셀을 훑어 "Called/Calling Function"
      행의 `SwUFn` 함수 ID까지 요구참조로 오수집했다.
    """
    out: List[Dict[str, Any]] = []
    for rows in (tables_text or []):
        if len(rows) < 4:
            continue
        first_cell = (rows[0][0] if rows[0] else "").strip()
        if "Function Information" not in first_cell:
            continue

        func_id = ""
        func_name = ""
        refs: List[str] = []
        for raw_cells in rows:
            cells = [str(c).strip() for c in raw_cells]
            label = cells[0] if cells else ""
            if len(cells) > 2:
                value = cells[2]
            elif len(cells) > 1:
                value = cells[1]
            else:
                value = ""
            # case-불문 비교 — 'Name'라벨↔'name'값 같은 변형 echo 도 제거.
            if value and value.lower() == label.lower():
                value = ""
            if label == "ID":
                func_id = value
            elif label == "Name":
                func_name = value
            elif label.lower().replace("_", " ").startswith("related id"):
                for c in cells:
                    refs.extend(DESIGN_ID_TOKEN_RE.findall(c))

        if not func_name:
            continue
        out.append({
            "id": func_id,
            "name": func_name,
            "design_ids": sorted(set(refs) - {func_id}),
        })
    return out
