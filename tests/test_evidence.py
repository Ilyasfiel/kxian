import json

from kxian_bot.config import RuntimeConfig
from kxian_bot.evidence import build_testnet_evidence, redact_for_evidence, write_evidence
from kxian_bot.storage import SQLiteStorage


def test_redact_for_evidence_recursively_keeps_credential_booleans():
    payload = {
        "credentials": {
            "present": {"binance_api_key": True, "binance_api_secret": False},
            "raw": {"binance_api_key": "api-key-value", "binance_api_secret": "secret-value"},
        },
        "nested": [{"token": "token-value", "safe": "ok"}],
    }

    redacted = redact_for_evidence(payload)

    assert redacted["credentials"]["present"]["binance_api_key"] is True
    assert redacted["credentials"]["present"]["binance_api_secret"] is False
    assert redacted["credentials"]["raw"]["binance_api_key"] == "<redacted>"
    assert redacted["credentials"]["raw"]["binance_api_secret"] == "<redacted>"
    assert redacted["nested"][0]["token"] == "<redacted>"
    assert "api-key-value" not in json.dumps(redacted)
    assert "secret-value" not in json.dumps(redacted)


def test_redact_for_evidence_redacts_sensitive_values_inside_plain_text():
    payload = {
        "message": "request failed with secret-value and api-key-value",
        "reason": "token-value is inside a normal field",
    }

    redacted = redact_for_evidence(payload, sensitive_values=["secret-value", "api-key-value", "token-value"])
    raw = json.dumps(redacted)

    assert "secret-value" not in raw
    assert "api-key-value" not in raw
    assert "token-value" not in raw
    assert redacted["message"].count("<redacted>") == 2


def test_write_evidence_creates_redacted_json(tmp_path):
    output_path = tmp_path / "artifacts" / "evidence.json"

    write_evidence(output_path, {"api_key": "api-key-value", "result": {"status": "pass"}})

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["api_key"] == "<redacted>"
    assert saved["result"]["status"] == "pass"
    assert "api-key-value" not in output_path.read_text(encoding="utf-8")


def test_build_testnet_evidence_uses_fixed_scope_and_no_secret_values(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    config = RuntimeConfig(
        mode="paper",
        exchange="okx",
        symbol="ETHUSDT",
        interval="1m",
        db_path=str(tmp_path / "kxian.sqlite3"),
        binance_api_key="api-key-value",
        binance_api_secret="secret-value",
    )

    evidence = build_testnet_evidence(config, storage, command="test")

    assert evidence["scope"]["mode"] == "testnet"
    assert evidence["scope"]["exchange"] == "binance"
    assert evidence["scope"]["symbol"] == "BTCUSDT"
    assert evidence["scope"]["interval"] == "4h"
    assert evidence["credentials"]["present"]["binance_api_key"] is True
    assert evidence["credentials"]["present"]["binance_api_secret"] is True
    assert "api-key-value" not in json.dumps(evidence)
    assert "secret-value" not in json.dumps(evidence)


def test_build_testnet_evidence_redacts_config_secret_values_in_messages(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        interval="4h",
        binance_api_key="api-key-value",
        binance_api_secret="secret-value",
    )

    evidence = build_testnet_evidence(
        config,
        storage,
        command="test",
        result={"status": "fail", "message": "secret-value leaked in exchange message"},
    )
    raw = json.dumps(evidence)

    assert "secret-value" not in raw
    assert evidence["result"]["message"] == "<redacted> leaked in exchange message"
