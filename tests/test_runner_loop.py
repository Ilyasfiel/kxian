import pytest

from kxian_bot.config import RuntimeConfig
from kxian_bot.models import AccountBalance, BacktestRunSummary, Candle, ExchangeOrder, Fill, Signal, TradeHistoryResult, WalkForwardRunSummary
from kxian_bot.runner import TradingRunner
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
        "worst_drawdown_pct": 3.0,
        "min_profit_factor": 1.2,
        "min_stress_pass_rate": 100.0,
        "min_walk_forward_pass_rate": 75.0,
    },
    "samples": [],
}


class FakeLoopLockStorage:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.heartbeats = []
        self.releases = []
        self.controls = []

    def acquire_loop_lock(self, mode, exchange, symbol, interval, loop_id, stale_after_seconds):
        if not self.acquired:
            return {
                "acquired": False,
                "reason": "loop_lock_active",
                "lock": {"loop_id": "existing-loop", "mode": mode, "exchange": exchange, "symbol": symbol, "interval": interval},
                "stale_after_seconds": stale_after_seconds,
            }
        return {
            "acquired": True,
            "reason": "loop_lock_acquired",
            "lock": {"loop_id": loop_id, "mode": mode, "exchange": exchange, "symbol": symbol, "interval": interval},
            "stale_after_seconds": stale_after_seconds,
        }

    def heartbeat_loop_lock(self, mode, exchange, symbol, interval, loop_id):
        self.heartbeats.append(loop_id)
        return True

    def release_loop_lock(self, mode, exchange, symbol, interval, loop_id):
        self.releases.append(loop_id)
        return True

    def set_automation_paused(self, mode, exchange, symbol, interval, paused, reason="", updated_by="operator"):
        control = {
            "mode": mode,
            "exchange": exchange,
            "symbol": symbol,
            "interval": interval,
            "paused": paused,
            "reason": reason,
            "updated_by": updated_by,
        }
        self.controls.append(control)
        return control


class AlwaysIdleRunner(TradingRunner):
    def __init__(self, config):
        self.config = config
        self.storage = FakeLoopLockStorage()
        self.events = []

    def run_once(self):
        return {"status": "idle", "reason": "no_signal"}

    def _record_loop_event(self, loop_id, iteration, status, message, payload):
        self.events.append(
            {
                "loop_id": loop_id,
                "iteration": iteration,
                "status": status,
                "message": message,
                "payload": payload,
            }
        )


class FailingRunner(AlwaysIdleRunner):
    def run_once(self):
        raise RuntimeError("exchange temporarily unavailable")


def test_runner_uses_binance_testnet_market_data_endpoint_for_testnet(monkeypatch, tmp_path):
    received = {}

    def fake_create_market_data_client(exchange, use_testnet=False):
        received["exchange"] = exchange
        received["use_testnet"] = use_testnet

        class FakeMarketData:
            pass

        return FakeMarketData()

    monkeypatch.setattr("kxian_bot.runner.create_market_data_client", fake_create_market_data_client)

    TradingRunner(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            use_testnet=True,
            db_path=str(tmp_path / "kxian.sqlite3"),
        )
    )

    assert received == {"exchange": "binance", "use_testnet": True}


def test_runner_uses_production_market_data_endpoint_for_paper(monkeypatch, tmp_path):
    received = {}

    def fake_create_market_data_client(exchange, use_testnet=False):
        received["exchange"] = exchange
        received["use_testnet"] = use_testnet

        class FakeMarketData:
            pass

        return FakeMarketData()

    monkeypatch.setattr("kxian_bot.runner.create_market_data_client", fake_create_market_data_client)

    TradingRunner(RuntimeConfig(mode="paper", exchange="binance", db_path=str(tmp_path / "kxian.sqlite3")))

    assert received == {"exchange": "binance", "use_testnet": False}


class FakeTestnetBroker:
    def __init__(self, status_result=None, account_result=None, trade_history_result=None):
        self.usdt_balance = 1000
        self.asset_balance = 0
        self.submitted = []
        self.status_checked = []
        self.account_checked = []
        self.trade_history_checked = []
        self.status_result = status_result
        self.account_result = account_result
        self.trade_history_result = trade_history_result

    def submit_order(self, order):
        self.submitted.append(order)
        return ExchangeOrder(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            status="submitted",
            exchange_order_id="testnet-1",
        )

    def order_status(self, symbol, order_id):
        self.status_checked.append((symbol, order_id))
        return self.status_result or ExchangeOrder(
            symbol=symbol,
            side="buy",
            quantity=0.01,
            price=100,
            status="submitted",
            exchange_order_id=order_id,
        )

    def account_balance(self, symbol):
        self.account_checked.append(symbol)
        return self.account_result or AccountBalance(
            symbol=symbol,
            base_asset="BTC",
            quote_asset="USDT",
            usdt_balance=self.usdt_balance,
            asset_balance=self.asset_balance,
            status="synced",
        )

    def trade_history(self, symbol, limit=500):
        self.trade_history_checked.append((symbol, limit))
        if self.trade_history_result is not None:
            return self.trade_history_result
        return TradeHistoryResult(symbol=symbol, status="synced", fills=[])


