# Admin 운영 가이드 (40차~)

> CLAUDE.md on-demand 레퍼런스 — admin/권한 작업 시 참조.
> 상세 JWT 운영 (생성/회복/검증): [`docs/rounds/auth_operations.md`](rounds/auth_operations.md)

| 시나리오 | 방법 |
|---------|------|
| 첫 admin 등록 | `.env`에 `BOOTSTRAP_ADMIN_USERS=user1,user2` 추가 → backend 가동 시 자동 |
| admin 추가 | admin이 `config/admin_users.json` 직접 편집 (mtime invalidate로 자동 반영) |
| admin 제거 | 동일 — json 편집 |
| Lockout 회복 | `config/admin_users.json` 수동 편집 + `.env` `BOOTSTRAP_ADMIN_USERS` 설정 + backend 재기동 |
| Frontend admin 모드 표시 | **탭마다 출처가 다르다** — 아래 §탭 표시 권한 참조 |
| 권한 동기화 | AdminContext가 `/api/auth/me` 호출 — 탭 visible 시 자동 refresh (41차) |

## 탭 표시 권한 (2026-08-04, §6 후보 24 파생)

`Ctrl+Shift+A` 토글(localStorage `devops_admin_mode`)이 **모든** admin 탭을 열던 것을
탭별로 갈랐다. 실권한은 backend `config/admin_users.json` 이라 둘이 어긋났다.

| 탭 | 표시 출처 | 왜 |
|---|---|---|
| **Quality** | backend `is_admin` (`/api/auth/me`) | 호출 3종이 전부 라우터 레벨 `require_admin`(`backend/routers/quality.py:16-20`)이라 비관리자에게 여는 것은 **100% false affordance** — 열어도 403 뿐이라 잃는 기능이 0이다 |
| **설정** | localStorage 토글 (현행 유지) | `health.py:233-239` 가 *"비-admin 이 직접 전환해야 한다"* 고 명시한 file-mode 를 담고 있고, doc paths·shared inputs 등 localStorage 로만 도는 기능도 있다. backend authority 로 옮기면 `/api/auth/me` 실패 시(AdminContext 는 실패를 `isAdmin:false` 로 접는다) **실제 기능이 잠긴다** |

- **`/api/auth/me` 응답 전**에는 localStorage 를 힌트로 쓴다(진짜 admin 이 RTT 만큼 탭이
  없다가 튀어나오는 것을 막는다). 힌트가 없으면 표시하지 않는다.
- **권한이 사라지면 보고 있던 뷰도 닫힌다** — 탭 목록에서 빼는 것만으로는 `activeTab`
  기준 렌더가 남아 화면이 그대로 보인다. 렌더 중 조정으로 대시보드에 돌린다.
- ⚠ 이건 **표시(UX/일관성)** 결정이지 보안 경계가 아니다. 실제 방어선은 backend
  `require_admin` 이고 위 변경은 그걸 건드리지 않는다.
- ⚠ `.env` `DEV_MODE_X_USER_FALLBACK=1` 이면 `X-User` 헤더 한 줄로 `is_admin` 이 통과한다
  (라이브 실증). 그 표면은 **별건**이고 이 항목으로 해소되지 않는다.
| 13 endpoint 보호 | SwIT 4 + SwUT 5 + file-mode 4 — 라우터 또는 endpoint dependency로 admin only |
