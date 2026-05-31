from kxian_bot.brokers.paper import PaperBroker
from kxian_bot.models import OrderRequest
from kxian_bot.risk import RiskManager


def test_risk_manager_caps_order_size():
    risk = RiskManager(risk_per_trade=0.1, max_position_usdt=300)

    quantity = risk.size_order(usdt_balance=1000, price=100)

    assert quantity == 1.0


def test_paper_broker_updates_balances_on_buy():
    broker = PaperBroker(starting_usdt=1000)
    order = OrderRequest(symbol="BTCUSDT", side="buy", quantity=1, price=100)

    fill = broker.execute(order)

    assert fill.status == "filled"
    assert broker.usdt_balance == 900
    assert broker.asset_balance == 1


def test_risk_manager_rejects_below_min_order():
    risk = RiskManager(risk_per_trade=0.1, max_position_usdt=300, min_order_usdt=20)

    decision = risk.validate(
        side="buy",
        quantity=0.1,
        price=100,
        usdt_balance=1000,
        asset_balance=0,
        current_equity=1000,
    )

    assert decision.allowed is False
    assert decision.reason == "below_min_order_usdt"


def test_risk_manager_rejects_sell_without_position():
    risk = RiskManager(risk_per_trade=0.1, max_position_usdt=300)

    decision = risk.validate(
        side="sell",
        quantity=1,
        price=100,
        usdt_balance=1000,
        asset_balance=0,
        current_equity=1000,
    )

    assert decision.allowed is False
    assert decision.reason == "insufficient_asset"


def test_risk_manager_rejects_buy_that_exceeds_total_position_cap():
    risk = RiskManager(risk_per_trade=0.1, max_position_usdt=100)

    decision = risk.validate(
        side="buy",
        quantity=0.6,
        price=100,
        usdt_balance=1000,
        asset_balance=0.5,
        current_equity=1000,
    )

    assert decision.allowed is False
    assert decision.reason == "max_position_exceeded"


def test_risk_manager_rejects_during_cooldown():
    risk = RiskManager(risk_per_trade=0.1, max_position_usdt=300, cooldown_seconds=60)
    risk.record_fill(timestamp=1000, equity=1000)

    decision = risk.validate(
        side="buy",
        quantity=1,
        price=100,
        usdt_balance=1000,
        asset_balance=0,
        current_equity=1000,
        now=1010,
    )

    assert decision.allowed is False
    assert decision.reason == "cooldown_active"


def test_risk_manager_allows_reduce_only_exit_through_entry_limits():
    risk = RiskManager(risk_per_trade=0.1, max_position_usdt=100, min_order_usdt=20, cooldown_seconds=60)
    risk.record_fill(timestamp=1000, equity=1000)

    decision = risk.validate(
        side="buy",
        quantity=0.1,
        price=100,
        usdt_balance=0,
        asset_balance=2,
        current_equity=800,
        now=1010,
        reduce_only=True,
    )

    assert decision.allowed is True


def test_risk_manager_reduce_only_sell_still_requires_position():
    risk = RiskManager(risk_per_trade=0.1, max_position_usdt=300)

    decision = risk.validate(
        side="sell",
        quantity=1,
        price=100,
        usdt_balance=1000,
        asset_balance=0,
        current_equity=1000,
        reduce_only=True,
    )

    assert decision.allowed is False
    assert decision.reason == "insufficient_asset"
