---
name: debug-diagnose
description: 버그, 오류, 성능 이슈를 체계적으로 진단합니다. 실제 에러 패턴, 로그 경로, 장애 분류 코드 내장.
trigger: 버그, 오류, 에러, 안됨, 실패, 느림, hanging, 크래시, 트러블슈팅 요청 시
---

# /debug-diagnose 스킬

## 로그 파일 위치
```
서버 로그:     .codex_tmp/backend_uvicorn*.err.log
시스템 로그:   reports/system.log
파이프라인 로그: reports/pipeline.log
임팩트 감사:   reports/impact_audit/impact_*.json
임팩트 변경:   reports/impact_changes/
잡 상태:       reports/impact_jobs/
```

## 에러 분류 코드 (impact_jobs.py _classify_exception)
| 코드 | 조건 | 재시도 |
|------|------|--------|
| `file_not_found` | FileNotFoundError | X |
| `registry_not_found` | "registry entry not found" | X |
| `svn_connection_error` | "e170013", "not a working copy" | O |
| `git_connection_error` | "not a git repository" | O |
| `impact_exception` | 기타 catch-all | O |

## 잡 상태 흐름
`queued` → `running` → `completed` | `failed`
- 동시 실행 차단: `active_lock` (FileLock, 5초 timeout)
- heartbeat: 15초 간격 keep-alive
- stale lock 감지: PID + thread_id 생존 확인

## 알려진 이슈 패턴

### 1. test_impact_jobs hanging
- **파일**: `tests/unit/test_impact_jobs.py`
- **CI 처리**: GitHub Actions에서 `--ignore` 제외, GitLab은 15분 timeout
- **원인**: 백그라운드 스레드 동기화, _wait_for_job() 10초 하드 timeout
- **진단**: `pytest tests/unit/test_impact_jobs.py -v --timeout=30`

### 2. Impact orchestrator RuntimeError
- **파일**: `workflow/impact_orchestrator.py`
- `line 452`: "UDS regeneration failed: {stderr}"
- `line 464`: "SUTS regeneration requires source_root"
- `line 508`: "SITS regeneration requires source_root"
- `line 550`: "unsupported AUTO target: {target}"
- 모두 subprocess.run() 3600초 timeout

### 3. Lock 충돌
- **파일**: `workflow/impact_audit.py`
- **Lock 경로**: `reports/impact_audit/.run_lock`
- **증상**: `{"ok": false, "reason": "active_lock"}`
- **해결**: stale lock 확인 후 수동 삭제 또는 기존 잡 완료 대기

### 4. 파이프라인 공통 경고
```
[Step 0] Preflight: missing tools -> clang_tidy
⚠️ SCM unavailable (git=not_git_repo, svn=not_svn_wc), falling back to full scan
❌ [Step 3] Build failed: reason=config_fail
⚠️ QEMU WARN (RP2040 Soft-Fail)
```

### 5. FastAPI 글로벌 예외 핸들러
- **파일**: `backend/main.py` (line 74-92)
- 모든 미처리 예외를 500으로 반환, detail 300자 truncate
- 로거: `_api_logger.error()`

### 6. Impact Router HTTP 에러
- **파일**: `backend/routers/impact.py`
- `400`: missing source_root, missing changed_files
- `500`: json output not found, json parse failed

## 진단 프로세스
1. **증상 수집**: 에러 메시지, 로그 파일 확인
2. **분류**: 위 에러 코드/패턴과 매칭
3. **범위 축소**: `git log --oneline -10 --name-only` + grep
4. **재현**: 최소 재현 케이스 → pytest 단일 테스트
5. **수정 → 검증**: `python -m pytest tests/unit/ -q --tb=short`
