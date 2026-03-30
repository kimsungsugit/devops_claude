"""
Selenium을 사용한 UDS 생성 UI 테스트
"""
import time
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager

def test_uds_generation():
    """UDS 생성 테스트"""
    
    driver = None
    try:
        print("=" * 80)
        print("UDS 생성 UI 테스트 시작")
        print("=" * 80)
        
        # Edge 드라이버 자동 설치 및 실행
        print("\nEdge 드라이버 설정 중...")
        service = EdgeService(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service)
        driver.maximize_window()
        
        print("브라우저 실행 완료")
        
        # 1. 웹 앱 열기
        print("\n[단계 1] http://localhost:5175/ 접속 중...")
        driver.get("http://localhost:5175/")
        time.sleep(3)
        
        print(f"현재 URL: {driver.current_url}")
        print(f"페이지 제목: {driver.title()}")
        
        driver.save_screenshot("d:/Project/devops/260105/selenium_01_initial.png")
        print("스크린샷 저장: selenium_01_initial.png")
        
        # 페이지 텍스트 확인
        body_text = driver.find_element(By.TAG_NAME, "body").text
        print(f"\n페이지 텍스트 (처음 300자):\n{body_text[:300]}")
        
        # 2. Analyzer 탭으로 이동
        print("\n[단계 2] Analyzer 탭 찾기...")
        
        analyzer_selectors = [
            (By.XPATH, "//button[contains(text(), 'Analyzer')]"),
            (By.XPATH, "//a[contains(text(), 'Analyzer')]"),
            (By.XPATH, "//button[contains(text(), '분석')]"),
            (By.XPATH, "//a[contains(text(), '분석')]"),
            (By.XPATH, "//*[@role='tab'][contains(text(), 'Analyzer')]"),
        ]
        
        analyzer_found = False
        for by, selector in analyzer_selectors:
            try:
                elements = driver.find_elements(by, selector)
                if elements:
                    elements[0].click()
                    print(f"✓ Analyzer 탭 클릭: {selector}")
                    analyzer_found = True
                    time.sleep(2)
                    break
            except Exception as e:
                print(f"  시도 실패 ({selector}): {e}")
        
        if not analyzer_found:
            print("⚠️ Analyzer 탭을 찾을 수 없습니다.")
        
        driver.save_screenshot("d:/Project/devops/260105/selenium_02_analyzer.png")
        print("스크린샷 저장: selenium_02_analyzer.png")
        
        # 3. 입력 필드 찾기 및 채우기
        print("\n[단계 3] 입력 필드 채우기...")
        
        # 모든 input 요소 찾기
        inputs = driver.find_elements(By.XPATH, "//input[@type='text' or not(@type)] | //textarea")
        print(f"발견된 입력 필드: {len(inputs)}개")
        
        for i, inp in enumerate(inputs[:5]):
            try:
                placeholder = inp.get_attribute("placeholder")
                name = inp.get_attribute("name")
                print(f"  입력 {i+1}: placeholder='{placeholder}', name='{name}'")
            except:
                pass
        
        # Source Root 입력
        source_root_path = r"D:\Project\Ados\PDS_64_RD"
        if len(inputs) >= 1:
            try:
                inputs[0].clear()
                inputs[0].send_keys(source_root_path)
                print(f"✓ Source Root 입력: {source_root_path}")
            except Exception as e:
                print(f"  Source Root 입력 실패: {e}")
        
        # Requirements Path 입력
        req_paths = r"D:\Project\devops\260105\docs\(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx,D:\Project\devops\260105\docs\(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx"
        if len(inputs) >= 2:
            try:
                inputs[1].clear()
                inputs[1].send_keys(req_paths)
                print(f"✓ Requirements Path 입력 완료")
            except Exception as e:
                print(f"  Requirements Path 입력 실패: {e}")
        
        # Template Path 입력
        template_path = r"D:\Project\devops\260105\docs\(HDPDM01_SUDS)_template_clean.docx"
        if len(inputs) >= 3:
            try:
                inputs[2].clear()
                inputs[2].send_keys(template_path)
                print(f"✓ Template Path 입력: {template_path}")
            except Exception as e:
                print(f"  Template Path 입력 실패: {e}")
        
        time.sleep(2)
        driver.save_screenshot("d:/Project/devops/260105/selenium_03_inputs_filled.png")
        print("스크린샷 저장: selenium_03_inputs_filled.png")
        
        # 4. UDS 생성 버튼 클릭
        print("\n[단계 4] UDS 생성 버튼 찾기 및 클릭...")
        
        # 모든 버튼 출력
        buttons = driver.find_elements(By.TAG_NAME, "button")
        print(f"\n발견된 버튼: {len(buttons)}개")
        for i, btn in enumerate(buttons):
            try:
                btn_text = btn.text
                if btn_text:
                    print(f"  버튼 {i+1}: '{btn_text}'")
            except:
                pass
        
        generate_selectors = [
            (By.XPATH, "//button[contains(text(), 'UDS 생성')]"),
            (By.XPATH, "//button[contains(text(), 'UDS')]"),
            (By.XPATH, "//button[contains(text(), '생성')]"),
            (By.XPATH, "//button[contains(text(), 'Generate')]"),
        ]
        
        generate_clicked = False
        for by, selector in generate_selectors:
            try:
                elements = driver.find_elements(by, selector)
                if elements:
                    elements[0].click()
                    print(f"✓ 생성 버튼 클릭: {selector}")
                    generate_clicked = True
                    time.sleep(3)
                    break
            except Exception as e:
                print(f"  시도 실패 ({selector}): {e}")
        
        if not generate_clicked:
            print("⚠️ UDS 생성 버튼을 찾을 수 없습니다!")
        
        driver.save_screenshot("d:/Project/devops/260105/selenium_04_after_click.png")
        print("스크린샷 저장: selenium_04_after_click.png")
        
        # 5. 진행 상황 모니터링
        print("\n[단계 5] 생성 진행 상황 모니터링 (최대 120초)...")
        
        max_wait_time = 120
        start_time = time.time()
        last_text = ""
        check_count = 0
        
        while time.time() - start_time < max_wait_time:
            check_count += 1
            current_text = driver.find_element(By.TAG_NAME, "body").text
            
            # 변경사항이 있으면 출력
            if current_text != last_text:
                elapsed = int(time.time() - start_time)
                print(f"\n[체크 {check_count}] 페이지 업데이트 ({elapsed}초 경과)")
                
                # 상태 관련 라인 출력
                lines = current_text.split('\n')
                for line in lines[-15:]:
                    line_lower = line.lower()
                    if any(kw in line_lower for kw in ['진행', '처리', '생성', '완료', '성공', '오류', 
                                                         'progress', 'processing', 'generating', 'complete', 
                                                         'success', 'error']):
                        print(f"  상태: {line.strip()}")
                
                last_text = current_text
            
            # 완료 또는 오류 확인
            text_lower = current_text.lower()
            
            if '완료' in text_lower or 'success' in text_lower or 'complete' in text_lower:
                print("\n✓ 생성 완료 감지!")
                break
            elif '오류' in text_lower or 'error' in text_lower or '실패' in text_lower:
                print("\n✗ 오류 감지!")
                break
            
            time.sleep(5)
        
        # 6. 최종 결과 확인
        print("\n[단계 6] 최종 결과 확인...")
        time.sleep(3)
        
        driver.save_screenshot("d:/Project/devops/260105/selenium_05_final_result.png")
        print("스크린샷 저장: selenium_05_final_result.png")
        
        # 페이지의 모든 텍스트 출력
        final_text = driver.find_element(By.TAG_NAME, "body").text
        print("\n" + "=" * 80)
        print("최종 페이지 텍스트:")
        print("=" * 80)
        print(final_text)
        print("=" * 80)
        
        # 결과 분석
        print("\n[결과 분석]")
        
        # 생성된 파일명/경로 찾기
        file_patterns = [
            r'[A-Z]:\\[^\s<>"|?*\n]+\.docx',
            r'생성.*?파일.*?:\s*([^\n]+\.docx)',
            r'파일.*?:\s*([^\n]+\.docx)',
        ]
        
        found_files = []
        for pattern in file_patterns:
            matches = re.findall(pattern, final_text, re.IGNORECASE)
            found_files.extend(matches)
        
        print("\n생성된 파일:")
        if found_files:
            for f in set(found_files):
                print(f"  ✓ {f}")
        else:
            print("  ⚠️ 생성된 파일 경로를 찾을 수 없습니다.")
        
        # Quality Gate/Metrics 찾기
        quality_keywords = ['quality', 'gate', '품질', '점수', 'score', 'rate', 'metric', 'coverage', '커버리지']
        print("\n품질 관련 정보:")
        lines = final_text.split('\n')
        quality_found = False
        for line in lines:
            if any(keyword in line.lower() for keyword in quality_keywords):
                if line.strip():
                    print(f"  {line.strip()}")
                    quality_found = True
        
        if not quality_found:
            print("  ⚠️ 품질 정보를 찾을 수 없습니다.")
        
        # 7. 파일 선택/뷰어 테스트
        print("\n[단계 7] 생성된 UDS 뷰어에서 열기 테스트...")
        
        file_select_selectors = [
            (By.XPATH, "//button[contains(text(), '파일 선택')]"),
            (By.XPATH, "//button[contains(text(), '열기')]"),
            (By.XPATH, "//button[contains(text(), 'Open')]"),
        ]
        
        viewer_opened = False
        for by, selector in file_select_selectors:
            try:
                elements = driver.find_elements(by, selector)
                if elements:
                    elements[0].click()
                    print(f"✓ 파일 선택 버튼 클릭: {selector}")
                    viewer_opened = True
                    time.sleep(3)
                    break
            except Exception as e:
                print(f"  시도 실패 ({selector}): {e}")
        
        if viewer_opened:
            driver.save_screenshot("d:/Project/devops/260105/selenium_06_viewer.png")
            print("스크린샷 저장: selenium_06_viewer.png")
        else:
            print("  ⚠️ 파일 선택/뷰어 요소를 찾을 수 없습니다.")
        
        print("\n" + "=" * 80)
        print("테스트 완료")
        print("=" * 80)
        
        # 결과 요약
        print("\n" + "=" * 80)
        print("[테스트 결과 요약]")
        print("=" * 80)
        
        if found_files:
            print("✓ 성공: UDS 문서 생성됨")
            print(f"  생성된 파일: {found_files[0]}")
        else:
            print("✗ 실패 또는 확인 불가: UDS 문서 생성 결과를 UI에서 확인할 수 없음")
        
        if quality_found:
            print("✓ 품질 정보 표시됨")
        else:
            print("⚠️ 품질 정보 미표시")
        
        if viewer_opened:
            print("✓ 뷰어 열기 성공")
        else:
            print("⚠️ 뷰어 열기 실패 또는 미지원")
        
        print("\n모든 스크린샷이 d:/Project/devops/260105/ 에 저장되었습니다.")
        print("\n15초 후 브라우저를 닫습니다...")
        time.sleep(15)
        
    except Exception as e:
        print(f"\n치명적 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        
        if driver:
            try:
                driver.save_screenshot("d:/Project/devops/260105/selenium_error.png")
                print("오류 스크린샷 저장: selenium_error.png")
            except:
                pass
    
    finally:
        if driver:
            driver.quit()
            print("\n브라우저 종료")

if __name__ == "__main__":
    test_uds_generation()
