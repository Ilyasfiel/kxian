import json
from pathlib import Path
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kxian_bot.dashboard_template import OPS_DASHBOARD_HTML


pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError, sync_playwright


def test_dashboard_buttons_have_real_feedback_and_persistent_results(tmp_path):
    with _mock_dashboard_server() as base_url, _browser_page() as page:
        page.goto(f"{base_url}?lang=en")
        page.wait_for_selector("#dryRunButton")

        _click_and_expect_feedback(page, "#reloadButton", "Data reloaded")
        _click_and_expect_feedback(page, "#dryRunButton", "Testnet dry-run passed")
        assert "good" in page.locator("#dryRunStatus").get_attribute("class")

        _click_and_expect_feedback(page, "#observeButton", "Testnet observation failed: Missing exchange sandbox credentials")
        assert "2/6" in page.locator("#observeCycleStatus").inner_text()
        assert "Missing exchange sandbox credentials" in page.locator("#observeReasonStatus").inner_text()
        assert "Missing exchange sandbox credentials" in page.locator("#testnetAcceptanceTimeline").inner_text()

        _click_and_expect_feedback(page, "#testnetEvidenceButton", "Testnet evidence package downloaded")
        page.wait_for_function("window.__downloadedFiles && window.__downloadedFiles.includes('kxian-testnet-evidence.json')")
        assert "good" in page.locator("#testnetLaunchStatus").get_attribute("class")

        _click_and_expect_feedback(page, "#exportButton", "JSON exported")
        page.wait_for_function("window.__downloadedFiles && window.__downloadedFiles.includes('kxian-ops-dashboard.json')")

        _click_and_expect_feedback(page, "#pauseButton", "Automation paused")
        _click_and_expect_feedback(page, "#backtestButton", "Run locally:")
        _click_and_expect_feedback(page, "#simulateButton", "Simulation action is UI-only")
        _click_and_expect_feedback(page, "#settingsButton", "read-only")
        _click_and_expect_feedback(page, ".rail-btn.active", "Already on this page")
        _click_and_expect_feedback(page, ".rail-btn:not(.active)", "read-only")

        _click_and_expect_feedback(page, '[data-lang-option="en"]', "Language already active")
        assert page.evaluate("document.documentElement.lang") == "en"


def test_dashboard_failed_request_restores_button_and_shows_failure_toast():
    with _mock_dashboard_server(fail_dry_run=True) as base_url, _browser_page() as page:
        page.goto(f"{base_url}?lang=en")
        page.wait_for_selector("#dryRunButton")

        _click_and_expect_feedback(page, "#dryRunButton", "Testnet dry-run failed: Request failed")
        assert page.locator("#dryRunButton").get_attribute("aria-busy") is None
        assert not page.locator("#dryRunButton").is_disabled()


def test_dashboard_mobile_viewports_keep_core_actions_visible_and_non_overlapping():
    with _mock_dashboard_server() as base_url, _browser_page() as page:
        page.goto(f"{base_url}?lang=en")
        page.wait_for_selector("#dryRunButton")

        for viewport in [{"width": 390, "height": 844}, {"width": 768, "height": 1024}]:
            page.set_viewport_size(viewport)
            page.wait_for_timeout(50)
            layout = _mobile_layout_state(page)

            assert layout["railDisplay"] == "none"
            assert layout["topbarHeight"] > 60
            assert layout["topbarRows"] >= 2
            assert layout["topbarOverlap"] is False
            assert layout["stripColumns"] == 2
            assert page.locator("#dryRunButton").is_visible()
            assert page.locator("#observeButton").is_visible()
            assert page.locator("#testnetEvidenceButton").is_visible()

        _click_and_expect_feedback(page, "#dryRunButton", "Testnet dry-run passed")
        assert "good" in page.locator("#dryRunStatus").get_attribute("class")


def test_dashboard_observe_request_failure_restores_button_and_shows_failure_toast():
    with _mock_dashboard_server(fail_observe=True) as base_url, _browser_page() as page:
        page.goto(f"{base_url}?lang=en")
        page.wait_for_selector("#observeButton")

        _click_and_expect_feedback(page, "#observeButton", "Testnet observation failed: Request failed")
        assert page.locator("#observeButton").get_attribute("aria-busy") is None
        assert not page.locator("#observeButton").is_disabled()


