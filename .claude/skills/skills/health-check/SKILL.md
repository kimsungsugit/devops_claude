---
name: health-check
description: "백엔드/프론트엔드 서비스 상태를 점검합니다."
---

# 서비스 헬스체크 스킬

## 수행 절차

1. **백엔드 상태 확인**
   ```bash
   curl -s http://127.0.0.1:8000/api/health 2>/dev/null || echo "Backend DOWN"
   ```

2. **프론트엔드 상태 확인**
   ```bash
   curl -s http://localhost:5174/ 2>/dev/null | head -5 || echo "Frontend DOWN"
   ```

3. **프로세스 확인**
   ```bash
   tasklist | grep -i -E "python|node|uvicorn" || echo "No related processes"
   ```

4. **최근 로그 확인** (있으면)
   - `backend/logs/` 디렉토리 확인
   - 최근 에러 로그 추출

5. **Git 상태**
   ```bash
   git status --short
   git log --oneline -5
   ```

6. **결과 요약**
   ```
   Backend:  [UP/DOWN] (port 8000)
   Frontend: [UP/DOWN] (port 5174)
   Tests:    [PASS/FAIL] (최근 실행)
   Git:      [clean/dirty] (branch: xxx)
   ```
