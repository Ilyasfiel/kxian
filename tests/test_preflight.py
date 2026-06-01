from kxian_bot.config import RuntimeConfig
from kxian_bot.models import BacktestRunSummary, Candle, ExchangeOrder, Fill, StressBacktestRunSummary, TradingRule, WalkForwardRunSummary
from kxian_bot.preflight import run_preflight
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


def test_preflight_passes_for_ready_testnet_database(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage, trade_count=35, return_pct=2.0, drawdown_pct=5.0, profit_factor=1.5)
    _record_stress_backtest(storage, min_trade_count=35, worst_return_pct=1.0, worst_drawdown_pct=7.0, worst_profit_factor=1.3)
    _record_walk_forward(storage, pass_rate=75, total_trade_count=35)
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

    result = run_preflight(config, storage, require_testnet_autotrade=False)

    assert result["status"] == "pass"
    assert {check["name"]: check["status"] for check in result["checks"]} == {
        "sqlite_schema": "pass",
        "automation_control": "pass",
        "trading_rules": "pass",
        "market_data": "pass",
        "position_state": "pass",
        "strategy_gate": "pass",
        "sample_validation_gate": "pass",
        "stress_gate": "pass",
        "walk_forward_gate": "pass",
        "open_orders": "pass",
        "loop_lock": "pass",
        "execution_mode": "pass",
    }


def test_preflight_reports_missing_data_gate_and_allows_non_ordering_testnet_checks(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="sqlite",
        short_window=3,
        long_window=5,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=False,
    )

    result = run_preflight(config, storage, require_testnet_autotrade=False)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["market_data"]["status"] == "fail"
    assert checks["automation_control"]["status"] == "pass"
    assert checks["trading_rules"]["status"] == "pass"
    assert checks["strategy_gate"]["status"] == "pass"
    assert checks["sample_validation_gate"]["status"] == "pass"
    assert checks["stress_gate"]["status"] == "pass"
    assert checks["walk_forward_gate"]["status"] == "pass"
    assert checks["execution_mode"]["details"]["failures"] == []


def test_preflight_can_require_testnet_autotrade_for_bounded_execution(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="exchange",
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=False,
        require_strategy_gate=False,
        require_sample_validation_gate=False,
        require_stress_gate=False,
        require_walk_forward_gate=False,
    )

    result = run_preflight(config, storage, require_testnet_autotrade=True)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["execution_mode"]["details"]["failures"] == ["testnet_autotrade_disabled"]


def test_preflight_gate_matches_protective_exit_parameters(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage, trade_count=35, return_pct=2.0, drawdown_pct=5.0, profit_factor=1.5)
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="sqlite",
        short_window=3,
        long_window=5,
        min_order_usdt=1,
        stop_loss_pct=5,
        trailing_stop_pct=3,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
        require_stress_gate=False,
        require_walk_forward_gate=False,
        require_sample_validation_gate=False,
    )

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert checks["strategy_gate"]["status"] == "fail"
    assert checks["strategy_gate"]["message"] == "missing matching backtest run"


