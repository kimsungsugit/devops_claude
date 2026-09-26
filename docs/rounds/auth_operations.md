# JWT 인증 운영 매뉴얼 (47차 W34/W36)

> 45차 commit `934d6bc`에서 JWT 인증 도입. 46차 commit `a1b9be9`에서 timing attack 차단.
> 47차 commit에서 refresh token revocation + 자동 refresh queue 추가.

## 첫 설치 (프로덕션)

### 1. JWT_SECRET 생성 및 설정 (W34 — 필수)

운영 환경에서 **반드시** `JWT_SECRET` env 변수 설정. 미설정 시 backend가 임시 random secret을 사용하며 **재기동마다 모든 토큰 무효화**되어 사용자가 매번 재로그인.

```bash
# Linux/macOS
openssl rand -base64 48 > /tmp/jwt_secret.txt
cat /tmp/jwt_secret.txt
# 출력값을 .env에 복사

# Windows PowerShell
[Convert]::ToBase64String((1..36 | ForEach-Object { Get-Random -Maximum 256 }))
```

`.env`:
```
JWT_SECRET=<base64 32바이트 이상>
JWT_ALGORITHM=HS256
JWT_ACCESS_EXPIRE_MINUTES=60
JWT_REFRESH_EXPIRE_DAYS=7
DEV_MODE_X_USER_FALLBACK=0
```

### 2. 첫 admin 사용자 등록 (lockout 회복)

빈 `config/users.json` + 두 env 설정 시 backend 가동 시 자동 등록:

```
BOOTSTRAP_ADMIN_USER=hbrnd2
BOOTSTRAP_ADMIN_PASSWORD=temp_password_changeme
BOOTSTRAP_ADMIN_USERS=hbrnd2
```

첫 로그인 시 `must_change_password=true`로 PW 변경 강제. 변경 후 정상 사용.

### 3. JWT_SECRET 변경 (긴급 상황)

비밀 노출 또는 보안 정책 갱신 시:

1. `.env`의 `JWT_SECRET` 값 변경
2. backend 재기동
3. **모든 사용자가 즉시 재로그인 필요** — 기존 토큰은 새 secret으로 decode 불가 (`TOKEN_INVALID` 401 응답)
4. frontend는 401 받으면 자동 logout + Login 화면 (47차 I5 자동 dispatch)

## 보안 동작 검증

### Timing attack (46차 W32) 검증

미존재 사용자와 잘못된 PW의 응답 시간이 비슷한지:

```bash
# 미존재 사용자
time curl -X POST http://localhost:9000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"nobody_xyz","password":"any_password"}'

# 등록된 사용자 + 잘못된 PW
time curl -X POST http://localhost:9000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"hbrnd2","password":"wrong"}'
```

두 응답 시간이 ~250ms 차이 이내면 정상 (bcrypt round 12). 미존재 사용자가 `<50ms`로 빠르게 거부되면 user enumeration leak — 즉시 fix 필요.

### W36 — Unknown user 응답 latency 안내

미존재 사용자 로그인은 정상적으로 ~250ms 소요. dummy bcrypt verify로 인한 의도된
지연 (user enumeration 차단). 사용자에게 "로그인 시도 시 1초 이내 응답"이라 안내 가능.

### Refresh token revocation (47차 W35) 검증

```bash
# 1. 로그인 + token 발급
TOKENS=$(curl -s -X POST http://localhost:9000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"hbrnd2","password":"actual_pw"}')
ACCESS=$(echo "$TOKENS" | jq -r '.access_token')
REFRESH=$(echo "$TOKENS" | jq -r '.refresh_token')

# 2. logout (token_version 증가)
curl -X POST http://localhost:9000/api/auth/logout \
  -H "Authorization: Bearer $ACCESS"
# {"ok":true,"username":"hbrnd2","revoked":true}

# 3. 기존 access로 호출 → TOKEN_REVOKED
curl http://localhost:9000/api/auth/admins \
  -H "Authorization: Bearer $ACCESS"
# {"ok":false,"error":{"code":"TOKEN_REVOKED",...}}

# 4. 기존 refresh로 갱신 → TOKEN_REVOKED (도난 토큰 차단)
curl -X POST http://localhost:9000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH\"}"
# {"ok":false,"error":{"code":"TOKEN_REVOKED",...}}
```

## 일상 운영

### Admin이 사용자 등록 (R48-a, 2026-09-14 — API·화면)

**설정 > 관리자 모드 > 👥 계정·승인자** 블록, 또는 API(전부 **JWT + admin** — X-User 만으로는 401):

```bash
# 생성 — 임시 비밀번호는 admin 이 정해 본인에게 직접 전달. 서버는 되돌려 주지 않고 첫 로그인에서 변경을 강제한다
curl -X POST http://127.0.0.1:9000/api/auth/users -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -d '{"username":"approver01","temp_password":"<8자 이상>","approver":true,"admin":false}'
# 목록(해시 없음) · 역할 · 삭제
curl http://127.0.0.1:9000/api/auth/users -H "Authorization: Bearer $ACCESS"
curl -X PUT http://127.0.0.1:9000/api/auth/users/approver01/roles -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" -d '{"approver":true}'
curl -X DELETE http://127.0.0.1:9000/api/auth/users/approver01 -H "Authorization: Bearer $ACCESS"
```

