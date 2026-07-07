"""
test_browser_tools.py
A simple script to verify that Playwright and browser_tools are correctly installed
and functional on your system without requiring any external LLM APIs.
"""

import os
import sys
from pathlib import Path
import browser_tools as bt

# Reconfigure stdout to use UTF-8 to prevent charmap encoding crashes on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def test_pipeline():
    print("Initializing environment test...")
    
    # 1. Open the browser (headless mode for test speed)
    print("\n[1/4] Launching browser...")
    try:
        res = bt.open_browser(headless=True)
        print("Success:", res)
    except Exception as e:
        print("FAIL: Could not launch browser.")
        print(f"Error detail: {e}")
        print("Make sure you have run: playwright install chromium")
        return False

    # 2. Navigate to a test page
    test_url = "https://example.com"
    print(f"\n[2/4] Navigating to {test_url}...")
    try:
        res = bt.navigate_to_url(test_url)
        print("Success:", res)
    except Exception as e:
        print(f"FAIL: Could not navigate to {test_url}.")
        print(f"Error detail: {e}")
        bt.close_browser()
        return False

    # 3. Take a screenshot to verify image generation and file I/O
    filename = "verify_test.png"
    print(f"\n[3/4] Taking screenshot ({filename})...")
    try:
        res = bt.take_screenshot(filename)
        print("Success:", {k: v for k, v in res.items() if k != 'base64'})
        
        # Verify file exists
        expected_path = Path("screenshots") / filename
        if expected_path.exists():
            print(f"Screenshot successfully saved to: {expected_path.resolve()}")
        else:
            print("WARNING: Screenshot function succeeded but file was not found!")
    except Exception as e:
        print("FAIL: Could not capture screenshot.")
        print(f"Error detail: {e}")
        bt.close_browser()
        return False

    # 4. Close the browser
    print("\n[4/4] Closing browser...")
    try:
        res = bt.close_browser()
        print("Success:", res)
    except Exception as e:
        print("FAIL: Error occurred during browser cleanup.")
        print(f"Error detail: {e}")
        return False

    print("\n🎉 Environment test PASSED successfully!")
    print("Playwright and your browser automation tools are ready.")
    return True

if __name__ == "__main__":
    success = test_pipeline()
    if not success:
        print("\n❌ Environment test FAILED. Please review the errors above.")
        exit(1)