def test_preflight_uses_active_strategy_profile_for_gate_evidence(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    profile_parameters = {"short_window": 2, "long_window": 4, "cooldown_seconds": 120}
    _record_candles(storage, count=12, parameters=profile_parameters)
    _record_backtest(
        storage,
        trade_count=35,
        return_pct=2.0,
        drawdown_pct=5.0,
        profit_factor=1.5,
        parameters=profile_parameters,
    )
    _record_stress_backtest(
        storage,
        min_trade_count=35,
        worst_return_pct=1.0,
        worst_drawdown_pct=7.0,
        worst_profit_factor=1.3,
        parameters=profile_parameters,
    )
    _record_walk_forward(
        storage,
        pass_rate=75,
        total_trade_count=35,
        parameters=profile_parameters,
    )
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters=profile_parameters,
        evidence={"backtest": {"run_id": "run-1"}, "sample_validation": SAMPLE_VALIDATION_EVIDENCE},
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

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "pass"
    assert result["mode"] == "testnet"
    assert checks["market_data"]["details"]["required"] == 9
    assert checks["strategy_gate"]["details"]["run_id"] == "run-1"
    assert checks["strategy_gate"]["details"]["parameters"]["cooldown_seconds"] == 120
    assert checks["sample_validation_gate"]["details"]["sample_count"] == 2
    assert checks["stress_gate"]["details"]["run_id"] == "stress-run-1"
    assert checks["walk_forward_gate"]["details"]["run_id"] == "walk-run-1"


def test_preflight_allows_exchange_market_data_without_local_candles(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    config = RuntimeConfig(db_path=str(db_path), market_data_source="exchange")

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert checks["market_data"]["status"] == "pass"
    assert checks["market_data"]["details"]["local_candles"] == 0
    assert checks["market_data"]["details"]["local_coverage_candles"] == 0
    assert checks["market_data"]["details"]["local_outlier_candles"] == 0
    assert checks["market_data"]["details"]["local_first_open_time"] is None
    assert checks["market_data"]["details"]["local_last_open_time"] is None
    assert checks["market_data"]["details"]["local_coverage_days"] == 0.0


def test_preflight_reports_local_candle_coverage(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    start_time = 1704067200000
    storage.upsert_candles(
        [
            Candle(
                open_time=start_time + index * 60000,
                open=10 + index,
                high=10 + index,
                low=10 + index,
                close=10 + index,
                volume=1,
                close_time=start_time + index * 60000 + 59999,
            )
            for index in range(3)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    config = RuntimeConfig(db_path=str(db_path), market_data_source="exchange")

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}
    details = checks["market_data"]["details"]

    assert details["local_candles"] == 3
    assert details["local_coverage_candles"] == 3
    assert details["local_outlier_candles"] == 0
    assert details["local_first_open_time"] == start_time
    assert details["local_last_open_time"] == start_time + 120000
    assert details["local_coverage_days"] == 0.0021


def test_preflight_coverage_ignores_stale_outlier_candle(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    start_time = 1704067200000
    storage.upsert_candles(
        [
            Candle(open_time=1, open=1, high=1, low=1, close=1, volume=1, close_time=2),
            *[
                Candle(
                    open_time=start_time + index * 60000,
                    open=10 + index,
                    high=10 + index,
                    low=10 + index,
                    close=10 + index,
                    volume=1,
                    close_time=start_time + index * 60000 + 59999,
                )
                for index in range(3)
            ],
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    config = RuntimeConfig(db_path=str(db_path), market_data_source="exchange")

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}
    details = checks["market_data"]["details"]

    assert details["local_candles"] == 4
    assert details["local_coverage_candles"] == 3
    assert details["local_outlier_candles"] == 1
    assert details["local_first_open_time"] == start_time
    assert details["local_last_open_time"] == start_time + 120000
    assert details["local_coverage_days"] == 0.0021


def test_preflight_reports_replayed_position_state(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="paper", exchange="binance")
    config = RuntimeConfig(db_path=str(db_path), market_data_source="exchange", starting_usdt=1000)

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert checks["position_state"]["status"] == "pass"
    assert checks["position_state"]["details"] == {
        "usdt_balance": 800.0,
        "asset_balance": 2.0,
        "average_entry_price": 100.0,
        "failures": [],
    }


def test_preflight_blocks_local_position_without_entry_price(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=1, price=0, status="filled"), mode="testnet", exchange="binance")
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="exchange",
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
        require_strategy_gate=False,
        require_stress_gate=False,
        require_walk_forward_gate=False,
        require_sample_validation_gate=False,
    )

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["position_state"]["status"] == "fail"
    assert checks["position_state"]["message"] == "local position entry price is missing"
    assert checks["position_state"]["details"]["asset_balance"] > 0
    assert checks["position_state"]["details"]["average_entry_price"] == 0
    assert checks["position_state"]["details"]["failures"] == ["missing_local_entry_price"]


def test_preflight_reports_persisted_trading_rules(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.upsert_trading_rule(
        TradingRule(
            exchange="binance",
            symbol="BTCUSDT",
            price_step=0.1,
            quantity_step=0.001,
            min_quantity=0.001,
            min_notional=10,
        )
    )
    config = RuntimeConfig(db_path=str(db_path))

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert checks["trading_rules"]["status"] == "pass"
    assert checks["trading_rules"]["details"]["source"] == "sqlite"
    assert checks["trading_rules"]["details"]["price_step"] == 0.1


def test_preflight_blocks_when_automation_is_paused(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.set_automation_paused("paper", "binance", "BTCUSDT", "1m", True, reason="maintenance")
    config = RuntimeConfig(db_path=str(db_path))

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["automation_control"]["status"] == "fail"
    assert checks["automation_control"]["message"] == "automation is paused"
    assert checks["automation_control"]["details"]["reason"] == "maintenance"


def test_preflight_reports_gate_failure_and_open_order(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage, trade_count=2, return_pct=-1.0, drawdown_pct=25.0, profit_factor=0.5)
    _record_stress_backtest(storage, min_trade_count=2, worst_return_pct=-2.0, worst_drawdown_pct=30.0, worst_profit_factor=0.5)
    _record_walk_forward(storage, pass_rate=25, total_trade_count=2, worst_return_pct=-2, worst_drawdown_pct=30, worst_profit_factor=0.5)
    storage.record_exchange_order(
        ExchangeOrder(
            symbol="BTCUSDT",
            side="buy",
            quantity=0.01,
            price=100,
            status="submitted",
            exchange_order_id="open-1",
        ),
        mode="testnet",
        exchange="binance",
    )
    config = RuntimeConfig(
        mode="testnet",
        exchange="binance",
        db_path=str(db_path),
        market_data_source="sqlite",
        short_window=3,
        long_window=5,
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["strategy_gate"]["details"]["failures"] == [
        "insufficient_trades",
        "return_too_low",
        "drawdown_too_high",
        "profit_factor_too_low",
    ]
    assert checks["stress_gate"]["details"]["failures"] == [
        "stress_insufficient_trades",
        "stress_return_too_low",
        "stress_drawdown_too_high",
        "stress_profit_factor_too_low",
    ]
    assert checks["walk_forward_gate"]["details"]["failures"] == [
        "walk_forward_pass_rate_too_low",
        "walk_forward_insufficient_trades",
        "walk_forward_return_too_low",
        "walk_forward_drawdown_too_high",
        "walk_forward_profit_factor_too_low",
    ]
    assert checks["open_orders"]["details"]["open_order_count"] == 1


def test_preflight_blocks_testnet_autotrade_without_multi_sample_evidence(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage, trade_count=35, return_pct=2.0, drawdown_pct=5.0, profit_factor=1.5)
    _record_stress_backtest(storage, min_trade_count=35, worst_return_pct=1.0, worst_drawdown_pct=7.0, worst_profit_factor=1.3)
    _record_walk_forward(storage, pass_rate=75, total_trade_count=35)
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

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["sample_validation_gate"]["status"] == "fail"
    assert checks["sample_validation_gate"]["details"]["reason"] == "missing_active_profile"


def test_preflight_blocks_failed_multi_sample_evidence(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage, trade_count=35, return_pct=2.0, drawdown_pct=5.0, profit_factor=1.5)
    _record_stress_backtest(storage, min_trade_count=35, worst_return_pct=1.0, worst_drawdown_pct=7.0, worst_profit_factor=1.3)
    _record_walk_forward(storage, pass_rate=75, total_trade_count=35)
    failed_evidence = {
        **SAMPLE_VALIDATION_EVIDENCE,
        "status": "fail",
        "failed_samples": 1,
        "summary": {
            **SAMPLE_VALIDATION_EVIDENCE["summary"],
            "min_return_pct": -1.0,
        },
    }
    _record_profile(storage, evidence={"sample_validation": failed_evidence})
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

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["sample_validation_gate"]["details"]["failures"] == [
        "sample_validation_not_passed",
        "not_all_samples_passed",
        "sample_validation_return_too_low",
    ]


def test_preflight_reports_active_loop_lock(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.acquire_loop_lock("paper", "binance", "BTCUSDT", "1m", "loop-1", stale_after_seconds=60)
    config = RuntimeConfig(db_path=str(db_path), loop_lock_stale_seconds=60)

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["loop_lock"]["status"] == "fail"
    assert checks["loop_lock"]["details"]["lock"]["loop_id"] == "loop-1"


def test_preflight_requires_live_confirmation_switches(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage, trade_count=35, return_pct=2.0, drawdown_pct=5.0, profit_factor=1.5)
    _record_stress_backtest(storage, min_trade_count=35, worst_return_pct=1.0, worst_drawdown_pct=7.0, worst_profit_factor=1.3)
    _record_walk_forward(storage, pass_rate=75, total_trade_count=35)
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
        use_testnet=True,
        live_dry_run=True,
        enable_live_autotrade=False,
        binance_api_key="key",
        binance_api_secret="secret",
    )

    result = run_preflight(config, storage)
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "fail"
    assert checks["strategy_gate"]["status"] == "pass"
    assert checks["sample_validation_gate"]["status"] == "pass"
    assert checks["stress_gate"]["status"] == "pass"
    assert checks["walk_forward_gate"]["status"] == "pass"
    assert checks["execution_mode"]["details"]["failures"] == [
        "live_dry_run_enabled",
        "live_autotrade_disabled",
        "live_endpoint_points_to_testnet",
        "live_confirmation_required",
    ]


def test_preflight_passes_for_confirmed_live_mode(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    _record_candles(storage, count=12)
    _record_backtest(storage, trade_count=35, return_pct=2.0, drawdown_pct=5.0, profit_factor=1.5)
    _record_stress_backtest(storage, min_trade_count=35, worst_return_pct=1.0, worst_drawdown_pct=7.0, worst_profit_factor=1.3)
    _record_walk_forward(storage, pass_rate=75, total_trade_count=35)
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
        binance_api_key="key",
        binance_api_secret="secret",
    )

    result = run_preflight(config, storage)

    assert result["status"] == "pass"


def _record_profile(storage, parameters: dict | None = None, evidence: dict | None = None, mode: str = "testnet"):
    parameters = {"strategy": "moving_average_cross", **(parameters or {"short_window": 3, "long_window": 5})}
    storage.upsert_strategy_profile(
        mode=mode,
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy=parameters["strategy"],
        parameters=parameters,
        evidence={"sample_validation": SAMPLE_VALIDATION_EVIDENCE, **(evidence or {})},
        updated_by="test",
    )


def _record_candles(storage, count: int, parameters: dict | None = None):
    parameters = {"strategy": "moving_average_cross", **(parameters or {"short_window": 3, "long_window": 5})}
    storage.upsert_candles(
        [
            Candle(open_time=i, open=10 + i, high=10 + i, low=10 + i, close=10 + i, volume=1, close_time=i + 1)
            for i in range(count)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )


def _record_backtest(
    storage,
    trade_count: int,
    return_pct: float,
    drawdown_pct: float,
    profit_factor: float,
    parameters: dict | None = None,
):
    parameters = {"strategy": "moving_average_cross", **(parameters or {"short_window": 3, "long_window": 5})}
    storage.record_backtest_run(
        BacktestRunSummary(
            run_id="run-1",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters=parameters,
            candle_count=12,
            initial_equity=1000,
            final_equity=1000 * (1 + return_pct / 100),
            return_pct=return_pct,
            max_drawdown_pct=drawdown_pct,
            win_rate=50,
            profit_factor=profit_factor,
            trade_count=trade_count,
            fees_paid=1,
            slippage_paid=0.5,
        )
    )


def _record_stress_backtest(
    storage,
    min_trade_count: int,
    worst_return_pct: float,
    worst_drawdown_pct: float,
    worst_profit_factor: float,
    pass_rate: float = 100.0,
    parameters: dict | None = None,
):
    parameters = {"strategy": "moving_average_cross", **(parameters or {"short_window": 3, "long_window": 5})}
    storage.record_stress_backtest_run(
        StressBacktestRunSummary(
            run_id="stress-run-1",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters=parameters,
            candle_count=12,
            scenario_count=5,
            passed_scenarios=5 if pass_rate == 100 else 0,
            failed_scenarios=0 if pass_rate == 100 else 5,
            pass_rate=pass_rate,
            worst_return_pct=worst_return_pct,
            worst_drawdown_pct=worst_drawdown_pct,
            worst_profit_factor=worst_profit_factor,
            min_trade_count=min_trade_count,
            scenarios=[],
        )
    )


def _record_walk_forward(
    storage,
    pass_rate: float,
    total_trade_count: int,
    worst_return_pct: float = 1.0,
    worst_drawdown_pct: float = 5.0,
    worst_profit_factor: float = 1.2,
    parameters: dict | None = None,
):
    parameters = {"strategy": "moving_average_cross", **(parameters or {"short_window": 3, "long_window": 5})}
    storage.record_walk_forward_run(
        WalkForwardRunSummary(
            run_id="walk-run-1",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters=parameters,
            candle_count=12,
            segment_count=3,
            passed_segments=2,
            failed_segments=1,
            pass_rate=pass_rate,
            total_trade_count=total_trade_count,
            min_segment_trade_count=1,
            worst_return_pct=worst_return_pct,
            worst_drawdown_pct=worst_drawdown_pct,
            worst_profit_factor=worst_profit_factor,
            segments=[],
        )
    )
