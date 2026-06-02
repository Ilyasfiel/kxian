from __future__ import annotations

from typing import Any

from kxian_bot.config import RuntimeConfig, expected_live_confirmation
from kxian_bot.readiness import run_readiness
from kxian_bot.storage import SQLiteStorage
from kxian_bot.strategies.factory import RESEARCH_ONLY_STRATEGIES
from kxian_bot.testnet_scope import (
    bitget_live_gray_next_steps,
    bitget_live_gray_scope_failures,
    has_unacceptable_order_lifecycle,
    testnet_closed_loop_next_steps,
    testnet_closed_loop_scope_failures,
    testnet_observation_failures,
)


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
    readiness = run_readiness(
        target_config,
        storage,
        require_testnet_autotrade=target != "testnet",
    )
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
    prerequisite_checks = [
        _testnet_closed_loop_scope_check(config, require_autotrade=False),
        _readiness_check(readiness),
        _profile_check(profile, require_testnet_promotion=True),
    ]
    checks = [
        *prerequisite_checks,
        _testnet_bounded_autotrade_check(config),
        _observation_check(non_order_observation, name="testnet_observation", execute_loop=False),
        _observation_check(order_observation, name="testnet_order_observation", execute_loop=True),
    ]
    cleanup_check = _observation_cleanup_check(non_order_observation, order_observation)
    checks = [*checks, cleanup_check]
    prerequisite_status = "pass" if all(check["status"] == "pass" for check in prerequisite_checks) else "blocked"
    status = "pass" if all(check["status"] == "pass" for check in checks) else "blocked"
    phase = _testnet_phase(
        prerequisite_status,
        non_order_observation,
        order_observation,
        bounded_autotrade_ready=config.enable_testnet_autotrade,
    )
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
        "next_steps": _testnet_next_steps(config, prerequisite_status, readiness, profile, non_order_observation, order_observation),
    }


def _live_checklist(config: RuntimeConfig, storage: SQLiteStorage, readiness: dict[str, Any]) -> dict[str, Any]:
    if config.exchange == "bitget":
        return _bitget_live_checklist(config, storage, readiness)

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


