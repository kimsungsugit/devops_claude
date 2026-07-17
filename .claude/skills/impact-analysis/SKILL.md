---
name: impact-analysis
description: "로컬에서 impact_orchestrator의 ACTION_MATRIX로 C 함수 변경을 분류(SIGNATURE/BODY/NEW/DELETE/VARIABLE/HEADER)하고 **문서 재생성 여부를 판정**합니다. 백엔드 없이 동작하는 dry-run 성격. 서버에 실제 분석 잡을 걸어 진행률을 보려면 `/impact`를 쓰세요."
when_to_use: 재생성 판정, ACTION_MATRIX, 함수 변경 유형 분류, 로컬 dry-run 영향도 요청 시
---

# /impact-analysis 스킬

C 소스 코드 변경에 대한 영향도 분석을 수행하고 문서 재생성 여부를 판정합니다.

## 배경
- impact_orchestrator.py의 ACTION_MATRIX 기반
- 변경 유형(6종): SIGNATURE, BODY, NEW, DELETE, VARIABLE, HEADER
- 대상 문서: UDS, STS, SUTS, SITS, SDS

## 실행 순서

### 1. 변경 감지
```bash
# ⚠ 이 저장소(Release_claude)는 **git** 이다. 여기서 `svn status` 를 돌리면
#    `svn: warning: W155007: … is not a working copy` 로 항상 실패한다.
#    SVN 워킹카피는 분석 **대상**(config/scm_registry.json 의 source_root, 예:
#    D:/Project/Ados/PDS64_RD) 쪽이므로 반드시 거기서 실행할 것.
cd "<source_root>" && svn status | grep -E "\.[ch]$"
```
- 변경된 C/H 파일 목록 수집
- 함수 단위 변경 분류 (SIGNATURE/BODY/NEW/DELETE/**VARIABLE**/HEADER — 6종)

### 2. 영향도 분석
- `workflow/impact_orchestrator.py` 의 ACTION_MATRIX 참조
- call graph 탐색 (max_hop=2)
- 직접 영향 + 간접 영향 함수 식별

### 3. 문서 판정

**SSOT = `workflow/impact_orchestrator.py` 의 `ACTION_MATRIX`** — 아래는 그 사본이니
의심되면 코드에서 직접 읽을 것:
`.venv/Scripts/python.exe -c "from workflow.impact_orchestrator import ACTION_MATRIX; print(ACTION_MATRIX)"`

| 변경 유형 | UDS | SUTS | SITS | STS | SDS |
|-----------|-----|------|------|-----|-----|
| SIGNATURE | AUTO | AUTO | AUTO | FLAG | FLAG |
| BODY | AUTO | AUTO | AUTO | FLAG | **-** |
| NEW | AUTO | AUTO | AUTO | FLAG | FLAG |
| DELETE | AUTO | AUTO | AUTO | FLAG | FLAG |
| **VARIABLE** | AUTO | AUTO | AUTO | FLAG | **-** |
| HEADER | **AUTO** | FLAG | FLAG | FLAG | FLAG |

- **AUTO** = 자동 재생성. 단 `trigger.auto_generate=True` 일 때만 실행되고,
  아니면 런타임에 **FLAG 로 강등**된다 (`impact_orchestrator.py:34-35, 1659-1660`)
- **FLAG** = 검토 대상으로 표시(자동 생성 안 함)
- **`-`** = **액션 없음** (검토조차 아님)

> ⚠ 이 표는 오래 틀려 있었다: `HEADER×UDS` 를 review, `BODY×SDS`/`VARIABLE×SDS` 를 review,
> `NEW×STS` 를 AUTO 로 적었고 **`VARIABLE` 행이 통째로 없었다**. 무엇보다 코드엔
> **`review` 라는 값이 존재하지 않는다**(`AUTO`/`FLAG`/`-` 뿐) — `-`(액션 없음)를
> "review"로 적어 **없는 검토를 만들어냈다**.

### 4. 실행/보고
- `dry_run=false` 시 실제 문서 재생성
- audit log → `reports/impact_audit/`
- change log → `reports/impact_changes/`

## 출력
```markdown
# 영향도 분석 결과
- 분석일: {{date}}
- 변경 파일: {{count}}개

## 변경 함수
| 파일 | 함수 | 변경유형 | 직접영향 | 간접영향 |
|------|------|----------|----------|----------|

## 문서 판정
| 문서 | 판정 | 사유 |
|------|------|------|

## 다음 액션
- [ ] 자동 재생성 대상
- [ ] 수동 리뷰 대상
```

## 핵심 파일
- `workflow/impact_orchestrator.py` - 오케스트레이션 로직
- `report_gen/source_parser.py` - C 소스 파싱
- `report_gen/function_analyzer.py` - 함수 분석
- `config/scm_registry.json` — SCM 설정. **`registries` 는 리스트이고 현재 3개**
  (`hdpdm01`, `kjpds02`, `kjpds02_pv` — 전부 `scm_type: svn`). 리비전 필드는
  `last_revision` 이며 **현재 세 항목 다 빈 문자열**이다.
  (과거 "base rev 527" 표기는 필드명·값·개수가 전부 실제와 달랐다 — 수치를 고정
   기재하지 말고 필요하면 파일을 직접 읽을 것)