def _click_and_expect_feedback(page, selector, expected_toast):
    button = page.locator(selector).first
    button.click()
    page.wait_for_function(
        """selector => document.querySelector(selector)?.getAttribute("aria-busy") === "true" """,
        arg=selector,
    )
    assert button.is_disabled()
    page.wait_for_function(
        """selector => document.querySelector(selector)?.disabled === false""",
        arg=selector,
    )
    assert button.get_attribute("aria-busy") is None
    page.wait_for_function(
        """text => document.querySelector("#toast")?.textContent.includes(text)""",
        arg=expected_toast,
    )


def _mobile_layout_state(page):
    return page.evaluate(
        """
        () => {
          const topbar = document.querySelector(".topbar");
          const strip = document.querySelector(".strip");
          const children = [...document.querySelectorAll(".topbar > *")].filter((el) => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && getComputedStyle(el).display !== "none";
          });
          const rects = children.map((el) => {
            const rect = el.getBoundingClientRect();
            return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom };
          });
          const topbarOverlap = rects.some((a, index) => rects.some((b, otherIndex) => {
            if (otherIndex <= index) return false;
            return a.x < b.right && a.right > b.x && a.y < b.bottom && a.bottom > b.y;
          }));
          return {
            railDisplay: getComputedStyle(document.querySelector(".rail")).display,
            topbarHeight: topbar.getBoundingClientRect().height,
            topbarRows: new Set(rects.map((rect) => Math.round(rect.y))).size,
            topbarOverlap,
            stripColumns: getComputedStyle(strip).gridTemplateColumns.trim().split(/\\s+/).length,
          };
        }
        """
    )


def _browser_page():
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(headless=True)
    except PlaywrightError as exc:
        playwright.stop()
        if "playwright install" in str(exc):
            pytest.skip("Playwright Chromium is not installed; run python -m playwright install chromium")
        raise
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    page.add_init_script(
        """
        window.__downloadedFiles = [];
        URL.createObjectURL = () => "blob:mock";
        URL.revokeObjectURL = () => {};
        HTMLAnchorElement.prototype.click = function () {
          if (this.download) window.__downloadedFiles.push(this.download);
        };
        """
    )

    class BrowserPage:
        def __enter__(self):
            return page

        def __exit__(self, exc_type, exc, tb):
            context.close()
            browser.close()
            playwright.stop()

    return BrowserPage()


def _mock_dashboard_server(fail_dry_run=False, fail_observe=False):
    server = ThreadingHTTPServer(("127.0.0.1", _free_port()), _MockDashboardHandler)
    server.fail_dry_run = fail_dry_run
    server.fail_observe = fail_observe
    base_url = f"http://127.0.0.1:{server.server_address[1]}/"

    class ServerContext:
        def __enter__(self):
            self.thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
            self.thread.start()
            return base_url

        def __exit__(self, exc_type, exc, tb):
            server.shutdown()
            server.server_close()
            self.thread.join(timeout=5)

    return ServerContext()


