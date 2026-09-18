# AGENTS.md — CLAUDE.md 참조 스텁

이 저장소의 에이전트 / 운영 / 안전 지침 **단일 출처(SSOT)는 [`CLAUDE.md`](CLAUDE.md)**다.
AGENTS.md는 `AGENTS.md`를 읽는 일부 에이전트 런타임과의 호환을 위한 **얇은 스텁**이며 정책 본문을 담지 않는다.
모든 규칙·에이전트 표·훅·스킬·워크플로우는 `CLAUDE.md`, `.claude/rules/*.md`(always-on import),
`.claude/agents/*`, `.claude/skills/*`를 따른다.

## ISO 26262 추적성 (요약 — 상세·근거는 CLAUDE.md)

V-model 수평쌍 (좌 설계 ↔ 우 검증):

```
SyRS (시스템 요구)        ─────►  SyTS  (시스템 시험)
HSIS (HW-SW 인터페이스)   ─────►  SyITS (시스템 통합시험)
SDS  (SW 아키텍처 설계)   ─────►  SITS  (SW 통합시험)
UDS  (단위 상세 설계)     ─────►  SUTS  (SW 단위시험)
Source (소스코드)         ─────►  VectorCAST (실행 결과)
```

⚠ 라벨 주의: **SUTS = SW 단위시험, SITS = SW 통합시험, SyITS = 시스템 통합시험, SyTS = 시스템 시험.**
과거 'SUTS=SW통합 / SITS=시스템통합' 표기는 **오류였음**. SW 요구(SRS/SwRS)가 추적 허브다.

> 정책을 바꾸려면 이 파일이 아니라 `CLAUDE.md` / `.claude/rules/` / `.claude/agents/`를 편집할 것.
> (이 스텁은 과거 Codex 시절 671줄 복제본을 대체한 것으로, 드리프트·라벨 모순 방지가 목적이다.)
