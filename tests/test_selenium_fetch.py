"""Tests for HttpReadingRepository.fetch_rendered_html (Selenium path).

These tests never launch a real browser. A fake `selenium` package is injected
into sys.modules so the repository's lazy import resolves to fake driver objects.
"""

from __future__ import annotations

import sys
import types

import pytest

from extraction_tool.repositories.http import HttpReadingRepository

_RENDERED = (
    "<html><body><h1>Rendered Article</h1>"
    "<p>" + " ".join(f"word{i}" for i in range(80)) + "</p></body></html>"
)


class _FakeOptions:
    def add_argument(self, arg: str) -> None:
        pass


class _FakeDriver:
    def __init__(self, options: object = None) -> None:
        self.options = options
        self.page_source = _RENDERED
        self.quit_called = False

    def set_page_load_timeout(self, timeout: int) -> None:
        pass

    def get(self, url: str) -> None:
        pass

    def quit(self) -> None:
        self.quit_called = True


def _install_fake_selenium(monkeypatch: pytest.MonkeyPatch) -> None:
    selenium = types.ModuleType("selenium")
    webdriver_mod = types.ModuleType("selenium.webdriver")
    webdriver_mod.Chrome = _FakeDriver
    chrome_mod = types.ModuleType("selenium.webdriver.chrome")
    options_mod = types.ModuleType("selenium.webdriver.chrome.options")
    options_mod.Options = _FakeOptions
    chrome_mod.options = options_mod
    webdriver_mod.chrome = chrome_mod
    selenium.webdriver = webdriver_mod

    monkeypatch.setitem(sys.modules, "selenium", selenium)
    monkeypatch.setitem(sys.modules, "selenium.webdriver", webdriver_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.chrome", chrome_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.chrome.options", options_mod)


def test_ssrf_refuses_loopback_without_browser():
    repo = HttpReadingRepository()
    html, err = repo.fetch_rendered_html("http://127.0.0.1/secret", 10)
    assert html == ""
    assert "loopback" in err


def test_ssrf_refuses_non_http_scheme():
    repo = HttpReadingRepository()
    html, err = repo.fetch_rendered_html("file:///etc/passwd", 10)
    assert html == ""
    assert "refused non-http" in err


def test_renders_public_url_and_returns_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_selenium(monkeypatch)
    repo = HttpReadingRepository()
    html, err = repo.fetch_rendered_html("https://example.com/article", 10)
    assert err == ""
    assert "Rendered Article" in html


def test_reports_error_on_render_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_selenium(monkeypatch)

    class _BoomDriver:
        def __init__(self, options: object = None) -> None:
            pass

        def set_page_load_timeout(self, timeout: int) -> None:
            pass

        def get(self, url: str) -> None:
            raise RuntimeError("tab crashed")

        @property
        def page_source(self) -> str:
            return ""

        def quit(self) -> None:
            pass

    import selenium.webdriver as wd

    monkeypatch.setattr(wd, "Chrome", _BoomDriver)
    repo = HttpReadingRepository()
    html, err = repo.fetch_rendered_html("https://example.com/article", 10)
    assert html == ""
    assert "RuntimeError" in err
