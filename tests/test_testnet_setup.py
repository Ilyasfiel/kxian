from kxian_bot.config import RuntimeConfig
from kxian_bot.testnet_setup import run_testnet_setup_check


def test_testnet_setup_check_reports_missing_credentials_without_secret_values(monkeypatch, tmp_path):
    config = RuntimeConfig(
        mode="paper",
        db_path=str(tmp_path / "kxian.sqlite3"),
        binance_api_key="",
        binance_api_secret="",
    )
    monkeypatch.setattr("kxian_bot.testnet_setup.run_exchange_health_check", lambda config, timeout_seconds=5.0: {"status": "pass", "checks": [], "next_steps": []})
    monkeypatch.setattr("kxian_bot.testnet_setup.run_readiness", lambda config: {"status": "fail", "checks": [], "next_steps": ["set sandbox API credentials for the selected exchange"]})
    monkeypatch.setattr("kxian_bot.testnet_setup.run_launch_checklist", lambda config, target_mode=None: {"status": "blocked", "reason": "testnet_launch_blocked", "phase": "blocked_before_testnet", "checks": [], "next_steps": ["set sandbox API credentials for the selected exchange"]})

    result = run_testnet_setup_check(config)

    assert result["status"] == "fail"
    assert result["mode"] == "testnet"
    assert result["credentials"]["failures"] == ["missing_binance_api_key", "missing_binance_api_secret"]
    assert result["credentials"]["present"]["binance_api_key"] is False
    assert "put Binance Spot Testnet" in result["next_steps"][0]
    assert "super-secret-value" not in str(result)
    assert "api-key-value" not in str(result)


def test_testnet_setup_check_passes_and_points_to_dry_run(monkeypatch, tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        binance_api_key="api-key-value",
        binance_api_secret="super-secret-value",
        enable_testnet_autotrade=True,
    )
    monkeypatch.setattr("kxian_bot.testnet_setup.run_exchange_health_check", lambda config, timeout_seconds=5.0: {"status": "pass", "checks": [], "next_steps": []})
    monkeypatch.setattr("kxian_bot.testnet_setup.run_readiness", lambda config: {"status": "pass", "checks": [], "next_steps": []})
    monkeypatch.setattr("kxian_bot.testnet_setup.run_launch_checklist", lambda config, target_mode=None: {"status": "pass", "reason": "testnet_launch_ready", "phase": "ready_for_testnet_dry_run", "checks": [], "next_steps": []})

    result = run_testnet_setup_check(config)

    assert result["status"] == "pass"
    assert result["credentials"]["present"]["binance_api_key"] is True
    assert result["credentials"]["present"]["binance_api_secret"] is True
    assert result["next_steps"] == ["run kxian-bot testnet-dry-run before any longer testnet loop"]
    assert "super-secret-value" not in str(result)
    assert "api-key-value" not in str(result)


def test_testnet_setup_check_includes_exchange_health_next_steps(monkeypatch, tmp_path):
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        binance_api_key="key",
        binance_api_secret="secret",
        enable_testnet_autotrade=True,
    )
    monkeypatch.setattr(
        "kxian_bot.testnet_setup.run_exchange_health_check",
        lambda config, timeout_seconds=5.0: {
            "status": "fail",
            "checks": [{"name": "public_market_data", "status": "fail"}],
            "next_steps": ["configure a stable proxy or deploy the bot on a network with exchange API access"],
        },
    )
    monkeypatch.setattr("kxian_bot.testnet_setup.run_readiness", lambda config: {"status": "pass", "checks": [], "next_steps": []})
    monkeypatch.setattr("kxian_bot.testnet_setup.run_launch_checklist", lambda config, target_mode=None: {"status": "pass", "reason": "testnet_launch_ready", "phase": "ready_for_testnet_dry_run", "checks": [], "next_steps": []})

    result = run_testnet_setup_check(config)

    assert result["status"] == "fail"
    assert result["checks"][2]["name"] == "exchange_health"
    assert result["checks"][2]["details"]["failed_checks"] == ["public_market_data"]
    assert "configure a stable proxy" in result["next_steps"][0]