def _bitget_live_checklist(config: RuntimeConfig, storage: SQLiteStorage, readiness: dict[str, Any]) -> dict[str, Any]:
    live_profile = storage.active_strategy_profile("live", config.exchange, config.symbol, config.interval)
    approval = _bitget_live_gray_evidence(live_profile)
    latest_order = storage.latest_exchange_order(
        "live",
        config.exchange,
        config.symbol,
        created_after=_bitget_approval_time(approval),
    )
    open_orders = storage.list_open_exchange_orders("live", config.exchange, config.symbol)
    checks = [
        _readiness_check(readiness),
        _bitget_live_scope_check(config),
        _bitget_live_profile_check(live_profile),
        _bitget_canary_limit_check(config),
        _bitget_canary_order_check(latest_order),
        _bitget_open_order_cleanup_check(open_orders),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "blocked"
    return {
        "status": status,
        "reason": "bitget_live_launch_ready" if status == "pass" else "bitget_live_launch_blocked",
        "phase": "ready_for_bounded_live_loop" if status == "pass" else "blocked_before_bitget_live_canary",
        "target_mode": "live",
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "live_confirmation_required": expected_live_confirmation(config),
        "checks": checks,
        "readiness": readiness,
        "profiles": {"live": live_profile},
        "approval": {
            "approval_id": approval.get("approval_id") if isinstance(approval, dict) else None,
            "approved_at": approval.get("approved_at") if isinstance(approval, dict) else None,
        },
        "live_canary": {
            "latest_order": latest_order,
            "open_orders": open_orders,
        },
        "next_steps": _bitget_live_next_steps(config, readiness, live_profile, latest_order, open_orders),
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


def _testnet_closed_loop_scope_check(config: RuntimeConfig, *, require_autotrade: bool = True) -> dict[str, Any]:
    failures = testnet_closed_loop_scope_failures(config, require_autotrade=require_autotrade)
    return {
        "name": "testnet_closed_loop_scope",
        "status": "pass" if not failures else "fail",
        "message": "testnet closed-loop scope is fixed" if not failures else "testnet closed-loop scope is not fixed",
        "details": {"failures": failures},
    }


def _testnet_bounded_autotrade_check(config: RuntimeConfig) -> dict[str, Any]:
    failures = []
    if not config.enable_testnet_autotrade:
        failures.append("testnet_autotrade_disabled")
    return {
        "name": "testnet_bounded_autotrade",
        "status": "pass" if not failures else "fail",
        "message": (
            "testnet bounded autotrade is enabled"
            if not failures
            else "testnet bounded autotrade must be enabled before --execute-loop observation"
        ),
        "details": {
            "failures": failures,
            "enable_testnet_autotrade": config.enable_testnet_autotrade,
        },
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
    if _profile_is_research_only(profile):
        failures.append("research_only_strategy_not_promotable")
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
            "strategy": profile.get("strategy"),
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
    if _profile_is_research_only(profile):
        failures.append("research_only_strategy_not_promotable")
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
            "strategy": profile.get("strategy"),
            "promotion_target_mode": promotion.get("target_mode") if isinstance(promotion, dict) else None,
        },
    }


def _bitget_live_scope_check(config: RuntimeConfig) -> dict[str, Any]:
    failures = bitget_live_gray_scope_failures(config)
    return {
        "name": "bitget_live_gray_scope",
        "status": "pass" if not failures else "fail",
        "message": "Bitget live gray scope is confirmed" if not failures else "Bitget live gray scope is blocked",
        "details": {
            "failures": failures,
            "mode": config.mode,
            "exchange": config.exchange,
            "symbol": config.symbol,
            "interval": config.interval,
            "use_testnet": config.use_testnet,
            "live_confirmation_required": expected_live_confirmation(config),
        },
    }


def _bitget_live_profile_check(profile: dict[str, Any] | None) -> dict[str, Any]:
    if profile is None:
        return {
            "name": "bitget_live_profile",
            "status": "fail",
            "message": "Bitget live strategy profile is missing",
            "details": {"reason": "missing_live_profile"},
        }
    evidence = profile.get("evidence", {}) if isinstance(profile.get("evidence"), dict) else {}
    sample_validation = evidence.get("sample_validation")
    failures: list[str] = []
    if _profile_is_research_only(profile):
        failures.append("research_only_strategy_not_promotable")
    if not isinstance(sample_validation, dict) or sample_validation.get("status") != "pass":
        failures.append("missing_passing_sample_validation")
    live_gray = _bitget_live_gray_evidence(profile)
    if not isinstance(live_gray, dict) or live_gray.get("status") != "approved":
        failures.append("missing_bitget_live_gray_approval")
    if _bitget_approval_time(live_gray) is None:
        failures.append("missing_bitget_live_gray_approval_time")
    return {
        "name": "bitget_live_profile",
        "status": "pass" if not failures else "fail",
        "message": "Bitget live profile has required gray evidence" if not failures else "Bitget live profile is incomplete",
        "details": {
            "profile_key": profile.get("profile_key"),
            "failures": failures,
            "strategy": profile.get("strategy"),
            "sample_validation_status": sample_validation.get("status") if isinstance(sample_validation, dict) else None,
            "bitget_live_gray_status": live_gray.get("status") if isinstance(live_gray, dict) else None,
        },
    }


def _profile_is_research_only(profile: dict[str, Any]) -> bool:
    parameters = profile.get("parameters", {}) if isinstance(profile.get("parameters"), dict) else {}
    strategy = str(profile.get("strategy") or parameters.get("strategy") or "")
    return strategy in RESEARCH_ONLY_STRATEGIES or parameters.get("research_only") is True


def _bitget_live_gray_evidence(profile: dict[str, Any] | None) -> dict[str, Any]:
    if profile is None:
        return {}
    evidence = profile.get("evidence", {}) if isinstance(profile.get("evidence"), dict) else {}
    live_gray = evidence.get("bitget_live_gray")
    return live_gray if isinstance(live_gray, dict) else {}


def _bitget_approval_time(live_gray: dict[str, Any]) -> float | None:
    approved_at = live_gray.get("approved_at")
    try:
        return float(approved_at) if approved_at is not None else None
    except (TypeError, ValueError):
        return None


def _bitget_canary_limit_check(config: RuntimeConfig) -> dict[str, Any]:
    failures = []
    if config.max_live_order_usdt > 5:
        failures.append("bitget_live_canary_limit_exceeded")
    return {
        "name": "bitget_live_canary_limit",
        "status": "pass" if not failures else "fail",
        "message": "Bitget live canary is limited to 5U" if not failures else "Bitget live canary limit is too high",
        "details": {
            "failures": failures,
            "max_live_order_usdt": config.max_live_order_usdt,
            "max_bitget_canary_order_usdt": 5,
        },
    }


def _bitget_canary_order_check(order: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    status = str((order or {}).get("status") or "")
    reason = str((order or {}).get("reason") or "")
    safe_rejections = {
        "no_signal",
        "no_new_candle",
        "position_already_open",
        "no_size",
        "cooldown_active",
        "daily_trade_limit",
        "daily_loss_limit",
        "live_order_notional_exceeds_limit",
        "exchange_rule_min_notional",
        "exchange_rule_min_quantity",
        "exchange_insufficient_balance",
    }
    if order is None:
        failures.append("missing_bitget_live_canary_order")
    elif status in {"submitted", "partially_filled"}:
        failures.append("bitget_live_canary_order_still_open")
    elif status == "rejected" and reason not in safe_rejections:
        failures.append("bitget_live_canary_order_rejected_unsafely")
    elif status not in {"filled", "canceled", "rejected"}:
        failures.append("bitget_live_canary_order_status_unknown")
    return {
        "name": "bitget_live_canary_order",
        "status": "pass" if not failures else "fail",
        "message": "Bitget live canary order lifecycle is acceptable" if not failures else "Bitget live canary order lifecycle is blocked",
        "details": {
            "failures": failures,
            "latest_order": order,
        },
    }


def _bitget_open_order_cleanup_check(open_orders: list[dict[str, Any]]) -> dict[str, Any]:
    failures = ["bitget_live_open_orders_require_cleanup"] if open_orders else []
    return {
        "name": "bitget_live_open_orders",
        "status": "pass" if not failures else "fail",
        "message": "Bitget live open orders are clean" if not failures else "Bitget live open orders require cleanup",
        "details": {
            "failures": failures,
            "open_order_count": len(open_orders),
            "open_orders": open_orders,
        },
    }


def _observation_check(observation: dict[str, Any] | None, name: str, execute_loop: bool) -> dict[str, Any]:
    failures = testnet_observation_failures(observation, execute_loop=execute_loop)
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


def _observation_cleanup_check(
    non_order_observation: dict[str, Any] | None,
    order_observation: dict[str, Any] | None,
) -> dict[str, Any]:
    failures = []
    if has_unacceptable_order_lifecycle(non_order_observation):
        failures.append("non_order_observation_order_lifecycle_not_acceptable")
    if has_unacceptable_order_lifecycle(order_observation):
        failures.append("bounded_order_observation_order_lifecycle_not_acceptable")
    return {
        "name": "testnet_order_cleanup",
        "status": "pass" if not failures else "fail",
        "message": "testnet observation orders are clean" if not failures else "testnet observation orders require cleanup",
        "details": {
            "failures": failures,
            "non_ordering": non_order_observation,
            "bounded_order": order_observation,
        },
    }


def _testnet_phase(
    status: str,
    non_order_observation: dict[str, Any] | None,
    order_observation: dict[str, Any] | None,
    *,
    bounded_autotrade_ready: bool = True,
) -> str:
    if status != "pass":
        return "blocked_before_testnet"
    if _acceptable_observation(non_order_observation, execute_loop=False) and _acceptable_observation(order_observation, execute_loop=True):
        if not bounded_autotrade_ready:
            return "ready_for_bounded_testnet_order_observation"
        return "testnet_observed_ready_for_live_review"
    if _acceptable_observation(non_order_observation, execute_loop=False):
        return "ready_for_bounded_testnet_order_observation"
    return "ready_for_testnet_dry_run"


def _testnet_next_steps(
    config: RuntimeConfig,
    status: str,
    readiness: dict[str, Any],
    profile: dict[str, Any] | None,
    non_order_observation: dict[str, Any] | None,
    order_observation: dict[str, Any] | None,
) -> list[str]:
    steps: list[str] = []
    if profile is None:
        steps.append("run kxian-bot promote-profile-to-testnet after the paper profile passes multi-sample validation")
    steps.extend(testnet_closed_loop_next_steps(testnet_closed_loop_scope_failures(config)))
    if readiness.get("status") != "pass":
        steps.extend(readiness.get("next_steps", []))
    if has_unacceptable_order_lifecycle(non_order_observation) or has_unacceptable_order_lifecycle(order_observation):
        steps.append("clear open sandbox orders with order-status, cancel-order if needed, sync-fills, then rerun preflight")
    if status == "pass" and not _acceptable_observation(non_order_observation, execute_loop=False):
        steps.append("run kxian-bot testnet-dry-run, then kxian-bot testnet-observe --cycles 6 --sleep-seconds 60")
    if status == "pass" and _acceptable_observation(non_order_observation, execute_loop=False) and not _acceptable_observation(order_observation, execute_loop=True):
        lifecycle = order_observation.get("order_lifecycle") if isinstance(order_observation, dict) else None
        if isinstance(lifecycle, dict) and lifecycle.get("state") == "open_orders":
            steps.append("clear open sandbox orders with order-status, cancel-order if needed, sync-fills, then rerun preflight")
        steps.append("run kxian-bot testnet-dry-run --execute-loop --sleep-seconds 0, then kxian-bot testnet-observe --cycles 6 --sleep-seconds 60 --execute-loop")
    if (
        status == "pass"
        and _acceptable_observation(non_order_observation, execute_loop=False)
        and _acceptable_observation(order_observation, execute_loop=True)
        and config.enable_testnet_autotrade
    ):
        steps.append("stop at testnet_observed_ready_for_live_review; do not promote to live in this phase")
    return _dedupe(steps)


def _acceptable_observation(observation: dict[str, Any] | None, execute_loop: bool) -> bool:
    return not testnet_observation_failures(observation, execute_loop=execute_loop)


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
    if testnet_observation_failures(non_order_observation, execute_loop=False):
        steps.append("run kxian-bot testnet-observe --cycles 6 --sleep-seconds 60 before live promotion")
    if has_unacceptable_order_lifecycle(order_observation):
        steps.append("clear open sandbox orders with order-status, cancel-order if needed, sync-fills, then rerun preflight")
    if testnet_observation_failures(order_observation, execute_loop=True):
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


def _bitget_live_next_steps(
    config: RuntimeConfig,
    readiness: dict[str, Any],
    live_profile: dict[str, Any] | None,
    latest_order: dict[str, Any] | None,
    open_orders: list[dict[str, Any]],
) -> list[str]:
    steps: list[str] = []
    if live_profile is None:
        steps.append("run a Bitget live gray promotion after passing sample validation and approval evidence")
    if readiness.get("status") != "pass":
        steps.extend(readiness.get("next_steps", []))
    if config.exchange != "bitget":
        steps.append("set KXIAN_EXCHANGE=bitget for the Bitget live gray path")
    if config.mode != "live":
        steps.append("set KXIAN_MODE=live for Bitget live gray")
    if config.use_testnet:
        steps.append("set KXIAN_USE_TESTNET=false for Bitget live gray")
    if config.max_live_order_usdt > 5:
        steps.append("set KXIAN_MAX_LIVE_ORDER_USDT<=5 for the Bitget canary")
    status = str((latest_order or {}).get("status") or "")
    reason = str((latest_order or {}).get("reason") or "")
    if status in {"submitted", "partially_filled"}:
        steps.append("run kxian-bot order-status --order-id <exchange_order_id>")
        steps.append("run kxian-bot cancel-order --order-id <exchange_order_id> if the order should not remain open")
        steps.append("run kxian-bot sync-fills")
        steps.append("rerun preflight after cleanup")
    elif status == "rejected" and reason and reason not in {"no_signal", "no_new_candle", "position_already_open", "no_size", "cooldown_active", "daily_trade_limit", "daily_loss_limit", "live_order_notional_exceeds_limit", "exchange_rule_min_notional", "exchange_rule_min_quantity", "exchange_insufficient_balance"}:
        steps.append("inspect the latest Bitget rejection reason and verify signing, permissions, and balance")
    if open_orders:
        steps.append("clear all Bitget open orders, sync fills, and rerun the checklist")
    if not steps:
        steps.append("ask the operator for explicit approval, then run exactly one bounded Bitget live canary with kxian-bot trade-loop --max-iterations 1 --sleep-seconds 0")
        steps.append("after the canary, run order-status if needed, sync-fills, account-balance, and launch-checklist --target live before any longer loop")
    return _dedupe(steps)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