def test_runner_loop_records_each_iteration():
    runner = AlwaysIdleRunner(RuntimeConfig())

    result = runner.run_loop(max_iterations=2, sleep_seconds=0)

    assert result["iterations"] == 2
    assert result["last_result"]["status"] == "idle"
    assert [event["iteration"] for event in runner.events] == [1, 2]
    assert runner.events[0]["status"] == "idle"
    assert runner.storage.heartbeats
    assert runner.storage.releases == [result["loop_id"]]


def test_runner_loop_records_errors_without_crashing():
    runner = FailingRunner(RuntimeConfig())

    result = runner.run_loop(max_iterations=1, sleep_seconds=0)

    assert result["last_result"]["status"] == "error"
    assert runner.events[0]["status"] == "error"
    assert runner.events[0]["message"] == "exchange temporarily unavailable"
    assert runner.storage.releases == [result["loop_id"]]


def test_runner_loop_pauses_after_consecutive_failures():
    runner = FailingRunner(RuntimeConfig(max_consecutive_loop_errors=3))

    result = runner.run_loop(max_iterations=5, sleep_seconds=0)

    assert result["iterations"] == 3
    assert result["last_result"]["status"] == "error"
    assert result["last_result"]["reason"] == "loop_circuit_breaker_tripped"
    assert result["last_result"]["consecutive_failures"] == 3
    assert runner.storage.controls == [
        {
            "mode": "paper",
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "paused": True,
            "reason": "loop_circuit_breaker_tripped",
            "updated_by": "trade-loop",
        }
    ]
    assert runner.events[-1]["payload"]["reason"] == "loop_circuit_breaker_tripped"
    assert runner.storage.releases == [result["loop_id"]]


def test_runner_loop_refuses_to_start_when_lock_active():
    runner = AlwaysIdleRunner(RuntimeConfig())
    runner.storage = FakeLoopLockStorage(acquired=False)

    result = runner.run_loop(max_iterations=1, sleep_seconds=0)

    assert result["iterations"] == 0
    assert result["last_result"]["status"] == "error"
    assert result["last_result"]["reason"] == "loop_lock_active"
    assert runner.events[0]["iteration"] == 0


def test_runner_can_trade_from_sqlite_replay_source(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
        )
    )

    result = runner.run_loop(max_iterations=2, sleep_seconds=0)

    fills = storage.fetch_all("fills")
    events = storage.list_loop_events()
    assert result["iterations"] == 2
    assert any(fill["status"] == "filled" for fill in fills)
    assert len(events) == 2


def test_runner_does_not_trade_when_automation_is_paused(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    storage.set_automation_paused("paper", "binance", "BTCUSDT", "1m", True, reason="operator_stop")
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
        )
    )

    result = runner.run_once()

    assert result["status"] == "idle"
    assert result["reason"] == "automation_paused"
    assert storage.fetch_all("fills") == []


def test_runner_blocks_research_only_active_profile_before_run_once(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="adaptive_range_reclaim",
        parameters={"short_window": 3, "long_window": 6, "research_only": True},
        evidence={"sample_validation": SAMPLE_VALIDATION_EVIDENCE},
        updated_by="test",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            strategy="moving_average_cross",
            short_window=3,
            long_window=6,
            min_order_usdt=1,
        )
    )

    result = runner.run_once()

    assert result["status"] == "blocked"
    assert result["reason"] == "research_only_strategy_runtime_blocked"
    assert result["strategy"] == "adaptive_range_reclaim"
    assert result["will_submit_orders"] is False
    assert storage.fetch_all("fills") == []
    assert storage.fetch_all("strategy_signals") == []


def test_runner_blocks_research_only_active_profile_before_loop_lock(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="adaptive_range_reclaim",
        parameters={"short_window": 3, "long_window": 6, "research_only": True},
        evidence={"sample_validation": SAMPLE_VALIDATION_EVIDENCE},
        updated_by="test",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            strategy="moving_average_cross",
            short_window=3,
            long_window=6,
            min_order_usdt=1,
        )
    )

    result = runner.run_loop(max_iterations=1, sleep_seconds=0)

    events = storage.list_loop_events()
    assert result["iterations"] == 0
    assert result["last_result"]["reason"] == "research_only_strategy_runtime_blocked"
    assert events[0]["iteration"] == 0
    assert events[0]["status"] == "blocked"
    assert storage.fetch_all("loop_locks") == []


