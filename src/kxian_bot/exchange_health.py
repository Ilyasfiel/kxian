from __future__ import annotations

import time
from typing import Any

import requests

from kxian_bot.config import RuntimeConfig
from kxian_bot.market_data import BinanceMarketDataClient, OkxMarketDataClient, format_okx_symbol


BINANCE_PRODUCTION_URL = BinanceMarketDataClient.BASE_URL
BINANCE_TESTNET_URL = BinanceMarketDataClient.TESTNET_URL
OKX_URL = OkxMarketDataClient.BASE_URL


def run_exchange_health_check(config: RuntimeConfig, timeout_seconds: float = 5.0) -> dict[str, Any]:
    timeout = max(0.5, min(float(timeout_seconds), 30.0))
    checks = [
        _market_data_check(config, timeout),
        _trading_endpoint_check(config, timeout),
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    return {
        "status": status,
        "mode": config.mode,
        "exchange": config.exchange,
        "symbol": config.symbol,
        "interval": config.interval,
        "timeout_seconds": timeout,
        "checks": checks,
        "next_steps": _next_steps(checks),
    }


def _market_data_check(config: RuntimeConfig, timeout_seconds: float) -> dict[str, Any]:
    if config.market_data_source == "sqlite":
        return {
            "name": "public_market_data",
            "status": "pass",
            "message": "public exchange market data is not required for sqlite replay",
            "details": {
                "required": False,
                "source": config.market_data_source,
                "failures": [],
            },
        }

    if config.exchange == "binance":
        base_url = _binance_market_data_url(config)
        url = f"{base_url}/api/v3/klines"
        params = {"symbol": config.symbol, "interval": config.interval, "limit": 1}
        return _json_get_check(
            name="public_market_data",
            url=url,
            params=params,
            timeout_seconds=timeout_seconds,
            validator=lambda payload: isinstance(payload, list) and len(payload) > 0,
            success_message="public exchange market data is reachable",
            failure_message="public exchange market data is unreachable",
            required=True,
        )

    url = f"{OKX_URL}/api/v5/market/candles"
    params = {"instId": format_okx_symbol(config.symbol), "bar": config.interval, "limit": 1}
    return _json_get_check(
        name="public_market_data",
        url=url,
        params=params,
        timeout_seconds=timeout_seconds,
        validator=lambda payload: isinstance(payload, dict)
        and str(payload.get("code", "0")) == "0"
        and len(payload.get("data", [])) > 0,
        success_message="public exchange market data is reachable",
        failure_message="public exchange market data is unreachable",
        required=True,
    )


def _binance_market_data_url(config: RuntimeConfig) -> str:
    if config.mode == "testnet" and config.use_testnet:
        return BINANCE_TESTNET_URL
    return BINANCE_PRODUCTION_URL


def _trading_endpoint_check(config: RuntimeConfig, timeout_seconds: float) -> dict[str, Any]:
    if config.mode == "paper":
        return {
            "name": "trading_endpoint",
            "status": "pass",
            "message": "trading endpoint is not required for paper mode",
            "details": {
                "required": False,
                "failures": [],
            },
        }

    if config.exchange == "binance":
        base_url = BINANCE_TESTNET_URL if config.use_testnet else BINANCE_PRODUCTION_URL
        url = f"{base_url}/api/v3/time"
        return _json_get_check(
            name="trading_endpoint",
            url=url,
            params={},
            timeout_seconds=timeout_seconds,
            validator=lambda payload: isinstance(payload, dict) and "serverTime" in payload,
            success_message="selected trading endpoint is reachable",
            failure_message="selected trading endpoint is unreachable",
            required=config.mode in {"testnet", "live"},
        )

    url = f"{OKX_URL}/api/v5/public/time"
    return _json_get_check(
        name="trading_endpoint",
        url=url,
        params={},
        timeout_seconds=timeout_seconds,
        validator=lambda payload: isinstance(payload, dict) and str(payload.get("code", "0")) == "0",
        success_message="selected trading endpoint is reachable",
        failure_message="selected trading endpoint is unreachable",
        required=config.mode in {"testnet", "live"},
    )


def _json_get_check(
    *,
    name: str,
    url: str,
    params: dict[str, Any],
    timeout_seconds: float,
    validator,
    success_message: str,
    failure_message: str,
    required: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    details: dict[str, Any] = {
        "required": required,
        "endpoint": url,
        "timeout_seconds": timeout_seconds,
        "failures": [],
    }
    try:
        response = requests.get(url, params=params, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        reason = _http_error_reason(exc)
        return {
            "name": name,
            "status": "fail",
            "message": failure_message,
            "details": {
                **details,
                "failures": [reason],
                "reason": reason,
                "latency_ms": _elapsed_ms(started),
                "status_code": getattr(getattr(exc, "response", None), "status_code", None),
                "error": _safe_error_text(exc),
            },
        }
    except ValueError as exc:
        return {
            "name": name,
            "status": "fail",
            "message": failure_message,
            "details": {
                **details,
                "failures": ["invalid_exchange_response"],
                "reason": "invalid_exchange_response",
                "latency_ms": _elapsed_ms(started),
                "error": _safe_error_text(exc),
            },
        }

    if not validator(payload):
        return {
            "name": name,
            "status": "fail",
            "message": failure_message,
            "details": {
                **details,
                "failures": ["unexpected_exchange_response"],
                "reason": "unexpected_exchange_response",
                "latency_ms": _elapsed_ms(started),
            },
        }
    return {
        "name": name,
        "status": "pass",
        "message": success_message,
        "details": {**details, "latency_ms": _elapsed_ms(started)},
    }


def _http_error_reason(exc: requests.RequestException) -> str:
    if isinstance(exc, (requests.Timeout, requests.ConnectTimeout, requests.ReadTimeout)):
        return "exchange_timeout"
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in {401, 403}:
        return f"exchange_http_{status_code}"
    if status_code == 429:
        return "exchange_rate_limited"
    if isinstance(status_code, int) and status_code >= 500:
        return "exchange_server_error"
    return "exchange_http_error"


def _safe_error_text(exc: BaseException) -> str:
    text = str(exc)
    if len(text) > 240:
        return f"{text[:237]}..."
    return text


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _next_steps(checks: list[dict[str, Any]]) -> list[str]:
    failures = {
        failure
        for check in checks
        for failure in check.get("details", {}).get("failures", [])
    }
    steps: list[str] = []
    if "exchange_timeout" in failures or "exchange_http_error" in failures:
        steps.append("verify this machine or deployment host can reach the selected exchange endpoints")
        steps.append("configure a stable proxy or deploy the bot on a network with exchange API access")
    if "exchange_http_401" in failures or "exchange_http_403" in failures:
        steps.append("check exchange regional restrictions, endpoint selection, and API access permissions")
    if "exchange_rate_limited" in failures:
        steps.append("wait for the exchange rate limit window to reset before starting automation")
    if "exchange_server_error" in failures:
        steps.append("wait for the exchange endpoint to recover before starting automation")
    if "invalid_exchange_response" in failures or "unexpected_exchange_response" in failures:
        steps.append("inspect exchange status and endpoint compatibility for the configured symbol and interval")
    if not steps:
        steps.append("exchange endpoints are reachable for the current configuration")
    return steps
