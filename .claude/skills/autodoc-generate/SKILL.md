---
name: autodoc-generate
description: "**별도 트리(`D:/Project/Program/AutoDoc`)** 의 발표·공유용 산출물 생성 — PPTX, Reveal.js 슬라이드, 프로젝트 포털, API 문서. 다국어 코드 분석 + RAG 통합. 이 저장소의 **ISO 26262 규격서와는 무관**하다 — UDS/STS/SUTS/SITS는 `/doc-pipeline`, UDS 단독은 `/uds-pipeline` 소관."
when_to_use: PPT 생성, PPTX, 슬라이드, 프레젠테이션, 발표자료, 프로젝트 포털, 대시보드 문서, API 문서 추출, AutoDoc, 다국어 코드 분석 요청 시
---

# /autodoc-generate 스킬

AutoDoc 시스템을 활용하여 다양한 형태의 문서를 자동 생성합니다.

## 생성 가능 산출물

### 1. PowerPoint (PPTX)
- Markdown → PPTX 변환
- 13개 레이아웃: Cards, Two-column, Timeline, Metrics, Comparison, Quote, Icon-grid, Chevron, Pyramid, Cycle, Chart, Split-image, Matrix
- 차트: Bar, Pie, Radar (matplotlib)
- Mermaid 다이어그램 지원
- 슬라이드 노트 포함

### 2. HTML 슬라이드
- Reveal.js 기반 인터랙티브 프레젠테이션
- 테마 지원 (light/dark)
- 다중 레이아웃 렌더링

### 3. 프로젝트 포털
- 프로젝트 메트릭 대시보드
- 기술 스택 시각화
- 문서 목록 및 링크
- 웹 참조 자료
- RAG 통계
- 커스텀 컬러 테마

### 4. API 문서
- Flask, FastAPI, Express, Spring, Gin 프레임워크 감지
- 엔드포인트 자동 추출
- Markdown 테이블 생성 (메서드, URL, 파라미터)

## 다국어 코드 분석

⚠ 언어 목록은 **모듈마다 다르다.** "8개"라는 단일 숫자는 어느 쪽과도 맞지 않았다
(2026-07-17 실측). 개수를 고정 기재하지 말고 아래 SSOT 를 직접 볼 것:

| 모듈 | 목록 | 개수 |
|------|------|------|
| `scripts/multi_lang_analyzer.py` `_EXT_LANG_MAP` | c, cpp, cs, java, go, ts, js — **Python 없음** | 7 |
| `scripts/analyze_all.py` `LANG_EXTENSIONS` | Python, C, C++, C#, Java, JavaScript, TypeScript, Go, **Rust** | 9 |

(Python 은 별도 `scripts/ast_analyzer.py` 가 담당. `tests/test_multi_lang.py` 가
검증하는 건 위 **7개** 쪽이다.)

| 언어 | 분석 항목 |
|------|-----------|
| C | 함수, 전역변수, include, 매크로 |
| C++ | 클래스, 메서드, 네임스페이스, 템플릿 |
| C# | 클래스, 인터페이스, 프로퍼티, LINQ |
| Java | 클래스, 어노테이션, 패키지, 제네릭 |
| Go | 구조체, 인터페이스, goroutine, 채널 |
| TypeScript | 클래스, 인터페이스, 타입, 이넘 |
| JavaScript | 함수, 클래스, 모듈, export |
| Python | 클래스, 함수, 데코레이터, import (※ `ast_analyzer.py` 경로) |

## RAG 통합
- DuckDuckGo / Tavily 웹 검색
- Jina 콘텐츠 추출
- 벡터 스토어 인덱싱
- 캐시 지원

## 실행

> ⚠ **AutoDoc 은 이 저장소가 아니라 별도 트리**(`D:/Project/Program/AutoDoc`)다.
> `AUTODOC_DIR` 은 live `.env` 에 **없고** `.env.example:87` 이 `AUTODOC_DIR=.` 이라
> `cd "${AUTODOC_DIR:-.}"` 는 **Release_claude 루트로 전개**된다 → `pytest tests/` 가
> 엉뚱한 3492개 스위트(약 4분 40초)를 돌린다. 기본값에 의존하지 말고 명시할 것.

```bash
# 테스트 — AUTODOC_DIR 이 실제 AutoDoc 트리를 가리키는지 먼저 확인
AUTODOC_DIR="${AUTODOC_DIR:-D:/Project/Program/AutoDoc}"
ls "$AUTODOC_DIR/scripts/generate_ppt.py" || { echo "AUTODOC_DIR 이 AutoDoc 트리가 아님"; exit 1; }
cd "$AUTODOC_DIR" && python -m pytest tests/ -v   # ← AutoDoc 트리의 인터프리터 규칙을 따를 것

# PPT 생성 — `autodoc` 이라는 패키지는 **존재하지 않는다**(ImportError).
# 실제 엔트리포인트:
#   scripts/generate_ppt.py       (CLI)
#   scripts/pptx_gen/presentation.py
cd "$AUTODOC_DIR" && python scripts/generate_ppt.py --help
```

## 핵심 파일
- `${AUTODOC_DIR}/tests/test_ppt_generation.py` - PPT 생성 테스트
- `${AUTODOC_DIR}/tests/test_html_slides.py` - HTML 슬라이드 테스트
- `${AUTODOC_DIR}/tests/test_project_portal.py` - 포털 생성 테스트
- `${AUTODOC_DIR}/tests/test_multi_lang.py` - 다국어 분석 테스트
- `${AUTODOC_DIR}/tests/test_web_search.py` - RAG/검색 테스트