def test_runner_blocks_active_profile_marked_research_only_even_with_tradable_strategy(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters={"short_window": 3, "long_window": 6, "research_only": True},
        evidence={"sample_validation": SAMPLE_VALIDATION_EVIDENCE},
        updated_by="test",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            strategy="moving_average_cross",
            short_window=3,
            long_window=6,
            min_order_usdt=1,
        )
    )

    result = runner.run_once()

    assert result["status"] == "blocked"
    assert result["reason"] == "research_only_strategy_runtime_blocked"
    assert result["strategy"] == "moving_average_cross"
    assert result["will_submit_orders"] is False
    assert storage.fetch_all("fills") == []
    assert storage.fetch_all("strategy_signals") == []


def test_runner_normalizes_order_to_trading_rule_before_fill(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            price_step=0.5,
            quantity_step=0.1,
            min_exchange_notional=1,
        )
    )

    result = runner.run_once()

    assert result["status"] == "filled"
    assert result["price"] == 11.0
    assert result["quantity"] == 9.0


def test_runner_rejects_order_below_exchange_min_notional(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            min_exchange_notional=10_000,
        )
    )

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "exchange_rule_min_notional"


def test_runner_ignores_buy_signal_when_position_is_open(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="paper", exchange="binance")
    runner = TradingRunner(RuntimeConfig(db_path=str(db_path), symbol="BTCUSDT", starting_usdt=1000, min_order_usdt=1))

    result = runner._execute_signal(Signal(symbol="BTCUSDT", side="buy", price=105, reason="scripted_buy"))

    fills = storage.fetch_all("fills")
    assert result == {"status": "idle", "reason": "position_already_open"}
    assert len(fills) == 1
    assert runner.broker.asset_balance == 2


def test_runner_restores_paper_balances_from_fills(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="paper", exchange="binance")

    runner = TradingRunner(RuntimeConfig(db_path=str(db_path), symbol="BTCUSDT", starting_usdt=1000))

    assert runner.broker.usdt_balance == 800
    assert runner.broker.asset_balance == 2
    assert runner.average_entry_price == 100


def test_runner_restores_testnet_balances_from_fills(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="testnet", exchange="binance")

    runner = TradingRunner(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            db_path=str(db_path),
            symbol="BTCUSDT",
            starting_usdt=1000,
            binance_api_key="key",
            binance_api_secret="secret",
        )
    )

    assert runner.broker.usdt_balance == 800
    assert runner.broker.asset_balance == 2
    assert runner.average_entry_price == 100


def test_runner_stop_loss_exits_restored_position(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="paper", exchange="binance")
    prices = [100, 101, 102, 101, 99, 94]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            stop_loss_pct=5,
            cooldown_seconds=3600,
        )
    )

    result = runner.run_once()

    fills = [dict(row) for row in storage.fetch_all("fills")]
    signals = [dict(row) for row in storage.fetch_all("strategy_signals")]
    assert result["status"] == "filled"
    assert result["side"] == "sell"
    assert result["reason"] == ""
    assert fills[-1]["side"] == "sell"
    assert signals[-1]["reason"] == "stop_loss_triggered"
    assert runner.average_entry_price == 0


def test_runner_trailing_stop_exits_restored_position_peak(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="paper", exchange="binance")
    storage.update_position_runtime_state("paper", "binance", "BTCUSDT", "1m", trailing_peak_price=110)
    prices = [105, 108, 106, 105, 104, 104]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            trailing_stop_pct=5,
            cooldown_seconds=3600,
        )
    )

    result = runner.run_once()

    fills = [dict(row) for row in storage.fetch_all("fills")]
    signals = [dict(row) for row in storage.fetch_all("strategy_signals")]
    runtime_state = storage.position_runtime_state("paper", "binance", "BTCUSDT", "1m")
    assert result["status"] == "filled"
    assert result["side"] == "sell"
    assert fills[-1]["side"] == "sell"
    assert signals[-1]["reason"] == "trailing_stop_triggered"
    assert runner.average_entry_price == 0
    assert runner.trailing_peak_price == 0
    assert runtime_state["trailing_peak_price"] == 0


