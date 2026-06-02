import base64
import hashlib
import hmac
import json

import pytest
import requests

from kxian_bot.brokers.live import LiveBrokerPlaceholder
from kxian_bot.config import RuntimeConfig
from kxian_bot.models import OrderRequest, SignedOrderRequest


def test_live_broker_placeholder_rejects_without_network_call():
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="binance",
            allow_live=True,
            binance_api_key="key",
            binance_api_secret="secret",
        )
    )
    order = OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.01, price=100)

    fill = broker.execute(order)

    assert fill.status == "rejected"
    assert fill.reason == "dry_run_signed_request_built"


def test_binance_signed_dry_run_order_request():
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="binance",
            allow_live=True,
            binance_api_key="api-key",
            binance_api_secret="secret",
        )
    )
    order = OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.01, price=100)

    request = broker.build_order_request(order, timestamp="1499827319559")

    payload = "symbol=BTCUSDT&side=BUY&type=LIMIT&timeInForce=GTC&quantity=0.01&price=100&recvWindow=5000&timestamp=1499827319559"
    expected_signature = hmac.new(b"secret", payload.encode("utf-8"), hashlib.sha256).hexdigest()
    assert request.method == "POST"
    assert request.url == "https://testnet.binance.vision/api/v3/order"
    assert request.headers["X-MBX-APIKEY"] == "api-key"
    assert request.params["signature"] == expected_signature
    assert request.signature_payload == payload
    assert "secret" not in request.model_dump_json()


def test_okx_signed_demo_order_request():
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="okx",
            allow_live=True,
            okx_api_key="api-key",
            okx_api_secret="secret",
            okx_api_passphrase="passphrase",
        )
    )
    order = OrderRequest(symbol="BTCUSDT", side="sell", quantity=0.02, price=101)

    request = broker.build_order_request(order, timestamp="2020-12-08T09:08:57.715Z")

    body = json.dumps(
        {
            "instId": "BTC-USDT",
            "tdMode": "cash",
            "side": "sell",
            "ordType": "limit",
            "sz": "0.02",
            "px": "101",
        },
        separators=(",", ":"),
    )
    payload = f"2020-12-08T09:08:57.715ZPOST/api/v5/trade/order{body}"
    expected_signature = base64.b64encode(
        hmac.new(b"secret", payload.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")

    assert request.method == "POST"
    assert request.url == "https://www.okx.com/api/v5/trade/order"
    assert request.headers["OK-ACCESS-KEY"] == "api-key"
    assert request.headers["OK-ACCESS-PASSPHRASE"] == "passphrase"
    assert request.headers["x-simulated-trading"] == "1"
    assert request.headers["OK-ACCESS-SIGN"] == expected_signature
    assert request.body == body
    assert request.signature_payload == payload
    assert "secret" not in request.model_dump_json()


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError("boom")
            error.response = self
            raise error


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def _next_response(self):
        if isinstance(self.response, list):
            return self.response[len(self.calls) - 1]
        return self.response

    def post(self, url, headers=None, params=None, data=None, timeout=None):
        self.calls.append(("POST", url, headers, params, data, timeout))
        return self._next_response()

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(("GET", url, headers, params, None, timeout))
        return self._next_response()

    def delete(self, url, headers=None, params=None, data=None, timeout=None):
        self.calls.append(("DELETE", url, headers, params, data, timeout))
        return self._next_response()


def test_binance_testnet_submit_order_uses_mock_http_and_maps_status():
    session = FakeSession(
        FakeResponse(
            {
                "symbol": "BTCUSDT",
                "orderId": 123,
                "status": "NEW",
                "executedQty": "0",
                "price": "100",
                "side": "BUY",
            }
        )
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.01, price=100))

    assert result.status == "submitted"
    assert result.exchange_order_id == "123"
    assert session.calls[0][0] == "POST"
    assert session.calls[0][1] == "https://testnet.binance.vision/api/v3/order"
    assert "secret" not in result.model_dump_json()


def test_binance_testnet_submit_order_blocks_production_endpoint():
    session = FakeSession(FakeResponse({"orderId": 123, "status": "NEW"}))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            use_testnet=False,
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.01, price=100))

    assert result.status == "rejected"
    assert result.reason == "testnet_endpoint_required"
    assert session.calls == []


