"""VectorCAST 파서 테스트 스크립트

TResultParser/TestCaseData 폴더의 HTML 파일로 파싱 정확도를 검증합니다.
"""

from pathlib import Path
from backend.services.vcast_parser import parse_vcast_report, ReportType, VCASTVersion

def test_parse_testcase_data():
    """TestCaseData 리포트 파싱 테스트"""
    testcase_dir = Path("TResultParser/TestCaseData_251104/TestCaseData")
    
    if not testcase_dir.exists():
        print(f"테스트 디렉토리를 찾을 수 없습니다: {testcase_dir}")
        return
    
    # 첫 번째 HTML 파일 찾기
    html_files = list(testcase_dir.glob("*.html"))
    if not html_files:
        print("테스트 파일을 찾을 수 없습니다")
        return
    
    test_file = html_files[0]
    print(f"테스트 파일: {test_file.name}")
    
    try:
        tcbank = parse_vcast_report(test_file, ReportType.TestCaseData, VCASTVersion.Ver2025)
        
        print(f"\n파싱 결과:")
        print(f"  환경: {tcbank.environment}")
        print(f"  컴포넌트: {tcbank.component_name}")
        print(f"  테스트 케이스 수: {tcbank.test_count}")
        print(f"  통과 수: {tcbank.passed_count}")
        print(f"  입력 필드 수: {len(tcbank.input_names)}")
        print(f"  예상 결과 필드 수: {len(tcbank.exp_result_names)}")
        print(f"  실제 결과 필드 수: {len(tcbank.act_result_names)}")
        
        if tcbank.test_cases:
            first_tc = list(tcbank.test_cases.values())[0]
            if first_tc:
                print(f"\n첫 번째 테스트 케이스:")
                print(f"  이름: {first_tc[0].header.test_case_name}")
                print(f"  입력 데이터 수: {len(first_tc[0].input_data)}")
                print(f"  예상 결과 수: {len(first_tc[0].expected_result)}")
        
        print("\n파싱 성공!")
        return True
        
    except Exception as e:
        print(f"\n파싱 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_parse_testcase_data()
