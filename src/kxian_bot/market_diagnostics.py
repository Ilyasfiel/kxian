from __future__ import annotations

from statistics import mean, pstdev
from typing import Any

from kxian_bot.models import Candle


def diagnose_market(
    candles: list[Candle],
    *,
    segments: int = 3,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0005,
) -> dict[str, Any]:
    sorted_candles = sorted(candles, key=lambda candle: candle.open_time)
    returns = _close_to_close_returns(sorted_candles)
    segment_results = [_diagnose_segment(index, segment) for index, segment in enumerate(_split_candles(sorted_candles, segments), start=1)]
    trend_efficiency = _trend_efficiency(sorted_candles)
    round_trip_friction_pct = (fee_rate + slippage_rate) * 2 * 100
    avg_abs_return_pct = mean(abs(value) for value in returns) * 100 if returns else 0.0

    return {
        "candle_count": len(sorted_candles),
        "start_time": sorted_candles[0].open_time if sorted_candles else 0,
        "end_time": sorted_candles[-1].open_time if sorted_candles else 0,
        "first_close": round(sorted_candles[0].close, 8) if sorted_candles else 0.0,
        "last_close": round(sorted_candles[-1].close, 8) if sorted_candles else 0.0,
        "buy_hold_return_pct": round(_buy_hold_return_pct(sorted_candles), 4),
        "buy_hold_max_drawdown_pct": round(_buy_hold_max_drawdown_pct(sorted_candles), 4),
        "realized_volatility_pct": round((pstdev(returns) * 100) if len(returns) > 1 else 0.0, 4),
        "avg_abs_candle_return_pct": round(avg_abs_return_pct, 4),
        "trend_efficiency": round(trend_efficiency, 4),
        "round_trip_friction_pct": round(round_trip_friction_pct, 4),
        "friction_to_avg_abs_return": round(round_trip_friction_pct / avg_abs_return_pct, 4) if avg_abs_return_pct > 0 else 0.0,
        "segment_count": len(segment_results),
        "segments": segment_results,
        "classification": _classify_market(
            buy_hold_return_pct=_buy_hold_return_pct(sorted_candles),
            max_drawdown_pct=_buy_hold_max_drawdown_pct(sorted_candles),
            trend_efficiency=trend_efficiency,
            round_trip_friction_pct=round_trip_friction_pct,
            avg_abs_return_pct=avg_abs_return_pct,
            segment_returns=[segment["return_pct"] for segment in segment_results],
        ),
    }


def _diagnose_segment(index: int, candles: list[Candle]) -> dict[str, Any]:
    return {
        "index": index,
        "start_time": candles[0].open_time if candles else 0,
        "end_time": candles[-1].open_time if candles else 0,
        "candle_count": len(candles),
        "first_close": round(candles[0].close, 8) if candles else 0.0,
        "last_close": round(candles[-1].close, 8) if candles else 0.0,
        "return_pct": round(_buy_hold_return_pct(candles), 4),
        "max_drawdown_pct": round(_buy_hold_max_drawdown_pct(candles), 4),
    }


def _close_to_close_returns(candles: list[Candle]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(candles, candles[1:]):
        if previous.close <= 0:
            continue
        returns.append((current.close - previous.close) / previous.close)
    return returns


def _buy_hold_return_pct(candles: list[Candle]) -> float:
    if len(candles) < 2 or candles[0].close <= 0:
        return 0.0
    return (candles[-1].close - candles[0].close) / candles[0].close * 100


def _buy_hold_max_drawdown_pct(candles: list[Candle]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for candle in candles:
        peak = max(peak, candle.close)
        if peak <= 0:
            continue
        max_drawdown = max(max_drawdown, (peak - candle.close) / peak * 100)
    return max_drawdown


def _trend_efficiency(candles: list[Candle]) -> float:
    if len(candles) < 2:
        return 0.0
    total_path = sum(abs(current.close - previous.close) for previous, current in zip(candles, candles[1:]))
    if total_path <= 0:
        return 0.0
    direct_move = abs(candles[-1].close - candles[0].close)
    return direct_move / total_path


def _classify_market(
    *,
    buy_hold_return_pct: float,
    max_drawdown_pct: float,
    trend_efficiency: float,
    round_trip_friction_pct: float,
    avg_abs_return_pct: float,
    segment_returns: list[float],
) -> dict[str, Any]:
    positive_segments = sum(1 for value in segment_returns if value > 0)
    negative_segments = sum(1 for value in segment_returns if value < 0)

    if buy_hold_return_pct > 2 and trend_efficiency >= 0.2:
        regime = "uptrend"
    elif buy_hold_return_pct < -2 and trend_efficiency >= 0.2:
        regime = "downtrend"
    elif trend_efficiency < 0.12:
        regime = "choppy"
    else:
        regime = "mixed"

    if avg_abs_return_pct <= 0:
        cost_pressure = "unknown"
    elif round_trip_friction_pct >= avg_abs_return_pct:
        cost_pressure = "high"
    elif round_trip_friction_pct >= avg_abs_return_pct * 0.5:
        cost_pressure = "medium"
    else:
        cost_pressure = "low"

    notes: list[str] = []
    if cost_pressure == "high":
        notes.append("round_trip_friction_exceeds_avg_candle_move")
    if positive_segments and negative_segments:
        notes.append("mixed_segment_returns")
    if max_drawdown_pct > abs(buy_hold_return_pct) * 2 and max_drawdown_pct > 5:
        notes.append("drawdown_large_vs_net_move")

    return {
        "regime": regime,
        "cost_pressure": cost_pressure,
        "positive_segments": positive_segments,
        "negative_segments": negative_segments,
        "notes": notes,
    }


def _split_candles(candles: list[Candle], segments: int) -> list[list[Candle]]:
    if not candles:
        return []
    segments = max(1, min(int(segments), len(candles)))
    base_size, remainder = divmod(len(candles), segments)
    output: list[list[Candle]] = []
    offset = 0
    for index in range(segments):
        size = base_size + (1 if index < remainder else 0)
        output.append(candles[offset : offset + size])
        offset += size
    return output
