from kxian_bot.models import (
    BacktestRunSummary,
    BacktestTrade,
    Candle,
    ExchangeOrder,
    Fill,
    LoopEvent,
    Signal,
    StressBacktestRunSummary,
    TradingRule,
    WalkForwardRunSummary,
)
from kxian_bot.risk import RiskManager
from kxian_bot.storage import SQLiteStorage


def test_storage_initializes_schema(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")

    tables = storage.table_names()

    assert {
        "exchange_orders",
        "strategy_signals",
        "fills",
        "backtest_trades",
            "trading_rules",
            "automation_controls",
            "strategy_profiles",
            "position_runtime_state",
        "risk_state",
        "candles",
        "backtest_runs",
        "stress_backtest_runs",
        "walk_forward_runs",
        "loop_events",
        "loop_locks",
    }.issubset(tables)


def test_storage_configures_sqlite_for_runtime_concurrency(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")

    with storage._connect() as connection:
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert busy_timeout == 30000
    assert journal_mode == "wal"


def test_storage_persists_exchange_order(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    order = ExchangeOrder(
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        price=100,
        status="submitted",
        exchange_order_id="123",
    )

    storage.record_exchange_order(order, mode="testnet", exchange="binance")

    rows = storage.fetch_all("exchange_orders")
    assert len(rows) == 1
    assert rows[0]["exchange_order_id"] == "123"
    assert rows[0]["status"] == "submitted"
    assert "secret" not in rows[0]["raw_json"]


def test_storage_lists_open_exchange_orders(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    open_order = ExchangeOrder(
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        price=100,
        status="submitted",
        exchange_order_id="open-1",
    )
    closed_order = ExchangeOrder(
        symbol="BTCUSDT",
        side="sell",
        quantity=0.01,
        price=101,
        status="filled",
        exchange_order_id="filled-1",
    )

    storage.record_exchange_order(open_order, mode="testnet", exchange="binance")
    storage.record_exchange_order(closed_order, mode="testnet", exchange="binance")

    orders = storage.list_open_exchange_orders("testnet", "binance", "BTCUSDT")

    assert len(orders) == 1
    assert orders[0]["exchange_order_id"] == "open-1"


def test_storage_open_orders_uses_latest_status_per_exchange_order_id(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    submitted = ExchangeOrder(
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        price=100,
        status="submitted",
        exchange_order_id="order-1",
    )
    filled = ExchangeOrder(
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        price=100,
        status="filled",
        exchange_order_id="order-1",
    )

    storage.record_exchange_order(submitted, mode="testnet", exchange="binance")
    storage.record_exchange_order(filled, mode="testnet", exchange="binance")

    assert storage.list_open_exchange_orders("testnet", "binance", "BTCUSDT") == []


def test_storage_persists_signal_fill_backtest_trade_and_risk(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    signal = Signal(symbol="BTCUSDT", side="buy", price=100, reason="test_signal")
    fill = Fill(symbol="BTCUSDT", side="buy", quantity=0.01, price=100, status="filled")
    trade = BacktestTrade(
        timestamp=1,
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        signal_price=100,
        execution_price=100,
        fee=0.1,
        slippage=0.0,
        pnl=0.0,
        reason="test_signal",
    )
    risk = RiskManager(risk_per_trade=0.1, max_position_usdt=300)
    risk.record_fill(timestamp=1_700_000_000, equity=1000)

    storage.record_signal(signal, mode="paper", exchange="binance")
    storage.record_fill(fill, mode="paper", exchange="binance")
    storage.record_backtest_trade(trade, run_id="run-1")
    storage.record_risk_state(risk, mode="paper", exchange="binance", symbol="BTCUSDT", interval="1m")

    assert storage.fetch_all("strategy_signals")[0]["reason"] == "test_signal"
    assert storage.fetch_all("fills")[0]["status"] == "filled"
    assert storage.fetch_all("backtest_trades")[0]["run_id"] == "run-1"
    assert storage.fetch_all("risk_state")[0]["trades_today"] == 1
    assert storage.fetch_all("risk_state")[0]["symbol"] == "BTCUSDT"


def test_storage_upserts_and_reads_trading_rule(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    initial = TradingRule(
        exchange="binance",
        symbol="BTCUSDT",
        price_step=0.01,
        quantity_step=0.00001,
        min_quantity=0.0001,
        min_notional=10,
    )
    updated = initial.model_copy(update={"price_step": 0.1, "min_notional": 20})

    storage.upsert_trading_rule(initial)
    storage.upsert_trading_rule(updated)

    rule = storage.latest_trading_rule("binance", "BTCUSDT")
    assert len(storage.fetch_all("trading_rules")) == 1
    assert rule["price_step"] == 0.1
    assert rule["min_notional"] == 20
    assert storage.latest_trading_rule("binance", "ETHUSDT") is None


def test_storage_persists_automation_control_status(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")

    paused = storage.set_automation_paused(
        "paper",
        "binance",
        "BTCUSDT",
        "1m",
        True,
        reason="operator_review",
        updated_by="test",
    )

    assert paused["paused"] is True
    assert paused["reason"] == "operator_review"
    assert storage.automation_control_status("paper", "binance", "BTCUSDT", "1m")["paused"] is True

    resumed = storage.set_automation_paused("paper", "binance", "BTCUSDT", "1m", False, reason="ready")
    assert resumed["paused"] is False
    assert len(storage.fetch_all("automation_controls")) == 1


def test_storage_upserts_and_reads_active_strategy_profile(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")

    first = storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters={"short_window": 2, "long_window": 5},
        evidence={"backtest": {"run_id": "run-1"}},
        updated_by="test",
    )
    second = storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters={"short_window": 3, "long_window": 8, "stop_loss_pct": 2, "cooldown_seconds": 120},
        evidence={"backtest": {"run_id": "run-2"}},
        updated_by="test",
    )

    profile = storage.active_strategy_profile("paper", "binance", "BTCUSDT", "1m")

    assert first["parameters"]["short_window"] == 2
    assert second["parameters"]["stop_loss_pct"] == 2.0
    assert profile["parameters"]["short_window"] == 3
    assert profile["parameters"]["long_window"] == 8
    assert profile["parameters"]["take_profit_pct"] == 0.0
    assert profile["parameters"]["cooldown_seconds"] == 120
    assert profile["evidence"]["backtest"]["run_id"] == "run-2"
    assert profile["active"] is True
    assert len(storage.fetch_all("strategy_profiles")) == 1
    assert storage.active_strategy_profile("paper", "binance", "ETHUSDT", "1m") is None


def test_storage_promotes_validated_paper_profile_to_testnet(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30, "stop_loss_pct": 2, "take_profit_pct": 8},
        evidence={
            "sample_validation": {
                "status": "pass",
                "sample_count": 2,
                "passed_samples": 2,
                "failed_samples": 0,
                "summary": {"total_trade_count": 70, "min_return_pct": 1, "min_profit_factor": 1.2},
            }
        },
        updated_by="select-samples",
    )

    result = storage.promote_strategy_profile_to_mode(
        source_mode="paper",
        target_mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        updated_by="test",
    )
    profile = storage.active_strategy_profile("testnet", "binance", "BTCUSDT", "4h")

    assert result["status"] == "pass"
    assert result["promoted"]["profile_key"] == "testnet:binance:BTCUSDT:4h"
    assert profile["parameters"]["short_window"] == 10
    assert profile["evidence"]["sample_validation"]["status"] == "pass"
    assert profile["evidence"]["promotion"]["source_profile_key"] == "paper:binance:BTCUSDT:4h"


def test_storage_blocks_profile_promotion_without_passing_sample_validation(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={"sample_validation": {"status": "fail"}},
        updated_by="test",
    )

    result = storage.promote_strategy_profile_to_mode(
        source_mode="paper",
        target_mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "source_profile_missing_passing_sample_validation"
    assert storage.active_strategy_profile("testnet", "binance", "BTCUSDT", "4h") is None


def test_storage_blocks_profile_promotion_to_live_without_testnet_source(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")

    result = storage.promote_strategy_profile_to_mode(
        source_mode="paper",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "unsupported_profile_promotion_path"


def _record_testnet_profile(storage: SQLiteStorage) -> None:
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={
            "sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0},
            "promotion": {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"},
        },
        updated_by="testnet",
    )


def test_storage_promotes_testnet_profile_to_live_with_promotion_evidence(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={
            "sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0},
            "promotion": {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"},
        },
        updated_by="testnet",
    )
    _record_testnet_observation(storage, execute_loop=False)
    _record_testnet_observation(storage, execute_loop=True)

    result = storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        updated_by="operator",
    )
    profile = storage.active_strategy_profile("live", "binance", "BTCUSDT", "4h")

    assert result["status"] == "pass"
    assert result["reason"] == "profile_promoted_to_live"
    assert profile["profile_key"] == "live:binance:BTCUSDT:4h"
    assert profile["evidence"]["promotion"]["source_profile_key"] == "testnet:binance:BTCUSDT:4h"
    assert profile["evidence"]["testnet_observation"]["non_ordering"]["status"] == "pass"
    assert profile["evidence"]["testnet_observation"]["bounded_order"]["execute_loop"] is True
    assert profile["updated_by"] == "operator"


def test_storage_blocks_live_promotion_without_testnet_promotion_evidence(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={"sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0}},
        updated_by="testnet",
    )

    result = storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "source_profile_missing_testnet_promotion_evidence"
    assert storage.active_strategy_profile("live", "binance", "BTCUSDT", "4h") is None


def test_storage_blocks_live_promotion_without_passing_testnet_observations(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={
            "sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0},
            "promotion": {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"},
        },
        updated_by="testnet",
    )

    missing_non_order = storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )
    _record_testnet_observation(storage, execute_loop=False)
    missing_order = storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )

    assert missing_non_order["status"] == "blocked"
    assert missing_non_order["reason"] == "source_profile_missing_passing_testnet_observation"
    assert missing_order["status"] == "blocked"
    assert missing_order["reason"] == "source_profile_missing_passing_testnet_order_observation"
    assert storage.active_strategy_profile("live", "binance", "BTCUSDT", "4h") is None


def test_storage_blocks_live_promotion_when_testnet_observation_cycles_are_insufficient(tmp_path):
    non_order_storage = SQLiteStorage(tmp_path / "non-order.sqlite3")
    _record_testnet_profile(non_order_storage)
    _record_testnet_observation(non_order_storage, execute_loop=False, cycles=5)
    _record_testnet_observation(non_order_storage, execute_loop=True, cycles=6)

    non_order_result = non_order_storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )
    order_storage = SQLiteStorage(tmp_path / "order.sqlite3")
    _record_testnet_profile(order_storage)
    _record_testnet_observation(order_storage, execute_loop=False, cycles=6)
    _record_testnet_observation(order_storage, execute_loop=True, cycles=5)

    order_result = order_storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )

    assert non_order_result["status"] == "blocked"
    assert non_order_result["reason"] == "source_profile_missing_passing_testnet_observation"
    assert non_order_result["testnet_observation"]["cycles_completed"] == 5
    assert "insufficient_testnet_observation_cycles" in non_order_result["failures"]
    assert order_result["status"] == "blocked"
    assert order_result["reason"] == "source_profile_missing_passing_testnet_order_observation"
    assert order_result["testnet_observation"]["cycles_completed"] == 5
    assert "insufficient_testnet_observation_cycles" in order_result["failures"]
    assert non_order_storage.active_strategy_profile("live", "binance", "BTCUSDT", "4h") is None
    assert order_storage.active_strategy_profile("live", "binance", "BTCUSDT", "4h") is None


def test_storage_blocks_live_promotion_when_bounded_observation_lacks_lifecycle(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"short_window": 10, "long_window": 30},
        evidence={
            "sample_validation": {"status": "pass", "sample_count": 2, "passed_samples": 2, "failed_samples": 0},
            "promotion": {"source_profile_key": "paper:binance:BTCUSDT:4h", "target_mode": "testnet"},
        },
        updated_by="testnet",
    )
    _record_testnet_observation(storage, execute_loop=False)
    for cycle in range(1, 7):
        storage.record_loop_event(
            LoopEvent(
                loop_id="observe-legacy-order",
                iteration=cycle,
                status="idle",
                mode="testnet",
                exchange="binance",
                symbol="BTCUSDT",
                interval="4h",
                message="testnet_observe_passed",
                payload={
                    "kind": "testnet_observe",
                    "observation_id": "legacy-order",
                    "cycle": cycle,
                    "status": "pass",
                    "execute_loop": True,
                },
            )
        )

    result = storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "source_profile_missing_passing_testnet_order_observation"
    assert "missing_order_lifecycle" in result["failures"]


def test_storage_blocks_live_promotion_when_bounded_observation_lifecycle_is_unacceptable(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    _record_testnet_profile(storage)
    _record_testnet_observation(storage, execute_loop=False)
    for cycle in range(1, 7):
        storage.record_loop_event(
            LoopEvent(
                loop_id="observe-open-order",
                iteration=cycle,
                status="idle",
                mode="testnet",
                exchange="binance",
                symbol="BTCUSDT",
                interval="4h",
                message="testnet_observe_passed",
                payload={
                    "kind": "testnet_observe",
                    "observation_id": "open-order",
                    "cycle": cycle,
                    "status": "pass",
                    "execute_loop": True,
                    "order_lifecycle": {
                        "state": "open_orders",
                        "acceptable": False,
                        "open_order_count": 1,
                    },
                },
            )
        )

    result = storage.promote_strategy_profile_to_mode(
        source_mode="testnet",
        target_mode="live",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "source_profile_missing_passing_testnet_order_observation"
    assert "testnet_observation_order_lifecycle_not_acceptable" in result["failures"]
    assert result["testnet_observation"]["order_lifecycle"]["state"] == "open_orders"
    assert storage.active_strategy_profile("live", "binance", "BTCUSDT", "4h") is None


def test_storage_persists_position_runtime_state(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")

    initial = storage.position_runtime_state("paper", "binance", "BTCUSDT", "1m")
    updated = storage.update_position_runtime_state("paper", "binance", "BTCUSDT", "1m", trailing_peak_price=112.5)
    reset = storage.reset_position_runtime_state("paper", "binance", "BTCUSDT", "1m")

    assert initial["trailing_peak_price"] == 0
    assert initial["source"] == "default"
    assert updated["trailing_peak_price"] == 112.5
    assert updated["source"] == "sqlite"
    assert reset["trailing_peak_price"] == 0
    assert len(storage.fetch_all("position_runtime_state")) == 1


def test_storage_fetch_all_rejects_unknown_table_names(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")

    try:
        storage.fetch_all("fills; DROP TABLE fills")
    except ValueError as exc:
        assert "Unsupported table" in str(exc)
    else:
        raise AssertionError("Expected unsupported table names to be rejected")


def test_storage_reads_latest_risk_state(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    older = RiskManager(risk_per_trade=0.1, max_position_usdt=300)
    older.record_fill(timestamp=1_700_000_000, equity=1000)
    latest = RiskManager(risk_per_trade=0.1, max_position_usdt=300)
    latest.record_fill(timestamp=1_700_000_010, equity=990)
    latest.record_fill(timestamp=1_700_000_020, equity=980)

    storage.record_risk_state(older, mode="paper", exchange="binance", symbol="BTCUSDT", interval="1m")
    storage.record_risk_state(latest, mode="paper", exchange="binance", symbol="BTCUSDT", interval="1m")

    state = storage.latest_risk_state("paper", "binance", "BTCUSDT", "1m")

    assert state["trades_today"] == 2
    assert state["start_equity"] == 990
    assert state["last_fill_timestamp"] == 1_700_000_020


def test_storage_risk_state_is_scoped_by_market(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    btc = RiskManager(risk_per_trade=0.1, max_position_usdt=300)
    btc.record_fill(timestamp=1_700_000_000, equity=1000)
    eth = RiskManager(risk_per_trade=0.1, max_position_usdt=300)
    eth.record_fill(timestamp=1_700_000_010, equity=1000)
    eth.record_fill(timestamp=1_700_000_020, equity=1000)

    storage.record_risk_state(btc, mode="paper", exchange="binance", symbol="BTCUSDT", interval="1m")
    storage.record_risk_state(eth, mode="paper", exchange="binance", symbol="ETHUSDT", interval="1m")

    assert storage.latest_risk_state("paper", "binance", "BTCUSDT", "1m")["trades_today"] == 1
    assert storage.latest_risk_state("paper", "binance", "ETHUSDT", "1m")["trades_today"] == 2
    assert storage.latest_risk_state("paper", "binance", "BTCUSDT", "5m") is None


def test_storage_migrates_legacy_risk_state_schema(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE risk_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                mode TEXT NOT NULL,
                day_key TEXT,
                trades_today INTEGER NOT NULL,
                start_equity REAL,
                last_fill_timestamp REAL,
                raw_json TEXT NOT NULL
            )
            """
        )
    storage = SQLiteStorage(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(risk_state)").fetchall()}

    assert {"exchange", "symbol", "interval"}.issubset(columns)


def test_storage_replays_fill_balances(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="paper", exchange="binance")
    storage.record_fill(Fill(symbol="BTCUSDT", side="sell", quantity=0.5, price=120, status="filled"), mode="paper", exchange="binance")
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=10, price=1, status="rejected"), mode="paper", exchange="binance")

    balances = storage.replay_fill_balances("paper", "binance", "BTCUSDT", starting_usdt=1000)

    assert balances == {"usdt_balance": 860.0, "asset_balance": 1.5}


def test_storage_replays_position_average_entry_price(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="paper", exchange="binance")
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=1, price=130, status="filled"), mode="paper", exchange="binance")
    storage.record_fill(Fill(symbol="BTCUSDT", side="sell", quantity=1, price=140, status="filled"), mode="paper", exchange="binance")

    state = storage.replay_position_state("paper", "binance", "BTCUSDT", starting_usdt=1000)

    assert state["asset_balance"] == 2
    assert state["average_entry_price"] == 110


def test_storage_upserts_and_loads_candles_by_range(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    first = Candle(open_time=1, open=10, high=11, low=9, close=10, volume=100, close_time=2)
    updated = Candle(open_time=1, open=10, high=12, low=9, close=11, volume=120, close_time=2)
    second = Candle(open_time=3, open=12, high=13, low=11, close=12, volume=100, close_time=4)

    storage.upsert_candles([first], exchange="binance", symbol="BTCUSDT", interval="1m")
    storage.upsert_candles([updated, second], exchange="binance", symbol="BTCUSDT", interval="1m")

    rows = storage.fetch_all("candles")
    candles = storage.load_candles("binance", "BTCUSDT", "1m", start_time=1, end_time=2)

    assert len(rows) == 2
    assert len(candles) == 1
    assert candles[0].close == 11
    assert candles[0].volume == 120


def test_storage_loads_recent_candles_in_ascending_order(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.upsert_candles(
        [
            Candle(open_time=i, open=i, high=i, low=i, close=i, volume=1, close_time=i + 1)
            for i in range(5)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )

    candles = storage.load_recent_candles("binance", "BTCUSDT", "1m", limit=3)

    assert [candle.open_time for candle in candles] == [2, 3, 4]


def test_storage_records_backtest_run_summary(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    summary = BacktestRunSummary(
        run_id="run-1",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        start_time=1,
        end_time=10,
        strategy="moving_average_cross",
        parameters={"short_window": 2, "long_window": 4},
        candle_count=10,
        initial_equity=1000,
        final_equity=1010,
        return_pct=1,
        max_drawdown_pct=2,
        win_rate=50,
        profit_factor=1.5,
        trade_count=2,
        fees_paid=1,
        slippage_paid=0.5,
    )

    storage.record_backtest_run(summary)

    rows = storage.fetch_all("backtest_runs")
    assert rows[0]["run_id"] == "run-1"
    assert '"short_window":2' in rows[0]["parameters_json"]
    assert '"return_pct":1' in rows[0]["metrics_json"]


def test_storage_finds_latest_matching_backtest_run(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    first = BacktestRunSummary(
        run_id="run-1",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        start_time=1,
        end_time=10,
        strategy="moving_average_cross",
        parameters={"short_window": 3, "long_window": 5},
        candle_count=10,
        initial_equity=1000,
        final_equity=1001,
        return_pct=0.1,
        max_drawdown_pct=2,
        win_rate=50,
        profit_factor=1.1,
        trade_count=30,
        fees_paid=1,
        slippage_paid=0.5,
    )
    second = first.model_copy(update={"run_id": "run-2", "final_equity": 1010, "return_pct": 1.0})
    mismatch = first.model_copy(update={"run_id": "run-3", "parameters": {"short_window": 2, "long_window": 5}})

    storage.record_backtest_run(first)
    storage.record_backtest_run(mismatch)
    storage.record_backtest_run(second)

    run = storage.latest_backtest_run("binance", "BTCUSDT", "1m", short_window=3, long_window=5)

    assert run["run_id"] == "run-2"
    assert run["metrics"]["return_pct"] == 1.0
    assert storage.latest_backtest_run("binance", "ETHUSDT", "1m", short_window=3, long_window=5) is None


def test_storage_latest_matching_backtest_can_filter_by_strategy(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    ma = BacktestRunSummary(
        run_id="run-ma",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        start_time=1,
        end_time=10,
        strategy="moving_average_cross",
        parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
        candle_count=10,
        initial_equity=1000,
        final_equity=1001,
        return_pct=0.1,
        max_drawdown_pct=2,
        win_rate=50,
        profit_factor=1.1,
        trade_count=30,
        fees_paid=1,
        slippage_paid=0.5,
    )
    donchian = ma.model_copy(
        update={
            "run_id": "run-donchian",
            "strategy": "donchian_breakout",
            "parameters": {"strategy": "donchian_breakout", "short_window": 3, "long_window": 5},
            "return_pct": 2.0,
        }
    )

    storage.record_backtest_run(ma)
    storage.record_backtest_run(donchian)

    run = storage.latest_backtest_run(
        "binance",
        "BTCUSDT",
        "1m",
        short_window=3,
        long_window=5,
        parameters={"strategy": "donchian_breakout", "short_window": 3, "long_window": 5},
        strategy="donchian_breakout",
    )

    assert run["run_id"] == "run-donchian"
    assert run["strategy"] == "donchian_breakout"


def test_storage_records_and_finds_latest_matching_stress_backtest_run(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    first = StressBacktestRunSummary(
        run_id="stress-1",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        start_time=1,
        end_time=10,
        strategy="moving_average_cross",
        parameters={"short_window": 3, "long_window": 5},
        candle_count=10,
        scenario_count=5,
        passed_scenarios=5,
        failed_scenarios=0,
        pass_rate=100,
        worst_return_pct=1,
        worst_drawdown_pct=2,
        worst_profit_factor=1.2,
        min_trade_count=30,
        scenarios=[{"name": "base", "passed": True}],
    )
    second = first.model_copy(update={"run_id": "stress-2", "worst_return_pct": 2})
    mismatch = first.model_copy(update={"run_id": "stress-3", "parameters": {"short_window": 2, "long_window": 5}})

    storage.record_stress_backtest_run(first)
    storage.record_stress_backtest_run(mismatch)
    storage.record_stress_backtest_run(second)

    rows = storage.fetch_all("stress_backtest_runs")
    run = storage.latest_stress_backtest_run("binance", "BTCUSDT", "1m", short_window=3, long_window=5)

    assert len(rows) == 3
    assert run["run_id"] == "stress-2"
    assert run["metrics"]["worst_return_pct"] == 2
    assert run["scenarios"][0]["name"] == "base"
    assert storage.latest_stress_backtest_run("binance", "ETHUSDT", "1m", short_window=3, long_window=5) is None


def test_storage_records_and_finds_latest_matching_walk_forward_run(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    first = WalkForwardRunSummary(
        run_id="walk-1",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        start_time=1,
        end_time=10,
        strategy="moving_average_cross",
        parameters={"short_window": 3, "long_window": 5},
        candle_count=10,
        segment_count=3,
        passed_segments=2,
        failed_segments=1,
        pass_rate=66.6667,
        total_trade_count=30,
        min_segment_trade_count=5,
        worst_return_pct=0.1,
        worst_drawdown_pct=2,
        worst_profit_factor=1.2,
        segments=[{"index": 1, "passed": True}],
    )
    second = first.model_copy(update={"run_id": "walk-2", "pass_rate": 100})
    mismatch = first.model_copy(update={"run_id": "walk-3", "parameters": {"short_window": 2, "long_window": 5}})

    storage.record_walk_forward_run(first)
    storage.record_walk_forward_run(mismatch)
    storage.record_walk_forward_run(second)

    rows = storage.fetch_all("walk_forward_runs")
    run = storage.latest_walk_forward_run("binance", "BTCUSDT", "1m", short_window=3, long_window=5)

    assert len(rows) == 3
    assert run["run_id"] == "walk-2"
    assert run["metrics"]["pass_rate"] == 100
    assert run["segments"][0]["index"] == 1
    assert storage.latest_walk_forward_run("binance", "ETHUSDT", "1m", short_window=3, long_window=5) is None


def test_storage_records_loop_event(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")

    storage.record_loop_event(
        LoopEvent(
            loop_id="loop-1",
            iteration=1,
            status="idle",
            mode="paper",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            payload={"reason": "no_signal"},
        )
    )

    events = storage.list_loop_events()

    assert events[0]["loop_id"] == "loop-1"
    assert events[0]["status"] == "idle"
    assert events[0]["payload"]["reason"] == "no_signal"


def test_storage_loop_lock_prevents_duplicate_active_loop(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")

    first = storage.acquire_loop_lock("paper", "binance", "BTCUSDT", "1m", "loop-1", stale_after_seconds=60)
    second = storage.acquire_loop_lock("paper", "binance", "BTCUSDT", "1m", "loop-2", stale_after_seconds=60)
    active = storage.active_loop_lock("paper", "binance", "BTCUSDT", "1m", stale_after_seconds=60)

    assert first["acquired"] is True
    assert second["acquired"] is False
    assert second["reason"] == "loop_lock_active"
    assert active["loop_id"] == "loop-1"


def test_storage_loop_lock_heartbeat_release_and_stale_takeover(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    storage.acquire_loop_lock("paper", "binance", "BTCUSDT", "1m", "loop-1", stale_after_seconds=60)

    assert storage.heartbeat_loop_lock("paper", "binance", "BTCUSDT", "1m", "loop-1") is True
    assert storage.release_loop_lock("paper", "binance", "BTCUSDT", "1m", "loop-1") is True
    assert storage.active_loop_lock("paper", "binance", "BTCUSDT", "1m", stale_after_seconds=60) is None

    storage.acquire_loop_lock("paper", "binance", "BTCUSDT", "1m", "stale-loop", stale_after_seconds=60)
    takeover = storage.acquire_loop_lock("paper", "binance", "BTCUSDT", "1m", "loop-2", stale_after_seconds=-1)
    active = storage.active_loop_lock("paper", "binance", "BTCUSDT", "1m", stale_after_seconds=60)

    assert takeover["acquired"] is True
    assert active["loop_id"] == "loop-2"


def _record_testnet_observation(storage: SQLiteStorage, execute_loop: bool, cycles: int = 6) -> None:
    observation_id = "order" if execute_loop else "check"
    for cycle in range(1, cycles + 1):
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
                    "execute_loop": execute_loop,
                    "order_lifecycle": {
                        "state": "healthy_idle" if execute_loop else "not_attempted",
                        "acceptable": True,
                        "open_order_count": 0,
                    },
                },
            )
        )
