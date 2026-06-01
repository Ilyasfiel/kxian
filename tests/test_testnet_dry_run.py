from kxian_bot.config import RuntimeConfig
from kxian_bot.models import ExchangeOrder
from kxian_bot import testnet_dry_run
from kxian_bot.storage import SQLiteStorage


def test_testnet_observation_stops_on_first_failure_and_records_event(monkeypatch, tmp_path):
    calls = []
    db_path = tmp_path / "kxian.sqlite3"

    def fake_dry_run(config, sync_limit, execute_loop, sleep_seconds):
        calls.append(
            {
                "mode": config.mode,
                "sync_limit": sync_limit,
                "execute_loop": execute_loop,
                "sleep_seconds": sleep_seconds,
            }
        )
        return {"status": "fail", "reason": "missing_exchange_credentials"}

    monkeypatch.setattr(testnet_dry_run, "run_testnet_dry_run", fake_dry_run)

    result = testnet_dry_run.run_testnet_observation(
        RuntimeConfig(mode="testnet", db_path=str(db_path)),
        cycles=3,
        sync_limit=25,
        execute_loop=False,
        sleep_seconds=0,
    )

    assert result["status"] == "fail"
    assert result["cycles_requested"] == 3
    assert result["cycles_completed"] == 1
    assert result["failures"] == 1
    assert result["stopped_early"] is True
    assert result["observation_id"]
    assert result["results"][0]["reason"] == "missing_exchange_credentials"
    assert calls == [{"mode": "testnet", "sync_limit": 25, "execute_loop": False, "sleep_seconds": 0.0}]
    events = SQLiteStorage(db_path).list_loop_events()
    assert len(events) == 1
    assert events[0]["loop_id"] == f"observe-{result['observation_id']}"
    assert events[0]["status"] == "error"
    assert events[0]["message"] == "testnet_observe_failed:missing_exchange_credentials"
    assert events[0]["payload"]["kind"] == "testnet_observe"
    assert events[0]["payload"]["cycle"] == 1


