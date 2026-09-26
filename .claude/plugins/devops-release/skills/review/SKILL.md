---
description: "코드 리뷰 체크리스트 실행 — PR 번호를 지정하거나 현재 uncommitted 변경을 리뷰합니다. 계획→설계→구현→**리뷰**→문서화 Gate 전체를 밟는 건 `/start-work`(Gate 5) 소관입니다."
when_to_use: 코드 리뷰해줘, 리뷰 부탁, PR 리뷰, 변경사항 검토, 리뷰 체크리스트 요청 시
---

# 코드 리뷰 (review)

$ARGUMENTS 에 PR 번호 또는 리뷰 범위가 들어옵니다. 비어있으면 현재 uncommitted 변경사항을 리뷰합니다.

## 리뷰 체크리스트

### Python Backend
- [ ] FastAPI 라우터 패턴 준수
- [ ] Pydantic 모델 유효성
- [ ] async/await 올바른 사용
- [ ] 에러 처리 (HTTPException)
- [ ] SQL Injection / Path Traversal 방지

### React Frontend
- [ ] 함수형 컴포넌트 사용
- [ ] Props destructuring
- [ ] useEffect 의존성 배열
- [ ] XSS 방지 (dangerouslySetInnerHTML 금지)

### 공통
- [ ] 하드코딩된 비밀값 없음
- [ ] 불필요한 console.log / print 제거
- [ ] 테스트 코드 존재
- [ ] CI 파이프라인 통과 가능 여부

## 수행 절차

1. PR 번호가 있으면: `gh pr diff <number>` 로 변경사항 가져오기
2. 없으면: `git diff` 와 `git diff --cached` 로 현재 변경 확인
3. 변경된 파일을 하나씩 읽고 위 체크리스트 적용
4. 결과를 심각도별로 분류:
   - **Critical**: 반드시 수정 (보안, 버그)
   - **Warning**: 수정 권장 (코드 품질)
   - **Info**: 참고 사항 (스타일, 개선)
