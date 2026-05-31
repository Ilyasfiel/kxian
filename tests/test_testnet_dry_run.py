from kxian_bot.config import RuntimeConfig
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
