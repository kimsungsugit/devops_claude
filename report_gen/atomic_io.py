"""원자적 파일 기록 — 사이드카(`.md`/`.payload.json`) 라이터의 **단일 출처**.

(R32, R31 리뷰 W2 편입) R31 은 `.quality_gate.md`·`.validation.md`·`.field_confidence.md` 세 라이터만
`report_gen/validation.py::_atomic_write_text` 로 원자화했다. 그런데 **같은 리더가 읽는 `.payload.json`
라이터 5곳**(`backend/helpers/uds.py`·`backend/routers/local.py`·`backend/routers/jenkins.py`·
`backend/helpers/common.py`·`tools/generate_uds_local.py`)은 여전히 `Path.write_text` 였다.
`write_text` 는 열기(truncate)→쓰기라, 그 사이에 품질 게이트가 payload 를 읽으면 **빈 파일/반쪽 JSON**
을 보고 `json.loads` 가 실패한다 → `_load_uds_payload` 가 `{}` 를 돌려주고 채점기는 **DOCX 자기 대조
모드로 조용히 강등**된다(R30 이 고친 출처 세탁이 torn read 경로로 되살아난다).

규약:
- 같은 디렉터리에 `pid+난수` 임시 파일을 쓰고 `os.replace` 로 바꿔 넣는다(같은 볼륨 안에서 원자적).
- 실패하면 임시 파일을 지우고 예외를 **그대로** 올린다 — 옛 내용이 있으면 옛 내용이 남고, 반쯤 쓰인
  파일은 절대 그 이름을 갖지 않는다.
- 이 모듈은 stdlib 만 쓴다(라우터·도구·report_gen 어디서든 import 비용 0).

(R47-k) 두 번째 책임 — `normalize_zip_member_times`: zip 컨테이너(docx) 멤버 시각을 고정해 같은 내용이면 같은
바이트가 되게 한다(같은 임시 파일 + `os.replace` 규약을 공유하므로 여기 둔다).
"""
from __future__ import annotations

import logging
import os
import uuid
import zipfile
from pathlib import Path
from typing import Tuple

_logger = logging.getLogger(__name__)

# zip(DOS) 시각의 최솟값. 재현 가능한 빌드가 쓰는 관례(SOURCE_DATE_EPOCH 류)와 같은 뜻 — "이 시각은 정보가 아니다".
_DateTime6 = Tuple[int, int, int, int, int, int]
ZIP_FIXED_DATE_TIME: _DateTime6 = (1980, 1, 1, 0, 0, 0)


def normalize_zip_member_times(path: Path, *, date_time: _DateTime6 = ZIP_FIXED_DATE_TIME) -> bool:
    """zip 컨테이너(docx/xlsx) 멤버의 기록 시각을 고정값으로 바꿔 **같은 내용이면 같은 바이트**가 되게 한다.

    (R47-k N27-e) python-docx 는 `ZipFile.writestr(name, blob)` 로 저장해 멤버 2,008개 전부에 **저장 시각**이
    박힌다. 그래서 같은 입력으로 만든 두 UDS 는 `word/document.xml` 이 같아도 `output_sha256` 이 늘 달랐다
    (2026-09-14 run 2072/2073: 내용이 다른 멤버 1 · 시각이 다른 멤버 2,008). 검토 기록이 판정하는 대상은
    산출물 **바이트**이므로, 시각을 지우지 않으면 "같은 입력 → 같은 문서" 를 해시로 확인할 길이 없다.

    규약: 같은 디렉터리의 임시 파일에 다시 쓰고, 멤버 (이름·CRC·크기·주석) 열과 아카이브 주석이 원본과 같고 시각이
    전부 고정값일 때만 `os.replace`. 어긋나거나 zip 이 아니면 **원본을 그대로 두고** warning + False — 산출물을 잃는
    것보다 시각이 남는 쪽이 낫다. 실측 60.5MB(2,008 멤버) 2.2초.
    ⚠ 멤버 `extra` 필드는 **버린다**(리뷰 W4) — 거기 UT/NTFS 확장 시각(0x5455/0x000A)이 들어 있으면 정규화 자체가 무력화된다.
      python-docx/openpyxl 산출물엔 extra 가 없다. extra 를 실은 zip 을 넣으면 검증에서 걸려 False(원본 유지)다.
    """
    src = Path(path)
    tmp = src.with_name(f"{src.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w") as zout:
            if any(i.extra for i in zin.infolist()):
                raise ValueError("member extra field present — would be dropped")
            zout.comment = zin.comment
            for info in zin.infolist():
                ninfo = zipfile.ZipInfo(info.filename, date_time=date_time)
                ninfo.compress_type = info.compress_type
                ninfo.external_attr = info.external_attr
                ninfo.comment = info.comment
                ninfo.create_system = 0   # OS 표기도 바이트에 들어간다 — 머신이 달라도 같게
                zout.writestr(ninfo, zin.read(info))   # ZipInfo 로 읽는다 — 이름 조회는 동명 멤버에서 마지막 것을 준다(W5)
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp) as zout:
            before = [(i.filename, i.CRC, i.file_size, i.comment) for i in zin.infolist()]
            after_infos = zout.infolist()
            after = [(i.filename, i.CRC, i.file_size, i.comment) for i in after_infos]
            if before != after or zin.comment != zout.comment:
                raise ValueError("member list/CRC/comment mismatch after rewrite")
            if any(i.date_time != date_time for i in after_infos):
                raise ValueError("member time not normalized")
        os.replace(tmp, src)
        return True
    except Exception as exc:  # noqa: BLE001 — (리뷰 W1) zlib.error·RuntimeError(암호화) 등 무엇이 나도 원본을 남기고 False 여야 한다
        _logger.warning("zip 멤버 시각 정규화 실패 — 원본을 그대로 둔다(%s: %s)", type(exc).__name__, str(exc)[:160])
        return False
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass  # silent-ok: 성공 경로에선 이미 replace 돼 없고, 실패 경로의 정리 실패는 결과를 바꾸지 않는다


def atomic_write_text(out: Path, text: str, *, encoding: str = "utf-8") -> None:
    """`text` 를 `out` 에 원자적으로 기록한다(임시 파일 + `os.replace`)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 이름에 pid+난수 — 같은 경로를 두 프로세스가 동시에 쓰면 고정 이름은 서로의 tmp 를 truncate 한다(R31 리뷰 I4).
    tmp = out.with_name(f"{out.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, out)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass  # silent-ok: 임시 파일 정리 실패는 원래 예외를 가리면 안 된다
        raise
