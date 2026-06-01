import json

from kxian_bot.config import RuntimeConfig
from kxian_bot.evidence import (
    TESTNET_EVIDENCE_REQUIRED_KEYS,
    build_testnet_evidence,
    redact_for_evidence,
    testnet_evidence_contract_failures as evidence_contract_failures,
    write_evidence,
)
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


def test_redact_for_evidence_redacts_headers_and_signatures_inside_plain_text():
    payload = {
        "message": "X-MBX-APIKEY: abcdefghijklmnop signature=0123456789abcdef0123456789abcdef",
        "details": "Authorization: Bearer secretaccesstokenvalue",
    }

    redacted = redact_for_evidence(payload)
    raw = json.dumps(redacted)

    assert "abcdefghijklmnop" not in raw
    assert "0123456789abcdef0123456789abcdef" not in raw
    assert "secretaccesstokenvalue" not in raw
    assert raw.count("<redacted>") == 3


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

    assert set(evidence) == TESTNET_EVIDENCE_REQUIRED_KEYS
    assert evidence["schema"] == "kxian.testnet.evidence.v1"
    assert evidence["schema_version"] == 1
    assert evidence["scope"]["mode"] == "testnet"
    assert evidence["scope"]["exchange"] == "binance"
    assert evidence["scope"]["symbol"] == "BTCUSDT"
    assert evidence["scope"]["interval"] == "4h"
    assert evidence["credentials"]["present"]["binance_api_key"] is True
    assert evidence["credentials"]["present"]["binance_api_secret"] is True
    assert "api-key-value" not in json.dumps(evidence)
    assert "secret-value" not in json.dumps(evidence)
    assert evidence["acceptance"]["live_ready"] is False
    assert evidence["redaction"]["credential_presence"] == "boolean_only"
    assert evidence_contract_failures(evidence) == []


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


def test_build_testnet_evidence_forces_live_flags_closed(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        interval="4h",
        binance_api_key="api-key-value",
        binance_api_secret="secret-value",
        allow_live=True,
        live_dry_run=False,
        enable_live_autotrade=True,
        live_confirmation="I_UNDERSTAND_LIVE_RISK",
    )

    evidence = build_testnet_evidence(config, storage, command="test")

    assert evidence["scope"]["allow_live"] is False
    assert evidence["scope"]["live_dry_run"] is True
    assert evidence["scope"]["enable_live_autotrade"] is False
    assert evidence["scope"]["live_confirmation_present"] is False
    assert evidence_contract_failures(evidence) == []


def test_testnet_evidence_contract_rejects_extra_keys_and_live_flags(tmp_path):
    storage = SQLiteStorage(tmp_path / "kxian.sqlite3")
    config = RuntimeConfig(
        mode="testnet",
        db_path=str(tmp_path / "kxian.sqlite3"),
        interval="4h",
        binance_api_key="api-key-value",
        binance_api_secret="secret-value",
    )
    evidence = build_testnet_evidence(config, storage, command="test")
    evidence["extra"] = "not allowed"
    evidence["scope"]["allow_live"] = True
    evidence["scope"]["live_dry_run"] = False
    evidence["credentials"]["present"]["binance_api_key"] = "yes"
    evidence["safety"]["live_loop_executed"] = True
    evidence["scope"]["live_confirmation_present"] = True

    failures = evidence_contract_failures(evidence)

    assert "unexpected_top_level_keys:extra" in failures
    assert "allow_live_must_be_false" in failures
    assert "live_dry_run_must_be_true" in failures
    assert "live_confirmation_present_must_be_false" in failures
    assert "credential_presence_must_be_boolean:binance_api_key" in failures
    assert "safety_flag_must_be_false:live_loop_executed" in failures
