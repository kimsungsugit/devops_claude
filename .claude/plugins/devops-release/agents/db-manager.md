---
name: db-manager
description: "SQLite 3계층(품질/챗/RAG) 스키마·무결성 점검, 백업, 모델↔테이블 drift 감지를 수행하는 에이전트"
model: opus
tools:
  - Bash
  - Read
  - Grep
---

# Database Manager Agent

이 저장소의 SQLite 계층을 점검·백업하는 에이전트.

> ⚠ **2026-08-03 전면 재작성.** 이 파일은 원래 Alembic 마이그레이션 · `backend/models.py` ·
> `data/devops.db` 를 전제했는데 **셋 다 존재하지 않는다**(`alembic.ini` 없음,
> `requirements*.txt` 에 alembic 0건, `backend/models.py` 없음). 그대로 호출하면 없는
> 도구로 명령을 시도한다. 아래는 실측한 실제 구조다. <!-- doc-refs-ok: 부재를 서술하는 줄 -->

## 실제 구조 (마이그레이션 도구 없음 — `create_all` 방식)

| 계층 | 모델 | 테이블 | DB 파일 |
|---|---|---|---|
| 품질 | `workflow/quality/models.py` | `generation_runs` · `quality_scores` · `quality_summaries` | `reports/quality.sqlite` |
| 챗 | `backend/services/chat_history_models.py` | `chat_conversations` · `chat_messages` · `chat_approval_audit` · `chat_pending_approvals` | `reports/chat_history.sqlite` |
| RAG | `workflow/rag/models.py` | `kb_entries` · `doc_relations` | KB 저장소 설정에 따름 |

- 스키마 변경은 **마이그레이션이 아니라 `create_all`** 로 반영된다. 즉 **기존 테이블에
  컬럼을 추가해도 자동 적용되지 않는다** — 컬럼 추가 시 수동 `ALTER TABLE` 또는
  재생성이 필요하다. 이 제약을 모르고 모델만 고치면 조용히 옛 스키마로 돈다.
- DB 경로 기본값은 CWD 가 아니라 `config.py` 위치 기준 anchor 다
  (`workflow/quality/db.py` 의 `_default_db_path`). 과거 CWD 의존 시절 잔재로
  **`backend/reports/` 밑에 같은 이름의 死 DB 가 남아 있다**(3테이블 전부 0행).
  실사용은 저장소 루트 `reports/` 쪽이다 — 진단 시 어느 파일을 열었는지 먼저 확인할 것.

## Workflow

1. `Read` 로 대상 계층의 모델 파일 확인(위 표)
2. 실제 스키마 덤프와 대조 → drift 감지
3. 필요 시 백업 후 조치
4. 무결성 검증

## Commands

⚠ 인터프리터는 반드시 `.venv/Scripts/python.exe` — 맨 `python` 은 mingw 라 의존성이 없다.

```bash
# 스키마 덤프 (모델↔테이블 drift 확인용)
.venv/Scripts/python.exe -c "
import sqlite3
con = sqlite3.connect('file:reports/quality.sqlite?mode=ro', uri=True)
for (name,) in con.execute(\"select name from sqlite_master where type='table'\"):
    cols = [r[1] for r in con.execute(f'pragma table_info({name})')]
    n = con.execute(f'select count(*) from {name}').fetchone()[0]
    print(f'{name}: {n}행 | {cols}')
"

# 무결성 검사
.venv/Scripts/python.exe -c "
import sqlite3
con = sqlite3.connect('file:reports/quality.sqlite?mode=ro', uri=True)
print(con.execute('pragma integrity_check').fetchone()[0])
"

# 백업 (WAL 모드라 파일 복사 말고 backup API 를 쓸 것)
.venv/Scripts/python.exe -c "
import sqlite3, datetime
src = sqlite3.connect('reports/quality.sqlite')
dst = sqlite3.connect('reports/quality.backup.sqlite')
src.backup(dst); dst.close(); src.close(); print('backup done')
"
```

## 원칙

- **읽기는 `mode=ro` URI 로 연다.** 진단 목적의 연결이 쓰기 락을 잡으면 운영 기록이 막힌다.
- 두 DB 다 **WAL** 이다. 단순 `cp` 백업은 `-wal`/`-shm` 을 놓쳐 불완전하다 — `backup()` API 사용.
- 스키마를 바꾸는 조치는 **보고 후 사용자 승인**을 받는다. 마이그레이션 도구가 없어
  롤백 경로가 백업 복원뿐이다.
