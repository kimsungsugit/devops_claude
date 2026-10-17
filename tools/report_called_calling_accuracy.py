"""가장 최근 로컬 UDS 산출물의 Called/Calling accuracy 리포트를 만드는 독립 CLI.

(R56 리뷰 W1) 예전엔 `D:\\Project\\devops\\260105` 를 sys.path 에 넣고 **그 트리의 `report_generator`** 를 import 했다 —
2026-03-12 스냅샷이라 대응표(`validation_labels`)도 없는 옛 리더/비교기였고, 이 도구로 R56 이후 문서를 재면 결론이 뒤집힌다.
이 저장소의 `report_gen` 을 쓴다.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from report_gen.validation import generate_called_calling_accuracy_report  # noqa: E402

DEFAULT_SOURCE_ROOT = Path(r"D:\Project\Ados\PDS_64_RD")


def main() -> None:
    # 산출 디렉터리 기본값은 여기(함수 안)에서 — 모듈 상수로 두면 `reports/` 격리 가드(`test_report_dirs_are_isolated`)가
    #   테스트 쓰기 대상으로 세는데, 이 CLI 는 테스트가 import 만 할 뿐 실행하지 않는다.
    report_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "backend" / "reports" / "uds_local"
    source_root = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SOURCE_ROOT
    docx_files = sorted(report_dir.glob("uds_spec_generated_expanded_*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not docx_files:
        raise FileNotFoundError(f"No generated UDS docx found in {report_dir}")
    target_doc = docx_files[0]
    out = report_dir / "called_calling_accuracy_latest.md"
    # 독립 CLI — 문서를 만든 분석이 손에 없다. `source_sections=None` 은 **의도한 재분석**이고, 리포트 머리글이
    #   "Expected side: re-analysis of source_root … may differ" 로 그 사실을 적는다(생성 경로 넷은 전부 파이프라인 분석을 넘긴다).
    report_path = generate_called_calling_accuracy_report(
        str(target_doc),
        str(source_root),
        str(out),
        relation_mode="code",
        source_sections=None,
    )
    print(report_path)


if __name__ == "__main__":
    main()