def test_runner_testnet_trailing_stop_uses_restored_position(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="testnet", exchange="binance")
    storage.update_position_runtime_state("testnet", "binance", "BTCUSDT", "1m", trailing_peak_price=110)
    prices = [105, 108, 106, 105, 104, 104]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            trailing_stop_pct=5,
            cooldown_seconds=3600,
            binance_api_key="key",
            binance_api_secret="secret",
            enable_testnet_autotrade=False,
        )
    )

    result = runner.run_once()

    signals = [dict(row) for row in storage.fetch_all("strategy_signals")]
    orders = [dict(row) for row in storage.fetch_all("exchange_orders")]
    runtime_state = storage.position_runtime_state("testnet", "binance", "BTCUSDT", "1m")
    assert result["status"] == "rejected"
    assert result["reason"] == "testnet_autotrade_disabled"
    assert signals[-1]["side"] == "sell"
    assert signals[-1]["reason"] == "trailing_stop_triggered"
    assert orders[-1]["side"] == "sell"
    assert orders[-1]["quantity"] == 2
    assert runner.broker.asset_balance == 2
    assert runner.average_entry_price == 100
    assert runner.trailing_peak_price == 110
    assert runtime_state["trailing_peak_price"] == 110


def test_runner_updates_trailing_peak_while_position_is_open(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=100, status="filled"), mode="paper", exchange="binance")
    prices = [100, 101, 102, 103, 104, 105]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            trailing_stop_pct=5,
            cooldown_seconds=3600,
        )
    )

    result = runner.run_once()

    runtime_state = storage.position_runtime_state("paper", "binance", "BTCUSDT", "1m")
    assert result["status"] in {"idle", "rejected"}
    assert result["reason"] in {"no_signal", "cooldown_active"}
    assert runtime_state["trailing_peak_price"] == 105
    assert runner.trailing_peak_price == 105


def test_runner_restores_risk_state_from_storage(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    runner = TradingRunner(RuntimeConfig(db_path=str(db_path), cooldown_seconds=60))
    runner.risk.record_fill(timestamp=1_700_000_000, equity=1000)
    runner.risk.record_fill(timestamp=1_700_000_010, equity=990)
    storage.record_risk_state(runner.risk, mode="paper", exchange="binance", symbol="BTCUSDT", interval="1m")

    restored = TradingRunner(RuntimeConfig(db_path=str(db_path), cooldown_seconds=60))

    assert restored.risk.trades_today == 2
    assert restored.risk.start_equity == 1000
    assert restored.risk.last_fill_timestamp == 1_700_000_010
    assert restored.risk.day_key is not None


def test_runner_does_not_restore_other_symbol_risk_state(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prior = TradingRunner(RuntimeConfig(db_path=str(db_path), symbol="ETHUSDT"))
    prior.risk.record_fill(equity=1000)
    storage.record_risk_state(prior.risk, mode="paper", exchange="binance", symbol="ETHUSDT", interval="1m")

    restored = TradingRunner(RuntimeConfig(db_path=str(db_path), symbol="BTCUSDT"))

    assert restored.risk.trades_today == 0
    assert restored.risk.start_equity is None


def test_runner_ignores_legacy_unscoped_risk_state(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prior = TradingRunner(RuntimeConfig(db_path=str(db_path), symbol="BTCUSDT"))
    prior.risk.record_fill(equity=1000)
    storage.record_risk_state(prior.risk, mode="paper")

    restored = TradingRunner(RuntimeConfig(db_path=str(db_path), symbol="BTCUSDT"))

    assert restored.risk.trades_today == 0


def test_runner_restored_cooldown_blocks_immediate_trade(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=10, status="filled"), mode="paper", exchange="binance")
    prices = [10, 11, 12, 11, 10, 9]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    prior = TradingRunner(RuntimeConfig(db_path=str(db_path), cooldown_seconds=3600))
    prior.risk.record_fill(equity=prior.broker.usdt_balance + prior.broker.asset_balance * 10)
    storage.record_risk_state(prior.risk, mode="paper", exchange="binance", symbol="BTCUSDT", interval="1m")
    restored = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            cooldown_seconds=3600,
        )
    )

    result = restored.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "cooldown_active"


def test_runner_restored_daily_trade_count_blocks_after_restart(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    prior = TradingRunner(RuntimeConfig(db_path=str(db_path), max_daily_trades=1))
    prior.risk.record_fill(equity=1000)
    storage.record_risk_state(prior.risk, mode="paper", exchange="binance", symbol="BTCUSDT", interval="1m")
    restored = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            max_daily_trades=1,
        )
    )

    result = restored.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "max_daily_trades_reached"


def test_runner_can_sell_after_restoring_paper_position(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_fill(Fill(symbol="BTCUSDT", side="buy", quantity=2, price=10, status="filled"), mode="paper", exchange="binance")
    prices = [10, 11, 12, 11, 10, 9]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
        )
    )

    result = runner.run_once()

    fills = [dict(row) for row in storage.fetch_all("fills")]
    assert result["status"] == "filled"
    assert result["side"] == "sell"
    assert runner.broker.asset_balance == 0
    assert fills[-1]["side"] == "sell"


