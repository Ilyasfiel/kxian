from kxian_bot.execution_rules import normalize_order
from kxian_bot.models import OrderRequest, TradingRule


def test_normalize_order_floors_price_and_quantity_to_exchange_steps():
    rule = TradingRule(
        exchange="binance",
        symbol="BTCUSDT",
        price_step=0.1,
        quantity_step=0.001,
        min_quantity=0.001,
        min_notional=10,
    )

    order, reason = normalize_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.123456, price=100.987),
        rule,
    )

    assert reason == "exchange_rule_normalized"
    assert order.quantity == 0.123
    assert order.price == 100.9


def test_normalize_order_rejects_below_exchange_min_notional():
    rule = TradingRule(
        exchange="binance",
        symbol="BTCUSDT",
        price_step=0.01,
        quantity_step=0.001,
        min_quantity=0.001,
        min_notional=10,
    )

    order, reason = normalize_order(
        OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.02, price=100),
        rule,
    )

    assert order is None
    assert reason == "exchange_rule_min_notional"
