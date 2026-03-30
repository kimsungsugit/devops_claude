"""
간단한 Playwright 테스트
"""
from playwright.sync_api import sync_playwright
import sys

print("Playwright 테스트 시작")
print(f"Python 버전: {sys.version}")

try:
    with sync_playwright() as p:
        print("Playwright 초기화 성공")
        
        browser = p.chromium.launch(headless=False)
        print("브라우저 실행 성공")
        
        page = browser.new_page()
        print("새 페이지 생성 성공")
        
        print("\nhttp://[::1]:5174/ 접속 시도...")
        response = page.goto("http://[::1]:5174/", wait_until="domcontentloaded", timeout=15000)
        print(f"응답 상태: {response.status if response else 'None'}")
        print(f"현재 URL: {page.url}")
        
        import time
        time.sleep(5)
        
        page.screenshot(path="d:/Project/devops/260105/test_screenshot.png")
        print("스크린샷 저장 완료")
        
        browser.close()
        print("브라우저 종료")
        
except Exception as e:
    print(f"오류 발생: {e}")
    import traceback
    traceback.print_exc()

print("테스트 완료")
