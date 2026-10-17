---
name: health-check
description: "기동 상태 점검 — 백엔드(:9000)/프론트(:5174) 응답, 관련 프로세스, DB 파일(`reports/*.sqlite`) 접근, git 상태를 한 번에 확인합니다."
when_to_use: 서버 떠 있나, 백엔드 살아있나, 상태 점검, 헬스체크, 포트 확인, 왜 연결이 안되지, 기동 확인 요청 시
---

# 서비스 헬스체크 스킬

## 수행 절차

1. **백엔드 상태 확인**
   ```bash
   curl -s http://127.0.0.1:${BACKEND_PORT:-9000}/api/health 2>/dev/null || echo "Backend DOWN"
   ```

2. **프론트엔드 상태 확인**
   ```bash
   curl -s http://localhost:${FRONTEND_PORT:-5174}/ 2>/dev/null | head -5 || echo "Frontend DOWN"
   ```

3. **프로세스 확인**
   ```bash
   tasklist 2>/dev/null | grep -i -E "python|node|uvicorn" || ps aux 2>/dev/null | grep -E "python|node|uvicorn" || echo "No related processes"
   ```

4. **최근 로그 확인** (있으면)
   - `${LOG_DIR:-backend/logs/}` 디렉토리 확인
   - 최근 에러 로그 추출

5. **데이터베이스 상태 확인**
   ```bash
   ls -l reports/quality.sqlite reports/chat_history.sqlite 2>/dev/null
   ```
   - **Quality DB = `reports/quality.sqlite`** (`workflow/quality/db.py:24` +
     `config.py:39 DEFAULT_REPORT_DIR="reports"`). ⚠ `workflow/quality/` 는
     **파이썬 패키지**(db/models/advisor/evaluator/recorder.py)이고 DB 파일은 0건이다
   - 접근 확인은 실제 조회로:
     `.venv/Scripts/python.exe -c "from workflow.quality.db import init_db, get_session; init_db(); print('quality DB OK')"`
   - ⚠ **마이그레이션 상태 점검은 대상이 없다** — alembic 도 migrations/ 도 없고
     `init_db()` 는 `create_all(checkfirst=True)` 뿐이다

6. **Git 상태**
   ```bash
   git status --short
   git log --oneline -5
   ```

7. **결과 요약**
   ```
   Backend:  [UP/DOWN] (port ${BACKEND_PORT:-9000})
   Frontend: [UP/DOWN] (port ${FRONTEND_PORT:-5174})
   Database: [OK/ERROR] (파일 크기, 마지막 수정)
   Tests:    [PASS/FAIL] (최근 실행)
   Git:      [clean/dirty] (branch: xxx)
   ```
