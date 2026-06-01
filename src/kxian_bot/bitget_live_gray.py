from __future__ import annotations

import time
import uuid
from typing import Any

from kxian_bot.config import RuntimeConfig, expected_live_confirmation
from kxian_bot.storage import SQLiteStorage


BITGET_LIVE_CANARY_MAX_ORDER_USDT = 5.0


def approve_bitget_live_gray(
    config: RuntimeConfig,
    storage: SQLiteStorage | None = None,
    *,
    updated_by: str = "operator",
    confirmation: str = "",
) -> dict[str, Any]:
    storage = storage or SQLiteStorage(config.db_path)
    live_config = config.model_copy(update={"mode": "live", "exchange": "bitget", "use_testnet": False})
    required_confirmation = expected_live_confirmation(live_config)
    failures: list[str] = []
    if config.mode != "live":
        failures.append("bitget_live_mode_required")
    if config.exchange != "bitget":
        failures.append("bitget_exchange_required")
    if config.use_testnet:
        failures.append("bitget_live_requires_production_endpoint")
    if not config.bitget_api_key:
        failures.append("missing_bitget_api_key")
    if not config.bitget_api_secret:
        failures.append("missing_bitget_api_secret")
    if not config.bitget_api_passphrase:
        failures.append("missing_bitget_api_passphrase")
    if not config.live_credentials_confirmed:
        failures.append("bitget_live_credentials_not_confirmed")
    if confirmation != required_confirmation:
        failures.append("bitget_live_confirmation_required")
    if config.max_live_order_usdt > BITGET_LIVE_CANARY_MAX_ORDER_USDT:
        failures.append("bitget_live_canary_limit_exceeded")
    if failures:
        return {
            "status": "blocked",
            "reason": failures[0],
            "mode": "live",
            "exchange": "bitget",
            "symbol": live_config.symbol,
            "interval": live_config.interval,
            "required_confirmation": required_confirmation,
            "failures": failures,
            "next_steps": _next_steps(failures, required_confirmation),
        }

    source = storage.active_strategy_profile("live", "bitget", live_config.symbol, live_config.interval)
    source_mode = "live"
    if source is None:
        source = storage.active_strategy_profile("paper", "bitget", live_config.symbol, live_config.interval)
        source_mode = "paper"
    if source is None:
        return {
            "status": "blocked",
            "reason": "missing_bitget_source_profile",
            "mode": "live",
            "exchange": "bitget",
            "symbol": live_config.symbol,
            "interval": live_config.interval,
            "next_steps": ["run paper validation and save an active bitget paper profile first"],
        }

    evidence = source.get("evidence", {}) if isinstance(source.get("evidence"), dict) else {}
    sample_validation = evidence.get("sample_validation")
    if not isinstance(sample_validation, dict) or sample_validation.get("status") != "pass":
        return {
            "status": "blocked",
            "reason": "source_profile_missing_passing_sample_validation",
            "source_profile_key": source.get("profile_key"),
            "mode": "live",
            "exchange": "bitget",
            "symbol": live_config.symbol,
            "interval": live_config.interval,
            "next_steps": ["run select-samples --promote or validate-samples until the bitget profile has passing sample validation"],
        }

    approved_at = time.time()
    approval_id = str(uuid.uuid4())
    approved_evidence = {
        **evidence,
        "bitget_live_gray": {
            "status": "approved",
            "approval_id": approval_id,
            "approved_at": approved_at,
            "approved_by": updated_by,
            "source_mode": source_mode,
            "source_profile_key": source.get("profile_key"),
            "confirmation": confirmation,
            "max_order_usdt": config.max_live_order_usdt,
            "canary_limit_usdt": BITGET_LIVE_CANARY_MAX_ORDER_USDT,
        },
    }
    profile = storage.upsert_strategy_profile(
        mode="live",
        exchange="bitget",
        symbol=live_config.symbol,
        interval=live_config.interval,
        strategy=source["strategy"],
        parameters=source["parameters"],
        evidence=approved_evidence,
        updated_by=updated_by,
    )
    return {
        "status": "pass",
        "reason": "bitget_live_gray_approved",
        "mode": "live",
        "exchange": "bitget",
        "symbol": live_config.symbol,
        "interval": live_config.interval,
        "source_mode": source_mode,
        "source_profile_key": source.get("profile_key"),
        "approval_id": approval_id,
        "approved_at": approved_at,
        "profile": profile,
        "next_steps": [
            "run kxian-bot trading-rules --refresh-from-exchange",
            "run kxian-bot live-setup-check --timeout-seconds 5",
            "run exactly one bounded Bitget canary only after live-setup-check passes",
        ],
    }


def _next_steps(failures: list[str], required_confirmation: str) -> list[str]:
    mapping = {
        "bitget_live_mode_required": "set KXIAN_MODE=live",
        "bitget_exchange_required": "set KXIAN_EXCHANGE=bitget",
        "bitget_live_requires_production_endpoint": "set KXIAN_USE_TESTNET=false",
        "missing_bitget_api_key": "set KXIAN_BITGET_API_KEY with a production Bitget key",
        "missing_bitget_api_secret": "set KXIAN_BITGET_API_SECRET with a production Bitget secret",
        "missing_bitget_api_passphrase": "set KXIAN_BITGET_API_PASSPHRASE with the production Bitget passphrase",
        "bitget_live_credentials_not_confirmed": "set KXIAN_LIVE_CREDENTIALS_CONFIRMED=true after disabling withdrawals and confirming permissions",
        "bitget_live_confirmation_required": f"rerun with --confirmation {required_confirmation}",
        "bitget_live_canary_limit_exceeded": "set KXIAN_MAX_LIVE_ORDER_USDT<=5",
    }
    return [mapping[failure] for failure in failures if failure in mapping]
