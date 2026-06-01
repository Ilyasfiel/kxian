from kxian_bot.config import RuntimeConfig
from kxian_bot import testnet_close_loop


def test_testnet_close_loop_stops_before_bounded_without_confirmation(monkeypatch, tmp_path):
    calls = []

    def fake_setup(config, timeout_seconds=5.0):
        calls.append("setup")
        return {"status": "pass", "checks": []}

    def fake_readiness(config, storage=None, require_testnet_autotrade=True):
        calls.append("readiness")
        return {"status": "pass", "checks": []}

    def fake_health(config, timeout_seconds=5.0):
        calls.append("health")
        return {"status": "pass", "checks": []}

    def fake_checklist(config, storage=None, target_mode=None):
        calls.append("checklist")
        return {
            "status": "blocked",
            "phase": "ready_for_bounded_testnet_order_observation",
            "checks": [{"name": "testnet_order_observation", "status": "fail"}],
            "next_steps": ["run bounded observation"],
        }

    def fake_dry_run(config, sync_limit, execute_loop, sleep_seconds):
        calls.append(f"dry:{execute_loop}")
        return {"status": "pass", "order_lifecycle": {"state": "not_attempted", "acceptable": True}}

    def fake_observe(config, cycles, sync_limit, execute_loop, sleep_seconds, continue_on_failure=False):
        calls.append(f"observe:{execute_loop}")
        return {"status": "pass", "cycles_completed": cycles, "failures": 0}

    monkeypatch.setattr(testnet_close_loop, "run_testnet_setup_check", fake_setup)
    monkeypatch.setattr(testnet_close_loop, "run_readiness", fake_readiness)
    monkeypatch.setattr(testnet_close_loop, "run_exchange_health_check", fake_health)
    monkeypatch.setattr(testnet_close_loop, "run_launch_checklist", fake_checklist)
    monkeypatch.setattr(testnet_close_loop, "run_testnet_dry_run", fake_dry_run)
    monkeypatch.setattr(testnet_close_loop, "run_testnet_observation", fake_observe)

    result = testnet_close_loop.run_testnet_close_loop(
        RuntimeConfig(mode="testnet", db_path=str(tmp_path / "kxian.sqlite3"), interval="4h"),
        cycles=6,
        sleep_seconds=0,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "bounded_testnet_confirmation_required"
    assert "dry:True" not in calls
    assert "observe:True" not in calls


def test_testnet_close_loop_blocks_when_autotrade_false_after_confirmation(monkeypatch, tmp_path):
    monkeypatch.setattr(testnet_close_loop, "run_testnet_setup_check", lambda config, timeout_seconds=5.0: {"status": "pass", "checks": []})
    monkeypatch.setattr(testnet_close_loop, "run_readiness", lambda config, storage=None, require_testnet_autotrade=True: {"status": "pass", "checks": []})
    monkeypatch.setattr(testnet_close_loop, "run_exchange_health_check", lambda config, timeout_seconds=5.0: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        testnet_close_loop,
        "run_launch_checklist",
        lambda config, storage=None, target_mode=None: {"status": "blocked", "phase": "ready_for_bounded_testnet_order_observation", "checks": []},
    )
    monkeypatch.setattr(testnet_close_loop, "run_testnet_dry_run", lambda config, sync_limit, execute_loop, sleep_seconds: {"status": "pass"})
    monkeypatch.setattr(
        testnet_close_loop,
        "run_testnet_observation",
        lambda config, cycles, sync_limit, execute_loop, sleep_seconds, continue_on_failure=False: {"status": "pass", "cycles_completed": cycles, "failures": 0},
    )

    result = testnet_close_loop.run_testnet_close_loop(
        RuntimeConfig(mode="testnet", db_path=str(tmp_path / "kxian.sqlite3"), interval="4h", enable_testnet_autotrade=False),
        confirm_bounded_testnet_order=True,
        sleep_seconds=0,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "testnet_autotrade_disabled"


def test_testnet_close_loop_blocks_live_switches_before_observation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        testnet_close_loop,
        "run_testnet_setup_check",
        lambda config, timeout_seconds=5.0: {
            "status": "fail",
            "checks": [{"name": "testnet_closed_loop_scope", "status": "fail"}],
        },
    )
    monkeypatch.setattr(testnet_close_loop, "run_readiness", lambda *args, **kwargs: calls.append("readiness") or {"status": "pass"})
    monkeypatch.setattr(testnet_close_loop, "run_testnet_dry_run", lambda *args, **kwargs: calls.append("dry") or {"status": "pass"})

    result = testnet_close_loop.run_testnet_close_loop(
        RuntimeConfig(
            mode="testnet",
            db_path=str(tmp_path / "kxian.sqlite3"),
            interval="4h",
            allow_live=True,
            enable_testnet_autotrade=True,
        ),
        confirm_bounded_testnet_order=True,
        sleep_seconds=0,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "testnet_setup_blocked"
    assert calls == []


def test_testnet_close_loop_requires_final_ready_phase(monkeypatch, tmp_path):
    checklist_calls = []
    monkeypatch.setattr(testnet_close_loop, "run_testnet_setup_check", lambda config, timeout_seconds=5.0: {"status": "pass", "checks": []})
    monkeypatch.setattr(testnet_close_loop, "run_readiness", lambda config, storage=None, require_testnet_autotrade=True: {"status": "pass", "checks": []})
    monkeypatch.setattr(testnet_close_loop, "run_exchange_health_check", lambda config, timeout_seconds=5.0: {"status": "pass", "checks": []})

    def fake_checklist(config, storage=None, target_mode=None):
        checklist_calls.append(1)
        phase = "ready_for_bounded_testnet_order_observation" if len(checklist_calls) == 1 else "ready_for_bounded_testnet_order_observation"
        return {"status": "pass", "phase": phase, "checks": []}

    monkeypatch.setattr(testnet_close_loop, "run_launch_checklist", fake_checklist)
    monkeypatch.setattr(testnet_close_loop, "run_testnet_dry_run", lambda config, sync_limit, execute_loop, sleep_seconds: {"status": "pass"})
    monkeypatch.setattr(
        testnet_close_loop,
        "run_testnet_observation",
        lambda config, cycles, sync_limit, execute_loop, sleep_seconds, continue_on_failure=False: {"status": "pass", "cycles_completed": cycles, "failures": 0},
    )

    result = testnet_close_loop.run_testnet_close_loop(
        RuntimeConfig(
            mode="testnet",
            db_path=str(tmp_path / "kxian.sqlite3"),
            interval="4h",
            enable_testnet_autotrade=True,
        ),
        confirm_bounded_testnet_order=True,
        sleep_seconds=0,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "final_launch_phase_not_ready"


def test_testnet_close_loop_writes_phase_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(testnet_close_loop, "run_testnet_setup_check", lambda config, timeout_seconds=5.0: {"status": "pass", "checks": []})
    monkeypatch.setattr(testnet_close_loop, "run_readiness", lambda config, storage=None, require_testnet_autotrade=True: {"status": "pass", "checks": []})
    monkeypatch.setattr(testnet_close_loop, "run_exchange_health_check", lambda config, timeout_seconds=5.0: {"status": "pass", "checks": []})
    monkeypatch.setattr(
        testnet_close_loop,
        "run_launch_checklist",
        lambda config, storage=None, target_mode=None: {"status": "pass", "phase": "testnet_observed_ready_for_live_review", "checks": []},
    )
    monkeypatch.setattr(testnet_close_loop, "run_testnet_dry_run", lambda config, sync_limit, execute_loop, sleep_seconds: {"status": "pass"})
    monkeypatch.setattr(
        testnet_close_loop,
        "run_testnet_observation",
        lambda config, cycles, sync_limit, execute_loop, sleep_seconds, continue_on_failure=False: {"status": "pass", "cycles_completed": cycles, "failures": 0},
    )
    evidence_dir = tmp_path / "artifacts"

    result = testnet_close_loop.run_testnet_close_loop(
        RuntimeConfig(
            mode="testnet",
            db_path=str(tmp_path / "kxian.sqlite3"),
            interval="4h",
            enable_testnet_autotrade=True,
            binance_api_key="api-key-value",
            binance_api_secret="secret-value",
        ),
        confirm_bounded_testnet_order=True,
        sleep_seconds=0,
        evidence_dir=str(evidence_dir),
    )

    saved_files = sorted(evidence_dir.glob("*.json"))
    assert result["status"] == "pass"
    assert len(saved_files) >= 8
    saved_text = "\n".join(path.read_text(encoding="utf-8") for path in saved_files)
    assert "api-key-value" not in saved_text
    assert "secret-value" not in saved_text
