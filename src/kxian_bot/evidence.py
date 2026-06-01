from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from kxian_bot.config import RuntimeConfig
from kxian_bot.storage import SQLiteStorage
from kxian_bot.testnet_dry_run import exchange_credential_status


SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "passphrase",
    "password",
    "token",
)
REDACTED = "<redacted>"


def redact_for_evidence(value: Any, sensitive_values: list[str] | None = None) -> Any:
    sensitive_values = [item for item in (sensitive_values or []) if item]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if _is_sensitive_key(key_text) and not isinstance(item, bool):
                output[key] = _redacted_value(item)
            else:
                output[key] = redact_for_evidence(item, sensitive_values)
        return output
    if isinstance(value, list):
        return [redact_for_evidence(item, sensitive_values) for item in value]
    if isinstance(value, tuple):
        return [redact_for_evidence(item, sensitive_values) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_text(value, sensitive_values)
    return value


def write_evidence(path: str | Path, payload: dict[str, Any], sensitive_values: list[str] | None = None) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    redacted = redact_for_evidence(payload, sensitive_values=sensitive_values)
    output_path.write_text(json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def build_testnet_evidence(
    config: RuntimeConfig,
    storage: SQLiteStorage,
    *,
    command: str,
    result: dict[str, Any] | None = None,
    launch_checklist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    testnet_config = _testnet_config(config)
    _, credential_presence = exchange_credential_status(testnet_config)
    sensitive_values = _config_sensitive_values(testnet_config)
    profile = storage.active_strategy_profile(
        "testnet",
        testnet_config.exchange,
        testnet_config.symbol,
        testnet_config.interval,
    )
    non_ordering = storage.latest_testnet_observation(
        testnet_config.exchange,
        testnet_config.symbol,
        testnet_config.interval,
        execute_loop=False,
    )
    bounded_order = storage.latest_testnet_observation(
        testnet_config.exchange,
        testnet_config.symbol,
        testnet_config.interval,
        execute_loop=True,
    )
    profile_evidence = profile.get("evidence", {}) if isinstance(profile, dict) else {}
    return redact_for_evidence(
        {
            "schema": "kxian.testnet.evidence.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "command": command,
            "scope": _config_scope(testnet_config),
            "credentials": {"required": True, "present": credential_presence},
            "profile": _profile_evidence_summary(profile, profile_evidence),
            "observations": {
                "non_ordering": non_ordering,
                "bounded_order": bounded_order,
            },
            "launch_checklist": launch_checklist,
            "result": result,
            "safety": {
                "live_promote_executed": False,
                "live_loop_executed": False,
                "live_checklist_required": False,
            },
        },
        sensitive_values=sensitive_values,
    )


def _is_sensitive_key(key: str) -> bool:
    return any(part in key for part in SENSITIVE_KEY_PARTS)


def _redacted_value(value: Any) -> str:
    if value in (None, "", False):
        return ""
    return REDACTED


def _redact_sensitive_text(text: str, sensitive_values: list[str]) -> str:
    redacted = text
    for secret in sorted(set(sensitive_values), key=len, reverse=True):
        if secret and secret in redacted:
            redacted = redacted.replace(secret, REDACTED)
    return redacted


def _config_sensitive_values(config: RuntimeConfig) -> list[str]:
    return [
        config.binance_api_key,
        config.binance_api_secret,
        config.okx_api_key,
        config.okx_api_secret,
        config.okx_api_passphrase,
    ]


def _testnet_config(config: RuntimeConfig) -> RuntimeConfig:
    return config.model_copy(
        update={
            "mode": "testnet",
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "use_testnet": True,
            "market_data_source": "exchange",
        }
    )


def _config_scope(config: RuntimeConfig) -> dict[str, Any]:
    return {
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "use_testnet": config.use_testnet,
        "market_data_source": config.market_data_source,
        "enable_testnet_autotrade": config.enable_testnet_autotrade,
        "allow_live": config.allow_live,
        "live_dry_run": config.live_dry_run,
        "enable_live_autotrade": config.enable_live_autotrade,
        "live_confirmation_present": bool(config.live_confirmation),
    }


def _profile_evidence_summary(profile: dict[str, Any] | None, evidence: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {"status": "missing", "profile_key": "testnet:binance:BTCUSDT:4h"}
    evidence = evidence if isinstance(evidence, dict) else {}
    gates = evidence.get("gates", {}) if isinstance(evidence.get("gates"), dict) else {}
    validation_run_ids: dict[str, str] = {}
    for name in ("strategy_gate", "stress_gate", "walk_forward_gate"):
        gate = gates.get(name)
        if isinstance(gate, dict) and gate.get("run_id"):
            validation_run_ids[name] = str(gate["run_id"])
    promotion = evidence.get("promotion") if isinstance(evidence.get("promotion"), dict) else {}
    sample_validation = evidence.get("sample_validation") if isinstance(evidence.get("sample_validation"), dict) else {}
    return {
        "status": "active",
        "profile_key": profile.get("profile_key"),
        "updated_at": profile.get("updated_at"),
        "updated_by": profile.get("updated_by"),
        "strategy": profile.get("strategy"),
        "parameters": profile.get("parameters", {}),
        "sample_validation": {
            "status": sample_validation.get("status"),
            "sample_count": sample_validation.get("sample_count"),
            "passed_samples": sample_validation.get("passed_samples"),
            "failed_samples": sample_validation.get("failed_samples"),
        },
        "promotion": {
            "source_profile_key": promotion.get("source_profile_key"),
            "target_mode": promotion.get("target_mode"),
        },
        "validation_run_ids": validation_run_ids,
    }
