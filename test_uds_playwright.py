"""
Playwright를 사용한 UDS 생성 UI 테스트
"""
import time
import re
from playwright.sync_api import sync_playwright, expect

def test_uds_generation():
    """UDS 생성 테스트"""
    
    with sync_playwright() as p:
        # 브라우저 실행
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        try:
            print("=" * 80)
            print("UDS 생성 UI 테스트 시작")
            print("=" * 80)
            
            # 1. 웹 앱 열기
            print("\n[단계 1] http://[::1]:5174/ 접속 중...")
            try:
                page.goto("http://[::1]:5174/", wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"접속 중 오류 발생: {e}")
                print("계속 진행...")
            time.sleep(3)
            
            print(f"현재 URL: {page.url}")
            print(f"페이지 제목: {page.title()}")
            
            # 스크린샷 저장
            page.screenshot(path="d:/Project/devops/260105/screenshot_01_initial.png")
            print("스크린샷 저장: screenshot_01_initial.png")
            
            # 2. Analyzer 탭으로 이동
            print("\n[단계 2] Analyzer 탭 찾기...")
            
            # 가능한 선택자들
            analyzer_selectors = [
                "button:has-text('Analyzer')",
                "a:has-text('Analyzer')",
                "button:has-text('분석')",
                "a:has-text('분석')",
                "[role='tab']:has-text('Analyzer')",
                "[role='tab']:has-text('분석')",
            ]
            
            analyzer_found = False
            for selector in analyzer_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.click()
                        print(f"Analyzer 탭 클릭 완료: {selector}")
                        analyzer_found = True
                        time.sleep(2)
                        break
                except:
                    continue
            
            if not analyzer_found:
                print("Analyzer 탭을 찾을 수 없습니다. 현재 페이지에 이미 있을 수 있습니다.")
            
            page.screenshot(path="d:/Project/devops/260105/screenshot_02_analyzer.png")
            print("스크린샷 저장: screenshot_02_analyzer.png")
            
            # 페이지 내용 출력
            print("\n현재 페이지 텍스트 (처음 500자):")
            body_text = page.locator("body").inner_text()
            print(body_text[:500])
            print("...")
            
            # 3. 입력 필드 찾기 및 채우기
            print("\n[단계 3] 입력 필드 채우기...")
            
            # 모든 input 요소 찾기
            inputs = page.locator("input[type='text'], input:not([type]), textarea").all()
            print(f"발견된 입력 필드 수: {len(inputs)}")
            
            # Source Root 입력
            source_root_path = r"D:\Project\Ados\PDS_64_RD"
            source_selectors = [
                "input[placeholder*='source' i]",
                "input[placeholder*='소스' i]",
                "input[name*='source' i]",
                "input[id*='source' i]",
            ]
            
            source_filled = False
            for selector in source_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.fill(source_root_path)
                        print(f"Source Root 입력 완료: {source_root_path}")
                        source_filled = True
                        break
                except Exception as e:
                    print(f"Source 입력 실패 ({selector}): {e}")
            
            if not source_filled:
                print("⚠️ Source Root 입력 필드를 찾을 수 없습니다.")
            
            # Requirements Path 입력
            req_paths = r"D:\Project\devops\260105\docs\(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx,D:\Project\devops\260105\docs\(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx"
            req_selectors = [
                "input[placeholder*='requirement' i]",
                "input[placeholder*='요구사항' i]",
                "textarea[placeholder*='requirement' i]",
                "textarea[placeholder*='요구사항' i]",
                "input[name*='requirement' i]",
                "input[id*='requirement' i]",
            ]
            
            req_filled = False
            for selector in req_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.fill(req_paths)
                        print(f"Requirements Path 입력 완료")
                        req_filled = True
                        break
                except Exception as e:
                    print(f"Requirements 입력 실패 ({selector}): {e}")
            
            if not req_filled:
                print("⚠️ Requirements Path 입력 필드를 찾을 수 없습니다.")
            
            # Template Path 입력
            template_path = r"D:\Project\devops\260105\docs\(HDPDM01_SUDS)_template_clean.docx"
            template_selectors = [
                "input[placeholder*='template' i]",
                "input[placeholder*='템플릿' i]",
                "input[name*='template' i]",
                "input[id*='template' i]",
            ]
            
            template_filled = False
            for selector in template_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.fill(template_path)
                        print(f"Template Path 입력 완료: {template_path}")
                        template_filled = True
                        break
                except Exception as e:
                    print(f"Template 입력 실패 ({selector}): {e}")
            
            if not template_filled:
                print("⚠️ Template Path 입력 필드를 찾을 수 없습니다.")
            
            time.sleep(1)
            page.screenshot(path="d:/Project/devops/260105/screenshot_03_inputs_filled.png")
            print("스크린샷 저장: screenshot_03_inputs_filled.png")
            
            # 4. UDS 생성 버튼 클릭
            print("\n[단계 4] UDS 생성 버튼 찾기 및 클릭...")
            
            # 모든 버튼 출력
            buttons = page.locator("button").all()
            print(f"\n발견된 버튼 수: {len(buttons)}")
            for i, btn in enumerate(buttons):
                try:
                    btn_text = btn.inner_text()
                    if btn_text:
                        print(f"  버튼 {i+1}: '{btn_text}'")
                except:
                    pass
            
            generate_selectors = [
                "button:has-text('UDS 생성')",
                "button:has-text('UDS')",
                "button:has-text('생성')",
                "button:has-text('Generate')",
                "button:has-text('generate')",
            ]
            
            generate_clicked = False
            for selector in generate_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.click()
                        print(f"UDS 생성 버튼 클릭 완료: {selector}")
                        generate_clicked = True
                        time.sleep(2)
                        break
                except Exception as e:
                    print(f"버튼 클릭 실패 ({selector}): {e}")
            
            if not generate_clicked:
                print("⚠️ UDS 생성 버튼을 찾을 수 없습니다!")
                page.screenshot(path="d:/Project/devops/260105/screenshot_04_no_button.png")
            
            # 5. 진행 상황 모니터링
            print("\n[단계 5] 생성 진행 상황 모니터링...")
            
            max_wait_time = 120  # 최대 2분 대기
            start_time = time.time()
            last_text = ""
            
            while time.time() - start_time < max_wait_time:
                current_text = page.locator("body").inner_text()
                
                # 변경사항이 있으면 출력
                if current_text != last_text:
                    # 상태 관련 키워드 찾기
                    status_keywords = ['진행', '처리', '생성', '완료', '성공', 'progress', 'processing', 'generating', 'complete', 'success']
                    lines = current_text.split('\n')
                    for line in lines:
                        if any(keyword in line.lower() for keyword in status_keywords):
                            print(f"상태: {line.strip()}")
                    
                    last_text = current_text
                
                # 완료 또는 오류 확인
                completion_keywords = ['완료', '성공', 'success', 'complete', 'finished', 'done']
                error_keywords = ['오류', '에러', '실패', 'error', 'fail', 'failed']
                
                text_lower = current_text.lower()
                
                if any(keyword in text_lower for keyword in completion_keywords):
                    print("\n✓ 생성 완료 감지!")
                    break
                elif any(keyword in text_lower for keyword in error_keywords):
                    print("\n✗ 오류 감지!")
                    break
                
                time.sleep(3)
            
            # 6. 최종 결과 확인
            print("\n[단계 6] 최종 결과 확인...")
            time.sleep(2)
            
            page.screenshot(path="d:/Project/devops/260105/screenshot_05_final_result.png")
            print("스크린샷 저장: screenshot_05_final_result.png")
            
            # 페이지의 모든 텍스트 출력
            final_text = page.locator("body").inner_text()
            print("\n" + "=" * 80)
            print("페이지 전체 텍스트:")
            print("=" * 80)
            print(final_text)
            print("=" * 80)
            
            # 결과 분석
            print("\n[결과 분석]")
            
            # 생성된 파일명/경로 찾기
            file_patterns = [
                r'D:\\[^\s<>"|?*]+\.docx',
                r'[A-Z]:\\[^\s<>"|?*]+\.docx',
                r'생성.*?:\s*([^\n]+\.docx)',
                r'파일.*?:\s*([^\n]+\.docx)',
                r'output.*?:\s*([^\n]+\.docx)',
            ]
            
            found_files = []
            for pattern in file_patterns:
                matches = re.findall(pattern, final_text, re.IGNORECASE)
                found_files.extend(matches)
            
            if found_files:
                print("\n생성된 파일:")
                for f in set(found_files):
                    print(f"  ✓ {f}")
            else:
                print("\n⚠️ 생성된 파일 경로를 찾을 수 없습니다.")
            
            # Quality Gate/Metrics 찾기
            quality_keywords = ['quality', 'gate', '품질', '점수', 'score', 'rate', 'metric', 'coverage', '커버리지']
            print("\n품질 관련 정보:")
            lines = final_text.split('\n')
            quality_found = False
            for line in lines:
                if any(keyword in line.lower() for keyword in quality_keywords):
                    print(f"  {line.strip()}")
                    quality_found = True
            
            if not quality_found:
                print("  품질 정보를 찾을 수 없습니다.")
            
            # 7. 파일 선택/뷰어 테스트
            print("\n[단계 7] 생성된 UDS 뷰어에서 열기 테스트...")
            
            file_select_selectors = [
                "button:has-text('파일 선택')",
                "button:has-text('열기')",
                "button:has-text('Open')",
                "input[type='file']",
            ]
            
            viewer_opened = False
            for selector in file_select_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        print(f"파일 선택 요소 발견: {selector}")
                        
                        # 파일 입력의 경우
                        if 'input' in selector:
                            if found_files:
                                try:
                                    page.locator(selector).first.set_input_files(found_files[0])
                                    print(f"파일 경로 입력: {found_files[0]}")
                                    viewer_opened = True
                                    time.sleep(2)
                                except Exception as e:
                                    print(f"파일 경로 입력 실패: {e}")
                        else:
                            page.locator(selector).first.click()
                            print("파일 선택 버튼 클릭")
                            viewer_opened = True
                            time.sleep(2)
                        break
                except Exception as e:
                    print(f"파일 선택 실패 ({selector}): {e}")
            
            if viewer_opened:
                page.screenshot(path="d:/Project/devops/260105/screenshot_06_viewer.png")
                print("스크린샷 저장: screenshot_06_viewer.png")
            else:
                print("파일 선택/뷰어 요소를 찾을 수 없습니다.")
            
            print("\n" + "=" * 80)
            print("테스트 완료")
            print("=" * 80)
            
            # 결과 요약
            print("\n[테스트 결과 요약]")
            if found_files:
                print(f"✓ 성공: UDS 문서 생성됨")
                print(f"  생성된 파일: {found_files[0] if found_files else 'N/A'}")
            else:
                print("✗ 실패 또는 확인 불가: UDS 문서 생성 결과를 UI에서 확인할 수 없음")
            
            # 10초 대기
            print("\n10초 후 브라우저를 닫습니다...")
            time.sleep(10)
            
        except Exception as e:
            print(f"\n오류 발생: {str(e)}")
            import traceback
            traceback.print_exc()
            
            page.screenshot(path="d:/Project/devops/260105/screenshot_error.png")
            print("오류 스크린샷 저장: screenshot_error.png")
        
        finally:
            context.close()
            browser.close()
            print("\n브라우저 종료")

if __name__ == "__main__":
    test_uds_generation()
