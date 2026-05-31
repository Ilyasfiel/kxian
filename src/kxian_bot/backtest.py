from __future__ import annotations

import math
from typing import Sequence

from kxian_bot.models import BacktestResult, BacktestTrade, Candle, OrderRequest


class BacktestEngine:
    def __init__(
        self,
        strategy,
        risk_manager,
        broker,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        stop_loss_pct: float = 0.0,
        take_profit_pct: float = 0.0,
        trailing_stop_pct: float = 0.0,
    ) -> None:
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.broker = broker
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct

    def run(self, candles: Sequence[Candle], symbol: str) -> BacktestResult:
        initial_equity = self.broker.usdt_balance
        equity_curve = [initial_equity]
        fees_paid = 0.0
        slippage_paid = 0.0
        realized_pnls: list[float] = []
        trades: list[BacktestTrade] = []
        history: list[Candle] = []
        average_entry_price = 0.0
        trailing_peak_price = 0.0

        for candle in candles:
            history.append(candle)
            signal = _protective_exit_signal(
                symbol,
                candle,
                self.broker.asset_balance,
                average_entry_price,
                self.stop_loss_pct,
                self.take_profit_pct,
                self.trailing_stop_pct,
                trailing_peak_price,
            ) or self.strategy.generate(history)
            if signal is None:
                if self.broker.asset_balance > 0 and average_entry_price > 0:
                    trailing_peak_price = max(trailing_peak_price, average_entry_price, candle.high)
                equity_curve.append(self._equity(candle.close))
                continue
            if signal.side == "buy" and self.broker.asset_balance > 0:
                trailing_peak_price = max(trailing_peak_price, average_entry_price, candle.high)
                equity_curve.append(self._equity(candle.close))
                continue

            execution_price = self._execution_price(signal.side, signal.price)
            quantity = self.risk_manager.size_order(self.broker.usdt_balance, execution_price)
            if signal.side == "buy":
                quantity = min(quantity, _floor_quantity(self.broker.usdt_balance / (execution_price * (1 + self.fee_rate))))
            if signal.side == "sell":
                quantity = round(self.broker.asset_balance, 8)
            if quantity <= 0:
                equity_curve.append(self._equity(candle.close))
                continue

            fee = quantity * execution_price * self.fee_rate
            notional = quantity * execution_price
            current_equity = self._equity(signal.price)
            event_timestamp = _risk_timestamp(candle.open_time)
            decision = self.risk_manager.validate(
                signal.side,
                quantity,
                execution_price,
                self.broker.usdt_balance,
                self.broker.asset_balance,
                current_equity,
                now=event_timestamp,
                reduce_only=_is_protective_exit(signal.reason),
            )
            if not decision.allowed:
                if self.broker.asset_balance > 0 and average_entry_price > 0:
                    trailing_peak_price = max(trailing_peak_price, average_entry_price, candle.high)
                equity_curve.append(self._equity(candle.close))
                continue

            previous_asset_balance = self.broker.asset_balance
            fill = self.broker.execute(
                OrderRequest(symbol=symbol, side=signal.side, quantity=quantity, price=execution_price)
            )
            if fill.status == "filled":
                if signal.side == "buy":
                    self.broker.usdt_balance -= fee
                    total_quantity = self.broker.asset_balance
                    previous_cost = previous_asset_balance * average_entry_price
                    total_cost = previous_cost + quantity * execution_price
                    average_entry_price = total_cost / total_quantity if total_quantity > 0 else 0.0
                    trailing_peak_price = max(trailing_peak_price, average_entry_price)
                    pnl = 0.0
                else:
                    self.broker.usdt_balance -= fee
                    pnl = (execution_price - average_entry_price) * quantity - fee
                    realized_pnls.append(pnl)
                    average_entry_price = 0.0 if self.broker.asset_balance == 0 else average_entry_price
                    if self.broker.asset_balance == 0:
                        trailing_peak_price = 0.0

                fees_paid += fee
                slippage_paid += abs(execution_price - signal.price) * quantity
                trade = BacktestTrade(
                    timestamp=candle.open_time,
                    symbol=symbol,
                    side=signal.side,
                    quantity=round(quantity, 8),
                    signal_price=round(signal.price, 8),
                    execution_price=round(execution_price, 8),
                    fee=round(fee, 4),
                    slippage=round(abs(execution_price - signal.price) * quantity, 4),
                    pnl=round(pnl, 4),
                    reason=signal.reason,
                )
                trades.append(trade)
                equity = self._equity(signal.price)
                self.risk_manager.record_fill(timestamp=event_timestamp, equity=equity)
                equity_curve.append(equity)
            else:
                equity_curve.append(self._equity(candle.close))

        if candles and self.broker.asset_balance > 0 and average_entry_price > 0:
            candle = candles[-1]
            quantity = round(self.broker.asset_balance, 8)
            signal_price = candle.close
            execution_price = self._execution_price("sell", signal_price)
            fee = quantity * execution_price * self.fee_rate
            fill = self.broker.execute(OrderRequest(symbol=symbol, side="sell", quantity=quantity, price=execution_price))
            if fill.status == "filled":
                self.broker.usdt_balance -= fee
                pnl = (execution_price - average_entry_price) * quantity - fee
                realized_pnls.append(pnl)
                fees_paid += fee
                slippage_paid += abs(execution_price - signal_price) * quantity
                trades.append(
                    BacktestTrade(
                        timestamp=candle.close_time,
                        symbol=symbol,
                        side="sell",
                        quantity=round(quantity, 8),
                        signal_price=round(signal_price, 8),
                        execution_price=round(execution_price, 8),
                        fee=round(fee, 4),
                        slippage=round(abs(execution_price - signal_price) * quantity, 4),
                        pnl=round(pnl, 4),
                        reason="end_of_backtest_liquidation",
                    )
                )
                average_entry_price = 0.0
                trailing_peak_price = 0.0
                equity_curve.append(self._equity(signal_price))

        last_price = candles[-1].close if candles else 0.0
        final_equity = self._equity(last_price)
        equity_curve.append(final_equity)
        return BacktestResult(
            initial_equity=round(initial_equity, 2),
            trade_count=len(trades),
            final_equity=round(final_equity, 2),
            return_pct=round(_return_pct(initial_equity, final_equity), 4),
            max_drawdown_pct=round(_max_drawdown_pct(equity_curve), 4),
            win_rate=round(_win_rate(realized_pnls), 4),
            profit_factor=round(_profit_factor(realized_pnls), 4),
            fees_paid=round(fees_paid, 4),
            slippage_paid=round(slippage_paid, 4),
            usdt_balance=round(self.broker.usdt_balance, 2),
            asset_balance=round(self.broker.asset_balance, 8),
            trades=trades,
        )

    def _execution_price(self, side: str, signal_price: float) -> float:
        if side == "buy":
            return signal_price * (1 + self.slippage_rate)
        return signal_price * (1 - self.slippage_rate)

    def _equity(self, mark_price: float) -> float:
        return self.broker.usdt_balance + self.broker.asset_balance * mark_price


