# Admin 운영 가이드 (40차~)

> CLAUDE.md on-demand 레퍼런스 — admin/권한 작업 시 참조.
> 상세 JWT 운영 (생성/회복/검증): [`docs/rounds/auth_operations.md`](rounds/auth_operations.md)

| 시나리오 | 방법 |
|---------|------|
| 첫 admin 등록 | `.env`에 `BOOTSTRAP_ADMIN_USERS=user1,user2` 추가 → backend 가동 시 자동 |
| admin 추가 | admin이 `config/admin_users.json` 직접 편집 (mtime invalidate로 자동 반영) |
| admin 제거 | 동일 — json 편집 |
| Lockout 회복 | `config/admin_users.json` 수동 편집 + `.env` `BOOTSTRAP_ADMIN_USERS` 설정 + backend 재기동 |
| Frontend admin 모드 표시 | `Ctrl+Shift+A` 키보드 토글 또는 Settings 페이지 AdminSection |
| 권한 동기화 | AdminContext가 `/api/auth/me` 호출 — 탭 visible 시 자동 refresh (41차) |
| 13 endpoint 보호 | SwIT 4 + SwUT 5 + file-mode 4 — 라우터 또는 endpoint dependency로 admin only |
