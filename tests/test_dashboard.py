import json

from kxian_bot.dashboard import _build_handler
from kxian_bot.config import RuntimeConfig
from kxian_bot.dashboard_template import OPS_DASHBOARD_HTML
from kxian_bot.models import BacktestRunSummary, BacktestTrade, Candle, LoopEvent, StressBacktestRunSummary, WalkForwardRunSummary
from kxian_bot.storage import SQLiteStorage


def test_dashboard_api_returns_overview_candles_runs_and_trades(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "kxian_bot.dashboard.run_exchange_health_check",
        lambda config, timeout_seconds=5.0: {
            "status": "pass",
            "mode": config.mode,
            "checks": [
                {"name": "public_market_data", "status": "pass"},
                {"name": "trading_endpoint", "status": "pass"},
            ],
        },
    )
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_candles(
        [
            Candle(open_time=1, open=10, high=11, low=9, close=10.5, volume=100, close_time=2),
            Candle(open_time=3, open=10.5, high=12, low=10, close=11.5, volume=120, close_time=4),
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    summary = BacktestRunSummary(
        run_id="run-1",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        start_time=1,
        end_time=4,
        strategy="moving_average_cross",
        parameters={"short_window": 2, "long_window": 4},
        candle_count=2,
        initial_equity=1000,
        final_equity=1001,
        return_pct=0.1,
        max_drawdown_pct=0.2,
        win_rate=50,
        profit_factor=1.2,
        trade_count=1,
        fees_paid=0.1,
        slippage_paid=0.05,
    )
    storage.record_backtest_run(summary)
    storage.record_stress_backtest_run(
        StressBacktestRunSummary(
            run_id="stress-1",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=1,
            end_time=4,
            strategy="moving_average_cross",
            parameters={"short_window": 2, "long_window": 4},
            candle_count=2,
            scenario_count=5,
            passed_scenarios=5,
            failed_scenarios=0,
            pass_rate=100,
            worst_return_pct=0.05,
            worst_drawdown_pct=0.3,
            worst_profit_factor=1.1,
            min_trade_count=1,
            scenarios=[{"name": "base", "passed": True}],
        )
    )
    storage.record_walk_forward_run(
        WalkForwardRunSummary(
            run_id="walk-1",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=1,
            end_time=4,
            strategy="moving_average_cross",
            parameters={"short_window": 2, "long_window": 4},
            candle_count=2,
            segment_count=2,
            passed_segments=2,
            failed_segments=0,
            pass_rate=100,
            total_trade_count=2,
            min_segment_trade_count=1,
            worst_return_pct=0.01,
            worst_drawdown_pct=0.2,
            worst_profit_factor=1.1,
            segments=[{"index": 1, "passed": True}],
        )
    )
    storage.record_backtest_trade(
        BacktestTrade(
            timestamp=1,
            symbol="BTCUSDT",
            side="buy",
            quantity=0.1,
            signal_price=10,
            execution_price=10.1,
            fee=0.01,
            slippage=0.01,
            pnl=0,
            reason="test",
        ),
        run_id="run-1",
    )
    storage.record_loop_event(
        LoopEvent(
            loop_id="loop-1",
            iteration=1,
            status="filled",
            mode="paper",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            payload={"reason": "demo_fill"},
        )
    )
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters={"short_window": 2, "long_window": 4, "stop_loss_pct": 1.5},
        evidence={
            "backtest": {"run_id": "run-1"},
            "stress": {"run_id": "stress-1"},
            "walk_forward": {"run_id": "walk-1"},
        },
        updated_by="test",
    )

    config = RuntimeConfig(db_path=str(tmp_path / "kxian.sqlite3"), market_data_source="sqlite", short_window=2, long_window=4)
    handler = _build_handler(storage, config)

    assert _call_json(handler, "/api/overview")["totals"]["backtest_runs"] == 1
    assert _call_json(handler, "/api/overview")["totals"]["stress_backtest_runs"] == 1
    assert _call_json(handler, "/api/overview")["totals"]["walk_forward_runs"] == 1
    assert len(_call_json(handler, "/api/candles?exchange=binance&symbol=BTCUSDT&interval=1m")["candles"]) == 2
    assert _call_json(handler, "/api/backtests")["runs"][0]["parameters"]["short_window"] == 2
    assert _call_json(handler, "/api/trades?run_id=run-1")["trades"][0]["side"] == "buy"
    preflight = _call_json(handler, "/api/preflight")
    assert preflight["mode"] == "paper"
    assert preflight["status"] == "fail"
    assert {check["name"] for check in preflight["checks"]} >= {"automation_control", "market_data", "execution_mode"}
    readiness = _call_json(handler, "/api/readiness")
    assert readiness["mode"] == "testnet"
    assert readiness["exchange"] == "binance"
    assert readiness["symbol"] == "BTCUSDT"
    assert readiness["interval"] == "4h"
    assert readiness["status"] == "fail"
    assert readiness["checks"][1]["name"] == "credentials"
    exchange_health = _call_json(handler, "/api/exchange-health?mode=testnet&timeout=1")
    assert exchange_health["mode"] == "testnet"
    assert "checks" in exchange_health
    checklist = _call_json(handler, "/api/launch-checklist?target=testnet")
    assert checklist["target_mode"] == "testnet"
    assert checklist["status"] == "blocked"
    assert checklist["checks"][0]["name"] == "testnet_closed_loop_scope"
    ops = _call_json(handler, "/api/ops")
    assert ops["loop_events"][0]["loop_id"] == "loop-1"
    assert ops["stress_runs"][0]["run_id"] == "stress-1"
    assert ops["walk_forward_runs"][0]["run_id"] == "walk-1"
    assert ops["strategies"][0]["stress_pass_rate"] == 100
    assert ops["strategies"][0]["walk_forward_pass_rate"] == 100
    assert ops["active_profile"]["status"] == "active"
    assert ops["active_profile"]["source"] == "sqlite"
    assert ops["active_profile"]["parameters"]["short_window"] == 2
    assert ops["active_profile"]["parameters"]["stop_loss_pct"] == 1.5
    assert ops["active_profile"]["evidence"]["walk_forward"]["run_id"] == "walk-1"
    assert ops["market_diagnostics"]["symbol"] == "BTCUSDT"
    assert ops["market_diagnostics"]["buy_hold_return_pct"] == 9.5238
    assert ops["market_diagnostics"]["classification"]["cost_pressure"] == "low"
    assert any(event["source"] == "LOOP" and "filled" in event["message"] for event in ops["events"])
    loop_event = next(event for event in ops["events"] if event["source"] == "LOOP")
    assert loop_event["payload"]["reason"] == "demo_fill"
    assert loop_event["payload"]["loop_id"] == "loop-1"

    paused = _call_json(handler, "/api/automation-control", method="POST", body={"action": "pause", "reason": "review"})
    assert paused["status"] == "ok"
    assert paused["control"]["paused"] is True
    assert paused["preflight"]["status"] == "fail"
    assert storage.automation_control_status("paper", "binance", "BTCUSDT", "1m")["paused"] is True

    resumed = _call_json(handler, "/api/automation-control", method="POST", body={"action": "resume"})
    assert resumed["control"]["paused"] is False


def test_dashboard_testnet_dry_run_reports_missing_credentials(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    handler = _build_handler(
        storage,
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            mode="paper",
            exchange="binance",
            interval="4h",
            binance_api_key="",
            binance_api_secret="",
        ),
    )

    result = _call_json(handler, "/api/testnet-dry-run", method="POST", body={"sync_limit": 2})

    assert result["status"] == "fail"
    assert result["reason"] == "missing_exchange_credentials"
    assert result["mode"] == "testnet"
    assert result["credentials"]["failures"] == ["missing_binance_api_key", "missing_binance_api_secret"]


def test_dashboard_exchange_health_uses_requested_mode_and_timeout(monkeypatch, tmp_path):
    received = {}

    def fake_exchange_health(config, timeout_seconds=5.0):
        received.update(
            {
                "mode": config.mode,
                "use_testnet": config.use_testnet,
                "market_data_source": config.market_data_source,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"status": "pass", "mode": config.mode, "checks": []}

    monkeypatch.setattr("kxian_bot.dashboard.run_exchange_health_check", fake_exchange_health)
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    handler = _build_handler(storage, RuntimeConfig(db_path=str(tmp_path / "kxian.sqlite3"), mode="paper"))

    result = _call_json(handler, "/api/exchange-health?mode=live&timeout=99")

    assert result["status"] == "pass"
    assert received == {
        "mode": "live",
        "use_testnet": False,
        "market_data_source": "exchange",
        "timeout_seconds": 30.0,
    }


def test_dashboard_testnet_health_and_checklist_are_fixed_to_closed_loop_scope(monkeypatch, tmp_path):
    received = {}

    def fake_exchange_health(config, timeout_seconds=5.0):
        received["health"] = {
            "mode": config.mode,
            "exchange": config.exchange,
            "symbol": config.symbol,
            "interval": config.interval,
            "use_testnet": config.use_testnet,
            "market_data_source": config.market_data_source,
            "timeout_seconds": timeout_seconds,
        }
        return {"status": "pass", "mode": config.mode, "checks": []}

    def fake_launch_checklist(config, storage, target_mode=None):
        received["checklist"] = {
            "mode": config.mode,
            "exchange": config.exchange,
            "symbol": config.symbol,
            "interval": config.interval,
            "use_testnet": config.use_testnet,
            "market_data_source": config.market_data_source,
            "target_mode": target_mode,
        }
        return {"status": "blocked", "target_mode": target_mode, "checks": []}

    monkeypatch.setattr("kxian_bot.dashboard.run_exchange_health_check", fake_exchange_health)
    monkeypatch.setattr("kxian_bot.dashboard.run_launch_checklist", fake_launch_checklist)
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    handler = _build_handler(
        storage,
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            mode="paper",
            exchange="okx",
            symbol="ETHUSDT",
            interval="1m",
        ),
    )

    assert _call_json(handler, "/api/exchange-health?mode=testnet&timeout=1")["status"] == "pass"
    assert _call_json(handler, "/api/launch-checklist?target=testnet")["target_mode"] == "testnet"
    assert received == {
        "health": {
            "mode": "testnet",
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "use_testnet": True,
            "market_data_source": "exchange",
            "timeout_seconds": 1.0,
        },
        "checklist": {
            "mode": "testnet",
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "use_testnet": True,
            "market_data_source": "exchange",
            "target_mode": "testnet",
        },
    }


def test_dashboard_testnet_dry_run_uses_sanitized_bounds(monkeypatch, tmp_path):
    received = {}

    def fake_run_testnet_dry_run(config, sync_limit, execute_loop, sleep_seconds):
        received.update(
            {
                "mode": config.mode,
                "exchange": config.exchange,
                "symbol": config.symbol,
                "interval": config.interval,
                "use_testnet": config.use_testnet,
                "market_data_source": config.market_data_source,
                "sync_limit": sync_limit,
                "execute_loop": execute_loop,
                "sleep_seconds": sleep_seconds,
            }
        )
        return {"status": "pass", "mode": config.mode, "symbol": config.symbol}

    monkeypatch.setattr("kxian_bot.dashboard.run_testnet_dry_run", fake_run_testnet_dry_run)
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    handler = _build_handler(
        storage,
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            mode="paper",
            exchange="okx",
            symbol="ETHUSDT",
            market_data_source="sqlite",
            interval="1m",
        ),
    )

    result = _call_json(
        handler,
        "/api/testnet-dry-run",
        method="POST",
        body={"sync_limit": 5000, "execute_loop": True, "sleep_seconds": 99},
    )

    assert result["status"] == "pass"
    assert received == {
        "mode": "testnet",
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "use_testnet": True,
        "market_data_source": "exchange",
        "sync_limit": 1000,
        "execute_loop": True,
        "sleep_seconds": 5.0,
    }


