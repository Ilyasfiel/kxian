from __future__ import annotations

import time
from datetime import date

from kxian_bot.models import RiskDecision


class RiskManager:
    def __init__(
        self,
        risk_per_trade: float,
        max_position_usdt: float,
        min_order_usdt: float = 10.0,
        max_daily_trades: int = 20,
        max_daily_loss_usdt: float = 100.0,
        cooldown_seconds: int = 0,
        allow_sell_without_position: bool = False,
    ) -> None:
        self.risk_per_trade = risk_per_trade
        self.max_position_usdt = max_position_usdt
        self.min_order_usdt = min_order_usdt
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss_usdt = max_daily_loss_usdt
        self.cooldown_seconds = cooldown_seconds
        self.allow_sell_without_position = allow_sell_without_position
        self.trades_today = 0
        self.start_equity: float | None = None
        self.last_fill_timestamp: float | None = None
        self.day_key: str | None = None

    def size_order(self, usdt_balance: float, price: float) -> float:
        allocated = min(usdt_balance * self.risk_per_trade, self.max_position_usdt)
        quantity = allocated / price
        return round(quantity, 8)

    def validate(
        self,
        side: str,
        quantity: float,
        price: float,
        usdt_balance: float,
        asset_balance: float,
        current_equity: float,
        now: float | None = None,
        reduce_only: bool = False,
    ) -> RiskDecision:
        now = time.time() if now is None else now
        self._ensure_day(now, current_equity)
        notional = quantity * price
        if quantity <= 0 or price <= 0:
            return RiskDecision(allowed=False, reason="invalid_order")
        if reduce_only:
            if side == "sell" and not self.allow_sell_without_position and quantity > asset_balance:
                return RiskDecision(allowed=False, reason="insufficient_asset")
            return RiskDecision(allowed=True)
        if not reduce_only and self.last_fill_timestamp is not None and now - self.last_fill_timestamp < self.cooldown_seconds:
            return RiskDecision(allowed=False, reason="cooldown_active")
        if not reduce_only and self.trades_today >= self.max_daily_trades:
            return RiskDecision(allowed=False, reason="max_daily_trades_reached")
        if side == "buy" and self.start_equity is not None and self.start_equity - current_equity >= self.max_daily_loss_usdt:
            return RiskDecision(allowed=False, reason="max_daily_loss_reached")
        if notional < self.min_order_usdt:
            return RiskDecision(allowed=False, reason="below_min_order_usdt")
        if side == "buy" and notional > usdt_balance:
            return RiskDecision(allowed=False, reason="insufficient_usdt")
        if side == "buy" and asset_balance * price + notional > self.max_position_usdt:
            return RiskDecision(allowed=False, reason="max_position_exceeded")
        if side == "sell" and not self.allow_sell_without_position and quantity > asset_balance:
            return RiskDecision(allowed=False, reason="insufficient_asset")
        return RiskDecision(allowed=True)

    def record_fill(self, timestamp: float | None = None, equity: float | None = None) -> None:
        timestamp = time.time() if timestamp is None else timestamp
        if equity is not None:
            self._ensure_day(timestamp, equity)
        self.trades_today += 1
        self.last_fill_timestamp = timestamp

    def _ensure_day(self, timestamp: float, current_equity: float) -> None:
        day_key = date.fromtimestamp(timestamp).isoformat()
        if self.day_key != day_key:
            self.day_key = day_key
            self.trades_today = 0
            self.start_equity = current_equity