def test_runner_testnet_autotrade_is_disabled_by_default(tmp_path):
    runner, broker, storage = _testnet_replay_runner(tmp_path, enable_testnet_autotrade=False)

    result = runner.run_once()

    orders = storage.fetch_all("exchange_orders")
    assert result["status"] == "rejected"
    assert result["reason"] == "testnet_autotrade_disabled"
    assert broker.submitted == []
    assert orders[0]["status"] == "rejected"
    assert orders[0]["reason"] == "testnet_autotrade_disabled"


def test_runner_testnet_autotrade_submits_and_records_order(tmp_path):
    runner, broker, storage = _testnet_replay_runner(tmp_path, enable_testnet_autotrade=True)

    result = runner.run_once()

    orders = storage.fetch_all("exchange_orders")
    risk_states = storage.fetch_all("risk_state")
    assert result["status"] == "submitted"
    assert result["exchange_order_id"] == "testnet-1"
    assert len(broker.submitted) == 1
    assert orders[0]["exchange_order_id"] == "testnet-1"
    assert risk_states[0]["trades_today"] == 1


def test_runner_testnet_autotrade_stops_when_account_sync_fails(tmp_path):
    account = AccountBalance(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        status="rejected",
        reason="exchange_http_error",
    )
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        broker=FakeTestnetBroker(account_result=account),
    )

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "exchange_http_error"
    assert broker.account_checked == ["BTCUSDT"]
    assert broker.status_checked == []
    assert broker.submitted == []
    assert storage.fetch_all("exchange_orders") == []


def test_runner_testnet_autotrade_uses_synced_account_balances_for_sizing(tmp_path):
    account = AccountBalance(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        usdt_balance=50,
        asset_balance=0,
        status="synced",
    )
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        broker=FakeTestnetBroker(account_result=account),
    )

    result = runner.run_once()

    assert result["status"] == "submitted"
    assert broker.account_checked == ["BTCUSDT"]
    assert broker.submitted[0].quantity == pytest.approx(0.45454)
    assert runner.broker.usdt_balance == 50
    assert runner.broker.asset_balance == 0


def test_runner_testnet_autotrade_blocks_unknown_entry_price_position(tmp_path):
    account = AccountBalance(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        usdt_balance=1000,
        asset_balance=0.25,
        status="synced",
    )
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        broker=FakeTestnetBroker(account_result=account),
    )

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "missing_local_entry_price"
    assert broker.account_checked == ["BTCUSDT"]
    assert broker.submitted == []
    assert storage.fetch_all("strategy_signals") == []
    assert storage.fetch_all("exchange_orders") == []
    assert runner.broker.asset_balance == 0.25
    assert runner.average_entry_price == 0


def test_runner_testnet_autotrade_syncs_trade_history_to_recover_entry_price(tmp_path):
    account = AccountBalance(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        usdt_balance=975,
        asset_balance=0.25,
        status="synced",
    )
    trades = [
        Fill(
            symbol="BTCUSDT",
            side="buy",
            quantity=0.25,
            price=100,
            status="filled",
            exchange_order_id="order-1",
            exchange_trade_id="trade-1",
            timestamp=1,
        )
    ]
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        broker=FakeTestnetBroker(account_result=account, trade_history_result=trades),
    )

    result = runner.run_once()

    fills = storage.fetch_all("fills")
    assert result["status"] in {"idle", "submitted"}
    assert broker.trade_history_checked == [("BTCUSDT", 500)]
    assert len(fills) == 1
    assert fills[0]["exchange_trade_id"] == "trade-1"
    assert runner.average_entry_price == 100


def test_runner_sync_exchange_fills_is_idempotent(tmp_path):
    trade = Fill(
        symbol="BTCUSDT",
        side="buy",
        quantity=0.25,
        price=100,
        status="filled",
        exchange_order_id="order-1",
        exchange_trade_id="trade-1",
        timestamp=1,
    )
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=False,
        broker=FakeTestnetBroker(trade_history_result=TradeHistoryResult(symbol="BTCUSDT", status="synced", fills=[trade])),
    )

    first = runner.sync_exchange_fills()
    second = runner.sync_exchange_fills()

    fills = storage.fetch_all("fills")
    assert first["imported_fills"] == 1
    assert second["imported_fills"] == 0
    assert len(fills) == 1
    assert runner.average_entry_price == 100


def test_runner_sync_exchange_fills_rejects_trade_history_failure(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=False,
        broker=FakeTestnetBroker(
            trade_history_result=TradeHistoryResult(
                symbol="BTCUSDT",
                status="rejected",
                reason="exchange_http_error",
            )
        ),
    )

    result = runner.sync_exchange_fills()

    assert result["status"] == "rejected"
    assert result["reason"] == "exchange_http_error"
    assert result["seen_fills"] == 0
    assert result["imported_fills"] == 0
    assert broker.trade_history_checked == [("BTCUSDT", 500)]
    assert storage.fetch_all("fills") == []


