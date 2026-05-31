from __future__ import annotations

from kxian_bot.models import AccountBalance, Fill, OrderRequest, TradeHistoryResult


class PaperBroker:
    def __init__(self, starting_usdt: float) -> None:
        self.usdt_balance = starting_usdt
        self.asset_balance = 0.0

    def execute(self, order: OrderRequest) -> Fill:
        notional = order.quantity * order.price
        if order.side == "buy":
            if notional > self.usdt_balance:
                return Fill(
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    price=order.price,
                    status="rejected",
                    reason="insufficient_usdt",
                )
            self.usdt_balance -= notional
            self.asset_balance += order.quantity
        else:
            if order.quantity > self.asset_balance:
                return Fill(
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    price=order.price,
                    status="rejected",
                    reason="insufficient_asset",
                )
            self.asset_balance -= order.quantity
            self.usdt_balance += notional

        return Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            status="filled",
        )

    def account_balance(self, symbol: str) -> AccountBalance:
        return AccountBalance(
            symbol=symbol,
            base_asset=_base_asset(symbol),
            quote_asset="USDT",
            usdt_balance=self.usdt_balance,
            asset_balance=self.asset_balance,
            status="synced",
        )

    def trade_history(self, symbol: str, limit: int = 500) -> TradeHistoryResult:
        return TradeHistoryResult(symbol=symbol, status="synced", fills=[])


def _base_asset(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") and len(symbol) > 4 else symbol