def test_live_submit_order_blocks_when_dry_run_enabled():
    session = FakeSession(FakeResponse({"orderId": 123, "status": "NEW"}))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="binance",
            allow_live=True,
            use_testnet=False,
            live_dry_run=True,
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.01, price=100))

    assert result.status == "rejected"
    assert result.reason == "live_dry_run_enabled"
    assert session.calls == []


def test_live_submit_order_blocks_when_production_credentials_are_not_confirmed():
    session = FakeSession(FakeResponse({"orderId": 123, "status": "NEW"}))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="binance",
            allow_live=True,
            use_testnet=False,
            live_dry_run=False,
            enable_live_autotrade=True,
            live_confirmation="LIVE:binance:BTCUSDT:1m",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.01, price=100))

    assert result.status == "rejected"
    assert result.reason == "live_credentials_not_confirmed"
    assert session.calls == []


def test_live_submit_order_uses_production_endpoint_only_after_confirmation():
    session = FakeSession(
        FakeResponse(
            {
                "symbol": "BTCUSDT",
                "orderId": 123,
                "status": "NEW",
                "executedQty": "0",
                "price": "100",
                "side": "BUY",
            }
        )
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="binance",
            allow_live=True,
            use_testnet=False,
            live_dry_run=False,
            enable_live_autotrade=True,
            live_confirmation="LIVE:binance:BTCUSDT:1m",
            live_credentials_confirmed=True,
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.01, price=100))

    assert result.status == "submitted"
    assert result.exchange_order_id == "123"
    assert session.calls[0][0] == "POST"
    assert session.calls[0][1] == "https://api.binance.com/api/v3/order"


def test_binance_testnet_order_status_and_cancel():
    status_session = FakeSession(FakeResponse({"symbol": "BTCUSDT", "orderId": 123, "status": "FILLED", "executedQty": "0.01", "price": "100", "side": "BUY"}))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=status_session,
    )

    status = broker.order_status("BTCUSDT", "123")
    canceled = broker.cancel_order("BTCUSDT", "123")

    assert status.status == "filled"
    assert canceled.status == "filled"
    assert status_session.calls[0][0] == "GET"
    assert status_session.calls[1][0] == "DELETE"


def test_binance_filled_order_uses_average_execution_price():
    session = FakeSession(
        FakeResponse(
            {
                "symbol": "BTCUSDT",
                "orderId": 123,
                "status": "FILLED",
                "executedQty": "0.02",
                "cummulativeQuoteQty": "2.01",
                "price": "100",
                "side": "BUY",
            }
        )
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    status = broker.order_status("BTCUSDT", "123")

    assert status.status == "filled"
    assert status.quantity == 0.02
    assert status.price == pytest.approx(100.5)


def test_binance_account_balance_sync_parses_base_and_quote_assets():
    session = FakeSession(
        FakeResponse(
            {
                "balances": [
                    {"asset": "BTC", "free": "0.25", "locked": "0.01"},
                    {"asset": "USDT", "free": "123.45", "locked": "6.7"},
                ]
            }
        )
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.account_balance("BTCUSDT")

    assert result.status == "synced"
    assert result.base_asset == "BTC"
    assert result.quote_asset == "USDT"
    assert result.asset_balance == 0.25
    assert result.asset_locked == 0.01
    assert result.usdt_balance == 123.45
    assert result.quote_locked == 6.7
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1] == "https://testnet.binance.vision/api/v3/account"
    assert "secret" not in result.model_dump_json()


def test_binance_trade_history_parses_fills():
    session = FakeSession(
        FakeResponse(
            [
                {
                    "symbol": "BTCUSDT",
                    "id": 7,
                    "orderId": 123,
                    "price": "100.5",
                    "qty": "0.02",
                    "time": 1700000000000,
                    "isBuyer": True,
                }
            ]
        )
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.trade_history("BTCUSDT", limit=10)

    assert result.status == "synced"
    assert len(result.fills) == 1
    assert result.fills[0].side == "buy"
    assert result.fills[0].quantity == 0.02
    assert result.fills[0].price == 100.5
    assert result.fills[0].exchange_order_id == "123"
    assert result.fills[0].exchange_trade_id == "7"
    assert result.fills[0].timestamp == 1700000000000
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1] == "https://testnet.binance.vision/api/v3/myTrades"


def test_okx_demo_submit_order_uses_simulated_trading_header():
    session = FakeSession(FakeResponse({"data": [{"ordId": "abc", "state": "live", "sCode": "0"}]}))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="okx",
            okx_api_key="api-key",
            okx_api_secret="secret",
            okx_api_passphrase="passphrase",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.01, price=100))

    assert result.status == "submitted"
    assert result.exchange_order_id == "abc"
    assert session.calls[0][2]["x-simulated-trading"] == "1"


