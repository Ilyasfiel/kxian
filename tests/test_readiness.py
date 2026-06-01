from kxian_bot.config import RuntimeConfig
from kxian_bot.models import BacktestRunSummary, Candle, StressBacktestRunSummary, WalkForwardRunSummary
from kxian_bot.readiness import run_readiness
from kxian_bot.storage import SQLiteStorage


SAMPLE_VALIDATION_EVIDENCE = {
    "status": "pass",
    "reason": "all_samples_passed",
    "sample_count": 2,
    "passed_samples": 2,
    "failed_samples": 0,
    "summary": {
        "total_trade_count": 70,
        "min_return_pct": 1.0,
        "worst_drawdown_pct": 7.0,
        "min_profit_factor": 1.3,
        "min_stress_pass_rate": 100.0,
        "min_walk_forward_pass_rate": 75.0,
    },
    "samples": [],
}


def test_readiness_reports_missing_testnet_credentials_without_secret_values(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        binance_api_key="",
        binance_api_secret="",
        enable_testnet_autotrade=False,
        require_strategy_gate=False,
        require_sample_validation_gate=False,
        require_stress_gate=False,
        require_walk_forward_gate=False,
    )

    result = run_readiness(config, SQLiteStorage(db_path))
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["credentials"]["status"] == "fail"
    assert checks["credentials"]["details"]["failures"] == [
        "missing_binance_api_key",
        "missing_binance_api_secret",
    ]
    assert result["credentials"] == {
        "binance_api_key": False,
        "binance_api_secret": False,
        "okx_api_key": False,
        "okx_api_secret": False,
        "okx_api_passphrase": False,
    }
    assert "set sandbox API credentials" in result["next_steps"][0]


def test_readiness_passes_for_ready_testnet_profile(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage)
    _record_stress(storage)
    _record_walk_forward(storage)
    _record_profile(storage)
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="sqlite",
        short_window=3,
        long_window=5,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_readiness(config, storage)

    assert result["status"] == "pass"
    assert result["credentials"]["binance_api_key"] is True
    assert result["credentials"]["binance_api_secret"] is True
    assert result["next_steps"] == [
        "run kxian-bot testnet-dry-run, then add --execute-loop for one bounded sandbox iteration"
    ]


def test_readiness_can_relax_testnet_autotrade_for_non_ordering_checks(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage)
    _record_stress(storage)
    _record_walk_forward(storage)
    _record_profile(storage)
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="sqlite",
        short_window=3,
        long_window=5,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=False,
    )

    relaxed = run_readiness(config, storage, require_testnet_autotrade=False)
    strict = run_readiness(config, storage, require_testnet_autotrade=True)
    strict_checks = {check["name"]: check for check in strict["checks"]}

    assert relaxed["status"] == "pass"
    assert relaxed["next_steps"] == [
        "run kxian-bot testnet-dry-run and non-ordering testnet-observe; set KXIAN_ENABLE_TESTNET_AUTOTRADE=true before bounded --execute-loop"
    ]
    assert strict["status"] == "fail"
    assert strict_checks["automation"]["details"]["failures"] == ["testnet_autotrade_disabled"]


def test_readiness_profile_check_uses_active_strategy_profile(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage)
    _record_stress(storage)
    _record_walk_forward(storage)
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
        evidence={"backtest": {"run_id": "run-ready"}, "sample_validation": SAMPLE_VALIDATION_EVIDENCE},
        updated_by="test",
    )
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="sqlite",
        short_window=9,
        long_window=20,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_readiness(config, storage)
    profile_check = {check["name"]: check for check in result["checks"]}["profile"]

    assert result["status"] == "pass"
    assert profile_check["details"]["short_window"] == 3
    assert profile_check["details"]["long_window"] == 5
    assert result["preflight"]["checks"][3]["details"]["required"] == 10


def test_readiness_points_to_multi_sample_promotion_when_evidence_missing(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage)
    _record_stress(storage)
    _record_walk_forward(storage)
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="sqlite",
        short_window=3,
        long_window=5,
        min_order_usdt=1,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_readiness(config, storage)

    assert result["status"] == "fail"
    assert any("select-samples --promote" in step for step in result["next_steps"])


def test_readiness_blocks_live_mode_until_all_live_switches_are_confirmed(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    config = RuntimeConfig(
        mode="live",
        exchange="binance",
        db_path=str(db_path),
        allow_live=True,
        use_testnet=False,
        binance_api_key="key",
        binance_api_secret="secret",
    )

    result = run_readiness(config, SQLiteStorage(db_path))
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["automation"]["details"]["failures"] == [
        "live_dry_run_enabled",
        "live_autotrade_disabled",
        "live_confirmation_required",
        "live_credentials_not_confirmed",
    ]
    assert checks["live_support"]["status"] == "pass"
    assert any("KXIAN_LIVE_DRY_RUN=false" in step for step in result["next_steps"])


def test_readiness_passes_for_confirmed_live_profile(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12, mode="live")
    _record_backtest(storage)
    _record_stress(storage)
    _record_walk_forward(storage)
    _record_profile(storage, mode="live")
    config = RuntimeConfig(
        mode="live",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="sqlite",
        short_window=3,
        long_window=5,
        min_order_usdt=1,
        allow_live=True,
        use_testnet=False,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="LIVE:binance:BTCUSDT:1m",
        live_credentials_confirmed=True,
        binance_api_key="key",
        binance_api_secret="secret",
    )

    result = run_readiness(config, storage)

    assert result["status"] == "pass"
    assert result["next_steps"] == [
        "run a bounded live trade-loop with a very small KXIAN_MAX_LIVE_ORDER_USDT and monitor fills"
    ]


def _record_candles(storage, count: int, mode: str = "testnet"):
    storage.upsert_candles(
        [
            Candle(open_time=i, open=10 + i, high=10 + i, low=10 + i, close=10 + i, volume=1, close_time=i + 1)
            for i in range(count)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )


def _record_profile(storage, mode: str = "testnet"):
    storage.upsert_strategy_profile(
        mode=mode,
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
        evidence={"sample_validation": SAMPLE_VALIDATION_EVIDENCE},
        updated_by="test",
    )


def _record_backtest(storage):
    storage.record_backtest_run(
        BacktestRunSummary(
            run_id="run-ready",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
            candle_count=12,
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


def _record_stress(storage):
    storage.record_stress_backtest_run(
        StressBacktestRunSummary(
            run_id="stress-ready",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
            candle_count=12,
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


def _record_walk_forward(storage):
    storage.record_walk_forward_run(
        WalkForwardRunSummary(
            run_id="walk-ready",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
            candle_count=12,
            segment_count=3,
            passed_segments=2,
            failed_segments=1,
            pass_rate=75,
            total_trade_count=35,
            min_segment_trade_count=5,
            worst_return_pct=0.5,
            worst_drawdown_pct=5.0,
            worst_profit_factor=1.2,
            segments=[],
        )
    )
