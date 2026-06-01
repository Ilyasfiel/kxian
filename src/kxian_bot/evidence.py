from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from copy import deepcopy
from typing import Any

from kxian_bot.config import RuntimeConfig
from kxian_bot.storage import SQLiteStorage
from kxian_bot.testnet_dry_run import exchange_credential_status


TESTNET_EVIDENCE_SCHEMA = "kxian.testnet.evidence.v1"
TESTNET_EVIDENCE_SCHEMA_VERSION = 1
TESTNET_EVIDENCE_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "schema_version",
        "generated_at",
        "command",
        "scope",
        "credentials",
        "profile",
        "observations",
        "launch_checklist",
        "result",
        "audit",
        "acceptance",
        "redaction",
        "safety",
    }
)
TESTNET_EVIDENCE_REQUIRED_KEYS = TESTNET_EVIDENCE_TOP_LEVEL_KEYS
TESTNET_SCOPE = {
    "mode": "testnet",
    "exchange": "binance",
    "symbol": "BTCUSDT",
    "interval": "4h",
    "use_testnet": True,
}
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "headers",
    "signature",
    "secret",
    "passphrase",
    "password",
    "token",
)
REDACTED = "<redacted>"
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)(x-mbx-apikey\s*[:=]\s*)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)(signature\s*[:=]\s*)[A-Fa-f0-9]{16,}"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)(api[_-]?secret\s*[:=]\s*)[A-Za-z0-9._~+/=-]{8,}"),
)


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
    launch_phase = launch_checklist.get("phase") if isinstance(launch_checklist, dict) else None
    launch_status = launch_checklist.get("status") if isinstance(launch_checklist, dict) else None
    audit = {
        "git_commit": _current_git_commit(),
        "dirty_worktree": _git_dirty_worktree(),
        "command_context": _audit_command_context(
            command=command,
            config=testnet_config,
            profile=profile,
            result=result,
            launch_checklist=launch_checklist,
        ),
    }
    evidence = redact_for_evidence(
        {
            "schema": TESTNET_EVIDENCE_SCHEMA,
            "schema_version": TESTNET_EVIDENCE_SCHEMA_VERSION,
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
            "audit": audit,
            "acceptance": {
                "required_status": "pass",
                "required_phase": "testnet_observed_ready_for_live_review",
                "status": launch_status,
                "phase": launch_phase,
                "ready_for_live_review": launch_status == "pass" and launch_phase == "testnet_observed_ready_for_live_review",
                "live_ready": False,
            },
            "redaction": {
                "credential_values": "redacted",
                "credential_presence": "boolean_only",
                "sensitive_headers": "redacted",
                "signatures": "redacted",
            },
            "safety": {
                "live_promote_executed": False,
                "live_loop_executed": False,
                "live_checklist_required": False,
                "production_credentials_allowed": False,
            },
        },
        sensitive_values=sensitive_values,
    )
    validation_failures = _testnet_evidence_contract_failures(evidence, require_audit_integrity=False)
    audit = evidence.get("audit")
    if isinstance(audit, dict):
        audit["schema_validation"] = {
            "status": "pass" if not validation_failures else "fail",
            "validator": "testnet_evidence_contract_failures",
            "failure_count": len(validation_failures),
            "failures": validation_failures,
        }
    if isinstance(audit, dict):
        audit["content_sha256"] = _evidence_content_hash(evidence)
    return evidence


def testnet_evidence_contract_failures(evidence: dict[str, Any]) -> list[str]:
    return _testnet_evidence_contract_failures(evidence, require_audit_integrity=True)