def test_runner_testnet_strategy_gate_blocks_missing_backtest(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        require_strategy_gate=True,
    )

    result = runner.run_once()

    orders = storage.fetch_all("exchange_orders")
    assert result["status"] == "rejected"
    assert result["reason"] == "strategy_gate_missing_backtest"
    assert result["strategy_gate"]["allowed"] is False
    assert broker.submitted == []
    assert orders[0]["reason"] == "strategy_gate_missing_backtest"


def test_runner_testnet_strategy_gate_does_not_reuse_other_strategy_evidence(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        require_strategy_gate=True,
    )
    storage.record_backtest_run(
        BacktestRunSummary(
            run_id="run-other-strategy",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="donchian_breakout",
            parameters={"strategy": "donchian_breakout", "short_window": 3, "long_window": 5},
            candle_count=6,
            initial_equity=1000,
            final_equity=1020,
            return_pct=2.0,
            max_drawdown_pct=2.0,
            win_rate=50,
            profit_factor=1.2,
            trade_count=35,
            fees_paid=1,
            slippage_paid=0.5,
        )
    )

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "strategy_gate_missing_backtest"
    assert broker.submitted == []


def test_runner_testnet_strategy_gate_blocks_weak_backtest(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        require_strategy_gate=True,
    )
    _record_gate_backtest(storage, trade_count=2, return_pct=1.0, drawdown_pct=2.0, profit_factor=1.2)

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "strategy_gate_insufficient_trades"
    assert result["strategy_gate"]["checks"]["trade_count"] == 2
    assert broker.submitted == []


def test_runner_testnet_strategy_gate_allows_strong_backtest(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        require_strategy_gate=True,
    )
    _record_gate_backtest(storage, trade_count=35, return_pct=1.0, drawdown_pct=2.0, profit_factor=1.2)
    _record_sample_validation_profile(storage)

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "stress_gate_missing_backtest"
    assert broker.submitted == []


def test_runner_testnet_stress_gate_allows_strong_backtest(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        require_strategy_gate=True,
    )
    _record_gate_backtest(storage, trade_count=35, return_pct=1.0, drawdown_pct=2.0, profit_factor=1.2)
    _record_sample_validation_profile(storage)
    _record_stress_backtest(storage, min_trade_count=35, worst_return_pct=0.5, worst_drawdown_pct=3.0, worst_profit_factor=1.1)

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "walk_forward_gate_missing_run"
    assert broker.submitted == []


def test_runner_testnet_walk_forward_gate_allows_strong_validation(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        require_strategy_gate=True,
    )
    _record_gate_backtest(storage, trade_count=35, return_pct=1.0, drawdown_pct=2.0, profit_factor=1.2)
    _record_stress_backtest(storage, min_trade_count=35, worst_return_pct=0.5, worst_drawdown_pct=3.0, worst_profit_factor=1.1)
    _record_walk_forward(storage, pass_rate=75, total_trade_count=35)
    _record_sample_validation_profile(storage)

    result = runner.run_once()

    assert result["status"] == "submitted"
    assert result["exchange_order_id"] == "testnet-1"
    assert len(broker.submitted) == 1


def test_runner_testnet_sample_validation_gate_blocks_missing_evidence(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        require_strategy_gate=True,
    )
    _record_gate_backtest(storage, trade_count=35, return_pct=1.0, drawdown_pct=2.0, profit_factor=1.2)
    _record_stress_backtest(storage, min_trade_count=35, worst_return_pct=0.5, worst_drawdown_pct=3.0, worst_profit_factor=1.1)
    _record_walk_forward(storage, pass_rate=75, total_trade_count=35)

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "sample_validation_gate_missing_profile"
    assert result["sample_validation_gate"]["allowed"] is False
    assert broker.submitted == []


def test_runner_testnet_walk_forward_gate_blocks_weak_validation(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        require_strategy_gate=True,
    )
    _record_gate_backtest(storage, trade_count=35, return_pct=1.0, drawdown_pct=2.0, profit_factor=1.2)
    _record_sample_validation_profile(storage)
    _record_stress_backtest(storage, min_trade_count=35, worst_return_pct=0.5, worst_drawdown_pct=3.0, worst_profit_factor=1.1)
    _record_walk_forward(storage, pass_rate=25, total_trade_count=35)

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "walk_forward_gate_pass_rate_too_low"
    assert result["walk_forward_gate"]["checks"]["pass_rate"] == 25
    assert broker.submitted == []


