# Onboarding / Setup

새 머신에서 처음 클론한 뒤 4차 세션(2026-04-30)에 정비된 hook/검증 정책이 정상 동작하려면 다음 절차를 한 번 실행해야 한다.

## Prerequisites

| 도구 | 권장 버전 | 비고 |
|------|----------|------|
| Python | **CPython 3.12** | mingw python(3.13) 기반 venv는 wheel 부재로 pydantic v2 / pandas 빌드 실패 — 4차 세션 부검 결과 |
| Node.js | 18+ | vite/vitest 동작 |
| git | 2.30+ | `core.hooksPath` 설정 사용 |
| bash | git-bash 또는 msys2 | hook 실행에 필요 (Windows) |

## 1. Clone

```bash
git clone <repo-url> Release_claude
cd Release_claude
```

## 2. Python venv

```bash
# CPython 3.12 명시 (mingw python 사용 금지 — 4차 세션 부검 W2)
py -3.12 -m venv .venv      # Windows
# python3.12 -m venv .venv  # Linux/Mac

# Windows
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install -r requirements.txt -r backend/requirements.txt

# Linux/Mac
# .venv/bin/python -m pip install --upgrade pip
# .venv/bin/python -m pip install -r requirements.txt -r backend/requirements.txt
```

## 3. Frontend deps

```bash
cd frontend-v2
npm install
cd ..
```

## 4. Git hooks 활성화

```bash
bash scripts/install_git_hooks.sh
```

이 스크립트는:
- `git config core.hooksPath .githooks` 설정 → `.githooks/*`가 hook으로 동작
- `.git/hooks/*`에 동명 legacy hook이 있으면 자동 삭제 (divergence 방지)

**자동화**: `.claude/settings.json`의 `SessionStart` hook이 Claude Code 세션 시작 시 자동으로 위 명령을 실행한다 (이미 설정 안 된 경우만). 따라서 Claude Code로 작업한다면 이 단계는 자동.

## 5. (선택) Backend dev server

```bash
.venv/Scripts/python.exe -m uvicorn backend.main:app --reload --port 9000
```

## 6. (선택) Frontend dev server

```bash
cd frontend-v2 && npm run dev   # http://localhost:5174
```

## 검증

```bash
# Backend pytest (Windows; Linux/Mac은 .venv/bin/python)
.venv/Scripts/python.exe -m pytest tests/unit/ -q     # 1379 tests

# Frontend vitest
cd frontend-v2 && npx vitest run                       # 186 tests

# Pre-commit hook 검증 (안전 — empty commit 사용)
git commit --allow-empty -m "test hook"
# hook이 통과하면 커밋이 생성됨. 검증 후 즉시 롤백:
git reset --hard HEAD~1
```

## 자주 발생하는 문제

### `ModuleNotFoundError: No module named 'numpy'` (또는 pydantic 등) on commit
- 원인: `.venv`가 mingw python으로 생성됨 → pydantic-core 빌드 실패로 v1로 다운그레이드되거나 패키지 누락
- 조치: `rm -rf .venv && py -3.12 -m venv .venv && pip install -r requirements.txt -r backend/requirements.txt`

### Pre-commit hook이 동작 안 함
- 원인: `core.hooksPath`가 `.githooks`로 설정 안 됨
- 조치: `bash scripts/install_git_hooks.sh`

### `bash: ./scripts/install_git_hooks.sh: /bin/bash^M: bad interpreter`
- 원인: Windows clone 시 `core.autocrlf`가 *.sh 를 CRLF로 변환
- 조치: `.gitattributes`가 LF 강제하므로 `git rm --cached scripts/install_git_hooks.sh && git checkout scripts/install_git_hooks.sh`로 재정규화