def test_okx_filled_order_uses_average_execution_price():
    session = FakeSession(
        FakeResponse(
            {
                "data": [
                    {
                        "ordId": "abc",
                        "state": "filled",
                        "sCode": "0",
                        "side": "buy",
                        "accFillSz": "0.02",
                        "avgPx": "100.5",
                        "px": "101",
                    }
                ]
            }
        )
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="okx",
            okx_api_key="api-key",
            okx_api_secret="secret",
            okx_api_passphrase="passphrase",
        ),
        session=session,
    )

    status = broker.order_status("BTCUSDT", "abc")

    assert status.status == "filled"
    assert status.quantity == 0.02
    assert status.price == pytest.approx(100.5)


def test_okx_account_balance_sync_parses_base_and_quote_assets():
    session = FakeSession(
        FakeResponse(
            {
                "data": [
                    {
                        "details": [
                            {"ccy": "BTC", "cashBal": "0.31", "availBal": "0.3"},
                            {"ccy": "USDT", "cashBal": "205", "availBal": "200"},
                        ]
                    }
                ]
            }
        )
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="okx",
            okx_api_key="api-key",
            okx_api_secret="secret",
            okx_api_passphrase="passphrase",
        ),
        session=session,
    )

    result = broker.account_balance("BTCUSDT")

    assert result.status == "synced"
    assert result.base_asset == "BTC"
    assert result.quote_asset == "USDT"
    assert result.asset_balance == 0.3
    assert result.asset_locked == pytest.approx(0.01)
    assert result.usdt_balance == 200
    assert result.quote_locked == 5
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1] == "https://www.okx.com/api/v5/account/balance"
    assert session.calls[0][2]["x-simulated-trading"] == "1"


def test_okx_trade_history_parses_fills():
    session = FakeSession(
        FakeResponse(
            {
                "data": [
                    {
                        "instId": "BTC-USDT",
                        "tradeId": "trade-7",
                        "ordId": "order-123",
                        "fillPx": "100.5",
                        "fillSz": "0.02",
                        "side": "sell",
                        "ts": "1700000000000",
                    }
                ]
            }
        )
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="okx",
            okx_api_key="api-key",
            okx_api_secret="secret",
            okx_api_passphrase="passphrase",
        ),
        session=session,
    )

    result = broker.trade_history("BTCUSDT", limit=10)

    assert result.status == "synced"
    assert len(result.fills) == 1
    assert result.fills[0].symbol == "BTCUSDT"
    assert result.fills[0].side == "sell"
    assert result.fills[0].quantity == 0.02
    assert result.fills[0].price == 100.5
    assert result.fills[0].exchange_order_id == "order-123"
    assert result.fills[0].exchange_trade_id == "trade-7"
    assert result.fills[0].timestamp == 1700000000000
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1] == "https://www.okx.com/api/v5/trade/fills-history"


