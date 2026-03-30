# UDS 생성 UI 테스트 매뉴얼

## 테스트 목표
Analyzer 탭에서 UDS 문서를 생성하고 UI에 표시된 결과를 확인

## 사전 준비
- 프론트엔드: http://localhost:5175/ (또는 http://localhost:5174/)
- 백엔드: localhost:8000 (실행 중)

## 테스트 단계

### 1단계: 웹 앱 접속
- 브라우저에서 http://localhost:5175/ 열기
- 페이지가 정상적으로 로드되는지 확인

### 2단계: Analyzer 탭으로 이동
- 전역 탭에서 'Analyzer' 또는 '분석' 탭 클릭
- Analyzer 페이지가 표시되는지 확인

### 3단계: 입력 필드 채우기
다음 경로를 해당 입력 필드에 입력:

**Source Root:**
```
D:\Project\Ados\PDS_64_RD
```

**Requirements Path(s):**
```
D:\Project\devops\260105\docs\(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx,D:\Project\devops\260105\docs\(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx
```

**Template (선택사항):**
```
D:\Project\devops\260105\docs\(HDPDM01_SUDS)_template_clean.docx
```

### 4단계: UDS 생성 실행
- 'UDS 생성' 버튼 클릭 (한국어 UI의 경우)
- 또는 'Generate UDS' 버튼 클릭 (영어 UI의 경우)

### 5단계: 진행 상황 모니터링
- UI에 표시되는 상태 메시지 확인
- 진행률 표시 확인
- 로그 메시지 확인

### 6단계: 결과 확인
생성 완료 후 다음 정보를 확인:

**필수 확인 사항:**
1. 생성된 파일 경로/이름
2. Quality Gate 결과 (Pass/Fail)
3. Quality Metrics (품질 점수, 커버리지 등)
4. 최종 상태 메시지

### 7단계: 뷰어에서 확인 (선택사항)
- '파일 선택' 또는 '열기' 버튼이 있다면 클릭
- 생성된 UDS 문서가 뷰어에서 열리는지 확인
- 문서 내용이 정상적으로 표시되는지 확인

## 결과 보고 양식

### 성공/실패 여부
- [ ] 성공
- [ ] 실패

### UI 단계별 실행 결과
1. 웹 앱 접속: 
2. Analyzer 탭 이동: 
3. 입력 필드 채우기: 
4. UDS 생성 버튼 클릭: 
5. 진행 상황 모니터링: 
6. 결과 확인: 
7. 뷰어 확인: 

### 최종 상태 텍스트
```
(UI에 표시된 최종 상태 메시지를 여기에 복사)
```

### 생성된 파일 정보
- 파일명/경로: 
- 파일 크기: 

### Quality Gate 및 Metrics
- Quality Gate: 
- Quality Score: 
- Coverage: 
- 기타 메트릭: 

### 발생한 오류 (있는 경우)
```
(오류 메시지를 여기에 복사)
```

### 스크린샷
- 최종 결과 화면 스크린샷 저장 권장

## 문제 해결

### 서버 연결 실패
- 백엔드 서버 (localhost:8000) 실행 여부 확인
- 프론트엔드 서버 (localhost:5175 또는 5174) 실행 여부 확인

### 파일 경로 오류
- 입력한 경로가 실제로 존재하는지 확인
- 경로에 특수 문자나 공백이 포함된 경우 정확히 입력했는지 확인

### 생성 버튼이 비활성화된 경우
- 모든 필수 입력 필드가 채워졌는지 확인
- 입력한 경로가 유효한지 확인

### 생성이 오래 걸리는 경우
- 최대 2-3분 정도 대기
- UI에 표시되는 진행 상황 메시지 확인
- 브라우저 콘솔 (F12) 에서 오류 메시지 확인
