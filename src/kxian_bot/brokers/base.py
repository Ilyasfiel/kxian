from __future__ import annotations

from typing import Protocol

from kxian_bot.config import RuntimeConfig
from kxian_bot.brokers.live import LiveBrokerPlaceholder
from kxian_bot.brokers.paper import PaperBroker
from kxian_bot.models import AccountBalance, ExchangeOrder, Fill, OrderRequest, TradeHistoryResult


class Broker(Protocol):
    def execute(self, order: OrderRequest) -> Fill:
        ...

    def submit_order(self, order: OrderRequest) -> ExchangeOrder:
        ...

    def order_status(self, symbol: str, order_id: str) -> ExchangeOrder:
        ...

    def cancel_order(self, symbol: str, order_id: str) -> ExchangeOrder:
        ...

    def account_balance(self, symbol: str) -> AccountBalance:
        ...

    def trade_history(self, symbol: str, limit: int = 500) -> TradeHistoryResult:
        ...


def create_broker(config: RuntimeConfig) -> Broker:
    if config.mode == "paper":
        return PaperBroker(config.starting_usdt)
    return LiveBrokerPlaceholder(config)
