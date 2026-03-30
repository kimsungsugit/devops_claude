"""
UDS 생성 UI 테스트 - 최종 버전
404 오류를 무시하고 진행
"""
import time
import re
from playwright.sync_api import sync_playwright

def test_uds_generation():
    """UDS 생성 테스트"""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        
        try:
            print("=" * 80)
            print("UDS 생성 UI 테스트 시작")
            print("=" * 80)
            
            # 1. 웹 앱 열기
            print("\n[단계 1] http://localhost:5175/ 접속 중...")
            try:
                page.goto("http://localhost:5175/", wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"접속 경고: {e}")
                print("페이지가 로드되었지만 오류가 있을 수 있습니다. 계속 진행...")
            
            time.sleep(3)
            
            print(f"현재 URL: {page.url}")
            print(f"페이지 제목: {page.title()}")
            
            page.screenshot(path="d:/Project/devops/260105/screenshot_01_initial.png", full_page=True)
            print("스크린샷 저장: screenshot_01_initial.png")
            
            # 페이지 내용 확인
            body_text = page.locator("body").inner_text()
            print(f"\n페이지 텍스트 (처음 300자):\n{body_text[:300]}")
            
            # 2. Analyzer 탭으로 이동
            print("\n[단계 2] Analyzer 탭 찾기...")
            
            # 모든 버튼과 링크 출력
            print("\n발견된 요소들:")
            buttons = page.locator("button, a[role='tab'], [role='tab']").all()
            for i, btn in enumerate(buttons[:10]):  # 처음 10개만
                try:
                    text = btn.inner_text()
                    if text:
                        print(f"  {i+1}. {text}")
                except:
                    pass
            
            analyzer_selectors = [
                "text=Analyzer",
                "text=분석",
                "button:has-text('Analyzer')",
                "a:has-text('Analyzer')",
                "[role='tab']:has-text('Analyzer')",
                "[role='tab']:has-text('분석')",
            ]
            
            analyzer_found = False
            for selector in analyzer_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.click()
                        print(f"✓ Analyzer 탭 클릭: {selector}")
                        analyzer_found = True
                        time.sleep(2)
                        break
                except Exception as e:
                    print(f"  시도 실패 ({selector}): {e}")
            
            if not analyzer_found:
                print("⚠️ Analyzer 탭을 찾을 수 없습니다. 현재 페이지에 이미 있을 수 있습니다.")
            
            page.screenshot(path="d:/Project/devops/260105/screenshot_02_analyzer.png", full_page=True)
            print("스크린샷 저장: screenshot_02_analyzer.png")
            
            # 3. 입력 필드 찾기 및 채우기
            print("\n[단계 3] 입력 필드 채우기...")
            
            # 모든 input 요소 출력
            inputs = page.locator("input[type='text'], input:not([type='button']):not([type='submit']):not([type='file']), textarea").all()
            print(f"\n발견된 입력 필드: {len(inputs)}개")
            for i, inp in enumerate(inputs):
                try:
                    placeholder = inp.get_attribute("placeholder")
                    name = inp.get_attribute("name")
                    id_attr = inp.get_attribute("id")
                    print(f"  입력 {i+1}: placeholder='{placeholder}', name='{name}', id='{id_attr}'")
                except:
                    pass
            
            # Source Root 입력
            source_root_path = r"D:\Project\Ados\PDS_64_RD"
            source_filled = False
            
            # 더 광범위한 선택자 시도
            if len(inputs) >= 1:
                try:
                    inputs[0].fill(source_root_path)
                    print(f"✓ 첫 번째 입력 필드에 Source Root 입력: {source_root_path}")
                    source_filled = True
                except Exception as e:
                    print(f"  첫 번째 입력 실패: {e}")
            
            # Requirements Path 입력
            req_paths = r"D:\Project\devops\260105\docs\(HDPDM01_SRS) Software Requirements Specification_v1.05_20230510.docx,D:\Project\devops\260105\docs\(HDPDM01_SDS) Software Architecture Design Specification_v1.04_20230512.docx"
            req_filled = False
            
            if len(inputs) >= 2:
                try:
                    inputs[1].fill(req_paths)
                    print(f"✓ 두 번째 입력 필드에 Requirements Path 입력")
                    req_filled = True
                except Exception as e:
                    print(f"  두 번째 입력 실패: {e}")
            
            # Template Path 입력
            template_path = r"D:\Project\devops\260105\docs\(HDPDM01_SUDS)_template_clean.docx"
            template_filled = False
            
            if len(inputs) >= 3:
                try:
                    inputs[2].fill(template_path)
                    print(f"✓ 세 번째 입력 필드에 Template Path 입력: {template_path}")
                    template_filled = True
                except Exception as e:
                    print(f"  세 번째 입력 실패: {e}")
            
            time.sleep(2)
            page.screenshot(path="d:/Project/devops/260105/screenshot_03_inputs_filled.png", full_page=True)
            print("스크린샷 저장: screenshot_03_inputs_filled.png")
            
            # 4. UDS 생성 버튼 클릭
            print("\n[단계 4] UDS 생성 버튼 찾기 및 클릭...")
            
            # 모든 버튼 출력
            all_buttons = page.locator("button").all()
            print(f"\n발견된 버튼: {len(all_buttons)}개")
            for i, btn in enumerate(all_buttons):
                try:
                    btn_text = btn.inner_text()
                    if btn_text:
                        print(f"  버튼 {i+1}: '{btn_text}'")
                except:
                    pass
            
            generate_selectors = [
                "text=UDS 생성",
                "text=생성",
                "button:has-text('UDS')",
                "button:has-text('생성')",
                "button:has-text('Generate')",
            ]
            
            generate_clicked = False
            for selector in generate_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.locator(selector).first.click()
                        print(f"✓ 생성 버튼 클릭: {selector}")
                        generate_clicked = True
                        time.sleep(3)
                        break
                except Exception as e:
                    print(f"  시도 실패 ({selector}): {e}")
            
            if not generate_clicked:
                print("⚠️ UDS 생성 버튼을 찾을 수 없습니다!")
                # 마지막 버튼 클릭 시도
                if len(all_buttons) > 0:
                    try:
                        all_buttons[-1].click()
                        print("마지막 버튼 클릭 시도")
                        generate_clicked = True
                        time.sleep(3)
                    except:
                        pass
            
            page.screenshot(path="d:/Project/devops/260105/screenshot_04_after_click.png", full_page=True)
            print("스크린샷 저장: screenshot_04_after_click.png")
            
            # 5. 진행 상황 모니터링
            print("\n[단계 5] 생성 진행 상황 모니터링...")
            print("(최대 120초 대기)")
            
            max_wait_time = 120
            start_time = time.time()
            last_text = ""
            check_count = 0
            
            while time.time() - start_time < max_wait_time:
                check_count += 1
                current_text = page.locator("body").inner_text()
                
                # 변경사항이 있으면 출력
                if current_text != last_text:
                    print(f"\n[{check_count}] 페이지 업데이트 감지 ({int(time.time() - start_time)}초 경과)")
                    
                    # 상태 관련 라인 출력
                    lines = current_text.split('\n')
                    for line in lines[-20:]:  # 마지막 20줄
                        line_lower = line.lower()
                        if any(kw in line_lower for kw in ['진행', '처리', '생성', '완료', '성공', '오류', '에러', 
                                                             'progress', 'processing', 'generating', 'complete', 
                                                             'success', 'error', 'fail']):
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
            
            page.screenshot(path="d:/Project/devops/260105/screenshot_05_final_result.png", full_page=True)
            print("스크린샷 저장: screenshot_05_final_result.png")
            
            # 페이지의 모든 텍스트 출력
            final_text = page.locator("body").inner_text()
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
                r'output.*?:\s*([^\n]+\.docx)',
                r'결과.*?:\s*([^\n]+\.docx)',
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
            quality_keywords = ['quality', 'gate', '품질', '점수', 'score', 'rate', 'metric', 'coverage', '커버리지', '%']
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
                "text=파일 선택",
                "text=열기",
                "text=Open",
                "button:has-text('파일')",
                "button:has-text('열기')",
            ]
            
            viewer_opened = False
            for selector in file_select_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        print(f"파일 선택 요소 발견: {selector}")
                        page.locator(selector).first.click()
                        print("파일 선택 버튼 클릭")
                        viewer_opened = True
                        time.sleep(3)
                        break
                except Exception as e:
                    print(f"  시도 실패 ({selector}): {e}")
            
            if viewer_opened:
                page.screenshot(path="d:/Project/devops/260105/screenshot_06_viewer.png", full_page=True)
                print("스크린샷 저장: screenshot_06_viewer.png")
                
                # 뷰어 내용 확인
                viewer_text = page.locator("body").inner_text()
                print("\n뷰어 내용 (처음 500자):")
                print(viewer_text[:500])
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
            
            try:
                page.screenshot(path="d:/Project/devops/260105/screenshot_error.png", full_page=True)
                print("오류 스크린샷 저장: screenshot_error.png")
            except:
                pass
        
        finally:
            context.close()
            browser.close()
            print("\n브라우저 종료")

if __name__ == "__main__":
    test_uds_generation()