def test_dashboard_testnet_observe_uses_sanitized_bounds(monkeypatch, tmp_path):
    received = {}

    def fake_run_testnet_observation(
        config,
        cycles,
        sync_limit,
        execute_loop,
        sleep_seconds,
        continue_on_failure,
    ):
        received.update(
            {
                "mode": config.mode,
                "exchange": config.exchange,
                "symbol": config.symbol,
                "interval": config.interval,
                "use_testnet": config.use_testnet,
                "market_data_source": config.market_data_source,
                "cycles": cycles,
                "sync_limit": sync_limit,
                "execute_loop": execute_loop,
                "sleep_seconds": sleep_seconds,
                "continue_on_failure": continue_on_failure,
            }
        )
        return {"status": "pass", "mode": config.mode, "cycles_completed": cycles}

    monkeypatch.setattr("kxian_bot.dashboard.run_testnet_observation", fake_run_testnet_observation)
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    handler = _build_handler(
        storage,
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            mode="paper",
            exchange="okx",
            symbol="ETHUSDT",
            market_data_source="sqlite",
            interval="1m",
        ),
    )

    result = _call_json(
        handler,
        "/api/testnet-observe",
        method="POST",
        body={
            "cycles": 200,
            "sync_limit": 5000,
            "execute_loop": True,
            "sleep_seconds": 99,
            "continue_on_failure": True,
        },
    )

    assert result["status"] == "pass"
    assert received == {
        "mode": "testnet",
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "use_testnet": True,
        "market_data_source": "exchange",
        "cycles": 24,
        "sync_limit": 1000,
        "execute_loop": True,
        "sleep_seconds": 5.0,
        "continue_on_failure": True,
    }