def test_bitget_signed_live_order_request():
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="bitget",
            allow_live=True,
            use_testnet=False,
            bitget_api_key="api-key",
            bitget_api_secret="secret",
            bitget_api_passphrase="passphrase",
        )
    )
    order = OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.0001, price=50000)

    request = broker.build_order_request(order, timestamp="1700000000000")

    body = json.dumps(
        {
            "symbol": "BTCUSDT",
            "side": "buy",
            "orderType": "limit",
            "force": "gtc",
            "price": "50000",
            "size": "0.0001",
        },
        separators=(",", ":"),
    )
    payload = f"1700000000000POST/api/v2/spot/trade/place-order{body}"
    expected_signature = base64.b64encode(
        hmac.new(b"secret", payload.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")

    assert request.method == "POST"
    assert request.url == "https://api.bitget.com/api/v2/spot/trade/place-order"
    assert request.headers["ACCESS-KEY"] == "api-key"
    assert request.headers["ACCESS-PASSPHRASE"] == "passphrase"
    assert request.headers["ACCESS-SIGN"] == expected_signature
    assert request.body == body
    assert request.signature_payload == payload
    dumped = request.model_dump_json()
    assert "api-key" not in dumped
    assert "passphrase" not in dumped
    assert expected_signature not in dumped
    assert payload not in dumped
    assert "secret" not in dumped
    assert "ACCESS-KEY" not in dumped or "<redacted>" in dumped


def test_bitget_get_request_signs_sorted_query_params():
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="bitget",
            allow_live=True,
            use_testnet=False,
            bitget_api_key="api-key",
            bitget_api_secret="secret",
            bitget_api_passphrase="passphrase",
        )
    )

    request = broker._build_bitget_signed_request(
        "GET",
        "/api/v2/spot/trade/orderInfo",
        timestamp="1700000000000",
        params={"symbol": "BTCUSDT", "orderId": "abc"},
    )

    payload = "1700000000000GET/api/v2/spot/trade/orderInfo?orderId=abc&symbol=BTCUSDT"
    expected_signature = base64.b64encode(
        hmac.new(b"secret", payload.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    assert request.params == {"orderId": "abc", "symbol": "BTCUSDT"}
    assert request.signature_payload == payload
    assert request.headers["ACCESS-SIGN"] == expected_signature


def test_bitget_testnet_submit_order_is_blocked():
    session = FakeSession(FakeResponse({"code": "00000", "data": {"orderId": "abc"}}))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="bitget",
            bitget_api_key="api-key",
            bitget_api_secret="secret",
            bitget_api_passphrase="passphrase",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.0001, price=50000))

    assert result.status == "rejected"
    assert result.reason == "bitget_testnet_not_supported"
    assert session.calls == []


def test_bitget_live_submit_order_uses_production_endpoint_after_confirmation():
    session = FakeSession(
        FakeResponse(
            {
                "code": "00000",
                "data": {
                    "symbol": "BTCUSDT",
                    "orderId": "abc",
                    "status": "live",
                    "side": "buy",
                    "size": "0.0001",
                    "price": "50000",
                },
            }
        )
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="bitget",
            allow_live=True,
            use_testnet=False,
            live_dry_run=False,
            enable_live_autotrade=True,
            live_confirmation="LIVE:bitget:BTCUSDT:1m",
            live_credentials_confirmed=True,
            bitget_api_key="api-key",
            bitget_api_secret="secret",
            bitget_api_passphrase="passphrase",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.0001, price=50000))

    assert result.status == "submitted"
    assert result.exchange_order_id == "abc"
    assert session.calls[0][0] == "POST"
    assert session.calls[0][1] == "https://api.bitget.com/api/v2/spot/trade/place-order"
    assert "ACCESS-SIGN" in session.calls[0][2]


