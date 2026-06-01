from kxian_bot.bitget_live_gray import approve_bitget_live_gray
from kxian_bot.config import RuntimeConfig
from kxian_bot.storage import SQLiteStorage


SAMPLE_VALIDATION_EVIDENCE = {
    "status": "pass",
    "sample_count": 1,
    "passed_samples": 1,
    "failed_samples": 0,
    "summary": {"total_trade_count": 35, "min_return_pct": 1.0, "min_profit_factor": 1.2},
    "samples": [],
}


def test_approve_bitget_live_gray_writes_live_profile(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    storage = SQLiteStorage(db_path)
    storage.upsert_strategy_profile(
        mode="paper",
        exchange="bitget",
        symbol="BTCUSDT",
        interval="4h",
        strategy="moving_average_cross",
        parameters={"strategy": "moving_average_cross", "short_window": 10, "long_window": 30},
        evidence={"sample_validation": SAMPLE_VALIDATION_EVIDENCE},
        updated_by="test",
    )
    config = RuntimeConfig(
        mode="live",
        exchange="bitget",
        db_path=str(db_path),
        interval="4h",
        use_testnet=False,
        max_live_order_usdt=5,
        live_credentials_confirmed=True,
        bitget_api_key="key",
        bitget_api_secret="secret",
        bitget_api_passphrase="passphrase",
    )

    result = approve_bitget_live_gray(
        config,
        storage,
        updated_by="operator",
        confirmation="LIVE:bitget:BTCUSDT:4h",
    )

    profile = storage.active_strategy_profile("live", "bitget", "BTCUSDT", "4h")
    assert result["status"] == "pass"
    assert result["reason"] == "bitget_live_gray_approved"
    assert result["approval_id"]
    assert result["approved_at"] > 0
    assert profile["evidence"]["bitget_live_gray"]["status"] == "approved"
    assert profile["evidence"]["bitget_live_gray"]["approval_id"] == result["approval_id"]
    assert profile["evidence"]["bitget_live_gray"]["approved_at"] == result["approved_at"]
    assert profile["evidence"]["bitget_live_gray"]["max_order_usdt"] == 5


def test_approve_bitget_live_gray_requires_exact_confirmation(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    config = RuntimeConfig(
        mode="live",
        exchange="bitget",
        db_path=str(db_path),
        interval="4h",
        use_testnet=False,
        max_live_order_usdt=5,
        live_credentials_confirmed=True,
        bitget_api_key="key",
        bitget_api_secret="secret",
        bitget_api_passphrase="passphrase",
    )

    result = approve_bitget_live_gray(config, SQLiteStorage(db_path), confirmation="wrong")

    assert result["status"] == "blocked"
    assert result["reason"] == "bitget_live_confirmation_required"
    assert result["required_confirmation"] == "LIVE:bitget:BTCUSDT:4h"


def test_approve_bitget_live_gray_blocks_above_5u(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    config = RuntimeConfig(
        mode="live",
        exchange="bitget",
        db_path=str(db_path),
        interval="4h",
        use_testnet=False,
        max_live_order_usdt=6,
        live_credentials_confirmed=True,
        bitget_api_key="key",
        bitget_api_secret="secret",
        bitget_api_passphrase="passphrase",
    )

    result = approve_bitget_live_gray(config, SQLiteStorage(db_path), confirmation="LIVE:bitget:BTCUSDT:4h")

    assert result["status"] == "blocked"
    assert result["reason"] == "bitget_live_canary_limit_exceeded"


def test_approve_bitget_live_gray_requires_live_mode_credentials_and_confirmation(tmp_path):
    db_path = tmp_path / "kxian.sqlite3"
    config = RuntimeConfig(
        mode="paper",
        exchange="bitget",
        db_path=str(db_path),
        interval="4h",
        use_testnet=False,
        max_live_order_usdt=5,
    )

    result = approve_bitget_live_gray(config, SQLiteStorage(db_path), confirmation="wrong")

    assert result["status"] == "blocked"
    assert "bitget_live_mode_required" in result["failures"]
    assert "missing_bitget_api_key" in result["failures"]
    assert "missing_bitget_api_secret" in result["failures"]
    assert "missing_bitget_api_passphrase" in result["failures"]
    assert "bitget_live_credentials_not_confirmed" in result["failures"]
    assert "bitget_live_confirmation_required" in result["failures"]
    assert "LIVE:bitget:BTCUSDT:4h" == result["required_confirmation"]