def test_dashboard_testnet_observe_defaults_to_six_cycles(monkeypatch, tmp_path):
    received = {}

    def fake_run_testnet_observation(
        config,
        cycles,
        sync_limit,
        execute_loop,
        sleep_seconds,
        continue_on_failure,
    ):
        received.update({"cycles": cycles, "sync_limit": sync_limit, "sleep_seconds": sleep_seconds})
        return {"status": "pass", "mode": config.mode, "cycles_completed": cycles}

    monkeypatch.setattr("kxian_bot.dashboard.run_testnet_observation", fake_run_testnet_observation)
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    handler = _build_handler(storage, RuntimeConfig(db_path=str(tmp_path / "kxian.sqlite3")))

    result = _call_json(handler, "/api/testnet-observe", method="POST", body={})

    assert result["cycles_completed"] == 6
    assert received == {"cycles": 6, "sync_limit": 500, "sleep_seconds": 0.0}


def test_dashboard_testnet_evidence_api_is_fixed_scope_and_redacted(monkeypatch, tmp_path):
    def fake_launch_checklist(config, storage, target_mode=None):
        assert target_mode == "testnet"
        return {
            "status": "pass",
            "target_mode": target_mode,
            "phase": "testnet_observed_ready_for_live_review",
            "api_secret": "secret-value",
        }

    monkeypatch.setattr("kxian_bot.dashboard.run_launch_checklist", fake_launch_checklist)
    monkeypatch.setattr(
        "kxian_bot.dashboard.run_testnet_dry_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("evidence API must not run dry-run")),
    )
    monkeypatch.setattr(
        "kxian_bot.dashboard.run_testnet_observation",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("evidence API must not run observation")),
    )
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    handler = _build_handler(
        storage,
        RuntimeConfig(
            db_path=str(tmp_path / "kxian.sqlite3"),
            mode="paper",
            exchange="okx",
            symbol="ETHUSDT",
            interval="1m",
            binance_api_key="api-key-value",
            binance_api_secret="secret-value",
        ),
    )

    result = _call_json(handler, "/api/testnet-evidence")
    raw = json.dumps(result)

    assert result["scope"]["mode"] == "testnet"
    assert result["scope"]["exchange"] == "binance"
    assert result["scope"]["symbol"] == "BTCUSDT"
    assert result["scope"]["interval"] == "4h"
    assert result["launch_checklist"]["api_secret"] == "<redacted>"
    assert "api-key-value" not in raw
    assert "secret-value" not in raw