def test_bitget_order_status_cancel_balance_and_fills():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "code": "00000",
                    "data": {
                        "symbol": "BTCUSDT",
                        "orderId": "abc",
                        "status": "filled",
                        "side": "buy",
                        "dealSize": "0.0001",
                        "dealFunds": "5",
                        "price": "50000",
                    },
                }
            ),
            FakeResponse({"code": "00000", "data": {"orderId": "abc"}}),
            FakeResponse({"code": "00000", "data": [{"coin": "BTC", "available": "0.01", "frozen": "0.001"}]}),
            FakeResponse({"code": "00000", "data": [{"coin": "USDT", "available": "9", "frozen": "1"}]}),
            FakeResponse(
                {
                    "code": "00000",
                    "data": [
                        {
                            "symbol": "BTCUSDT",
                            "orderId": "abc",
                            "tradeId": "trade-1",
                            "side": "buy",
                            "size": "0.0001",
                            "price": "50000",
                            "cTime": "1700000000000",
                        }
                    ],
                }
            ),
        ]
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="bitget",
            allow_live=True,
            use_testnet=False,
            bitget_api_key="api-key",
            bitget_api_secret="secret",
            bitget_api_passphrase="passphrase",
        ),
        session=session,
    )

    order = broker.order_status("BTCUSDT", "abc")
    canceled = broker.cancel_order("BTCUSDT", "abc")
    balance = broker.account_balance("BTCUSDT")
    fills = broker.trade_history("BTCUSDT")

    assert order.status == "filled"
    assert order.quantity == 0.0001
    assert order.price == pytest.approx(50000)
    assert canceled.status == "canceled"
    assert balance.status == "synced"
    assert balance.asset_balance == 0.01
    assert balance.asset_locked == 0.001
    assert balance.usdt_balance == 9
    assert balance.quote_locked == 1
    assert fills.status == "synced"
    assert fills.fills[0].exchange_trade_id == "trade-1"
    assert [call[1] for call in session.calls] == [
        "https://api.bitget.com/api/v2/spot/trade/orderInfo",
        "https://api.bitget.com/api/v2/spot/trade/cancel-order",
        "https://api.bitget.com/api/v2/spot/account/assets",
        "https://api.bitget.com/api/v2/spot/account/assets",
        "https://api.bitget.com/api/v2/spot/trade/fills",
    ]
    assert "secret" not in order.model_dump_json()
    assert "secret" not in balance.model_dump_json()


def test_bitget_api_errors_are_classified_without_secrets():
    session = FakeSession(FakeResponse({"code": "40009", "msg": "signature invalid"}, status_code=400))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="bitget",
            allow_live=True,
            use_testnet=False,
            live_dry_run=False,
            enable_live_autotrade=True,
            live_confirmation="LIVE:bitget:BTCUSDT:1m",
            live_credentials_confirmed=True,
            bitget_api_key="api-key",
            bitget_api_secret="secret",
            bitget_api_passphrase="passphrase",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.0001, price=50000))

    assert result.status == "rejected"
    assert result.reason == "exchange_invalid_signature"
    assert "secret" not in result.model_dump_json()


def test_signed_order_request_redacts_sensitive_fields():
    request = SignedOrderRequest(
        method="POST",
        url="https://api.bitget.com/api/v2/spot/trade/place-order",
        headers={
            "ACCESS-KEY": "api-key",
            "ACCESS-SIGN": "signature",
            "ACCESS-PASSPHRASE": "passphrase",
            "Content-Type": "application/json",
        },
        params={"signature": "query-signature", "foo": "bar"},
        body='{"hello":"world"}',
        signature_payload="payload",
    )

    dumped = request.model_dump()

    assert dumped["headers"]["ACCESS-KEY"] == "<redacted>"
    assert dumped["headers"]["ACCESS-SIGN"] == "<redacted>"
    assert dumped["headers"]["ACCESS-PASSPHRASE"] == "<redacted>"
    assert dumped["params"]["signature"] == "<redacted>"
    assert dumped["signature_payload"] == "<redacted>"


def test_bitget_order_response_requires_order_id_and_known_status():
    session = FakeSession(
        [
            FakeResponse({"code": "00000", "data": {"symbol": "BTCUSDT", "status": "live"}}),
            FakeResponse({"code": "00000", "data": {"symbol": "BTCUSDT", "orderId": "abc", "status": "mystery"}}),
            FakeResponse({"code": "00000", "data": {"symbol": "BTCUSDT", "orderId": "abc"}}),
            FakeResponse({"code": "00000", "data": {}}),
        ]
    )
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="live",
            exchange="bitget",
            allow_live=True,
            use_testnet=False,
            live_dry_run=False,
            enable_live_autotrade=True,
            live_confirmation="LIVE:bitget:BTCUSDT:1m",
            live_credentials_confirmed=True,
            bitget_api_key="api-key",
            bitget_api_secret="secret",
            bitget_api_passphrase="passphrase",
        ),
        session=session,
    )

    missing_id = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.0001, price=50000))
    unknown_status = broker.order_status("BTCUSDT", "abc")
    missing_status = broker.order_status("BTCUSDT", "abc")
    incomplete_cancel = broker.cancel_order("BTCUSDT", "")

    assert missing_id.status == "rejected"
    assert missing_id.reason == "exchange_response_incomplete"
    assert unknown_status.status == "rejected"
    assert unknown_status.exchange_order_id == "abc"
    assert missing_status.status == "rejected"
    assert missing_status.reason == "exchange_response_incomplete"
    assert incomplete_cancel.status == "rejected"
    assert incomplete_cancel.reason == "exchange_cancel_response_incomplete"


