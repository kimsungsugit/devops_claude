"""산출물 경로 선점 — 같은 초에 만든 두 산출물이 서로를 덮어쓰지 않게.

## 무엇이 문제였나

산출물 경로는 전부 `datetime.now().strftime("%Y%m%d_%H%M%S")` 로 만든다 — **초 단위**다.
같은 키(job/카테고리)에 대한 요청 둘이 같은 초에 경로를 조립하면 **완전히 같은 경로**가
나오고, 마지막 쓰기만 남는다. 앞선 요청의 사용자는 자기 것이 아닌 문서를 받는다.

ISO 26262 산출물에서 이건 단순 덮어쓰기가 아니다 — **A 가 받은 STS 가 실은 B 의 것**이
될 수 있고, 어디에도 흔적이 안 남는다.

키가 약할수록 확률이 올라간다. 최악은 키가 아예 없는 것들이다(`local_report_{ts}`,
`suts_vectorcast_{ts}`) — 서로 다른 사용자·프로젝트여도 같은 초면 그냥 부딪힌다.

## 왜 랜덤 접미사가 아니라 '선점'인가

`_{uuid4}` 를 붙이면 **모든 산출물 이름이 바뀐다**(정상 경로까지). 사용자가 파일명으로
식별하는 도구에서 그건 별개의 변경이다. 선점 방식은 충돌이 **실제로 있을 때만** 이름이
달라지고, 없으면 오늘과 똑같은 이름이 나온다.

## 원자성

`os.O_CREAT | os.O_EXCL` 은 "없으면 만들고, 있으면 실패"를 **커널이 원자적으로** 보장한다.
`if path.exists()` 로 먼저 보고 쓰는 방식은 두 요청이 같은 순간에 '없음'을 볼 수 있어
(TOCTOU) 정작 막으려던 경합을 그대로 남긴다.

⚠ **trade-off**: 선점은 0바이트 파일을 먼저 만든다. 이후 생성이 실패하면 0바이트 파일이
남는다. 실패 시 부분 산출물이 남는 건 기존에도 마찬가지고(부분 docx 등), **남의 산출물을
조용히 덮어쓰는 것보다는 낫다**고 판단했다.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

_logger = logging.getLogger("devops_api")

# 같은 초에 같은 키로 이만큼 겹치면 그건 다른 문제다 — 무한 루프 대신 명시 실패.
_MAX_ATTEMPTS = 50


def _numbered(path: Path, n: int) -> Path:
    """`a.xlsx` → `a_2.xlsx`. 확장자를 보존한다(`.xlsm` 이 `.xlsx` 가 되면 안 된다)."""
    return path.with_name(f"{path.stem}_{n}{path.suffix}")


def reserve_unique_path(path: Path) -> Path:
    """파일 경로를 **원자적으로 선점**하고 실제 확보한 경로를 준다.

    비어 있으면 요청한 경로 그대로(= 오늘과 같은 이름), 이미 있으면 `_2`, `_3` … 으로
    비켜간다. 반환된 경로에는 **0바이트 파일이 이미 만들어져 있다** — 호출부는 그대로
    덮어써 쓰면 된다(`write_bytes` / `save()` / builder 모두 문제없다).

    Raises:
        OSError: 상한(50)까지 전부 점유됐거나 디렉터리를 만들 수 없을 때.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for n in range(1, _MAX_ATTEMPTS + 1):
        cand = path if n == 1 else _numbered(path, n)
        try:
            fd = os.open(cand, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(fd)
        return cand
    raise OSError(
        f"산출물 경로를 선점하지 못했다({_MAX_ATTEMPTS}회 전부 점유): {path} — "
        "같은 초에 같은 키로 과도한 동시 생성이 일어나고 있다"
    )


def drop_empty_reservation(path: Optional[Path]) -> None:
    """선점만 하고 생성이 실패했으면 0바이트 파일을 치운다.

    선점은 원자성을 위해 **먼저 0바이트 파일을 만든다**(위 trade-off). 생성이 실패하면
    그게 남아 리포트 목록 API 에 **열리지 않는 산출물**로 뜬다 —
    `/api/qac/reports`·`/api/vcast/reports` 는 디렉터리를 glob 해서 그대로 보여준다.

    ⚠ **크기 0 인 것만** 지운다. 내용이 들어간 부분 산출물은 진단 근거라 손대지 않는다.
    """
    if path is None:
        return
    try:
        if path.is_file() and path.stat().st_size == 0:
            path.unlink()
    except OSError as exc:  # 정리 실패가 본래 오류를 가리면 안 된다
        _logger.debug("빈 선점 파일 정리 실패 %s: %s", path, exc)


def reserve_unique_dir(path: Path) -> Path:
    """디렉터리를 **원자적으로 선점**한다(패키지 산출물처럼 폴더 단위인 경우).

    `mkdir(exist_ok=True)` 로는 두 요청이 **같은 폴더를 공유**해 안의 파일을 서로
    덮어쓴다. `exist_ok=False` 로 만들어 이미 있으면 `_2`, `_3` … 으로 비켜간다.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for n in range(1, _MAX_ATTEMPTS + 1):
        cand = path if n == 1 else path.with_name(f"{path.name}_{n}")
        try:
            cand.mkdir()
        except FileExistsError:
            continue
        return cand
    raise OSError(
        f"산출물 디렉터리를 선점하지 못했다({_MAX_ATTEMPTS}회 전부 점유): {path}"
    )