def test_testnet_observation_can_continue_after_failures_and_bounds_values(monkeypatch, tmp_path):
    dry_run_results = [
        {"status": "fail", "reason": "exchange_timeout"},
        {"status": "pass", "reason": ""},
    ]
    calls = []
    sleeps = []
    db_path = tmp_path / "kxian.sqlite3"

    def fake_dry_run(config, sync_limit, execute_loop, sleep_seconds):
        calls.append({"sync_limit": sync_limit, "execute_loop": execute_loop, "sleep_seconds": sleep_seconds})
        return dry_run_results.pop(0)

    monkeypatch.setattr(testnet_dry_run, "run_testnet_dry_run", fake_dry_run)
    monkeypatch.setattr(testnet_dry_run.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = testnet_dry_run.run_testnet_observation(
        RuntimeConfig(mode="testnet", db_path=str(db_path)),
        cycles=2,
        sync_limit=5000,
        execute_loop=False,
        sleep_seconds=-5,
        continue_on_failure=True,
    )

    assert result["status"] == "fail"
    assert result["cycles_completed"] == 2
    assert result["failures"] == 1
    assert result["stopped_early"] is False
    assert result["sync_limit"] == 1000
    assert result["sleep_seconds"] == 0.0
    assert calls == [
        {"sync_limit": 1000, "execute_loop": False, "sleep_seconds": 0.0},
        {"sync_limit": 1000, "execute_loop": False, "sleep_seconds": 0.0},
    ]
    assert sleeps == [0.0]
    events = SQLiteStorage(db_path).list_loop_events()
    assert [event["status"] for event in events] == ["idle", "error"]
    assert events[0]["message"] == "testnet_observe_passed"
    assert events[1]["message"] == "testnet_observe_failed:exchange_timeout"


def test_testnet_observation_execute_loop_uses_zero_inner_sleep(monkeypatch, tmp_path):
    calls = []

    def fake_dry_run(config, sync_limit, execute_loop, sleep_seconds):
        calls.append({"sync_limit": sync_limit, "execute_loop": execute_loop, "sleep_seconds": sleep_seconds})
        return {"status": "pass"}

    monkeypatch.setattr(testnet_dry_run, "run_testnet_dry_run", fake_dry_run)
    monkeypatch.setattr(testnet_dry_run.time, "sleep", lambda seconds: None)

    result = testnet_dry_run.run_testnet_observation(
        RuntimeConfig(mode="testnet", db_path=str(tmp_path / "kxian.sqlite3")),
        cycles=1,
        sync_limit=10,
        execute_loop=True,
        sleep_seconds=60,
    )

    assert result["status"] == "pass"
    assert result["cycles_completed"] == 1
    assert result["execute_loop"] is True
    assert calls == [{"sync_limit": 10, "execute_loop": True, "sleep_seconds": 0.0}]


def test_testnet_observation_records_order_lifecycle(monkeypatch, tmp_path):
    lifecycle = {"state": "filled", "acceptable": True, "open_order_count": 0}
    profile = {"profile_key": "testnet:binance:BTCUSDT:4h", "validation_run_ids": {"strategy_gate": "run-1"}}
    db_path = tmp_path / "kxian.sqlite3"

    def fake_dry_run(config, sync_limit, execute_loop, sleep_seconds):
        return {
            "status": "pass",
            "profile": profile,
            "account": {"status": "synced", "asset_balance": 0.0},
            "fill_sync": {"status": "synced", "seen_fills": 1, "imported_fills": 0},
            "preflight": {"status": "pass"},
            "order_lifecycle": lifecycle,
        }

    monkeypatch.setattr(testnet_dry_run, "run_testnet_dry_run", fake_dry_run)

    result = testnet_dry_run.run_testnet_observation(
        RuntimeConfig(mode="testnet", db_path=str(db_path)),
        cycles=1,
        sync_limit=10,
        execute_loop=True,
        sleep_seconds=0,
    )

    assert result["status"] == "pass"
    assert result["order_lifecycle"] == lifecycle
    events = SQLiteStorage(db_path).list_loop_events()
    assert events[0]["payload"]["order_lifecycle"] == lifecycle
    assert events[0]["payload"]["profile"] == profile
    assert events[0]["payload"]["account"] == {"status": "synced"}
    assert events[0]["payload"]["fill_sync"] == {"status": "synced", "seen_fills": 1, "imported_fills": 0}
    assert events[0]["payload"]["preflight"] == {"status": "pass"}
    assert events[0]["payload"]["open_order_count"] == 0
    latest = SQLiteStorage(db_path).latest_testnet_observation("binance", "BTCUSDT", "1m", execute_loop=True)
    assert latest["profile"] == profile
    assert latest["fill_sync"]["status"] == "synced"
    assert latest["open_order_count"] == 0


def test_testnet_dry_run_rejects_out_of_scope_closed_loop_config(tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        exchange="okx",
        symbol="ETHUSDT",
        interval="1m",
        db_path=str(tmp_path / "kxian.sqlite3"),
        use_testnet=True,
        okx_api_key="key",
        okx_api_secret="secret",
        okx_api_passphrase="pass",
        enable_testnet_autotrade=True,
    )

    result = testnet_dry_run.run_testnet_dry_run(
        config,
        sync_limit=10,
        execute_loop=False,
        sleep_seconds=0,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "binance_exchange_required"
    assert result["scope"]["failures"] == [
        "binance_exchange_required",
        "btcusdt_symbol_required",
        "4h_interval_required",
    ]


def test_testnet_dry_run_rejects_live_switches_for_closed_loop(tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        interval="4h",
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
        allow_live=True,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="LIVE:binance:BTCUSDT:4h",
        live_credentials_confirmed=True,
    )

    result = testnet_dry_run.run_testnet_dry_run(
        config,
        sync_limit=10,
        execute_loop=False,
        sleep_seconds=0,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "live_allow_must_remain_disabled"
    assert result["scope"]["failures"] == [
        "live_allow_must_remain_disabled",
        "live_autotrade_must_remain_disabled",
        "live_dry_run_must_remain_enabled",
        "live_confirmation_must_remain_empty",
        "live_credentials_confirmation_must_remain_false",
    ]


def test_testnet_dry_run_missing_credentials_keeps_secret_values_out(tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        interval="4h",
        binance_api_key="",
        binance_api_secret="",
    )

    result = testnet_dry_run.run_testnet_dry_run(
        config,
        sync_limit=10,
        execute_loop=False,
        sleep_seconds=0,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "missing_exchange_credentials"
    assert result["config"]["mode"] == "testnet"
    assert result["config"]["use_testnet"] is True
    assert result["credentials"]["present"]["binance_api_key"] is False
    assert "api-key-value" not in str(result)
    assert "super-secret-value" not in str(result)


def test_testnet_dry_run_partial_credentials_keep_present_secret_out(tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        interval="4h",
        binance_api_key="api-key-value",
        binance_api_secret="",
    )

    result = testnet_dry_run.run_testnet_dry_run(
        config,
        sync_limit=10,
        execute_loop=False,
        sleep_seconds=0,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "missing_exchange_credentials"
    assert result["credentials"]["present"]["binance_api_key"] is True
    assert result["credentials"]["present"]["binance_api_secret"] is False
    assert "api-key-value" not in str(result)


def test_testnet_dry_run_execute_loop_autotrade_false_stops_before_runner(monkeypatch, tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        interval="4h",
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=False,
    )

    def fail_runner(*args, **kwargs):
        raise AssertionError("TradingRunner should not be created when testnet autotrade is disabled")

    monkeypatch.setattr(testnet_dry_run, "TradingRunner", fail_runner)

    result = testnet_dry_run.run_testnet_dry_run(
        config,
        sync_limit=10,
        execute_loop=True,
        sleep_seconds=0,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "testnet_autotrade_disabled"


def test_testnet_dry_run_without_execute_loop_allows_autotrade_false(monkeypatch, tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        interval="4h",
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=False,
    )

    preflight_calls = []

    def fake_preflight(config, storage=None, require_testnet_autotrade=True):
        preflight_calls.append(require_testnet_autotrade)
        return {"status": "pass", "checks": []}

    monkeypatch.setattr(testnet_dry_run, "run_preflight", fake_preflight)
    monkeypatch.setattr(
        testnet_dry_run,
        "create_broker",
        lambda config: type("Broker", (), {"account_balance": lambda self, symbol: {"status": "synced"}})(),
    )

    class FakeRunner:
        def __init__(self, config):
            self.config = config

        def sync_exchange_fills(self, limit):
            return {"status": "synced"}

    monkeypatch.setattr(testnet_dry_run, "TradingRunner", FakeRunner)

    result = testnet_dry_run.run_testnet_dry_run(
        config,
        sync_limit=10,
        execute_loop=False,
        sleep_seconds=0,
    )

    assert result["status"] == "pass"
    assert preflight_calls == [False, False]
    assert result["order_lifecycle"]["state"] == "not_attempted"


def test_testnet_dry_run_reports_profile_and_order_lifecycle(monkeypatch, tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="testnet",
        exchange="binance",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
        evidence={
            "sample_validation": {"status": "pass", "sample_count": 2},
            "gates": {
                "strategy_gate": {"run_id": "bt-run"},
                "stress_gate": {"run_id": "stress-run"},
                "walk_forward_gate": {"run_id": "walk-run"},
            },
        },
        updated_by="test",
    )
    storage.record_exchange_order(
        ExchangeOrder(
            symbol="BTCUSDT",
            side="buy",
            quantity=0.01,
            price=100,
            status="submitted",
            exchange_order_id="order-1",
        ),
        mode="testnet",
        exchange="binance",
    )
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        interval="4h",
        binance_api_key="api-key-value",
        binance_api_secret="super-secret-value",
        enable_testnet_autotrade=True,
    )

    monkeypatch.setattr(testnet_dry_run, "run_preflight", lambda config, **kwargs: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        testnet_dry_run,
        "create_broker",
        lambda config: type(
            "Broker",
            (),
            {"account_balance": lambda self, symbol: {"status": "synced", "symbol": symbol}},
        )(),
    )

    class FakeRunner:
        def __init__(self, config):
            self.config = config

        def sync_exchange_fills(self, limit):
            return {"status": "synced", "imported_fills": 0, "seen_fills": 0}

        def run_loop(self, max_iterations, sleep_seconds):
            return {"loop_id": "loop-1", "iterations": 1, "last_result": {"status": "idle", "reason": "no_signal"}}

    monkeypatch.setattr(testnet_dry_run, "TradingRunner", FakeRunner)

    result = testnet_dry_run.run_testnet_dry_run(
        config,
        sync_limit=10,
        execute_loop=True,
        sleep_seconds=0,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "open_testnet_order_requires_cleanup"
    assert result["config"]["interval"] == "4h"
    assert result["profile"]["profile_key"] == "testnet:binance:BTCUSDT:4h"
    assert result["profile"]["validation_run_ids"] == {
        "strategy_gate": "bt-run",
        "stress_gate": "stress-run",
        "walk_forward_gate": "walk-run",
    }
    assert result["order_lifecycle"]["state"] == "open_orders"
    assert result["order_lifecycle"]["open_order_count"] == 1
    assert any("cancel-order" in step for step in result["next_steps"])
    assert "api-key-value" not in str(result)
    assert "super-secret-value" not in str(result)


def test_testnet_dry_run_order_lifecycle_ignores_old_terminal_orders(monkeypatch, tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.record_exchange_order(
        ExchangeOrder(
            symbol="BTCUSDT",
            side="buy",
            quantity=0.01,
            price=100,
            status="filled",
            exchange_order_id="old-filled",
        ),
        mode="testnet",
        exchange="binance",
    )
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        interval="4h",
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
        require_strategy_gate=False,
        require_sample_validation_gate=False,
        require_stress_gate=False,
        require_walk_forward_gate=False,
    )

    monkeypatch.setattr(testnet_dry_run, "run_preflight", lambda config, **kwargs: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        testnet_dry_run,
        "create_broker",
        lambda config: type("Broker", (), {"account_balance": lambda self, symbol: {"status": "synced"}})(),
    )

    class FakeRunner:
        def __init__(self, config):
            self.config = config

        def sync_exchange_fills(self, limit):
            return {"status": "synced"}

        def run_loop(self, max_iterations, sleep_seconds):
            return {"loop_id": "loop-1", "iterations": 1, "last_result": {"status": "idle", "reason": "no_signal"}}

    monkeypatch.setattr(testnet_dry_run, "TradingRunner", FakeRunner)

    result = testnet_dry_run.run_testnet_dry_run(
        config,
        sync_limit=10,
        execute_loop=True,
        sleep_seconds=0,
    )

    assert result["status"] == "pass"
    assert result["order_lifecycle"]["state"] == "healthy_idle"
    assert result["order_lifecycle"]["latest_order"] is None


def test_testnet_dry_run_accepts_new_filled_or_canceled_order_lifecycle(monkeypatch, tmp_path):
    for terminal_status in ("filled", "canceled"):
        db_path = tmp_path / f"{terminal_status}.sqlite3"
        storage = SQLiteStorage(db_path)
        config = RuntimeConfig(
            mode="testnet",
            db_path=str(db_path),
            interval="4h",
            binance_api_key="key",
            binance_api_secret="secret",
            enable_testnet_autotrade=True,
            require_strategy_gate=False,
            require_sample_validation_gate=False,
            require_stress_gate=False,
            require_walk_forward_gate=False,
        )

        monkeypatch.setattr(testnet_dry_run, "run_preflight", lambda config, **kwargs: {"status": "pass", "checks": []})
        monkeypatch.setattr(
            testnet_dry_run,
            "create_broker",
            lambda config: type("Broker", (), {"account_balance": lambda self, symbol: {"status": "synced"}})(),
        )

        class FakeRunner:
            def __init__(self, config):
                self.config = config

            def sync_exchange_fills(self, limit):
                return {"status": "synced"}

            def run_loop(self, max_iterations, sleep_seconds):
                storage.record_exchange_order(
                    ExchangeOrder(
                        symbol="BTCUSDT",
                        side="buy",
                        quantity=0.01,
                        price=100,
                        status=terminal_status,
                        exchange_order_id=f"new-{terminal_status}",
                    ),
                    mode="testnet",
                    exchange="binance",
                )
                return {
                    "loop_id": "loop-1",
                    "iterations": 1,
                    "last_result": {"status": terminal_status, "exchange_order_id": f"new-{terminal_status}"},
                }

        monkeypatch.setattr(testnet_dry_run, "TradingRunner", FakeRunner)

        result = testnet_dry_run.run_testnet_dry_run(
            config,
            sync_limit=10,
            execute_loop=True,
            sleep_seconds=0,
        )

        assert result["status"] == "pass"
        assert result["order_lifecycle"]["state"] == terminal_status
        assert result["order_lifecycle"]["acceptable"] is True
        assert result["order_lifecycle"]["latest_order"]["exchange_order_id"] == f"new-{terminal_status}"


def test_testnet_dry_run_classifies_safe_and_unsafe_rejections(monkeypatch, tmp_path):
    for reason, expected_state, expected_status in (
        ("no_signal", "safe_rejected", "pass"),
        ("exchange_http_401", "rejected", "fail"),
    ):
        db_path = tmp_path / f"{reason}.sqlite3"
        storage = SQLiteStorage(db_path)
        config = RuntimeConfig(
            mode="testnet",
            db_path=str(db_path),
            interval="4h",
            binance_api_key="key",
            binance_api_secret="secret",
            enable_testnet_autotrade=True,
            require_strategy_gate=False,
            require_sample_validation_gate=False,
            require_stress_gate=False,
            require_walk_forward_gate=False,
        )

        monkeypatch.setattr(testnet_dry_run, "run_preflight", lambda config, **kwargs: {"status": "pass", "checks": []})
        monkeypatch.setattr(
            testnet_dry_run,
            "create_broker",
            lambda config: type("Broker", (), {"account_balance": lambda self, symbol: {"status": "synced"}})(),
        )

        class FakeRunner:
            def __init__(self, config):
                self.config = config

            def sync_exchange_fills(self, limit):
                return {"status": "synced"}

            def run_loop(self, max_iterations, sleep_seconds):
                storage.record_exchange_order(
                    ExchangeOrder(
                        symbol="BTCUSDT",
                        side="buy",
                        quantity=0.01,
                        price=100,
                        status="rejected",
                        reason=reason,
                        exchange_order_id=f"rejected-{reason}",
                    ),
                    mode="testnet",
                    exchange="binance",
                )
                return {
                    "loop_id": "loop-1",
                    "iterations": 1,
                    "last_result": {"status": "rejected", "reason": reason, "exchange_order_id": f"rejected-{reason}"},
                }

        monkeypatch.setattr(testnet_dry_run, "TradingRunner", FakeRunner)

        result = testnet_dry_run.run_testnet_dry_run(
            config,
            sync_limit=10,
            execute_loop=True,
            sleep_seconds=0,
        )

        assert result["status"] == expected_status
        assert result["order_lifecycle"]["state"] == expected_state
        assert result["order_lifecycle"]["acceptable"] is (expected_status == "pass")
        if expected_status == "fail":
            assert result["reason"] == "testnet_order_lifecycle_not_acceptable"


def test_testnet_dry_run_rejects_unrecorded_bounded_order_result(monkeypatch, tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(db_path),
        interval="4h",
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
        require_strategy_gate=False,
        require_sample_validation_gate=False,
        require_stress_gate=False,
        require_walk_forward_gate=False,
    )

    monkeypatch.setattr(testnet_dry_run, "run_preflight", lambda config, **kwargs: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        testnet_dry_run,
        "create_broker",
        lambda config: type("Broker", (), {"account_balance": lambda self, symbol: {"status": "synced"}})(),
    )

    class FakeRunner:
        def __init__(self, config):
            self.config = config

        def sync_exchange_fills(self, limit):
            return {"status": "synced"}

        def run_loop(self, max_iterations, sleep_seconds):
            return {
                "loop_id": "loop-1",
                "iterations": 1,
                "last_result": {"status": "submitted", "reason": "", "exchange_order_id": "missing-order"},
            }

    monkeypatch.setattr(testnet_dry_run, "TradingRunner", FakeRunner)

    result = testnet_dry_run.run_testnet_dry_run(
        config,
        sync_limit=10,
        execute_loop=True,
        sleep_seconds=0,
    )

    assert result["status"] == "fail"
    assert result["reason"] == "testnet_order_lifecycle_not_acceptable"
    assert result["order_lifecycle"]["state"] == "unverified_order_result"
    assert result["order_lifecycle"]["acceptable"] is False