def test_runner_testnet_stress_gate_blocks_weak_stress_backtest(tmp_path):
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        require_strategy_gate=True,
    )
    _record_gate_backtest(storage, trade_count=35, return_pct=1.0, drawdown_pct=2.0, profit_factor=1.2)
    _record_sample_validation_profile(storage)
    _record_stress_backtest(storage, min_trade_count=10, worst_return_pct=0.5, worst_drawdown_pct=3.0, worst_profit_factor=1.1)

    result = runner.run_once()

    assert result["status"] == "rejected"
    assert result["reason"] == "stress_gate_insufficient_trades"
    assert result["stress_gate"]["checks"]["min_trade_count"] == 10
    assert broker.submitted == []


def test_runner_testnet_autotrade_waits_when_open_order_exists(tmp_path):
    runner, broker, storage = _testnet_replay_runner(tmp_path, enable_testnet_autotrade=True)
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

    result = runner.run_once()

    assert result["status"] == "idle"
    assert result["reason"] == "open_exchange_orders_refreshed"
    assert result["open_order_count"] == 1
    assert broker.status_checked == [("BTCUSDT", "open-1")]
    assert broker.submitted == []


def test_runner_testnet_autotrade_refreshes_filled_open_order(tmp_path):
    filled_order = ExchangeOrder(
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        price=100.5,
        status="filled",
        exchange_order_id="open-1",
    )
    runner, broker, storage = _testnet_replay_runner(
        tmp_path,
        enable_testnet_autotrade=True,
        broker=FakeTestnetBroker(status_result=filled_order),
    )
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

    result = runner.run_once()

    fills = storage.fetch_all("fills")
    assert result["status"] == "synced"
    assert result["reason"] == "open_exchange_orders_refreshed"
    assert result["open_order_count"] == 0
    assert broker.status_checked == [("BTCUSDT", "open-1")]
    assert broker.account_checked == []
    assert storage.list_open_exchange_orders("testnet", "binance", "BTCUSDT") == []
    assert fills[0]["status"] == "filled"
    assert fills[0]["exchange"] == "binance"
    assert fills[0]["price"] == 100.5
    assert broker.usdt_balance == 998.995
    assert broker.asset_balance == 0.01
    assert runner.average_entry_price == pytest.approx(100.5)


def test_runner_testnet_refresh_does_not_double_count_accepted_order(tmp_path):
    filled_order = ExchangeOrder(
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        price=100,
        status="filled",
        exchange_order_id="testnet-1",
    )
    runner, broker, storage = _testnet_replay_runner(tmp_path, enable_testnet_autotrade=True)

    submitted = runner.run_once()
    runner.broker = FakeTestnetBroker(status_result=filled_order)
    refreshed = runner.run_once()

    risk_states = storage.fetch_all("risk_state")
    fills = storage.fetch_all("fills")
    assert submitted["status"] == "submitted"
    assert refreshed["status"] == "synced"
    assert refreshed["open_order_count"] == 0
    assert len(risk_states) == 1
    assert risk_states[0]["trades_today"] == 1
    assert fills[0]["status"] == "filled"


def test_runner_live_autotrade_is_blocked_while_dry_run_enabled(tmp_path):
    runner, broker, storage = _live_replay_runner(
        tmp_path,
        live_dry_run=True,
        enable_live_autotrade=False,
    )

    result = runner.run_once()

    orders = storage.fetch_all("exchange_orders")
    assert result["status"] == "rejected"
    assert result["reason"] == "live_dry_run_enabled"
    assert broker.submitted == []
    assert orders[0]["mode"] == "live"
    assert orders[0]["reason"] == "live_dry_run_enabled"


def test_runner_live_autotrade_blocks_orders_above_live_notional_limit(tmp_path):
    runner, broker, storage = _live_replay_runner(
        tmp_path,
        live_dry_run=False,
        enable_live_autotrade=True,
        max_live_order_usdt=5,
    )

    result = runner.run_once()

    orders = storage.fetch_all("exchange_orders")
    assert result["status"] == "rejected"
    assert result["reason"] == "live_order_notional_exceeds_limit"
    assert result["live_gate"]["checks"]["order_notional"] > 5
    assert broker.submitted == []
    assert orders[0]["reason"] == "live_order_notional_exceeds_limit"


def test_runner_live_autotrade_blocks_before_account_sync_when_credentials_are_not_confirmed(tmp_path):
    runner, broker, storage = _live_replay_runner(
        tmp_path,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_credentials_confirmed=False,
    )

    result = runner.run_once()

    orders = storage.fetch_all("exchange_orders")
    assert result["status"] == "rejected"
    assert result["reason"] == "live_credentials_not_confirmed"
    assert broker.account_checked == []
    assert broker.submitted == []
    assert orders[0]["reason"] == "live_credentials_not_confirmed"