class SyntheticShortBacktestEngine:
    def __init__(
        self,
        strategy,
        risk_manager,
        starting_usdt: float,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        stop_loss_pct: float = 0.0,
        take_profit_pct: float = 0.0,
        trailing_stop_pct: float = 0.0,
    ) -> None:
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.usdt_balance = starting_usdt
        self.short_quantity = 0.0
        self.average_entry_price = 0.0
        self.trailing_low_price = 0.0
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct

    def run(self, candles: Sequence[Candle], symbol: str) -> BacktestResult:
        initial_equity = self.usdt_balance
        equity_curve = [initial_equity]
        fees_paid = 0.0
        slippage_paid = 0.0
        realized_pnls: list[float] = []
        trades: list[BacktestTrade] = []
        history: list[Candle] = []

        for candle in candles:
            history.append(candle)
            signal = self._protective_cover_signal(symbol, candle) or self.strategy.generate(history)
            if signal is None:
                if self.short_quantity > 0 and self.average_entry_price > 0:
                    self.trailing_low_price = min(self.trailing_low_price or candle.low, candle.low)
                equity_curve.append(self._equity(candle.close))
                continue
            if signal.side == "sell" and self.short_quantity > 0:
                self.trailing_low_price = min(self.trailing_low_price or candle.low, candle.low)
                equity_curve.append(self._equity(candle.close))
                continue
            if signal.side == "buy" and self.short_quantity <= 0:
                equity_curve.append(self._equity(candle.close))
                continue

            execution_price = self._execution_price(signal.side, signal.price)
            if signal.side == "sell":
                quantity = self.risk_manager.size_order(self.usdt_balance, execution_price)
                max_quantity = self.usdt_balance / (execution_price * (1 + self.fee_rate))
                quantity = min(quantity, _floor_quantity(max_quantity))
            else:
                quantity = round(self.short_quantity, 8)
            if quantity <= 0:
                equity_curve.append(self._equity(candle.close))
                continue

            fee = quantity * execution_price * self.fee_rate
            current_equity = self._equity(signal.price)
            event_timestamp = _risk_timestamp(candle.open_time)
            decision = self.risk_manager.validate(
                "buy",
                quantity,
                execution_price,
                self.usdt_balance,
                0.0,
                current_equity,
                now=event_timestamp,
                reduce_only=signal.side == "buy",
            )
            if not decision.allowed:
                if self.short_quantity > 0 and self.average_entry_price > 0:
                    self.trailing_low_price = min(self.trailing_low_price or candle.low, candle.low)
                equity_curve.append(self._equity(candle.close))
                continue

            pnl = 0.0
            if signal.side == "sell":
                self.usdt_balance -= fee
                self.short_quantity = quantity
                self.average_entry_price = execution_price
                self.trailing_low_price = execution_price
            else:
                self.usdt_balance += (self.average_entry_price - execution_price) * quantity
                self.usdt_balance -= fee
                pnl = (self.average_entry_price - execution_price) * quantity - fee
                realized_pnls.append(pnl)
                self.short_quantity = 0.0
                self.average_entry_price = 0.0
                self.trailing_low_price = 0.0

            fees_paid += fee
            slippage_paid += abs(execution_price - signal.price) * quantity
            trades.append(
                BacktestTrade(
                    timestamp=candle.open_time,
                    symbol=symbol,
                    side=signal.side,
                    quantity=round(quantity, 8),
                    signal_price=round(signal.price, 8),
                    execution_price=round(execution_price, 8),
                    fee=round(fee, 4),
                    slippage=round(abs(execution_price - signal.price) * quantity, 4),
                    pnl=round(pnl, 4),
                    reason=signal.reason,
                )
            )
            equity = self._equity(signal.price)
            self.risk_manager.record_fill(timestamp=event_timestamp, equity=equity)
            equity_curve.append(equity)

        if candles and self.short_quantity > 0 and self.average_entry_price > 0:
            candle = candles[-1]
            quantity = round(self.short_quantity, 8)
            signal_price = candle.close
            execution_price = self._execution_price("buy", signal_price)
            fee = quantity * execution_price * self.fee_rate
            self.usdt_balance += (self.average_entry_price - execution_price) * quantity
            self.usdt_balance -= fee
            pnl = (self.average_entry_price - execution_price) * quantity - fee
            realized_pnls.append(pnl)
            fees_paid += fee
            slippage_paid += abs(execution_price - signal_price) * quantity
            trades.append(
                BacktestTrade(
                    timestamp=candle.close_time,
                    symbol=symbol,
                    side="buy",
                    quantity=round(quantity, 8),
                    signal_price=round(signal_price, 8),
                    execution_price=round(execution_price, 8),
                    fee=round(fee, 4),
                    slippage=round(abs(execution_price - signal_price) * quantity, 4),
                    pnl=round(pnl, 4),
                    reason="end_of_backtest_short_cover",
                )
            )
            self.short_quantity = 0.0
            self.average_entry_price = 0.0
            self.trailing_low_price = 0.0
            equity_curve.append(self._equity(signal_price))

        last_price = candles[-1].close if candles else 0.0
        final_equity = self._equity(last_price)
        equity_curve.append(final_equity)
        return BacktestResult(
            initial_equity=round(initial_equity, 2),
            trade_count=len(trades),
            final_equity=round(final_equity, 2),
            return_pct=round(_return_pct(initial_equity, final_equity), 4),
            max_drawdown_pct=round(_max_drawdown_pct(equity_curve), 4),
            win_rate=round(_win_rate(realized_pnls), 4),
            profit_factor=round(_profit_factor(realized_pnls), 4),
            fees_paid=round(fees_paid, 4),
            slippage_paid=round(slippage_paid, 4),
            usdt_balance=round(self.usdt_balance, 2),
            asset_balance=round(-self.short_quantity, 8),
            trades=trades,
        )

    def _protective_cover_signal(self, symbol: str, candle: Candle):
        if self.short_quantity <= 0 or self.average_entry_price <= 0:
            return None
        from kxian_bot.models import Signal

        if self.stop_loss_pct > 0:
            stop_price = self.average_entry_price * (1 + self.stop_loss_pct / 100)
            if candle.high >= stop_price:
                return Signal(symbol=symbol, side="buy", price=stop_price, reason="short_stop_loss_triggered")
        if self.take_profit_pct > 0:
            take_profit_price = self.average_entry_price * (1 - self.take_profit_pct / 100)
            if candle.low <= take_profit_price:
                return Signal(symbol=symbol, side="buy", price=take_profit_price, reason="short_take_profit_triggered")
        if self.trailing_stop_pct > 0 and self.trailing_low_price > 0 and self.trailing_low_price < self.average_entry_price:
            trailing_stop_price = self.trailing_low_price * (1 + self.trailing_stop_pct / 100)
            if candle.high >= trailing_stop_price:
                return Signal(symbol=symbol, side="buy", price=trailing_stop_price, reason="short_trailing_stop_triggered")
        return None

    def _execution_price(self, side: str, signal_price: float) -> float:
        if side == "sell":
            return signal_price * (1 - self.slippage_rate)
        return signal_price * (1 + self.slippage_rate)

    def _equity(self, mark_price: float) -> float:
        if self.short_quantity <= 0 or self.average_entry_price <= 0:
            return self.usdt_balance
        return self.usdt_balance + (self.average_entry_price - mark_price) * self.short_quantity