def _testnet_evidence_contract_failures(evidence: dict[str, Any], *, require_audit_integrity: bool) -> list[str]:
    failures: list[str] = []
    keys = set(evidence)
    missing = TESTNET_EVIDENCE_REQUIRED_KEYS - keys
    extra = keys - TESTNET_EVIDENCE_TOP_LEVEL_KEYS
    if missing:
        failures.append(f"missing_top_level_keys:{','.join(sorted(missing))}")
    if extra:
        failures.append(f"unexpected_top_level_keys:{','.join(sorted(extra))}")
    if evidence.get("schema") != TESTNET_EVIDENCE_SCHEMA:
        failures.append("invalid_schema")
    if evidence.get("schema_version") != TESTNET_EVIDENCE_SCHEMA_VERSION:
        failures.append("invalid_schema_version")
    command = evidence.get("command")
    if not isinstance(command, str) or not command:
        failures.append("invalid_command")
    audit = evidence.get("audit")
    if not isinstance(audit, dict):
        failures.append("missing_audit")
    else:
        git_commit = audit.get("git_commit")
        if not isinstance(git_commit, str) or (git_commit != "unknown" and not re.fullmatch(r"[0-9a-f]{40}", git_commit)):
            failures.append("invalid_audit_git_commit")
        dirty_worktree = audit.get("dirty_worktree")
        if dirty_worktree not in {True, False, "unknown"}:
            failures.append("invalid_audit_dirty_worktree")
        command_context = audit.get("command_context")
        if not isinstance(command_context, dict):
            failures.append("missing_audit_command_context")
        else:
            if not isinstance(command_context.get("command"), str) or not command_context.get("command"):
                failures.append("invalid_audit_command")
            elif command_context.get("command") != command:
                failures.append("invalid_audit_command_context:command")
            if command_context.get("profile_key") != "testnet:binance:BTCUSDT:4h":
                failures.append("invalid_audit_profile_key")
            for key, expected in TESTNET_SCOPE.items():
                if command_context.get(key) != expected:
                    failures.append(f"invalid_audit_command_context:{key}")
        schema_validation = audit.get("schema_validation")
        if require_audit_integrity and schema_validation is None:
            failures.append("missing_audit_schema_validation")
        elif require_audit_integrity and not isinstance(schema_validation, dict):
            failures.append("invalid_audit_schema_validation")
        elif isinstance(schema_validation, dict):
            schema_shape_valid = True
            if schema_validation.get("validator") != "testnet_evidence_contract_failures":
                failures.append("invalid_audit_schema_validator")
                schema_shape_valid = False
            if schema_validation.get("status") not in {"pass", "fail"}:
                failures.append("invalid_audit_schema_validation_status")
                schema_shape_valid = False
            if not isinstance(schema_validation.get("failure_count"), int) or schema_validation["failure_count"] < 0:
                failures.append("invalid_audit_schema_failure_count")
                schema_shape_valid = False
            failures_list = schema_validation.get("failures")
            if not isinstance(failures_list, list) or any(not isinstance(item, str) for item in failures_list):
                failures.append("invalid_audit_schema_failures")
                schema_shape_valid = False
            elif schema_validation.get("status") == "pass" and (schema_validation.get("failure_count") != 0 or failures_list):
                failures.append("invalid_audit_schema_validation_pass_mismatch")
                schema_shape_valid = False
            elif schema_validation.get("status") == "fail" and (schema_validation.get("failure_count", 0) <= 0 or not failures_list):
                failures.append("invalid_audit_schema_validation_fail_mismatch")
                schema_shape_valid = False
            if require_audit_integrity and schema_shape_valid:
                expected_failures = _testnet_evidence_contract_failures(evidence, require_audit_integrity=False)
                expected_status = "pass" if not expected_failures else "fail"
                if (
                    schema_validation.get("status") != expected_status
                    or schema_validation.get("failure_count") != len(expected_failures)
                    or failures_list != expected_failures
                ):
                    failures.append("invalid_audit_schema_validation_current_mismatch")
        elif schema_validation is not None:
            if not isinstance(schema_validation, dict):
                failures.append("invalid_audit_schema_validation")
        content_sha256 = audit.get("content_sha256")
        if require_audit_integrity and content_sha256 is None:
            failures.append("missing_audit_content_sha256")
        elif content_sha256 is not None:
            if not isinstance(content_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
                failures.append("invalid_audit_content_sha256")
            elif content_sha256 != _evidence_content_hash(evidence):
                failures.append("invalid_audit_content_sha256_mismatch")
    scope = evidence.get("scope")
    if not isinstance(scope, dict):
        failures.append("missing_scope")
    else:
        for key, expected in TESTNET_SCOPE.items():
            if scope.get(key) != expected:
                failures.append(f"invalid_scope:{key}")
        if scope.get("allow_live") is not False:
            failures.append("allow_live_must_be_false")
        if scope.get("live_dry_run") is not True:
            failures.append("live_dry_run_must_be_true")
        if scope.get("enable_live_autotrade") is not False:
            failures.append("enable_live_autotrade_must_be_false")
        if scope.get("live_confirmation_present") is not False:
            failures.append("live_confirmation_present_must_be_false")
    credentials = evidence.get("credentials")
    if not isinstance(credentials, dict) or not isinstance(credentials.get("present"), dict):
        failures.append("invalid_credentials")
    else:
        for key, value in credentials["present"].items():
            if not isinstance(value, bool):
                failures.append(f"credential_presence_must_be_boolean:{key}")
    safety = evidence.get("safety")
    if not isinstance(safety, dict):
        failures.append("missing_safety")
    else:
        for key, value in safety.items():
            if value is not False:
                failures.append(f"safety_flag_must_be_false:{key}")
    acceptance = evidence.get("acceptance")
    if not isinstance(acceptance, dict):
        failures.append("missing_acceptance")
    elif acceptance.get("live_ready") is not False:
        failures.append("acceptance_live_ready_must_be_false")
    return failures


testnet_evidence_contract_failures.__test__ = False


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
    for pattern in SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
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
            "allow_live": False,
            "live_dry_run": True,
            "enable_live_autotrade": False,
            "live_confirmation": "",
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


def _audit_command_context(
    *,
    command: str,
    config: RuntimeConfig,
    profile: dict[str, Any] | None,
    result: dict[str, Any] | None,
    launch_checklist: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "command": command,
        "profile_key": (profile or {}).get("profile_key") or "testnet:binance:BTCUSDT:4h",
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "use_testnet": config.use_testnet,
        "result_status": result.get("status") if isinstance(result, dict) else None,
        "result_reason": result.get("reason") if isinstance(result, dict) else None,
        "launch_checklist_status": launch_checklist.get("status") if isinstance(launch_checklist, dict) else None,
        "launch_checklist_phase": launch_checklist.get("phase") if isinstance(launch_checklist, dict) else None,
    }


def _current_git_commit() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _git_dirty_worktree() -> bool | str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return bool(completed.stdout.strip())


def _evidence_content_hash(evidence: dict[str, Any]) -> str:
    payload = deepcopy(evidence)
    audit = payload.get("audit")
    if isinstance(audit, dict):
        audit = dict(audit)
        audit.pop("content_sha256", None)
        payload["audit"] = audit
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