- 사용자 이름은 `[A-Za-z0-9._-]` 2~64자, 영문/숫자로 시작·끝, `..` 불가(캐시 경로 `{base}/{user}/` 에 들어가는 값이다).
- 자기 자신 삭제·admin 해제는 **409** `SELF_DELETE`/`SELF_DEMOTE`(lockout 방어 — 행위자가 admin 이라 남을 내려도 자기가 남으므로 '마지막 admin' 검사는 따로 두지 않는다). 삭제는 역할(admin·승인자)부터 지운다 — 같은 이름의 새 계정이 역할을 상속하지 않게.
- 계정·역할 변경은 `reports/account_audit.jsonl`(git 밖) 에 append-only 로 남는다 — "누가 누구에게 승인 권한을 줬나" 까지가 4-eyes 의 증거다. 승인자 목록 조회(`GET /api/auth/approvers`)는 admin 전용(검토 응답의 마스킹된 이름을 되맞히지 못하게).
- `config/users.json` 직접 편집도 여전히 동작한다(mtime invalidate). 그러나 bcrypt 해시를 손으로 만들 이유가 없어졌다.

### 승인자(approver) 역할 (R48-a)

검토 기록(`POST /api/review/runs/{id}`)은 **admin 또는 승인자**(`config/approvers.json`)만 남기고, **자기가 만든 run 은
누구도 판정할 수 없다**(`generation_runs.created_by` ↔ 검토자, 403 `SELF_REVIEW`). 그래서 문서를 생성하는 계정과 다른
승인자 계정이 하나 이상 있어야 승인 절차가 성립한다. 게시(`POST /api/jenkins/uds/publish`)는 그 파일 바이트에
`approved` 기록이 있어야 한다(409 `NOT_APPROVED`).

### Admin 권한 부여 (40차 admin_users.json)

```bash
# config/admin_users.json 직접 편집
{
  "admins": ["hbrnd2", "another_admin"],
  "schema_version": 1
}
```

mtime invalidate로 자동 반영. backend 재기동 불필요.

### 사용자 강제 logout (boot-out)

admin이 다른 사용자의 모든 토큰을 즉시 무효화:

```python
# Python REPL or admin script
from backend.services.users import increment_token_version
increment_token_version("compromised_user")
# → 해당 user의 access/refresh 모두 TOKEN_REVOKED
```

향후 admin API 추가 예정 (`POST /api/auth/admins/revoke/{username}`).

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 모든 사용자가 즉시 재로그인 요구 | JWT_SECRET 변경 또는 backend 재기동 (secret 미설정 시) | 정상 동작. `JWT_SECRET` 영구 설정 |
| 로그인 후 즉시 401 | system clock 차이로 iat/exp 검증 실패 | NTP 동기화 |
| TOKEN_REVOKED 빈번 발생 | logout 또는 PW 변경 후 client 캐시 미갱신 | 47차 I5 — frontend 자동 logout dispatch. 구버전 client는 강제 새로고침 |
| 첫 로그인 latency 길음 | dummy hash warmup 미실행 | `main.py` startup hook 호출 확인 |
| 한국어 password 일부만 인식 | bcrypt 72-byte limit | 47차 W33 PasswordHint UI 안내 — 24자 이하 권장 |

## 비상 회복

### Admin lockout (모든 admin 토큰 무효)

1. `.env`에 `BOOTSTRAP_ADMIN_USERS=hbrnd2` + `BOOTSTRAP_ADMIN_USER=hbrnd2` + `BOOTSTRAP_ADMIN_PASSWORD=<temp>` 설정
2. `config/users.json` 백업 후 빈 list로 초기화 (`{"users": [], "schema_version": 1}`)
3. `config/admin_users.json` 백업 후 빈 list (`{"admins": [], "schema_version": 1}`)
4. backend 재기동 → startup이 bootstrap 호출 → 첫 admin 등록 + admin role 부여
5. 임시 PW로 로그인 → must_change_password=true → 영구 PW 설정

### JWT_SECRET 분실 (운영 사고)

JWT_SECRET을 잃어버리면 기존 토큰은 모두 무효. 모든 사용자 재로그인. 사용자 데이터(password_hash)는 그대로 유효 — 로그인만 다시 하면 정상 복구.

## 모니터링 권장

- 401 응답 빈도 (특히 TOKEN_REVOKED) — 도난 시도 또는 client 버그
- login 응답 시간 — 250ms 미만이면 timing safety 깨짐 의심
- refresh 호출 빈도 — 정상은 access expire (60분)마다. 그 이상이면 client 버그
