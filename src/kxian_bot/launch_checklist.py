from __future__ import annotations

from typing import Any

from kxian_bot.config import RuntimeConfig, expected_live_confirmation
from kxian_bot.readiness import run_readiness
from kxian_bot.storage import SQLiteStorage


def run_launch_checklist(
    config: RuntimeConfig,
    storage: SQLiteStorage | None = None,
    target_mode: str | None = None,
) -> dict[str, Any]:
    storage = storage or SQLiteStorage(config.db_path)
    target = target_mode or (config.mode if config.mode in {"testnet", "live"} else "testnet")
    if target not in {"testnet", "live"}:
        return {
            "status": "blocked",
            "reason": "unsupported_launch_target",
            "target_mode": target,
            "supported_targets": ["testnet", "live"],
        }

    target_config = _target_config(config, target)
    readiness = run_readiness(target_config, storage)
    if target == "testnet":
        return _testnet_checklist(target_config, storage, readiness)
    return _live_checklist(target_config, storage, readiness)


def _testnet_checklist(config: RuntimeConfig, storage: SQLiteStorage, readiness: dict[str, Any]) -> dict[str, Any]:
    profile = storage.active_strategy_profile("testnet", config.exchange, config.symbol, config.interval)
    non_order_observation = storage.latest_testnet_observation(
        config.exchange,
        config.symbol,
        config.interval,
        execute_loop=False,
    )
    order_observation = storage.latest_testnet_observation(
        config.exchange,
        config.symbol,
        config.interval,
        execute_loop=True,
    )
    checks = [
        _readiness_check(readiness),
        _profile_check(profile, require_testnet_promotion=True),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "blocked"
    phase = _testnet_phase(status, non_order_observation, order_observation)
    return {
        "status": status,
        "reason": "testnet_launch_ready" if status == "pass" else "testnet_launch_blocked",
        "phase": phase,
        "target_mode": "testnet",
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "checks": checks,
        "readiness": readiness,
        "profiles": {"testnet": profile},
        "testnet_observation": {
            "non_ordering": non_order_observation,
            "bounded_order": order_observation,
        },
        "next_steps": _testnet_next_steps(status, readiness, profile, non_order_observation, order_observation),
    }


def _live_checklist(config: RuntimeConfig, storage: SQLiteStorage, readiness: dict[str, Any]) -> dict[str, Any]:
    testnet_profile = storage.active_strategy_profile("testnet", config.exchange, config.symbol, config.interval)
    live_profile = storage.active_strategy_profile("live", config.exchange, config.symbol, config.interval)
    non_order_observation = storage.latest_testnet_observation(
        config.exchange,
        config.symbol,
        config.interval,
        execute_loop=False,
    )
    order_observation = storage.latest_testnet_observation(
        config.exchange,
        config.symbol,
        config.interval,
        execute_loop=True,
    )
    checks = [
        _readiness_check(readiness),
        _profile_check(testnet_profile, name="testnet_profile", require_testnet_promotion=True),
        _observation_check(non_order_observation, name="testnet_observation", execute_loop=False),
        _observation_check(order_observation, name="testnet_order_observation", execute_loop=True),
        _live_profile_check(live_profile),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "blocked"
    return {
        "status": status,
        "reason": "live_launch_ready" if status == "pass" else "live_launch_blocked",
        "phase": "ready_for_bounded_live_loop" if status == "pass" else "blocked_before_live",
        "target_mode": "live",
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "live_confirmation_required": expected_live_confirmation(config),
        "checks": checks,
        "readiness": readiness,
        "profiles": {
            "testnet": testnet_profile,
            "live": live_profile,
        },
        "testnet_observation": {
            "non_ordering": non_order_observation,
            "bounded_order": order_observation,
        },
        "next_steps": _live_next_steps(
            readiness,
            testnet_profile,
            live_profile,
            non_order_observation,
            order_observation,
            config,
        ),
    }


def _target_config(config: RuntimeConfig, target_mode: str) -> RuntimeConfig:
    if target_mode == "testnet":
        return config.model_copy(update={"mode": "testnet", "use_testnet": True, "market_data_source": "exchange"})
    return config.model_copy(update={"mode": "live", "use_testnet": False, "market_data_source": "exchange"})


def _readiness_check(readiness: dict[str, Any]) -> dict[str, Any]:
    failed = [
        check["name"]
        for check in readiness.get("checks", [])
        if check.get("status") != "pass"
    ]
    return {
        "name": "readiness",
        "status": "pass" if readiness.get("status") == "pass" else "fail",
        "message": "readiness passes" if readiness.get("status") == "pass" else "readiness has blocking checks",
        "details": {"failed_checks": failed},
    }


def _profile_check(
    profile: dict[str, Any] | None,
    name: str = "testnet_profile",
    require_testnet_promotion: bool = False,
) -> dict[str, Any]:
    if profile is None:
        return {
            "name": name,
            "status": "fail",
            "message": "active strategy profile is missing",
            "details": {"reason": "missing_active_profile"},
        }
    evidence = profile.get("evidence", {}) if isinstance(profile.get("evidence"), dict) else {}
    failures: list[str] = []
    sample_validation = evidence.get("sample_validation")
    if not isinstance(sample_validation, dict) or sample_validation.get("status") != "pass":
        failures.append("missing_passing_sample_validation")
    promotion = evidence.get("promotion")
    if require_testnet_promotion and (not isinstance(promotion, dict) or promotion.get("target_mode") != "testnet"):
        failures.append("missing_testnet_promotion_evidence")
    return {
        "name": name,
        "status": "pass" if not failures else "fail",
        "message": "active strategy profile has required evidence" if not failures else "active strategy profile is not promotable",
        "details": {
            "profile_key": profile.get("profile_key"),
            "failures": failures,
            "sample_validation_status": sample_validation.get("status") if isinstance(sample_validation, dict) else None,
            "promotion_target_mode": promotion.get("target_mode") if isinstance(promotion, dict) else None,
        },
    }


def _live_profile_check(profile: dict[str, Any] | None) -> dict[str, Any]:
    if profile is None:
        return {
            "name": "live_profile",
            "status": "fail",
            "message": "live strategy profile has not been promoted",
            "details": {"reason": "missing_live_profile"},
        }
    evidence = profile.get("evidence", {}) if isinstance(profile.get("evidence"), dict) else {}
    promotion = evidence.get("promotion")
    observation = evidence.get("testnet_observation")
    failures: list[str] = []
    if not isinstance(promotion, dict) or promotion.get("target_mode") != "live":
        failures.append("missing_live_promotion_evidence")
    if not isinstance(observation, dict):
        failures.append("missing_testnet_observation_evidence")
    return {
        "name": "live_profile",
        "status": "pass" if not failures else "fail",
        "message": "live strategy profile is promoted with testnet evidence" if not failures else "live strategy profile is incomplete",
        "details": {
            "profile_key": profile.get("profile_key"),
            "failures": failures,
            "promotion_target_mode": promotion.get("target_mode") if isinstance(promotion, dict) else None,
        },
    }


def _observation_check(observation: dict[str, Any] | None, name: str, execute_loop: bool) -> dict[str, Any]:
    if observation is None:
        return {
            "name": name,
            "status": "fail",
            "message": "testnet observation evidence is missing",
            "details": {"execute_loop": execute_loop, "reason": "missing_testnet_observation"},
        }
    failures: list[str] = []
    if observation.get("status") != "pass":
        failures.append("testnet_observation_not_passed")
    if bool(observation.get("execute_loop")) != execute_loop:
        failures.append("testnet_observation_scope_mismatch")
    return {
        "name": name,
        "status": "pass" if not failures else "fail",
        "message": "testnet observation passed" if not failures else "testnet observation is not acceptable",
        "details": {
            "failures": failures,
            "execute_loop": execute_loop,
            "observation": observation,
        },
    }


def _testnet_phase(
    status: str,
    non_order_observation: dict[str, Any] | None,
    order_observation: dict[str, Any] | None,
) -> str:
    if status != "pass":
        return "blocked_before_testnet"
    if order_observation and order_observation.get("status") == "pass":
        return "testnet_observed_ready_for_live_review"
    if non_order_observation and non_order_observation.get("status") == "pass":
        return "ready_for_bounded_testnet_order_observation"
    return "ready_for_testnet_dry_run"


def _testnet_next_steps(
    status: str,
    readiness: dict[str, Any],
    profile: dict[str, Any] | None,
    non_order_observation: dict[str, Any] | None,
    order_observation: dict[str, Any] | None,
) -> list[str]:
    steps: list[str] = []
    if profile is None:
        steps.append("run kxian-bot promote-profile-to-testnet after the paper profile passes multi-sample validation")
    if readiness.get("status") != "pass":
        steps.extend(readiness.get("next_steps", []))
    if status == "pass" and not non_order_observation:
        steps.append("run kxian-bot testnet-dry-run, then kxian-bot testnet-observe --cycles 6 --sleep-seconds 60")
    if status == "pass" and non_order_observation and non_order_observation.get("status") == "pass" and not order_observation:
        steps.append("run kxian-bot testnet-observe --cycles 6 --sleep-seconds 60 --execute-loop")
    if status == "pass" and order_observation and order_observation.get("status") == "pass":
        steps.append("review testnet fills and promote the profile to live only for a very small order cap")
    return _dedupe(steps)


def _live_next_steps(
    readiness: dict[str, Any],
    testnet_profile: dict[str, Any] | None,
    live_profile: dict[str, Any] | None,
    non_order_observation: dict[str, Any] | None,
    order_observation: dict[str, Any] | None,
    config: RuntimeConfig,
) -> list[str]:
    steps: list[str] = []
    if testnet_profile is None:
        steps.append("promote a passing paper profile to testnet before live review")
    if non_order_observation is None or non_order_observation.get("status") != "pass":
        steps.append("run kxian-bot testnet-observe --cycles 6 --sleep-seconds 60 before live promotion")
    if order_observation is None or order_observation.get("status") != "pass":
        steps.append("run kxian-bot testnet-observe --cycles 6 --sleep-seconds 60 --execute-loop before live promotion")
    if live_profile is None:
        steps.append("run kxian-bot promote-profile-to-live after both testnet observations pass")
    if readiness.get("status") != "pass":
        steps.extend(readiness.get("next_steps", []))
    if not steps:
        steps.append(
            f"run one bounded live loop with KXIAN_LIVE_CONFIRMATION={expected_live_confirmation(config)} and a small KXIAN_MAX_LIVE_ORDER_USDT"
        )
    return _dedupe(steps)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
