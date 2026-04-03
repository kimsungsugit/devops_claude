---
name: autodoc-generate
description: AutoDoc 시스템으로 PPT, HTML 슬라이드, 프로젝트 포털, API 문서를 자동 생성합니다. 다국어 코드 분석 및 RAG 통합.
trigger: PPT 생성, 슬라이드, 프로젝트 포털, API 문서, AutoDoc, 프레젠테이션, 다국어 코드 분석 요청 시
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
지원 언어 (8개):
| 언어 | 분석 항목 |
|------|-----------|
| C | 함수, 전역변수, include, 매크로 |
| C++ | 클래스, 메서드, 네임스페이스, 템플릿 |
| C# | 클래스, 인터페이스, 프로퍼티, LINQ |
| Java | 클래스, 어노테이션, 패키지, 제네릭 |
| Go | 구조체, 인터페이스, goroutine, 채널 |
| TypeScript | 클래스, 인터페이스, 타입, 이넘 |
| JavaScript | 함수, 클래스, 모듈, export |
| Python | 클래스, 함수, 데코레이터, import |

## RAG 통합
- DuckDuckGo / Tavily 웹 검색
- Jina 콘텐츠 추출
- 벡터 스토어 인덱싱
- 캐시 지원

## 실행
```bash
# 테스트
cd /d/Project/Program/AutoDoc
pytest tests/ -v

# PPT 생성 예시
python -c "from autodoc import generate_pptx; generate_pptx('input.md', 'output.pptx')"
```

## 핵심 파일
- `D:/Project/Program/AutoDoc/tests/test_ppt_generation.py` - PPT 생성 테스트
- `D:/Project/Program/AutoDoc/tests/test_html_slides.py` - HTML 슬라이드 테스트
- `D:/Project/Program/AutoDoc/tests/test_project_portal.py` - 포털 생성 테스트
- `D:/Project/Program/AutoDoc/tests/test_multi_lang.py` - 다국어 분석 테스트
- `D:/Project/Program/AutoDoc/tests/test_web_search.py` - RAG/검색 테스트
