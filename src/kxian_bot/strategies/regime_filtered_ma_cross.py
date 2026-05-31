from __future__ import annotations

from statistics import pstdev
from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class RegimeFilteredMovingAverageCrossStrategy:
    def __init__(self, short_window: int, long_window: int, symbol: str = "BTCUSDT") -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        self.short_window = short_window
        self.long_window = long_window
        self.context_window = long_window * 3
        self.symbol = symbol

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(candles) < self.context_window + self.short_window:
            return None

        previous = candles[:-1]
        last = candles[-1]
        previous_close = closes[-2]
        current_short = simple_moving_average(closes, self.short_window)
        previous_short = simple_moving_average(closes[:-1], self.short_window)
        current_long = simple_moving_average(closes, self.long_window)
        previous_long = simple_moving_average(closes[:-1], self.long_window)
        older_long = simple_moving_average(closes[: -self.short_window], self.long_window)
        current_context = simple_moving_average(closes, self.context_window)
        previous_context = simple_moving_average(closes[:-1], self.context_window)
        older_context = simple_moving_average(closes[: -self.short_window], self.context_window)
        if None in {
            current_short,
            previous_short,
            current_long,
            previous_long,
            older_long,
            current_context,
            previous_context,
            older_context,
        }:
            return None

        context_closes = closes[-self.context_window :]
        deviation = pstdev(context_closes)
        if deviation <= 0 or current_context <= 0:
            return None

        volatility_pct = deviation / current_context
        long_slope_pct = (current_long - older_long) / older_long if older_long > 0 else 0.0
        short_slope_pct = (current_short - previous_short) / previous_short if previous_short > 0 else 0.0
        context_slope_pct = (current_context - older_context) / older_context if older_context > 0 else 0.0
        trend_efficiency = _trend_efficiency(context_closes)
        extension_pct = (last.close - current_context) / current_context
        previous_high = max(candle.high for candle in previous[-self.short_window :])
        breakout_margin_pct = (last.close - previous_high) / previous_high if previous_high > 0 else 0.0
        recent_regime = candles[-self.long_window :]
        recent_high = max(candle.high for candle in recent_regime)
        recent_high_index = max(
            range(len(candles) - len(recent_regime), len(candles)),
            key=lambda index: candles[index].high,
        )
        bars_since_recent_high = len(candles) - 1 - recent_high_index
        drawdown_from_recent_high_pct = (recent_high - last.close) / recent_high if recent_high > 0 else 0.0

        bullish_cross = previous_short <= previous_long and current_short > current_long
        fresh_pullback_reclaim = (
            bars_since_recent_high <= max(3, self.short_window)
            and drawdown_from_recent_high_pct <= max(0.006, min(0.035, volatility_pct * 0.75))
        )
        reclaimed_short = (
            previous_close <= previous_short
            and last.close > current_short
            and short_slope_pct >= 0.0003
            and fresh_pullback_reclaim
        )
        breakout_not_blowoff = extension_pct <= max(0.055, min(0.105, volatility_pct * 2.6))
        short_breakout = (
            last.close > previous_high
            and breakout_margin_pct >= max(0.0008, min(0.004, volatility_pct * 0.18))
            and breakout_not_blowoff
        )
        context_is_rising = current_context >= previous_context * 0.9997 and context_slope_pct >= 0.0002
        long_is_rising = current_long >= previous_long * 0.9998 and long_slope_pct >= 0.0002
        moving_averages_aligned = current_short > current_long * 0.9995 and current_long > current_context * 0.998
        price_has_context_support = last.close > current_context * 0.999 and last.close > current_long * 1.0008
        tradable_volatility = 0.003 <= volatility_pct <= 0.09
        orderly_context = trend_efficiency >= 0.12
        not_overextended = extension_pct <= max(0.055, min(0.13, volatility_pct * 3.1))
        entry_trigger = bullish_cross or reclaimed_short or short_breakout

        if (
            entry_trigger
            and context_is_rising
            and long_is_rising
            and moving_averages_aligned
            and price_has_context_support
            and tradable_volatility
            and orderly_context
            and not_overextended
        ):
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="regime_filtered_ma_buy")

        bearish_cross = previous_short >= previous_long and current_short < current_long
        short_lost = previous_close >= previous_short and last.close < current_short
        long_floor_lost = last.close < current_long * 0.993
        context_rolled_over = current_context < previous_context * 0.9997 and last.close < current_short
        if bearish_cross or short_lost or long_floor_lost or context_rolled_over:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="regime_filtered_ma_sell")
        return None


def _trend_efficiency(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    total_path = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    if total_path <= 0:
        return 0.0
    return abs(values[-1] - values[0]) / total_path
