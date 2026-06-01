import json

from kxian_bot.config import RuntimeConfig
from kxian_bot import live_setup
from kxian_bot.live_setup import run_live_setup_check
from kxian_bot.models import BacktestRunSummary, Candle, ExchangeOrder, LoopEvent, StressBacktestRunSummary, WalkForwardRunSummary
from kxian_bot.storage import SQLiteStorage


SAMPLE_VALIDATION_EVIDENCE = {
    "status": "pass",
    "sample_count": 2,
    "passed_samples": 2,
    "failed_samples": 0,
    "summary": {
        "total_trade_count": 70,
        "min_return_pct": 1.0,
        "min_profit_factor": 1.3,
        "min_stress_pass_rate": 100.0,
        "min_walk_forward_pass_rate": 75.0,
    },
    "samples": [],
}


def test_live_setup_check_blocks_with_only_testnet_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(live_setup, "run_exchange_health_check", lambda config, timeout_seconds=5.0: _health(endpoint="https://api.binance.com/api/v3/time"))
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        interval="4h",
        binance_api_key="api-key-value",
        binance_api_secret="secret-value",
    )

    result = run_live_setup_check(config)
    raw = json.dumps(result)

    assert result["status"] == "blocked"
    assert result["phase"] == "blocked_before_live_canary"
    assert result["mode"] == "live"
    assert result["use_testnet"] is False
    assert result["will_submit_orders"] is False
    assert result["credentials"]["present"]["binance_api_key"] is True
    assert result["credentials"]["production_credentials_confirmed"] is False
    assert "api-key-value" not in raw
    assert "secret-value" not in raw
    assert any("KXIAN_LIVE_CREDENTIALS_CONFIRMED=true" in step for step in result["next_steps"])


