"""SwSA PMD/CPD 중복코드 파서 — ST201 ST206(Number Duplicated Code Lines).

PMD CPD(Copy-Paste Detector) 텍스트 리포트를 파싱한다. 형식 (실측)::

    Found a 176 line (562 tokens) duplication in the following files:
    Starting at line 263 of C:\\...\\lin_cfg.c
    Starting at line 481 of C:\\...\\lin_cfg.c
    <중복 코드 블록 본문...>
    Found a ...   (다음 블록)

회사 양식 ST206 밴드 (템플릿 2.ST201 rows 42~44)::

    0 ~ 9   Low Duplication       Pass
    10 ~ 49 Moderate Duplication  Conditional Pass
    >= 50   High Duplication      Fail

verdict: Fail = High(>=50줄) 블록 1개 이상. Conditional 은 수동 판정 → 자동 Pass
처리하되 conditional_blocks 노출.

ISO 26262: 중복코드는 유지보수성/오류전파 리스크 (ASIL 무관 권장 점검).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Union

__all__ = [
    "DuplicationBlock",
    "PmdResult",
    "DUP_BANDS",
    "parse_pmd_cpd",
]

# (upper_inclusive|None, label, verdict)
DUP_BANDS = [
    (9, "0 ~ 9", "Pass"),
    (49, "10 ~ 49", "Conditional"),
    (None, ">= 50", "Fail"),
]

_FOUND_RE = re.compile(
    r"Found a\s+(\d+)\s+line\s+\((\d+)\s+tokens?\)\s+duplication", re.IGNORECASE
)
_STARTING_RE = re.compile(r"Starting at line\s+(\d+)\s+of\s+(.+?)\s*$", re.IGNORECASE)


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path.strip())[-1] if path.strip() else path


@dataclass
class DuplicationBlock:
    lines: int
    tokens: int
    files: List[str] = field(default_factory=list)        # 전체 경로
    start_lines: List[int] = field(default_factory=list)  # 각 파일 시작 라인

    @property
    def basenames(self) -> List[str]:
        return [_basename(f) for f in self.files]

    @property
    def band(self) -> str:
        for upper, label, _verdict in DUP_BANDS:
            if upper is None or self.lines <= upper:
                return label
        return DUP_BANDS[-1][1]

    @property
    def verdict(self) -> str:
        for upper, _label, verdict in DUP_BANDS:
            if upper is None or self.lines <= upper:
                return verdict
        return "Fail"


@dataclass
class PmdResult:
    blocks: List[DuplicationBlock] = field(default_factory=list)
    parse_warnings: List[str] = field(default_factory=list)

    @property
    def total_blocks(self) -> int:
        return len(self.blocks)

    @property
    def total_duplicated_lines(self) -> int:
        return sum(b.lines for b in self.blocks)

    @property
    def max_lines(self) -> int:
        return max((b.lines for b in self.blocks), default=0)

    @property
    def band_counts(self) -> Dict[str, int]:
        out = {label: 0 for _u, label, _v in DUP_BANDS}
        for b in self.blocks:
            out[b.band] += 1
        return out

    @property
    def fail_count(self) -> int:
        return sum(1 for b in self.blocks if b.verdict == "Fail")

    @property
    def conditional_count(self) -> int:
        return sum(1 for b in self.blocks if b.verdict == "Conditional")

    @property
    def result(self) -> str:
        return "Fail" if self.fail_count > 0 else "Pass"

    def blocks_sorted(self) -> List[DuplicationBlock]:
        return sorted(self.blocks, key=lambda b: -b.lines)


def _read_text(source: Union[str, bytes, Path]) -> str:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source).decode("utf-8", errors="ignore")
    p = Path(source)
    if p.exists():
        return p.read_text(encoding="utf-8", errors="ignore")
    if isinstance(source, str):
        return source  # 원시 텍스트 직접 전달
    raise FileNotFoundError(f"PMD report not found: {source!r}")


def parse_pmd_cpd(source: Union[str, bytes, Path]) -> PmdResult:
    """PMD CPD 텍스트 → PmdResult.

    Args:
        source: 리포트 경로/bytes/raw 텍스트.

    Returns:
        PmdResult. 'Found a' 블록 미발견 시 parse_warnings 누적.
    """
    result = PmdResult()
    text = _read_text(source)
    lines = text.splitlines()

    current: DuplicationBlock | None = None
    for line in lines:
        m = _FOUND_RE.search(line)
        if m:
            if current is not None:
                result.blocks.append(current)
            current = DuplicationBlock(lines=int(m.group(1)), tokens=int(m.group(2)))
            continue
        if current is not None:
            sm = _STARTING_RE.search(line)
            if sm:
                current.start_lines.append(int(sm.group(1)))
                current.files.append(sm.group(2).strip())
    if current is not None:
        result.blocks.append(current)

    if not result.blocks:
        result.parse_warnings.append(
            "PMD 'Found a N line (M tokens) duplication' 블록 미발견 — CPD 형식 확인 필요"
        )
    return result
