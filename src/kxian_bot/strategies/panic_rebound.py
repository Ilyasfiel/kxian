from __future__ import annotations

from statistics import pstdev
from typing import Sequence

from kxian_bot.indicators import simple_moving_average
from kxian_bot.models import Candle, Signal


class PanicReboundStrategy:
    def __init__(self, rebound_window: int, context_window: int, symbol: str = "BTCUSDT") -> None:
        if rebound_window >= context_window:
            raise ValueError("rebound_window must be smaller than context_window")
        self.rebound_window = rebound_window
        self.context_window = context_window
        self.symbol = symbol

    @property
    def short_window(self) -> int:
        return self.rebound_window

    @property
    def long_window(self) -> int:
        return self.context_window

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        closes = [candle.close for candle in candles]
        if len(candles) < self.context_window + 1:
            return None

        previous = candles[:-1]
        last = candles[-1]
        previous_close = closes[-2]
        current_fast = simple_moving_average(closes, self.rebound_window)
        previous_fast = simple_moving_average(closes[:-1], self.rebound_window)
        current_context = simple_moving_average(closes, self.context_window)
        previous_context = simple_moving_average(closes[:-1], self.context_window)
        if None in {current_fast, previous_fast, current_context, previous_context}:
            return None

        current_context_closes = closes[-self.context_window :]
        previous_context_closes = closes[-self.context_window - 1 : -1]
        current_deviation = pstdev(current_context_closes)
        previous_deviation = pstdev(previous_context_closes)
        if current_deviation <= 0 or previous_deviation <= 0:
            return None

        volatility_pct = current_deviation / current_context if current_context > 0 else 0.0
        lower_band = current_context - 1.35 * current_deviation
        previous_lower_band = previous_context - 1.35 * previous_deviation
        rolling_high = max(candle.high for candle in candles[-self.context_window :])
        previous_recent_low = min(candle.low for candle in previous[-self.rebound_window :])
        previous_drawdown_pct = (rolling_high - previous_close) / rolling_high if rolling_high > 0 else 0.0
        bounce_floor = max(0.006, min(0.025, volatility_pct * 0.25))
        panic_floor = max(0.018, min(0.08, volatility_pct * 0.9))

        panic_washout = previous_close <= previous_lower_band or previous_recent_low <= previous_lower_band
        deep_enough = previous_drawdown_pct >= panic_floor
        bounced_from_low = last.close >= previous_recent_low * (1 + bounce_floor)
        recovered_momentum = last.close >= previous_close * 1.003
        reclaimed_fast = previous_close <= previous_fast and last.close > current_fast
        reclaimed_lower_band = previous_close <= lower_band and last.close > lower_band
        structural_floor_ok = last.close >= current_context * 0.86 and current_context >= previous_context * 0.975

        if (
            panic_washout
            and deep_enough
            and bounced_from_low
            and recovered_momentum
            and structural_floor_ok
            and (reclaimed_fast or reclaimed_lower_band)
        ):
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="panic_rebound_buy")

        recovery_target_hit = last.close >= current_context or last.close >= current_fast * (1 + max(0.008, volatility_pct * 0.2))
        recovery_stalled = previous_close >= previous_fast and last.close < current_fast
        breakdown_continues = last.close <= previous_recent_low * 0.992 or last.close < current_context - 1.8 * current_deviation
        if recovery_target_hit or recovery_stalled or breakdown_continues:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="panic_rebound_sell")
        return None
