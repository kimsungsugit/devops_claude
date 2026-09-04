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
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path


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
