"""
tests/test_browser_tools.py
Comprehensive test suite for browser_tools module.
"""

import os
import sys
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import browser_tools as bt


class TestBrowserLifecycle:
    """Test browser open/close lifecycle."""
    
    def test_open_browser_headless(self):
        """Test opening browser in headless mode."""
        result = bt.open_browser(headless=True)
        assert result["status"] == "ok"
        assert "message" in result
        
    def test_open_browser_reuse(self):
        """Test that calling open_browser twice reuses session."""
        result1 = bt.open_browser(headless=True)
        result2 = bt.open_browser(headless=True)
        assert result1["status"] == "ok"
        assert "already open" in result2["message"].lower()
        
    def test_close_browser(self):
        """Test closing browser."""
        bt.open_browser(headless=True)
        result = bt.close_browser()
        assert result["status"] == "ok"
        
    def test_require_page_raises_when_closed(self):
        """Test that _require_page raises error when browser is closed."""
        bt.close_browser()
        with pytest.raises(bt.BrowserNotOpenError):
            bt._require_page()


class TestNavigation:
    """Test navigation functionality."""
    
    def setup_method(self):
        bt.open_browser(headless=True)
        
    def teardown_method(self):
        bt.close_browser()
        
    def test_navigate_to_url(self):
        """Test basic navigation."""
        result = bt.navigate_to_url("https://example.com")
        assert result["status"] == "ok"
        assert "url" in result
        assert "title" in result
        
    def test_navigate_invalid_url(self):
        """Test navigation to invalid URL."""
        with pytest.raises(bt.NavigationTimeoutError):
            bt.navigate_to_url("not-a-valid-url")


class TestScreenshot:
    """Test screenshot functionality."""
    
    def setup_method(self):
        bt.open_browser(headless=True)
        
    def teardown_method(self):
        bt.close_browser()
        
    def test_take_screenshot(self):
        """Test taking screenshot."""
        bt.navigate_to_url("https://example.com")
        result = bt.take_screenshot("test_screenshot.jpg")
        assert result["status"] == "ok"
        assert "base64" in result
        assert "path" in result
        
    def test_screenshot_file_exists(self):
        """Test that screenshot file is created."""
        bt.navigate_to_url("https://example.com")
        result = bt.take_screenshot("verify_test.jpg")
        path = Path(result["path"])
        assert path.exists()


class TestInteractiveElements:
    """Test interactive element detection."""
    
    def setup_method(self):
        bt.open_browser(headless=True)
        
    def teardown_method(self):
        bt.close_browser()
        
    def test_get_interactive_elements(self):
        """Test getting interactive elements."""
        bt.navigate_to_url("https://example.com")
        result = bt.get_interactive_elements()
        assert result["status"] == "ok"
        assert "elements" in result
        assert isinstance(result["elements"], list)
        
    def test_get_interactive_elements_max_elements(self):
        """Test max_elements limit."""
        bt.navigate_to_url("https://example.com")
        result = bt.get_interactive_elements(max_elements=5)
        assert len(result["elements"]) <= 5


class TestMouseActions:
    """Test mouse action tools."""
    
    def setup_method(self):
        bt.open_browser(headless=True)
        
    def teardown_method(self):
        bt.close_browser()
        
    def test_click_on_screen(self):
        """Test clicking on screen."""
        bt.navigate_to_url("https://example.com")
        result = bt.click_on_screen(100, 100)
        assert result["status"] == "ok"
        assert result["x"] == 100
        assert result["y"] == 100
        
    def test_double_click(self):
        """Test double clicking."""
        bt.navigate_to_url("https://example.com")
        result = bt.double_click(100, 100)
        assert result["status"] == "ok"


class TestKeyboard:
    """Test keyboard action tools."""
    
    def setup_method(self):
        bt.open_browser(headless=True)
        
    def teardown_method(self):
        bt.close_browser()
        
    def test_send_keys(self):
        """Test sending keys."""
        bt.navigate_to_url("https://example.com")
        result = bt.send_keys("test text")
        assert result["status"] == "ok"


class TestScroll:
    """Test scroll functionality."""
    
    def setup_method(self):
        bt.open_browser(headless=True)
        
    def teardown_method(self):
        bt.close_browser()
        
    def test_scroll_down(self):
        """Test scrolling down."""
        bt.navigate_to_url("https://example.com")
        result = bt.scroll("down", 300)
        assert result["status"] == "ok"
        assert result["direction"] == "down"
        
    def test_scroll_up(self):
        """Test scrolling up."""
        bt.navigate_to_url("https://example.com")
        result = bt.scroll("up", 300)
        assert result["status"] == "ok"


class TestPageHTML:
    """Test page HTML retrieval."""
    
    def setup_method(self):
        bt.open_browser(headless=True)
        
    def teardown_method(self):
        bt.close_browser()
        
    def test_get_page_html(self):
        """Test getting page HTML."""
        bt.navigate_to_url("https://example.com")
        result = bt.get_page_html()
        assert result["status"] == "ok"
        assert "html" in result
        
    def test_get_page_html_max_chars(self):
        """Test HTML truncation."""
        bt.navigate_to_url("https://example.com")
        result = bt.get_page_html(max_chars=100)
        assert len(result["html"]) <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])