def test_live_setup_check_passes_after_live_profile_and_gates(monkeypatch, tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_live_ready_state(storage)
    monkeypatch.setattr(live_setup, "run_exchange_health_check", lambda config, timeout_seconds=5.0: _health(endpoint="https://api.binance.com/api/v3/time"))
    config = RuntimeConfig(
        mode="live",
        db_path=str(db_path),
        interval="4h",
        market_data_source="sqlite",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        allow_live=True,
        use_testnet=True,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="LIVE:binance:BTCUSDT:4h",
        live_credentials_confirmed=True,
        max_live_order_usdt=25,
        binance_api_key="api-key-value",
        binance_api_secret="secret-value",
    )

    result = run_live_setup_check(config, storage)

    assert result["status"] == "pass"
    assert result["reason"] == "live_setup_ready"
    assert result["phase"] == "ready_for_bounded_live_canary"
    assert result["use_testnet"] is False
    assert result["risk_limits"]["max_live_order_usdt"] == 25
    assert [check["status"] for check in result["checks"]] == ["pass"] * len(result["checks"])
    assert result["next_steps"][0].startswith("ask the operator for explicit approval")


def test_live_setup_check_blocks_if_health_points_to_testnet(monkeypatch, tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_live_ready_state(storage)
    monkeypatch.setattr(live_setup, "run_exchange_health_check", lambda config, timeout_seconds=5.0: _health(endpoint="https://testnet.binance.vision/api/v3/time"))
    config = _ready_live_config(db_path)

    result = run_live_setup_check(config, storage)
    endpoint_check = next(check for check in result["checks"] if check["name"] == "endpoint_safety")

    assert result["status"] == "blocked"
    assert "live_trading_endpoint_is_testnet" in endpoint_check["details"]["failures"]
    assert any("live trading endpoint is production" in step for step in result["next_steps"])


def test_live_setup_check_blocks_large_first_canary(monkeypatch, tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_live_ready_state(storage)
    monkeypatch.setattr(live_setup, "run_exchange_health_check", lambda config, timeout_seconds=5.0: _health(endpoint="https://api.binance.com/api/v3/time"))
    config = _ready_live_config(db_path, max_live_order_usdt=51)

    result = run_live_setup_check(config, storage)
    risk_check = next(check for check in result["checks"] if check["name"] == "live_canary_risk_limit")

    assert result["status"] == "blocked"
    assert risk_check["details"]["failures"] == ["max_live_order_exceeds_canary_limit"]
    assert any("KXIAN_MAX_LIVE_ORDER_USDT<=50" in step for step in result["next_steps"])


def test_live_setup_check_blocks_bitget_canary_above_5u(monkeypatch, tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    monkeypatch.setattr(live_setup, "run_exchange_health_check", lambda config, timeout_seconds=5.0: _health(endpoint="https://api.bitget.com/api/v2/public/time", exchange="bitget"))
    monkeypatch.setattr(live_setup, "run_readiness", lambda config, storage: {"status": "pass", "checks": [], "next_steps": []})
    monkeypatch.setattr(live_setup, "run_launch_checklist", lambda config, storage, target_mode="live": {"status": "pass", "phase": "ready_for_bounded_live_loop", "checks": [], "next_steps": []})
    config = RuntimeConfig(
        mode="live",
        exchange="bitget",
        db_path=str(db_path),
        allow_live=True,
        use_testnet=False,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="LIVE:bitget:BTCUSDT:4h",
        live_credentials_confirmed=True,
        max_live_order_usdt=6,
        bitget_api_key="key",
        bitget_api_secret="secret",
        bitget_api_passphrase="passphrase",
    )

    result = run_live_setup_check(config, SQLiteStorage(db_path))
    risk_check = next(check for check in result["checks"] if check["name"] == "live_canary_risk_limit")

    assert result["status"] == "blocked"
    assert risk_check["details"]["max_live_canary_order_usdt"] == 5
    assert any("KXIAN_MAX_LIVE_ORDER_USDT<=5" in step for step in result["next_steps"])


def test_live_setup_check_allows_bitget_before_first_canary(monkeypatch, tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_bitget_live_profile(storage)
    monkeypatch.setattr(
        live_setup,
        "run_exchange_health_check",
        lambda config, timeout_seconds=5.0: _health(
            endpoint="https://api.bitget.com/api/v2/public/time",
            exchange="bitget",
        ),
    )
    config = _ready_bitget_live_config(db_path)

    result = run_live_setup_check(config, storage)
    launch_check = next(check for check in result["checks"] if check["name"] == "launch_checklist")

    assert result["status"] == "pass"
    assert result["phase"] == "ready_for_bounded_live_canary"
    assert result["will_submit_orders"] is False
    assert result["risk_limits"]["max_live_canary_order_usdt"] == 5
    assert launch_check["details"]["pre_canary_ready"] is True
    assert launch_check["details"]["failed_checks"] == ["bitget_live_canary_order"]
    assert result["launch_checklist"]["phase"] == "blocked_before_bitget_live_canary"
    assert result["launch_checklist"]["checks"][4]["details"]["failures"] == ["missing_bitget_live_canary_order"]
    assert result["next_steps"][0].startswith("ask the operator")


def test_live_setup_check_blocks_bitget_open_canary_order(monkeypatch, tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_bitget_live_profile(storage)
    storage.record_exchange_order(
        ExchangeOrder(
            symbol="BTCUSDT",
            side="buy",
            quantity=0.0001,
            price=50000,
            status="submitted",
            exchange_order_id="bitget-open",
        ),
        mode="live",
        exchange="bitget",
    )
    monkeypatch.setattr(
        live_setup,
        "run_exchange_health_check",
        lambda config, timeout_seconds=5.0: _health(
            endpoint="https://api.bitget.com/api/v2/public/time",
            exchange="bitget",
        ),
    )
    config = _ready_bitget_live_config(db_path)

    result = run_live_setup_check(config, storage)
    launch_check = next(check for check in result["checks"] if check["name"] == "launch_checklist")

    assert result["status"] == "blocked"
    assert launch_check["details"]["pre_canary_ready"] is False
    assert any("order-status" in step or "clear all Bitget open orders" in step for step in result["next_steps"])


def _ready_live_config(db_path, max_live_order_usdt: float = 25) -> RuntimeConfig:
    return RuntimeConfig(
        mode="live",
        db_path=str(db_path),
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        allow_live=True,
        use_testnet=False,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="LIVE:binance:BTCUSDT:4h",
        live_credentials_confirmed=True,
        max_live_order_usdt=max_live_order_usdt,
        binance_api_key="key",
        binance_api_secret="secret",
    )


def _ready_bitget_live_config(db_path, max_live_order_usdt: float = 5) -> RuntimeConfig:
    return RuntimeConfig(
        mode="live",
        exchange="bitget",
        db_path=str(db_path),
        interval="4h",
        short_window=10,
        long_window=30,
        min_order_usdt=1,
        allow_live=True,
        use_testnet=False,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="LIVE:bitget:BTCUSDT:4h",
        live_credentials_confirmed=True,
        max_live_order_usdt=max_live_order_usdt,
        bitget_api_key="key",
        bitget_api_secret="secret",
        bitget_api_passphrase="passphrase",
    )


def _health(endpoint: str, exchange: str = "binance") -> dict:
    return {
        "status": "pass",
        "mode": "live",
        "exchange": exchange,
        "symbol": "BTCUSDT",
        "interval": "4h",
        "checks": [
            {"name": "public_market_data", "status": "pass", "details": {"endpoint": "https://api.binance.com/api/v3/klines", "failures": []}},
            {"name": "trading_endpoint", "status": "pass", "details": {"endpoint": endpoint, "failures": []}},
        ],
        "next_steps": ["exchange endpoints are reachable for the current configuration"],
    }


def _record_bitget_live_profile(storage: SQLiteStorage) -> None:
    storage.record_backtest_run(
        BacktestRunSummary(
            run_id="bitget-run-ready",
            exchange="bitget",
            symbol="BTCUSDT",
            interval="4h",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
            candle_count=40,
            initial_equity=1000,
            final_equity=1020,
            return_pct=2.0,
            max_drawdown_pct=5.0,
            win_rate=50,
            profit_factor=1.5,
            trade_count=35,
            fees_paid=1,
            slippage_paid=0.5,
        )
    )
    storage.record_stress_backtest_run(
        StressBacktestRunSummary(
            run_id="bitget-stress-ready",
            exchange="bitget",
            symbol="BTCUSDT",
            interval="4h",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
            candle_count=40,
            scenario_count=5,
            passed_scenarios=5,
            failed_scenarios=0,
            pass_rate=100,
            worst_return_pct=1.0,
            worst_drawdown_pct=7.0,
            worst_profit_factor=1.3,
            min_trade_count=35,
            scenarios=[],
        )
    )
    storage.record_walk_forward_run(
        WalkForwardRunSummary(
            run_id="bitget-walk-ready",
            exchange="bitget",
            symbol="BTCUSDT",
            interval="4h",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
            candle_count=40,
            segment_count=3,
            passed_segments=3,
            failed_segments=0,
            pass_rate=100,
            total_trade_count=35,
            min_segment_trade_count=5,
            worst_return_pct=0.5,
            worst_drawdown_pct=5.0,
            worst_profit_factor=1.2,
            segments=[],
        )
    )
    storage.upsert_strategy_profile(
        mode="live",
        exchange="bitget",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
        evidence={
            "sample_validation": SAMPLE_VALIDATION_EVIDENCE,
            "bitget_live_gray": {"status": "approved", "max_order_usdt": 5, "canary_limit_usdt": 5, "approved_at": 1},
        },
        updated_by="test",
    )


def _record_live_ready_state(storage: SQLiteStorage) -> None:
    storage.upsert_candles(
        [
            Candle(open_time=i, open=10 + i, high=10 + i, low=10 + i, close=10 + i, volume=1, close_time=i + 1)
            for i in range(40)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )
    storage.record_backtest_run(
        BacktestRunSummary(
            run_id="run-ready",
            exchange="binance",
            symbol="BTCUSDT",
            interval="4h",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
            candle_count=40,
            initial_equity=1000,
            final_equity=1020,
            return_pct=2.0,
            max_drawdown_pct=5.0,
            win_rate=50,
            profit_factor=1.5,
            trade_count=35,
            fees_paid=1,
            slippage_paid=0.5,
        )
    )
    storage.record_stress_backtest_run(
        StressBacktestRunSummary(
            run_id="stress-ready",
            exchange="binance",
            symbol="BTCUSDT",
            interval="4h",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
            candle_count=40,
            scenario_count=5,
            passed_scenarios=5,
            failed_scenarios=0,
            pass_rate=100,
            worst_return_pct=1.0,
            worst_drawdown_pct=7.0,
            worst_profit_factor=1.3,
            min_trade_count=35,
            scenarios=[],
        )
    )
    storage.record_walk_forward_run(
        WalkForwardRunSummary(
            run_id="walk-ready",
            exchange="binance",
            symbol="BTCUSDT",
            interval="4h",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
            candle_count=40,
            segment_count=3,
            passed_segments=3,
            failed_segments=0,
            pass_rate=100,
            total_trade_count=35,
            min_segment_trade_count=5,
            worst_return_pct=0.5,
            worst_drawdown_pct=5.0,
            worst_profit_factor=1.2,
            segments=[],
        )
    )
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
        evidence={
            "sample_validation": SAMPLE_VALIDATION_EVIDENCE,
            "promotion": {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"},
        },
        updated_by="test",
    )
    _record_observation(storage, execute_loop=False)
    _record_observation(storage, execute_loop=True)
    storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        updated_by="test",
    )


def _record_observation(storage: SQLiteStorage, execute_loop: bool) -> None:
    observation_id = "order" if execute_loop else "check"
    for cycle in range(1, 7):
        storage.record_loop_event(
            LoopEvent(
                loop_id=f"observe-{observation_id}",
                iteration=cycle,
                status="idle",
                mode="testnet",
                exchange="binance",
                symbol="BTCUSDT",
                interval="4h",
                message="testnet_observe_passed",
                payload={
                    "kind": "testnet_observe",
                    "observation_id": observation_id,
                    "cycle": cycle,
                    "status": "pass",
                    "reason": "",
                    "duration_seconds": 0.1,
                    "execute_loop": execute_loop,
                    "order_lifecycle": {
                        "state": "healthy_idle" if execute_loop else "not_attempted",
                        "acceptable": True,
                        "open_order_count": 0,
                    },
                },
            )
        )
