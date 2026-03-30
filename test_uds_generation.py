"""
UDS 생성 UI 테스트 스크립트
"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options

def test_uds_generation():
    """UDS 생성 테스트"""
    
    # Edge 브라우저 설정
    edge_options = Options()
    # edge_options.add_argument('--headless')  # 헤드리스 모드 (필요시 주석 해제)
    
    driver = None
    try:
        driver = webdriver.Edge(options=edge_options)
        driver.maximize_window()
        
        print("=" * 80)
        print("UDS 생성 UI 테스트 시작")
        print("=" * 80)
        
        # 1. 웹 앱 열기
        print("\n[단계 1] http://localhost:5174/ 접속 중...")
        driver.get("http://localhost:5174/")
        time.sleep(2)
        
        print(f"현재 URL: {driver.current_url}")
        print(f"페이지 제목: {driver.title}")
        
        # 2. Analyzer 탭으로 이동
        print("\n[단계 2] Analyzer 탭 찾기...")
        wait = WebDriverWait(driver, 10)
        
        # 가능한 Analyzer 탭 선택자들
        analyzer_selectors = [
            "//button[contains(text(), 'Analyzer')]",
            "//a[contains(text(), 'Analyzer')]",
            "//div[contains(text(), 'Analyzer')]",
            "//button[contains(text(), '분석')]",
            "//a[contains(text(), '분석')]",
        ]
        
        analyzer_tab = None
        for selector in analyzer_selectors:
            try:
                analyzer_tab = driver.find_element(By.XPATH, selector)
                print(f"Analyzer 탭 발견: {selector}")
                break
            except:
                continue
        
        if analyzer_tab:
            analyzer_tab.click()
            print("Analyzer 탭 클릭 완료")
            time.sleep(2)
        else:
            print("Analyzer 탭을 찾을 수 없습니다. 현재 페이지에 이미 있을 수 있습니다.")
        
        # 페이지 스크린샷 저장
        driver.save_screenshot("d:/Project/devops/260105/screenshot_analyzer.png")
        print("스크린샷 저장: screenshot_analyzer.png")
        
        # 3. 입력 필드 찾기 및 채우기
        print("\n[단계 3] 입력 필드 채우기...")
        
        # Source Root 입력
        source_root_path = r"D:\Project\Ados\PDS_64_RD"
        source_root_selectors = [
            "//input[@placeholder*='source' or @placeholder*='Source' or @placeholder*='소스']",
            "//input[@name*='source' or @name*='Source']",
            "//input[@id*='source' or @id*='Source']",
        ]
        
        for selector in source_root_selectors:
            try:
                source_input = driver.find_element(By.XPATH, selector)
                source_input.clear()
                source_input.send_keys(source_root_path)
                print(f"Source Root 입력 완료: {source_root_path}")
                break
            except:
                continue
        
        # Requirements Path 입력
        req_paths = r"D:\Project\devops\260105\docs\(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx,D:\Project\devops\260105\docs\(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx"
        req_selectors = [
            "//input[@placeholder*='requirement' or @placeholder*='Requirement' or @placeholder*='요구사항']",
            "//input[@name*='requirement' or @name*='Requirement']",
            "//input[@id*='requirement' or @id*='Requirement']",
            "//textarea[@placeholder*='requirement' or @placeholder*='Requirement' or @placeholder*='요구사항']",
        ]
        
        for selector in req_selectors:
            try:
                req_input = driver.find_element(By.XPATH, selector)
                req_input.clear()
                req_input.send_keys(req_paths)
                print(f"Requirements Path 입력 완료")
                break
            except:
                continue
        
        # Template Path 입력
        template_path = r"D:\Project\devops\260105\docs\(HDPDM01_SUDS)_template_clean.docx"
        template_selectors = [
            "//input[@placeholder*='template' or @placeholder*='Template' or @placeholder*='템플릿']",
            "//input[@name*='template' or @name*='Template']",
            "//input[@id*='template' or @id*='Template']",
        ]
        
        for selector in template_selectors:
            try:
                template_input = driver.find_element(By.XPATH, selector)
                template_input.clear()
                template_input.send_keys(template_path)
                print(f"Template Path 입력 완료: {template_path}")
                break
            except:
                continue
        
        time.sleep(1)
        driver.save_screenshot("d:/Project/devops/260105/screenshot_inputs_filled.png")
        print("스크린샷 저장: screenshot_inputs_filled.png")
        
        # 4. UDS 생성 버튼 클릭
        print("\n[단계 4] UDS 생성 버튼 찾기 및 클릭...")
        
        generate_selectors = [
            "//button[contains(text(), 'UDS 생성')]",
            "//button[contains(text(), 'UDS')]",
            "//button[contains(text(), '생성')]",
            "//button[contains(text(), 'Generate')]",
            "//button[contains(text(), 'generate')]",
        ]
        
        generate_button = None
        for selector in generate_selectors:
            try:
                generate_button = driver.find_element(By.XPATH, selector)
                print(f"생성 버튼 발견: {selector}")
                break
            except:
                continue
        
        if generate_button:
            generate_button.click()
            print("UDS 생성 버튼 클릭 완료")
            time.sleep(2)
        else:
            print("⚠️ UDS 생성 버튼을 찾을 수 없습니다!")
            driver.save_screenshot("d:/Project/devops/260105/screenshot_no_button.png")
            print("현재 페이지의 모든 버튼:")
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for i, btn in enumerate(buttons):
                print(f"  버튼 {i+1}: {btn.text}")
        
        # 5. 진행 상황 모니터링
        print("\n[단계 5] 생성 진행 상황 모니터링...")
        
        max_wait_time = 120  # 최대 2분 대기
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            # 상태 메시지 찾기
            status_selectors = [
                "//div[contains(@class, 'status')]",
                "//div[contains(@class, 'progress')]",
                "//div[contains(@class, 'message')]",
                "//p[contains(@class, 'status')]",
                "//span[contains(@class, 'status')]",
            ]
            
            for selector in status_selectors:
                try:
                    status_elements = driver.find_elements(By.XPATH, selector)
                    for elem in status_elements:
                        if elem.text:
                            print(f"상태: {elem.text}")
                except:
                    pass
            
            # 완료 또는 오류 메시지 확인
            completion_keywords = ['완료', '성공', 'success', 'complete', 'finished']
            error_keywords = ['오류', '에러', '실패', 'error', 'fail', 'failed']
            
            page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
            
            if any(keyword in page_text for keyword in completion_keywords):
                print("\n✓ 생성 완료 감지!")
                break
            elif any(keyword in page_text for keyword in error_keywords):
                print("\n✗ 오류 감지!")
                break
            
            time.sleep(3)
        
        # 6. 최종 결과 확인
        print("\n[단계 6] 최종 결과 확인...")
        time.sleep(2)
        
        driver.save_screenshot("d:/Project/devops/260105/screenshot_final_result.png")
        print("스크린샷 저장: screenshot_final_result.png")
        
        # 페이지의 모든 텍스트 출력
        body_text = driver.find_element(By.TAG_NAME, "body").text
        print("\n" + "=" * 80)
        print("페이지 전체 텍스트:")
        print("=" * 80)
        print(body_text)
        print("=" * 80)
        
        # 생성된 파일명/경로 찾기
        print("\n[결과 분석]")
        
        # 파일 경로 패턴 찾기
        import re
        file_patterns = [
            r'D:\\[^"<>\|\s]+\.docx',
            r'[A-Z]:\\[^"<>\|\s]+\.docx',
            r'생성.*?:\s*(.+\.docx)',
            r'파일.*?:\s*(.+\.docx)',
        ]
        
        found_files = []
        for pattern in file_patterns:
            matches = re.findall(pattern, body_text)
            found_files.extend(matches)
        
        if found_files:
            print("생성된 파일:")
            for f in set(found_files):
                print(f"  - {f}")
        else:
            print("생성된 파일 경로를 찾을 수 없습니다.")
        
        # Quality Gate/Metrics 찾기
        quality_keywords = ['quality', 'gate', '품질', '점수', 'score', 'rate', 'metric']
        lines = body_text.split('\n')
        print("\n품질 관련 정보:")
        for line in lines:
            if any(keyword in line.lower() for keyword in quality_keywords):
                print(f"  {line.strip()}")
        
        # 7. 파일 선택/뷰어 테스트
        print("\n[단계 7] 생성된 UDS 뷰어에서 열기 테스트...")
        
        file_select_selectors = [
            "//button[contains(text(), '파일 선택')]",
            "//button[contains(text(), '열기')]",
            "//button[contains(text(), 'Open')]",
            "//input[@type='file']",
        ]
        
        for selector in file_select_selectors:
            try:
                file_select = driver.find_element(By.XPATH, selector)
                print(f"파일 선택 요소 발견: {selector}")
                # 파일 입력의 경우 직접 경로 설정 시도
                if 'input' in selector:
                    if found_files:
                        try:
                            file_select.send_keys(found_files[0])
                            print(f"파일 경로 입력: {found_files[0]}")
                            time.sleep(2)
                        except:
                            print("파일 경로 입력 실패")
                else:
                    file_select.click()
                    print("파일 선택 버튼 클릭")
                    time.sleep(2)
                break
            except:
                continue
        
        driver.save_screenshot("d:/Project/devops/260105/screenshot_viewer.png")
        print("스크린샷 저장: screenshot_viewer.png")
        
        print("\n" + "=" * 80)
        print("테스트 완료")
        print("=" * 80)
        
        # 결과 요약
        print("\n[테스트 결과 요약]")
        if found_files:
            print(f"✓ 성공: UDS 문서 생성됨")
            print(f"  생성된 파일: {found_files[0] if found_files else 'N/A'}")
        else:
            print("✗ 실패: UDS 문서 생성 확인 불가")
        
        # 10초 대기 후 종료
        print("\n10초 후 브라우저를 닫습니다...")
        time.sleep(10)
        
    except Exception as e:
        print(f"\n오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        
        if driver:
            driver.save_screenshot("d:/Project/devops/260105/screenshot_error.png")
            print("오류 스크린샷 저장: screenshot_error.png")
    
    finally:
        if driver:
            driver.quit()
            print("\n브라우저 종료")

if __name__ == "__main__":
    test_uds_generation()
