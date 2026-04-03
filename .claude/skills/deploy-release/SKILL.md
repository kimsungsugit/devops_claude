---
name: deploy-release
description: Docker 빌드, CI/CD 파이프라인, 버전 태깅, 릴리스 준비를 수행합니다.
trigger: 배포, 릴리스, Docker, 버전, 태깅, CI/CD 파이프라인 실행 요청 시
---

# /deploy-release 스킬

빌드, 배포, 릴리스 프로세스를 실행합니다.

## 배포 대상

### Docker
```bash
# 빌드
docker build -t devops-toolkit .

# 실행
docker run -p 7000:7000 -e GOOGLE_API_KEY=$GOOGLE_API_KEY devops-toolkit

# 헬스 체크
curl -s http://localhost:7000/api/health
```

### 로컬 개발 서버
```bash
# Backend
uvicorn backend.main:app --host 0.0.0.0 --port 7000 --reload

# Frontend
cd frontend && npm run build && npm run preview
```

## 릴리스 체크리스트

### Pre-release
- [ ] 모든 테스트 통과 (`pytest tests/unit/ -v --timeout=60`)
- [ ] Frontend 빌드 성공 (`cd frontend && npm run build`)
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
- 통과: {{n}}/253

## 체크리스트
- [ ] 항목별 통과 여부

## 배포 명령어
{{실행할 명령어 목록}}
```
