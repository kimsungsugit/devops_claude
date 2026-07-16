---
name: deploy-release
description: "**릴리스 풀체인** — 테스트 검증 → Docker 이미지 빌드 → 버전 태깅 → 배포까지 한 번에. 새 버전을 실제로 내보낼 때 씁니다. 빌드/태깅 없이 배포 실행·상태 확인만 하려면 `/deploy`를 쓰세요."
trigger: 릴리스, 새 버전 배포, Docker 이미지 빌드, 버전 태깅 요청 시
---

# /deploy-release 스킬

빌드, 배포, 릴리스 프로세스를 실행합니다.

## 배포 대상

### Docker
```bash
# 빌드
docker build -t devops-toolkit .

# 실행
docker run -p ${BACKEND_PORT:-9000}:${BACKEND_PORT:-9000} --env-file .env devops-toolkit

# 헬스 체크
curl -s http://localhost:${BACKEND_PORT:-9000}/api/health
```

### 로컬 개발 서버
```bash
# Backend
uvicorn backend.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-9000} --reload

# Frontend
cd frontend-v2 && npm run build && npm run preview
```

## 릴리스 체크리스트

### Pre-release
- [ ] 모든 테스트 통과 (`pytest tests/unit/ -v --timeout=60`)
- [ ] Frontend 빌드 성공 (`cd frontend-v2 && npm run build`)
- [ ] Docker 빌드 성공
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
