---
name: health-check
description: "백엔드/프론트엔드 서비스 상태를 점검합니다."
---

# 서비스 헬스체크 스킬

## 수행 절차

1. **백엔드 상태 확인**
   ```bash
   curl -s http://127.0.0.1:${BACKEND_PORT:-8000}/api/health 2>/dev/null || echo "Backend DOWN"
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
   - SQLite DB 파일 존재 여부 및 크기 확인
   - Quality DB (`workflow/quality/`) 접근 가능 여부 확인
   - DB 마이그레이션 상태 점검

6. **Git 상태**
   ```bash
   git status --short
   git log --oneline -5
   ```

7. **결과 요약**
   ```
   Backend:  [UP/DOWN] (port ${BACKEND_PORT:-8000})
   Frontend: [UP/DOWN] (port ${FRONTEND_PORT:-5174})
   Database: [OK/ERROR] (파일 크기, 마지막 수정)
   Tests:    [PASS/FAIL] (최근 실행)
   Git:      [clean/dirty] (branch: xxx)
   ```
