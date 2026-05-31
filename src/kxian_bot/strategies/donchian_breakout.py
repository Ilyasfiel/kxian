from __future__ import annotations

from typing import Sequence

from kxian_bot.models import Candle, Signal


class DonchianBreakoutStrategy:
    def __init__(self, entry_window: int, exit_window: int, symbol: str = "BTCUSDT") -> None:
        if entry_window <= exit_window:
            raise ValueError("entry_window must be larger than exit_window")
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.symbol = symbol

    def generate(self, candles: Sequence[Candle]) -> Signal | None:
        if len(candles) < self.entry_window + 1:
            return None

        previous = candles[:-1]
        last = candles[-1]
        entry_high = max(candle.high for candle in previous[-self.entry_window :])
        exit_low = min(candle.low for candle in previous[-self.exit_window :])

        if last.close > entry_high:
            return Signal(symbol=self.symbol, side="buy", price=last.close, reason="donchian_breakout_buy")
        if last.close < exit_low:
            return Signal(symbol=self.symbol, side="sell", price=last.close, reason="donchian_breakout_sell")
        return None
