# ARIA 배포 가이드

## 시나리오 A: 서버 PC 한 대 (권장)

백엔드 + 프론트엔드를 한 PC에서 실행, 다른 사용자들은 브라우저로 접속.

### 1. 사전 준비
```bash
# 프론트엔드 빌드
cd frontend-v2
npm install
npm run build
cd ..
```

### 2. 허용 사용자 설정
`config/allowed_users.json`:
- `[]` → 내부망 전체 허용
- `["alice", "bob"]` → 지정 사용자만

### 2-1. 관리자 설정 (Jenkins 연결 설정 저장 권한)
`config/admins.json`:
- **파일 없음** → 부트스트랩 모드 (누구나 저장 가능 — 첫 관리자 지정 후 파일 생성 권장)
- `["kimsungsu"]` → 지정한 사용자만 서버 Jenkins 설정 변경 가능

관리자만 볼 수 있는 "설정" 탭 노출:
```javascript
// 브라우저 DevTools Console에서:
localStorage.setItem('devops_admin_mode', 'true');
// 페이지 새로고침 → "설정" 탭 표시
```

관리자가 Settings → Jenkins 섹션 → "서버에 저장" 클릭 → 모든 사용자가 자동 공유.

### 3. Docker Compose 기동
```bash
docker-compose up -d
docker-compose logs -f aria-backend
```

### 4. 접속
- 서버 PC: `http://localhost`
- 다른 PC: `http://{서버 PC IP}` (예: `http://192.168.110.144`)

### 5. 방화벽 (Windows)
```powershell
# 관리자 PowerShell
New-NetFirewallRule -DisplayName "ARIA HTTP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
```

### 6. 포트 변경 (선택)
80 포트가 사용 중이면:
```bash
FRONTEND_PORT=8080 docker-compose up -d
```

---

## 시나리오 B: 백엔드/프론트엔드 분리 PC

### PC-A: 프론트엔드
```bash
cd frontend-v2
npm run build
# dist/config.js 편집 → API URL 지정
```
`dist/config.js`:
```javascript
window.__ARIA_API_BASE__ = 'http://192.168.1.100:9000';  // PC-B 주소
```
정적 파일 서빙:
```bash
# Python 간단 서버
cd dist && python -m http.server 80
# 또는 nginx, IIS 등
```

### PC-B: 백엔드
```bash
# Docker (프론트엔드 서비스 비활성화)
docker-compose up -d aria-backend

# 또는 직접 실행
python -m uvicorn backend.main:app --host 0.0.0.0 --port 9000
```

**주의**: 시나리오 B는 9000 포트를 외부에 노출해야 합니다. `docker-compose.yml`의 `ports: "9000:9000"` 주석 해제.

---

## 배포 전 체크리스트

- [ ] `frontend-v2/dist/` 빌드 완료
- [ ] `config/allowed_users.json` 설정
- [ ] 서버 PC에서 Jenkins(`192.168.110.40:7000`) 접근 가능 확인
- [ ] SCM 로컬 저장소 경로(Git/SVN)가 서버 PC에 있는지 확인
- [ ] 방화벽에서 80 포트 (또는 설정 포트) 허용
- [ ] `.env` 파일 존재 여부 (필요시 `.env.example` 복사)

---

## 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| `Cannot GET /` | 프론트엔드 빌드 안 됨 | `cd frontend-v2 && npm run build` |
| 401 Unauthorized | X-User 헤더 없음 | 로그인 화면에서 사용자명 입력 |
| 403 Forbidden | allowed_users에 없음 | `config/allowed_users.json` 편집 또는 `[]`로 변경 |
| 진행률 안 움직임 | SSE 버퍼링 | nginx.conf의 `proxy_buffering off` 확인 |
| 빌드 정보 못 찾음 | Jenkins 접근 불가 | 서버 PC → Jenkins 네트워크 확인 |

---

## 보안 권장사항 (프로덕션)

1. **HTTPS 적용**: Let's Encrypt 또는 내부 인증서
2. **백엔드 직접 노출 차단**: docker-compose에서 `ports` 대신 `expose` 사용 (이미 적용됨)
3. **방화벽**: 외부망 차단, 내부망만 허용
4. **JWT 인증 도입**: X-User 헤더 대신 (Phase 2)
5. **로그 모니터링**: `docker-compose logs` 또는 ELK/Loki
