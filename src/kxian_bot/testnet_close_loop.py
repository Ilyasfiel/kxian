from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from kxian_bot.config import RuntimeConfig
from kxian_bot.evidence import build_testnet_evidence, write_evidence
from kxian_bot.exchange_health import run_exchange_health_check
from kxian_bot.launch_checklist import run_launch_checklist
from kxian_bot.readiness import run_readiness
from kxian_bot.storage import SQLiteStorage
from kxian_bot.testnet_dry_run import run_testnet_dry_run, run_testnet_observation
from kxian_bot.testnet_scope import testnet_closed_loop_scope_failures
from kxian_bot.testnet_setup import run_testnet_setup_check


BLOCKING_SETUP_CHECKS = {
    "testnet_closed_loop_scope",
    "credentials",
    "exchange_health",
    "readiness",
}


def run_testnet_close_loop(
    config: RuntimeConfig,
    *,
    cycles: int = 6,
    sync_limit: int = 500,
    sleep_seconds: float = 60.0,
    confirm_bounded_testnet_order: bool = False,
    evidence_dir: str | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    testnet_config = _testnet_config(config)
    storage = SQLiteStorage(testnet_config.db_path)
    evidence_path = Path(evidence_dir) if evidence_dir else None
    phases: list[dict[str, Any]] = []

    def add_phase(name: str, runner: Callable[[], dict[str, Any]], *, allow_observation_blocked: bool = False) -> dict[str, Any]:
        result = runner()
        phase = _phase_summary(name, result, allow_observation_blocked=allow_observation_blocked)
        phases.append(phase)
        _write_phase_evidence(evidence_path, len(phases), name, testnet_config, storage, result)
        return result

    setup = add_phase(
        "testnet_setup_check",
        lambda: run_testnet_setup_check(testnet_config, timeout_seconds=timeout_seconds),
        allow_observation_blocked=True,
    )
    blocking_setup_failures = _blocking_setup_failures(setup)
    if blocking_setup_failures:
        return _close_loop_result(
            "blocked",
            "testnet_setup_blocked",
            testnet_config,
            phases,
            [
                "fix testnet setup blocking checks before any observation",
                "rerun kxian-bot testnet-close-loop",
            ],
            blocking_failures=blocking_setup_failures,
        )

    readiness = add_phase("readiness", lambda: run_readiness(testnet_config, storage, require_testnet_autotrade=False))
    if readiness.get("status") != "pass":
        return _close_loop_result(
            "blocked",
            "readiness_blocked",
            testnet_config,
            phases,
            readiness.get("next_steps", []),
        )

    health = add_phase("exchange_health", lambda: run_exchange_health_check(testnet_config, timeout_seconds=timeout_seconds))
    if health.get("status") != "pass":
        return _close_loop_result(
            "blocked",
            "exchange_health_blocked",
            testnet_config,
            phases,
            health.get("next_steps", []),
        )

    initial_checklist = add_phase(
        "launch_checklist_initial",
        lambda: run_launch_checklist(testnet_config, storage, target_mode="testnet"),
        allow_observation_blocked=True,
    )
    if initial_checklist.get("status") != "pass" and not _only_waiting_for_observation(initial_checklist):
        return _close_loop_result(
            "blocked",
            "initial_launch_checklist_blocked",
            testnet_config,
            phases,
            initial_checklist.get("next_steps", []),
        )

    dry_run = add_phase(
        "testnet_dry_run",
        lambda: run_testnet_dry_run(testnet_config, sync_limit=sync_limit, execute_loop=False, sleep_seconds=0.0),
    )
    if dry_run.get("status") != "pass":
        return _close_loop_result(
            "blocked",
            "testnet_dry_run_blocked",
            testnet_config,
            phases,
            dry_run.get("next_steps", []),
        )

    non_order_observe = add_phase(
        "testnet_observe",
        lambda: run_testnet_observation(
            testnet_config,
            cycles=cycles,
            sync_limit=sync_limit,
            execute_loop=False,
            sleep_seconds=sleep_seconds,
        ),
    )
    if non_order_observe.get("status") != "pass":
        return _close_loop_result(
            "blocked",
            "testnet_observation_blocked",
            testnet_config,
            phases,
            ["fix non-ordering testnet observation failures, then rerun testnet-close-loop"],
        )

    if not confirm_bounded_testnet_order:
        return _close_loop_result(
            "blocked",
            "bounded_testnet_confirmation_required",
            testnet_config,
            phases,
            [
                "review non-ordering observation evidence",
                "set KXIAN_ENABLE_TESTNET_AUTOTRADE=true",
                "rerun kxian-bot testnet-close-loop --confirm-bounded-testnet-order",
            ],
        )

    if not testnet_config.enable_testnet_autotrade:
        return _close_loop_result(
            "blocked",
            "testnet_autotrade_disabled",
            testnet_config,
            phases,
            ["set KXIAN_ENABLE_TESTNET_AUTOTRADE=true before bounded testnet order observation"],
        )

    bounded_scope_failures = testnet_closed_loop_scope_failures(testnet_config, require_autotrade=True)
    if bounded_scope_failures:
        return _close_loop_result(
            "blocked",
            bounded_scope_failures[0],
            testnet_config,
            phases,
            ["fix closed-loop testnet scope before bounded observation"],
            blocking_failures=bounded_scope_failures,
        )

    bounded_dry_run = add_phase(
        "testnet_dry_run_execute_loop",
        lambda: run_testnet_dry_run(testnet_config, sync_limit=sync_limit, execute_loop=True, sleep_seconds=0.0),
    )
    if bounded_dry_run.get("status") != "pass":
        return _close_loop_result(
            "blocked",
            bounded_dry_run.get("reason") or "bounded_testnet_dry_run_blocked",
            testnet_config,
            phases,
            bounded_dry_run.get("next_steps", []),
        )

    bounded_observe = add_phase(
        "testnet_observe_execute_loop",
        lambda: run_testnet_observation(
            testnet_config,
            cycles=cycles,
            sync_limit=sync_limit,
            execute_loop=True,
            sleep_seconds=sleep_seconds,
        ),
    )
    if bounded_observe.get("status") != "pass":
        return _close_loop_result(
            "blocked",
            "bounded_testnet_observation_blocked",
            testnet_config,
            phases,
            ["clear any sandbox order state, sync fills, rerun preflight, then rerun bounded observation"],
        )

    final_checklist = add_phase(
        "launch_checklist_final",
        lambda: run_launch_checklist(testnet_config, storage, target_mode="testnet"),
    )
    if final_checklist.get("status") != "pass" or final_checklist.get("phase") != "testnet_observed_ready_for_live_review":
        return _close_loop_result(
            "blocked",
            (
                "final_launch_phase_not_ready"
                if final_checklist.get("status") == "pass"
                else "final_launch_checklist_blocked"
            ),
            testnet_config,
            phases,
            final_checklist.get("next_steps", []),
        )

    return _close_loop_result(
        "pass",
        "testnet_close_loop_complete",
        testnet_config,
        phases,
        ["stop at testnet_observed_ready_for_live_review; do not promote to live in this phase"],
        final_checklist=final_checklist,
    )


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


def _phase_summary(name: str, result: dict[str, Any], *, allow_observation_blocked: bool = False) -> dict[str, Any]:
    status = str(result.get("status") or "unknown")
    allow_continue = status == "pass" or (allow_observation_blocked and _only_waiting_for_observation(result))
    return {
        "name": name,
        "status": status,
        "reason": result.get("reason", ""),
        "phase": result.get("phase", result.get("launch_summary", {}).get("phase") if isinstance(result.get("launch_summary"), dict) else ""),
        "allow_continue": allow_continue,
        "blocking_failures": _blocking_setup_failures(result) if name == "testnet_setup_check" else [],
    }


def _only_waiting_for_observation(result: dict[str, Any]) -> bool:
    if result.get("status") == "pass":
        return True
    failed = _failed_check_names(result)
    allowed = {"launch_checklist", "testnet_bounded_autotrade", "testnet_observation", "testnet_order_observation"}
    if failed and set(failed).issubset(allowed):
        return True
    phase = str(result.get("phase") or result.get("launch_summary", {}).get("phase") or "")
    return phase in {"ready_for_testnet_dry_run", "ready_for_bounded_testnet_order_observation"}


def _blocking_setup_failures(result: dict[str, Any]) -> list[str]:
    failed = _failed_check_names(result)
    return [name for name in failed if name in BLOCKING_SETUP_CHECKS]


def _failed_check_names(result: dict[str, Any]) -> list[str]:
    checks = result.get("checks", [])
    if not isinstance(checks, list):
        return []
    return [str(check.get("name")) for check in checks if isinstance(check, dict) and check.get("status") != "pass"]


def _write_phase_evidence(
    evidence_path: Path | None,
    index: int,
    name: str,
    config: RuntimeConfig,
    storage: SQLiteStorage,
    result: dict[str, Any],
) -> None:
    if evidence_path is None:
        return
    file_name = f"{index:02d}-{name}.json"
    write_evidence(evidence_path / file_name, build_testnet_evidence(config, storage, command=name, result=result))


def _close_loop_result(
    status: str,
    reason: str,
    config: RuntimeConfig,
    phases: list[dict[str, Any]],
    next_steps: list[str],
    *,
    final_checklist: dict[str, Any] | None = None,
    blocking_failures: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "use_testnet": config.use_testnet,
        "phase": final_checklist.get("phase") if isinstance(final_checklist, dict) else _latest_phase(phases),
        "phases": phases,
        "blocking_failures": blocking_failures or [],
        "final_checklist": final_checklist,
        "next_steps": _dedupe(next_steps),
        "safety": {
            "bounded_requires_confirmation": True,
            "bounded_confirmed": any(phase["name"] == "testnet_dry_run_execute_loop" for phase in phases),
            "live_promote_executed": False,
            "live_loop_executed": False,
        },
    }


def _latest_phase(phases: list[dict[str, Any]]) -> str:
    for phase in reversed(phases):
        value = phase.get("phase")
        if value:
            return str(value)
    return ""


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
