from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from kxian_bot.config import RuntimeConfig
from kxian_bot.models import OrderRequest, TradingRule


def default_trading_rule(config: RuntimeConfig) -> TradingRule:
    return TradingRule(
        exchange=config.exchange,
        symbol=config.symbol,
        price_step=config.price_step,
        quantity_step=config.quantity_step,
        min_quantity=config.min_exchange_quantity,
        min_notional=config.min_exchange_notional,
    )


def normalize_order(order: OrderRequest, rule: TradingRule) -> tuple[OrderRequest | None, str]:
    price = _floor_to_step(order.price, rule.price_step)
    quantity = _floor_to_step(order.quantity, rule.quantity_step)
    if price <= 0 or quantity <= 0:
        return None, "exchange_rule_zero_after_rounding"
    if quantity < rule.min_quantity:
        return None, "exchange_rule_min_quantity"
    if price * quantity < rule.min_notional:
        return None, "exchange_rule_min_notional"
    return (
        OrderRequest(
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=price,
        ),
        "exchange_rule_normalized",
    )


def _floor_to_step(value: float, step: float) -> float:
    value_decimal = Decimal(str(value))
    step_decimal = Decimal(str(step))
    if step_decimal <= 0:
        raise ValueError("step must be positive")
    return float((value_decimal / step_decimal).to_integral_value(rounding=ROUND_DOWN) * step_decimal)
