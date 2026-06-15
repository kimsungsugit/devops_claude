# backend/services — 빌더 코드 제약 (nested, lazy load)

> 이 디렉토리 파일을 읽거나 편집할 때 자동 로드되는 제약. SwUT/SwIT 빌더 구현 작업 시 항상 준수.
> 전체 빌더 설계: [`docs/builders/swut_builder.md`](../../docs/builders/swut_builder.md) · [`docs/builders/swit_builder.md`](../../docs/builders/swit_builder.md)

## 하드 제약
- **Cloudium worker는 read-only** — 절대 cloudium 파일 생성/수정 금지 (사용자 의사결정). worker(8765) TCP IPC로 read/browse만 위임.
- **Design Token 단일 출처**: RGB / placeholder는 `design_tokens.py`에서만 정의. 신규 Excel builder는 반드시 거기서 import (module-level hardcode 금지). 변경 시 [`docs/builders/visual-marking-and-design-tokens.md`](../../docs/builders/visual-marking-and-design-tokens.md) + audit reviewer 통보 의무.
- **ASIL Source 우선순위**: `c_source_root` > `swuds_docx_path` > 없음. 충돌 시 c_source 우선 + `parse_warnings`에 사유 누적.
- **안전 관련(ASIL C/D) 함수 변경 시**: reviewer 리뷰 필수, 테스트 자동 수정 금지.

## Reload 의무
- `backend/services/*.py` / `routers/*.py` / `schemas.py` / `main.py` 변경 후 **uvicorn 재시작 필수** — stale 코드로 PoC/endpoint 결과 오염.
- `config/swut_meta.json`은 lru_cache + mtime invalidate로 자동 반영 (재시작 불필요).
- 상세 절차/영향 매트릭스: [`docs/builders/swut_builder.md`](../../docs/builders/swut_builder.md) `## Backend Reload 절차`.

## 동시성
- Coverage/SUTR/SITR 빌드는 Semaphore 공유 (SwUT capacity 3 / SwIT 2). worst-case 메모리 ≈ 12.6MB — 한도 내이나 신규 동시 작업 추가 시 재평가.