def test_runner_live_autotrade_submits_when_confirmed_and_within_limit(tmp_path):
    runner, broker, storage = _live_replay_runner(
        tmp_path,
        live_dry_run=False,
        enable_live_autotrade=True,
        max_live_order_usdt=200,
    )

    result = runner.run_once()

    orders = storage.fetch_all("exchange_orders")
    risk_states = storage.fetch_all("risk_state")
    assert result["status"] == "submitted"
    assert result["exchange_order_id"] == "testnet-1"
    assert len(broker.submitted) == 1
    assert orders[0]["mode"] == "live"
    assert orders[0]["exchange_order_id"] == "testnet-1"
    assert risk_states[0]["mode"] == "live"
    assert risk_states[0]["trades_today"] == 1


def _testnet_replay_runner(
    tmp_path,
    enable_testnet_autotrade: bool,
    broker=None,
    require_strategy_gate: bool = False,
):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            min_exchange_notional=1,
            binance_api_key="key",
            binance_api_secret="secret",
            enable_testnet_autotrade=enable_testnet_autotrade,
            require_strategy_gate=require_strategy_gate,
            require_sample_validation_gate=require_strategy_gate,
            require_stress_gate=require_strategy_gate,
            require_walk_forward_gate=require_strategy_gate,
        )
    )
    broker = broker or FakeTestnetBroker()
    runner.broker = broker
    return runner, broker, storage


def _live_replay_runner(
    tmp_path,
    live_dry_run: bool,
    enable_live_autotrade: bool,
    broker=None,
    max_live_order_usdt: float = 50,
    live_credentials_confirmed: bool = True,
):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    prices = [10, 9, 8, 9, 10, 11]
    storage.upsert_candles(
        [
            Candle(open_time=i, open=price, high=price, low=price, close=price, volume=1, close_time=i + 1)
            for i, price in enumerate(prices)
        ],
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
    )
    runner = TradingRunner(
        RuntimeConfig(
            mode="live",
            exchange="binance",
            db_path=str(db_path),
            market_data_source="sqlite",
            short_window=3,
            long_window=5,
            min_order_usdt=1,
            min_exchange_notional=1,
            allow_live=True,
            use_testnet=False,
            live_dry_run=live_dry_run,
            enable_live_autotrade=enable_live_autotrade,
            live_confirmation="LIVE:binance:BTCUSDT:1m",
            live_credentials_confirmed=live_credentials_confirmed,
            max_live_order_usdt=max_live_order_usdt,
            binance_api_key="key",
            binance_api_secret="secret",
            require_strategy_gate=False,
            require_sample_validation_gate=False,
            require_stress_gate=False,
            require_walk_forward_gate=False,
        )
    )
    broker = broker or FakeTestnetBroker()
    runner.broker = broker
    return runner, broker, storage


def _record_gate_backtest(
    storage,
    trade_count: int,
    return_pct: float,
    drawdown_pct: float,
    profit_factor: float,
):
    storage.record_backtest_run(
        BacktestRunSummary(
            run_id=f"run-{trade_count}-{return_pct}",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
            candle_count=6,
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


def _record_sample_validation_profile(storage, evidence: dict | None = None):
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1m",
        strategy="moving_average_cross",
        parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
        evidence={"sample_validation": evidence or SAMPLE_VALIDATION_EVIDENCE},
        updated_by="test",
    )


def _record_stress_backtest(
    storage,
    min_trade_count: int,
    worst_return_pct: float,
    worst_drawdown_pct: float,
    worst_profit_factor: float,
):
    from kxian_bot.models import StressBacktestRunSummary

    storage.record_stress_backtest_run(
        StressBacktestRunSummary(
            run_id=f"stress-{min_trade_count}-{worst_return_pct}",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
            candle_count=6,
            scenario_count=5,
            passed_scenarios=5,
            failed_scenarios=0,
            pass_rate=100,
            worst_return_pct=worst_return_pct,
            worst_drawdown_pct=worst_drawdown_pct,
            worst_profit_factor=worst_profit_factor,
            min_trade_count=min_trade_count,
            scenarios=[],
        )
    )


def _record_walk_forward(storage, pass_rate: float, total_trade_count: int):
    storage.record_walk_forward_run(
        WalkForwardRunSummary(
            run_id=f"walk-{pass_rate}-{total_trade_count}",
            exchange="binance",
            symbol="BTCUSDT",
            interval="1m",
            start_time=0,
            end_time=10,
            strategy="moving_average_cross",
            parameters={"strategy": "moving_average_cross", "short_window": 3, "long_window": 5},
            candle_count=30,
            segment_count=3,
            passed_segments=2,
            failed_segments=1,
            pass_rate=pass_rate,
            total_trade_count=total_trade_count,
            min_segment_trade_count=5,
            worst_return_pct=0.2,
            worst_drawdown_pct=3.0,
            worst_profit_factor=1.2,
            segments=[],
        )
    )