def _return_pct(initial_equity: float, final_equity: float) -> float:
    if initial_equity == 0:
        return 0.0
    return (final_equity - initial_equity) / initial_equity * 100


def _max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak == 0:
            continue
        drawdown = (peak - equity) / peak * 100
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown


def _win_rate(realized_pnls: Sequence[float]) -> float:
    if not realized_pnls:
        return 0.0
    wins = sum(1 for pnl in realized_pnls if pnl > 0)
    return wins / len(realized_pnls) * 100


def _profit_factor(realized_pnls: Sequence[float]) -> float:
    gross_profit = sum(pnl for pnl in realized_pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in realized_pnls if pnl < 0))
    if gross_loss == 0:
        return 0.0 if gross_profit == 0 else gross_profit
    return gross_profit / gross_loss


def _floor_quantity(value: float) -> float:
    return math.floor(value * 100_000_000) / 100_000_000


def _risk_timestamp(open_time: int) -> float:
    numeric = float(open_time)
    return numeric / 1000 if numeric > 10_000_000_000 else 1_700_000_000.0 + numeric


def _protective_exit_signal(
    symbol: str,
    candle: Candle,
    asset_balance: float,
    average_entry_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float,
    trailing_peak_price: float,
):
    if asset_balance <= 0 or average_entry_price <= 0:
        return None
    from kxian_bot.models import Signal

    if stop_loss_pct > 0:
        stop_price = average_entry_price * (1 - stop_loss_pct / 100)
        if candle.low <= stop_price:
            return Signal(symbol=symbol, side="sell", price=stop_price, reason="stop_loss_triggered")
    if take_profit_pct > 0:
        take_profit_price = average_entry_price * (1 + take_profit_pct / 100)
        if candle.high >= take_profit_price:
            return Signal(symbol=symbol, side="sell", price=take_profit_price, reason="take_profit_triggered")
    if trailing_stop_pct > 0 and trailing_peak_price > average_entry_price:
        trailing_stop_price = trailing_peak_price * (1 - trailing_stop_pct / 100)
        if candle.low <= trailing_stop_price:
            return Signal(symbol=symbol, side="sell", price=trailing_stop_price, reason="trailing_stop_triggered")
    return None


def _is_protective_exit(reason: str) -> bool:
    return reason in {"stop_loss_triggered", "take_profit_triggered", "trailing_stop_triggered"}