def test_http_error_is_redacted():
    session = FakeSession(FakeResponse({"msg": "bad key"}, status_code=401))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.submit_order(OrderRequest(symbol="BTCUSDT", side="buy", quantity=0.01, price=100))

    assert result.status == "rejected"
    assert result.reason == "exchange_http_401"
    assert "secret" not in result.model_dump_json()


def test_account_balance_http_error_is_redacted():
    session = FakeSession(FakeResponse({"msg": "bad key"}, status_code=401))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.account_balance("BTCUSDT")

    assert result.status == "rejected"
    assert result.reason == "exchange_http_401"
    assert "secret" not in result.model_dump_json()


def test_trade_history_http_error_is_redacted():
    session = FakeSession(FakeResponse({"msg": "bad key"}, status_code=401))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.trade_history("BTCUSDT")

    assert result.status == "rejected"
    assert result.reason == "exchange_http_401"
    assert result.fills == []
    assert "secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("status_code", "expected_reason"),
    [
        (403, "exchange_http_403"),
        (429, "exchange_rate_limited"),
        (500, "exchange_server_error"),
    ],
)
def test_http_error_reason_distinguishes_common_exchange_failures(status_code, expected_reason):
    session = FakeSession(FakeResponse({"msg": "exchange failure"}, status_code=status_code))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    result = broker.account_balance("BTCUSDT")

    assert result.status == "rejected"
    assert result.reason == expected_reason
    assert "secret" not in result.model_dump_json()


def test_timeout_error_reason_is_redacted():
    class TimeoutSession:
        def get(self, *args, **kwargs):
            raise requests.Timeout("timed out")

    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=TimeoutSession(),
    )

    result = broker.account_balance("BTCUSDT")

    assert result.status == "rejected"
    assert result.reason == "exchange_timeout"
    assert "secret" not in result.model_dump_json()


def test_okx_top_level_api_error_rejects_order_status_balance_and_trade_history():
    session = FakeSession(FakeResponse({"code": "50113", "msg": "invalid signature", "data": []}))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="okx",
            okx_api_key="api-key",
            okx_api_secret="secret",
            okx_api_passphrase="passphrase",
        ),
        session=session,
    )

    order = broker.order_status("BTCUSDT", "bad-order")
    balance = broker.account_balance("BTCUSDT")
    trades = broker.trade_history("BTCUSDT")

    assert order.status == "rejected"
    assert order.reason == "exchange_api_error"
    assert balance.status == "rejected"
    assert balance.reason == "exchange_api_error"
    assert trades.status == "rejected"
    assert trades.reason == "exchange_api_error"
    assert trades.fills == []
    assert "secret" not in order.model_dump_json()
    assert "secret" not in balance.model_dump_json()
    assert "secret" not in trades.model_dump_json()


def test_binance_api_error_payload_rejects_order_and_account_balance():
    session = FakeSession(FakeResponse({"code": -1022, "msg": "signature invalid"}))
    broker = LiveBrokerPlaceholder(
        RuntimeConfig(
            mode="testnet",
            exchange="binance",
            binance_api_key="api-key",
            binance_api_secret="secret",
        ),
        session=session,
    )

    order = broker.order_status("BTCUSDT", "123")
    balance = broker.account_balance("BTCUSDT")

    assert order.status == "rejected"
    assert order.reason == "exchange_api_error"
    assert balance.status == "rejected"
    assert balance.reason == "exchange_api_error"
    assert "secret" not in order.model_dump_json()
    assert "secret" not in balance.model_dump_json()