def test_dashboard_api_uses_latest_contiguous_candle_window(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_candles(
        [
            Candle(open_time=0, open=1, high=1, low=1, close=1, volume=1, close_time=59_999),
            Candle(open_time=1_704_067_200_000, open=10, high=10, low=10, close=10, volume=1, close_time=1_704_067_259_999),
            Candle(open_time=1_704_067_260_000, open=11, high=11, low=11, close=11, volume=1, close_time=1_704_067_319_999),
            Candle(open_time=1_704_067_320_000, open=12, high=12, low=12, close=12, volume=1, close_time=1_704_067_379_999),
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    handler = _build_handler(storage, RuntimeConfig(db_path=str(tmp_path / "kxian.sqlite3"), market_data_source="sqlite"))

    overview = _call_json(handler, "/api/overview")
    candles = _call_json(handler, "/api/candles?exchange=binance&symbol=BTCUSDT&interval=1m&limit=10")

    assert overview["markets"][0]["candle_count"] == 3
    assert overview["markets"][0]["raw_candle_count"] == 4
    assert overview["markets"][0]["outlier_candle_count"] == 1
    assert overview["markets"][0]["start_time"] == 1_704_067_200_000
    assert [candle["open_time"] for candle in candles["candles"]] == [
        1_704_067_200_000,
        1_704_067_260_000,
        1_704_067_320_000,
    ]


def test_dashboard_template_exposes_preflight_startup_gate():
    assert "/api/preflight" in OPS_DASHBOARD_HTML
    assert 'id="preflightStatus"' in OPS_DASHBOARD_HTML
    assert 'id="activeProfileSource"' in OPS_DASHBOARD_HTML
    assert 'id="activeProfileWindows"' in OPS_DASHBOARD_HTML
    assert 'id="activeProfileExits"' in OPS_DASHBOARD_HTML
    assert 'id="activeProfileEvidence"' in OPS_DASHBOARD_HTML
    assert 'function renderActiveProfile' in OPS_DASHBOARD_HTML
    assert 'data-i18n="startupGate"' in OPS_DASHBOARD_HTML
    assert 'data-i18n="marketDiagnostics"' in OPS_DASHBOARD_HTML
    assert 'id="marketRegime"' in OPS_DASHBOARD_HTML
    assert 'id="marketCostPressure"' in OPS_DASHBOARD_HTML
    assert 'id="marketBuyHold"' in OPS_DASHBOARD_HTML
    assert 'id="marketFriction"' in OPS_DASHBOARD_HTML
    assert 'function renderMarketDiagnostics' in OPS_DASHBOARD_HTML
    assert "/api/launch-checklist?target=testnet" in OPS_DASHBOARD_HTML
    assert "/api/launch-checklist?target=live" in OPS_DASHBOARD_HTML
    assert 'data-i18n="launchGate"' in OPS_DASHBOARD_HTML
    assert 'data-i18n="exchangeHealth"' in OPS_DASHBOARD_HTML
    assert 'id="publicMarketHealth"' in OPS_DASHBOARD_HTML
    assert 'id="tradingEndpointHealth"' in OPS_DASHBOARD_HTML
    assert 'id="exchangeHealthSteps"' in OPS_DASHBOARD_HTML
    assert "/api/exchange-health?mode=testnet&timeout=2" in OPS_DASHBOARD_HTML
    assert "function renderExchangeHealth" in OPS_DASHBOARD_HTML
    assert 'id="testnetLaunchStatus"' in OPS_DASHBOARD_HTML
    assert 'id="liveLaunchStatus"' in OPS_DASHBOARD_HTML
    assert 'id="launchObservationStatus"' in OPS_DASHBOARD_HTML
    assert 'id="launchSteps"' in OPS_DASHBOARD_HTML
    assert "function renderLaunchChecklist" in OPS_DASHBOARD_HTML
    assert "function refreshLaunchChecklist" in OPS_DASHBOARD_HTML
    assert "/api/testnet-evidence" in OPS_DASHBOARD_HTML
    assert 'id="testnetAcceptanceTimeline" aria-live="polite"' in OPS_DASHBOARD_HTML
    assert 'id="testnetEvidenceButton"' in OPS_DASHBOARD_HTML
    assert "function renderTestnetAcceptanceTimeline" in OPS_DASHBOARD_HTML


def test_dashboard_template_exposes_language_switch():
    assert 'class="language-control"' in OPS_DASHBOARD_HTML
    assert 'data-i18n="language"' in OPS_DASHBOARD_HTML
    assert 'data-lang-option="zh" aria-pressed="true" data-i18n="chinese" data-i18n-attr="title:switchToChinese">中文</button>' in OPS_DASHBOARD_HTML
    assert 'data-lang-option="en" aria-pressed="false" data-i18n="english" data-i18n-attr="title:switchToEnglish">English</button>' in OPS_DASHBOARD_HTML
    assert 'id="observeButton" data-i18n="runTestnetObserve"' in OPS_DASHBOARD_HTML
    assert 'postJson("/api/testnet-observe"' in OPS_DASHBOARD_HTML
    assert 'run_kxian_bot_testnet_dry_run' in OPS_DASHBOARD_HTML
    assert 'set_sandbox_api_credentials_for_the_selected_exchange' in OPS_DASHBOARD_HTML
    assert '<title>量化运维控制台</title>' in OPS_DASHBOARD_HTML
    assert 'aria-label="主导航"' in OPS_DASHBOARD_HTML
    assert 'data-i18n="envProdPaper">生产 / 模拟盘</option>' in OPS_DASHBOARD_HTML
    assert 'data-i18n="totalEquity">总权益</div>' in OPS_DASHBOARD_HTML
    assert 'data-i18n="riskInspector">风险检查器</h2>' in OPS_DASHBOARD_HTML
    assert 'data-i18n="runBacktest">运行回测</button>' in OPS_DASHBOARD_HTML
    assert 'id="chartTitle" data-i18n="chartTitleEmpty">价格带</h2>' in OPS_DASHBOARD_HTML
    assert 'primaryNav: "主导航"' in OPS_DASHBOARD_HTML
    assert 'switchToChinese: "切换到中文"' in OPS_DASHBOARD_HTML
    assert 'switchToEnglish: "Switch to English"' in OPS_DASHBOARD_HTML
    assert 'chartTitleEmpty: "价格带"' in OPS_DASHBOARD_HTML
    assert 'chartTitleEmpty: "Price Tape"' in OPS_DASHBOARD_HTML
    assert 'envProdPaper: "PROD / PAPER"' in OPS_DASHBOARD_HTML
    assert 'function preferredLanguage()' in OPS_DASHBOARD_HTML
    assert 'new URLSearchParams(window.location.search).get("lang")' in OPS_DASHBOARD_HTML
    assert 'const LANGUAGE_STORAGE_KEY = "kxian-dashboard-lang-v2"' in OPS_DASHBOARD_HTML
    assert "function persistLanguage(lang)" in OPS_DASHBOARD_HTML
    assert "function storedLanguage()" in OPS_DASHBOARD_HTML
    assert "persistLanguage(urlLang);" in OPS_DASHBOARD_HTML
    assert "localStorage.getItem(LANGUAGE_STORAGE_KEY)" in OPS_DASHBOARD_HTML
    assert 'return "zh";' in OPS_DASHBOARD_HTML
    assert ".language-control {" in OPS_DASHBOARD_HTML
    language_css = OPS_DASHBOARD_HTML.split(".language-control {", 1)[1].split("}", 1)[0]
    assert "position: fixed;" not in language_css
    assert "updateChartTitle();" in OPS_DASHBOARD_HTML
    assert "function updateChartTitle(market)" in OPS_DASHBOARD_HTML
    assert 'String(target.exchange).toUpperCase()' in OPS_DASHBOARD_HTML
    assert 'function messageLabel' in OPS_DASHBOARD_HTML
    assert 'function checkMessage(check)' in OPS_DASHBOARD_HTML
    assert 'local_coverage_days' in OPS_DASHBOARD_HTML
    assert 'local_coverage_candles' in OPS_DASHBOARD_HTML
    assert 'local_outlier_candles' in OPS_DASHBOARD_HTML
    assert 'localCandles: "本地K线"' in OPS_DASHBOARD_HTML
    assert 'localCoverage: "本地覆盖"' in OPS_DASHBOARD_HTML
    assert 'function eventMessage' in OPS_DASHBOARD_HTML
    assert 'required_tables_are_present' in OPS_DASHBOARD_HTML
    assert 'stress_gate' in OPS_DASHBOARD_HTML
    assert 'walk_forward_gate' in OPS_DASHBOARD_HTML
    assert 'trading_rules' in OPS_DASHBOARD_HTML
    assert 'automation_control' in OPS_DASHBOARD_HTML
    assert 'exchange_rule_min_notional' in OPS_DASHBOARD_HTML
    assert 'trailing_stop_triggered' in OPS_DASHBOARD_HTML
    assert 'downtrend_breakdown_short_entry' in OPS_DASHBOARD_HTML
    assert 'regime_filtered_ma_buy' in OPS_DASHBOARD_HTML
    assert 'regime_filtered_ma_sell' in OPS_DASHBOARD_HTML
    assert 'volatility_breakout_trend_buy' in OPS_DASHBOARD_HTML
    assert 'volatility_breakout_trend_sell' in OPS_DASHBOARD_HTML
    assert 'short_stop_loss_triggered' in OPS_DASHBOARD_HTML
    assert 'research_only_strategy_not_promotable' in OPS_DASHBOARD_HTML
    assert 'profileEvidence' in OPS_DASHBOARD_HTML
    assert 'promotedProfile' in OPS_DASHBOARD_HTML
    assert 'pnlShort' in OPS_DASHBOARD_HTML
    assert 'walkForwardShort' in OPS_DASHBOARD_HTML


def test_dashboard_template_has_unified_button_feedback_and_testnet_result_state():
    assert 'function withButtonFeedback' in OPS_DASHBOARD_HTML
    assert 'button.disabled = true' in OPS_DASHBOARD_HTML
    assert 'button.disabled = false' in OPS_DASHBOARD_HTML
    assert 'button.setAttribute("aria-busy", "true")' in OPS_DASHBOARD_HTML
    assert 'button.removeAttribute("aria-busy")' in OPS_DASHBOARD_HTML
    assert "const minimumMs = Number(options.minimumMs ?? 220)" in OPS_DASHBOARD_HTML
    assert 'role="status" aria-live="polite" aria-atomic="true"' in OPS_DASHBOARD_HTML
    assert 'button:disabled' in OPS_DASHBOARD_HTML
    assert 'id="settingsButton"' in OPS_DASHBOARD_HTML
    assert 'id="observeCycleStatus"' in OPS_DASHBOARD_HTML
    assert 'id="observeReasonStatus"' in OPS_DASHBOARD_HTML
    assert 'id="orderLifecycleStatus"' in OPS_DASHBOARD_HTML
    assert 'function renderObservationSummary' in OPS_DASHBOARD_HTML
    assert 'function latestOrderLifecycle' in OPS_DASHBOARD_HTML
    assert 'function refreshLaunchChecklistInBackground' in OPS_DASHBOARD_HTML
    assert 'refreshLaunchChecklistInBackground();' in OPS_DASHBOARD_HTML
    assert 'fetchJson("/api/ops").then((ops)' in OPS_DASHBOARD_HTML
    assert 'withButtonFeedback($("reloadButton")' in OPS_DASHBOARD_HTML
    assert 'withButtonFeedback($("pauseButton")' in OPS_DASHBOARD_HTML
    assert 'withButtonFeedback($("dryRunButton")' in OPS_DASHBOARD_HTML
    assert 'withButtonFeedback($("observeButton")' in OPS_DASHBOARD_HTML
    assert 'withButtonFeedback($("testnetEvidenceButton")' in OPS_DASHBOARD_HTML
    assert 'withButtonFeedback($("exportButton")' in OPS_DASHBOARD_HTML
    assert 'withButtonFeedback(button' in OPS_DASHBOARD_HTML
    assert 'row.addEventListener("click", () => withButtonFeedback(row' in OPS_DASHBOARD_HTML
    assert 'cycles: 6' in OPS_DASHBOARD_HTML
    assert 'Observe 6 Cycles' in OPS_DASHBOARD_HTML
    assert 'settingsUnavailable' in OPS_DASHBOARD_HTML
    assert 'navUnavailable' in OPS_DASHBOARD_HTML
    assert 'currentNav' in OPS_DASHBOARD_HTML
    assert 'langAlreadyActive' in OPS_DASHBOARD_HTML
    assert 'restoreText: false' in OPS_DASHBOARD_HTML
    assert 'dryRunEl.textContent = state.dryRun ? dryRunLabel(state.dryRun)' in OPS_DASHBOARD_HTML
    assert 'renderObservationSummary(state.observation)' in OPS_DASHBOARD_HTML
    assert 'renderTestnetAcceptanceTimeline();' in OPS_DASHBOARD_HTML
    assert 'downloadJson("kxian-testnet-evidence.json", data)' in OPS_DASHBOARD_HTML
    assert "function checkStepMeta" in OPS_DASHBOARD_HTML
    assert "function checklistStepMeta" in OPS_DASHBOARD_HTML
    assert "observation.latest_reason || latestObservationReason(observation)" in OPS_DASHBOARD_HTML
    assert "clear open sandbox orders with order-status" in OPS_DASHBOARD_HTML
    assert 'if (!succeeded || options.restoreText !== false) button.textContent = originalText' in OPS_DASHBOARD_HTML
    assert 'document.querySelectorAll(".rail-btn").forEach' in OPS_DASHBOARD_HTML


def test_dashboard_template_escapes_dynamic_html_fields():
    assert "const escapeHtml" in OPS_DASHBOARD_HTML
    assert "${escapeHtml(row.symbol || \"-\")}" in OPS_DASHBOARD_HTML
    assert "${escapeHtml(eventMessage(event))}" in OPS_DASHBOARD_HTML
    assert "${escapeHtml(run.run_id)}" in OPS_DASHBOARD_HTML
    assert "errorBlock.textContent" in OPS_DASHBOARD_HTML
    assert "document.body.innerHTML" not in OPS_DASHBOARD_HTML


def test_dashboard_responses_include_security_headers(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    handler = _build_handler(storage, RuntimeConfig(db_path=str(tmp_path / "kxian.sqlite3")))

    response = _call_response(handler, "/")
    assert response["headers"]["X-Content-Type-Options"] == "nosniff"
    assert response["headers"]["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response["headers"]["Content-Security-Policy"]


def _call_json(handler, path, method="GET", body=None):
    captured = _call_response(handler, path, method=method, body=body)
    assert captured["status"] == 200
    return json.loads(captured["body"].decode("utf-8"))


def _call_response(handler, path, method="GET", body=None):
    captured = {}

    def send_response(self, status):
        captured["status"] = status

    def send_header(self, key, value):
        captured.setdefault("headers", {})[key] = value

    def end_headers(self):
        return None

    class Writer:
        def write(self, payload):
            captured["body"] = payload

    class Reader:
        def __init__(self, payload):
            self.payload = payload

        def read(self, length):
            return self.payload[:length]

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
    request = handler.__new__(handler)
    request.path = path
    request.wfile = Writer()
    payload = json.dumps(body or {}).encode("utf-8")
    request.rfile = Reader(payload)
    request.headers = {"Content-Length": str(len(payload))}
    if method == "POST":
        request.do_POST()
    else:
        request.do_GET()
    return captured