class _MockDashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._send_html(OPS_DASHBOARD_HTML)
            return
        if self.path.endswith("/api/overview"):
            payload = _overview_payload()
        elif self.path.endswith("/api/ops"):
            payload = _ops_payload()
        elif self.path.endswith("/api/preflight"):
            payload = _preflight_payload()
        elif self.path.endswith("/api/readiness"):
            payload = _readiness_payload()
        elif "/api/exchange-health" in self.path:
            payload = _exchange_health_payload()
        elif "/api/launch-checklist?target=testnet" in self.path:
            payload = _launch_payload(status="blocked", phase="waiting_for_testnet_observation")
        elif "/api/launch-checklist?target=live" in self.path:
            payload = {"status": "blocked", "phase": "live_disabled", "next_steps": []}
        elif self.path.endswith("/api/candles"):
            payload = {"candles": []}
        elif "/api/trades" in self.path:
            payload = {"trades": []}
        elif self.path.endswith("/api/testnet-evidence"):
            payload = {
                "schema": "kxian.testnet.evidence.v1",
                "schema_version": 1,
                "scope": {"mode": "testnet", "exchange": "binance", "symbol": "BTCUSDT", "interval": "4h", "use_testnet": True},
                "launch_checklist": _launch_payload(status="pass", phase="testnet_observed_ready_for_live_review"),
            }
        else:
            payload = {}
        self._send_json(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 0:
            self.rfile.read(length)
        if self.path.endswith("/api/testnet-dry-run"):
            if getattr(self.server, "fail_dry_run", False):
                self._send_json({"status": "fail", "reason": "mock_failure"}, status=500)
                return
            payload = {
                "status": "pass",
                "mode": "testnet",
                "exchange": "binance",
                "symbol": "BTCUSDT",
                "interval": "4h",
                "reason": "pass",
                "preflight": _preflight_payload(status="pass"),
            }
        elif self.path.endswith("/api/testnet-observe"):
            if getattr(self.server, "fail_observe", False):
                self._send_json({"status": "fail", "reason": "mock_failure"}, status=500)
                return
            payload = _failed_observation_payload()
        elif self.path.endswith("/api/automation-control"):
            payload = {"status": "ok", "preflight": _preflight_payload(status="pass")}
        else:
            payload = {}
        self._send_json(payload)

    def log_message(self, format, *args):
        return

    def _send_html(self, body):
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload, status=200):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _overview_payload():
    return {
        "markets": [],
        "latest_runs": [],
        "totals": {"markets": 0, "backtest_runs": 0, "trades": 0},
    }


def _ops_payload():
    return {
        "health": {
            "total_equity": 1000,
            "pnl": 0,
            "return_pct": 0,
            "gross_exposure": 0,
            "risk_budget_used": 0,
            "margin_health": 100,
            "open_alerts": 0,
        },
        "markets": [],
        "strategies": [],
        "runs": [],
        "orders": [],
        "fills": [],
        "signals": [],
        "risk_states": [],
        "loop_events": [],
        "events": [],
        "security": {"api_keys_active": 0, "audit_events": 0, "read_only": True},
        "market_diagnostics": {"classification": {"cost_pressure": "low", "regime": "unknown"}},
        "active_profile": {"status": "default", "source": "config", "parameters": {}, "evidence": {}},
    }


def _preflight_payload(status="fail"):
    return {
        "status": status,
        "mode": "paper",
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "checks": [{"name": "automation_control", "status": "pass", "message": "automation_control_is_active", "details": {"paused": False}}],
    }


def _readiness_payload():
    return {
        "status": "fail",
        "checks": [
            {"name": "scope", "status": "pass"},
            {"name": "credentials", "status": "fail", "message": "missing_exchange_credentials"},
            {"name": "automation", "status": "fail", "message": "testnet_autotrade_disabled"},
        ],
        "next_steps": ["set Binance Spot Testnet credentials"],
    }


def _exchange_health_payload():
    return {
        "status": "pass",
        "checks": [
            {"name": "public_market_data", "status": "pass", "message": "pass"},
            {"name": "trading_endpoint", "status": "pass", "message": "pass"},
        ],
    }


def _launch_payload(status, phase):
    return {
        "status": status,
        "phase": phase,
        "target_mode": "testnet",
        "checks": [
            {"name": "testnet_closed_loop_scope", "status": "pass", "message": "pass"},
            {"name": "testnet_profile", "status": "pass", "message": "pass"},
            {"name": "testnet_order_cleanup", "status": "pass", "message": "pass"},
        ],
        "testnet_observation": {"non_ordering": _failed_observation_payload(), "bounded_order": None},
        "next_steps": ["run testnet-observe --cycles 6"],
    }


def _failed_observation_payload():
    return {
        "status": "fail",
        "mode": "testnet",
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "cycles_completed": 2,
        "cycles_requested": 6,
        "failures": 1,
        "latest_reason": "missing_exchange_credentials",
        "results": [
            {"result": {"status": "pass", "reason": "pass", "order_lifecycle": {"state": "healthy_idle", "acceptable": True, "open_order_count": 0}}},
            {"reason": "missing_exchange_credentials", "result": {"status": "fail", "reason": "missing_exchange_credentials"}},
        ],
    }
