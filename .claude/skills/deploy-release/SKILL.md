---
name: deploy-release
description: "**릴리스 준비** — 사전 체크리스트(테스트/프론트 빌드/.env.example/CHANGELOG) 검증 후 **버전 태깅**(git tag v1.x.x)까지. 새 버전을 끊을 때 씁니다. 태깅 없이 push→파이프라인 트리거·상태 확인만 하려면 `/deploy`를 쓰세요."
trigger: 릴리스, 새 버전 끊기, 버전 태깅, 릴리스 전 체크리스트 요청 시
---

# /deploy-release 스킬

빌드, 배포, 릴리스 프로세스를 실행합니다.

## 배포 대상

### ⚠ Docker — **현재 미사용 (2026-07-17 확인)**

과거 검토했다가 채택하지 않았다. **릴리스 절차에서 docker build 를 하지 말 것.**
근거: CI(`.github/workflows/ci.yml`=syntax-check+unit-tests, `.gitlab-ci.yml`=lint/test/frontend)
어디에도 docker 스텝이 없고, 실제 기동은 `start.bat`(+`backend\.venv`)이다.
또한 이미지가 `python:3.12-slim`(apt: git/curl/subversion만)이라 **tkinter 가 없어
파일 선택(`/api/file-mode/browse-file`, 프론트 4곳 사용)이 동작하지 않고**,
cloudium worker(`127.0.0.1:8765`)도 컨테이너 localhost라 사용자 PC에 닿지 않는다.
되살리려면 이 두 가지부터 해결해야 한다.

<details><summary>참고용 명령 (미사용)</summary>

```bash
docker build -t devops-toolkit .
docker run -p ${BACKEND_PORT:-9000}:${BACKEND_PORT:-9000} --env-file .env devops-toolkit
curl -s http://localhost:${BACKEND_PORT:-9000}/api/health
```
</details>

### 로컬 개발 서버
```bash
# Backend
# canonical = backend\.venv (scripts/start.bat:15-18). 맨 uvicorn 은 mingw 것이라
# bcrypt 미설치 → auth_service import 에서 앱 전체가 죽는다.
backend/.venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-9000} --reload

# Frontend
cd frontend-v2 && npm run build && npm run preview
```

## 릴리스 체크리스트

### Pre-release
- [ ] 모든 테스트 통과 (`.venv/Scripts/python.exe -m pytest tests/unit/ -q --timeout=90` — 전체 약 4분 40초)
- [ ] Frontend 빌드 성공 (`cd frontend-v2 && npm run build`)
- [ ] .env.example 최신화
- [ ] CHANGELOG 갱신

### Version tagging
```bash
# Semantic versioning
git tag -a v1.x.x -m "Release v1.x.x: 설명"
git push origin v1.x.x
```

### CI/CD 검증
```bash
# GitLab CI 상태 확인
# GitHub Actions 상태 확인
gh run list --limit 5
```

## 출력
```markdown
# 릴리스 준비 상태

## 빌드
| 대상 | 상태 | 비고 |
|------|------|------|

## 테스트
- 통과: {{n}}/{{total}}

## 체크리스트
- [ ] 항목별 통과 여부

## 배포 명령어
{{실행할 명령어 목록}}
```
