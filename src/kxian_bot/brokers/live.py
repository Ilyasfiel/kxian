from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from kxian_bot.config import RuntimeConfig, expected_live_confirmation
from kxian_bot.market_data import format_okx_symbol
from kxian_bot.models import AccountBalance, ExchangeOrder, Fill, OrderRequest, SignedOrderRequest, TradeHistoryResult


class LiveBrokerPlaceholder:
    BINANCE_TESTNET_URL = "https://testnet.binance.vision"
    BINANCE_PRODUCTION_URL = "https://api.binance.com"
    OKX_URL = "https://www.okx.com"
    BITGET_URL = "https://api.bitget.com"

    def __init__(self, config: RuntimeConfig, session=None) -> None:
        self.config = config
        self.exchange = config.exchange
        self.session = session or requests.Session()
        self.usdt_balance = config.starting_usdt
        self.asset_balance = 0.0

    def execute(self, order: OrderRequest) -> Fill:
        self.build_order_request(order)
        return Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            status="rejected",
            reason="dry_run_signed_request_built",
        )

    def submit_order(self, order: OrderRequest) -> ExchangeOrder:
        block_reason = self._submit_block_reason()
        if block_reason:
            return ExchangeOrder(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                status="rejected",
                reason=block_reason,
            )
        request = self.build_order_request(order)
        try:
            if self.exchange == "binance":
                response = self.session.post(
                    request.url,
                    headers=request.headers,
                    params=request.params,
                    timeout=10,
                )
            elif self.exchange == "okx":
                response = self.session.post(
                    request.url,
                    headers=request.headers,
                    data=request.body,
                    timeout=10,
                )
            elif self.exchange == "bitget":
                response = self.session.post(
                    request.url,
                    headers=request.headers,
                    data=request.body,
                    timeout=10,
                )
            else:
                return ExchangeOrder(symbol=order.symbol, side=order.side, status="rejected", reason="unsupported_exchange")
            response.raise_for_status()
            return self._parse_order_response(response.json(), order.symbol, order.side)
        except requests.RequestException as exc:
            return ExchangeOrder(symbol=order.symbol, side=order.side, status="rejected", reason=_http_error_reason(exc))

    def order_status(self, symbol: str, order_id: str) -> ExchangeOrder:
        try:
            if self.exchange == "binance":
                request = self._build_binance_order_lookup(symbol, order_id)
                response = self.session.get(request.url, headers=request.headers, params=request.params, timeout=10)
            elif self.exchange == "okx":
                request = self._build_okx_order_lookup(symbol, order_id)
                response = self.session.get(request.url, headers=request.headers, params=request.params, timeout=10)
            elif self.exchange == "bitget":
                request = self._build_bitget_order_lookup(symbol, order_id)
                response = self.session.get(request.url, headers=request.headers, params=request.params, timeout=10)
            else:
                return ExchangeOrder(symbol=symbol, status="rejected", exchange_order_id=order_id, reason="unsupported_exchange")
            response.raise_for_status()
            return self._parse_order_response(response.json(), symbol, None)
        except requests.RequestException as exc:
            return ExchangeOrder(symbol=symbol, status="rejected", exchange_order_id=order_id, reason=_http_error_reason(exc))

    def cancel_order(self, symbol: str, order_id: str) -> ExchangeOrder:
        try:
            if self.exchange == "binance":
                request = self._build_binance_order_lookup(symbol, order_id)
                response = self.session.delete(request.url, headers=request.headers, params=request.params, timeout=10)
            elif self.exchange == "okx":
                request = self._build_okx_cancel_order(symbol, order_id)
                response = self.session.post(request.url, headers=request.headers, data=request.body, timeout=10)
            elif self.exchange == "bitget":
                request = self._build_bitget_cancel_order(symbol, order_id)
                response = self.session.post(request.url, headers=request.headers, data=request.body, timeout=10)
            else:
                return ExchangeOrder(symbol=symbol, status="rejected", exchange_order_id=order_id, reason="unsupported_exchange")
            response.raise_for_status()
            if self.exchange == "bitget":
                return self._parse_bitget_cancel_response(response.json(), symbol, order_id)
            return self._parse_order_response(response.json(), symbol, None)
        except requests.RequestException as exc:
            return ExchangeOrder(symbol=symbol, status="rejected", exchange_order_id=order_id, reason=_http_error_reason(exc))

    def account_balance(self, symbol: str) -> AccountBalance:
        base_asset = _base_asset(symbol)
        quote_asset = "USDT"
        try:
            if self.exchange == "binance":
                request = self._build_binance_account_request()
                response = self.session.get(request.url, headers=request.headers, params=request.params, timeout=10)
                response.raise_for_status()
                return self._parse_binance_account_balance(response.json(), symbol, base_asset, quote_asset)
            if self.exchange == "okx":
                request = self._build_okx_account_balance()
                response = self.session.get(request.url, headers=request.headers, params=request.params, timeout=10)
                response.raise_for_status()
                return self._parse_okx_account_balance(response.json(), symbol, base_asset, quote_asset)
            if self.exchange != "bitget":
                return AccountBalance(
                    symbol=symbol,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                    status="rejected",
                    reason="unsupported_exchange",
                )
            base_request = self._build_bitget_account_request(base_asset)
            quote_request = self._build_bitget_account_request(quote_asset)
            base_response = self.session.get(base_request.url, headers=base_request.headers, params=base_request.params, timeout=10)
            quote_response = self.session.get(quote_request.url, headers=quote_request.headers, params=quote_request.params, timeout=10)
            base_response.raise_for_status()
            quote_response.raise_for_status()
            return self._parse_bitget_account_balance(
                base_response.json(),
                quote_response.json(),
                symbol,
                base_asset,
                quote_asset,
            )
        except requests.RequestException as exc:
            return AccountBalance(
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                status="rejected",
                reason=_http_error_reason(exc),
            )

    def trade_history(self, symbol: str, limit: int = 500) -> TradeHistoryResult:
        try:
            if self.exchange == "binance":
                request = self._build_binance_my_trades(symbol, limit)
                response = self.session.get(request.url, headers=request.headers, params=request.params, timeout=10)
                response.raise_for_status()
                return TradeHistoryResult(symbol=symbol, status="synced", fills=self._parse_binance_trades(response.json(), symbol))
            if self.exchange == "okx":
                request = self._build_okx_fills_history(symbol, limit)
                response = self.session.get(request.url, headers=request.headers, params=request.params, timeout=10)
                response.raise_for_status()
                return self._parse_okx_trades(response.json(), symbol)
            if self.exchange != "bitget":
                return TradeHistoryResult(symbol=symbol, status="rejected", reason="unsupported_exchange")
            request = self._build_bitget_fills_history(symbol, limit)
            response = self.session.get(request.url, headers=request.headers, params=request.params, timeout=10)
            response.raise_for_status()
            return self._parse_bitget_trades(response.json(), symbol)
        except requests.RequestException as exc:
            return TradeHistoryResult(symbol=symbol, status="rejected", reason=_http_error_reason(exc))

    def build_order_request(self, order: OrderRequest, timestamp: str | None = None) -> SignedOrderRequest:
        if self.exchange == "binance":
            return self._build_binance_order_request(order, timestamp)
        if self.exchange == "okx":
            return self._build_okx_order_request(order, timestamp)
        if self.exchange == "bitget":
            return self._build_bitget_order_request(order, timestamp)
        raise ValueError(f"Unsupported exchange: {self.exchange}")

    def _build_binance_order_request(self, order: OrderRequest, timestamp: str | None) -> SignedOrderRequest:
        timestamp = timestamp or str(int(time.time() * 1000))
        params = {
            "symbol": order.symbol,
            "side": order.side.upper(),
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": _format_number(order.quantity),
            "price": _format_number(order.price),
            "recvWindow": "5000",
            "timestamp": timestamp,
        }
        payload = urlencode(params)
        signature = hmac.new(
            self.config.binance_api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params = {**params, "signature": signature}
        base_url = self.BINANCE_TESTNET_URL if self.config.use_testnet else self.BINANCE_PRODUCTION_URL
        return SignedOrderRequest(
            method="POST",
            url=f"{base_url}/api/v3/order",
            headers={"X-MBX-APIKEY": self.config.binance_api_key},
            params=signed_params,
            signature_payload=payload,
        )

    def _build_binance_order_lookup(self, symbol: str, order_id: str) -> SignedOrderRequest:
        timestamp = str(int(time.time() * 1000))
        params = {
            "symbol": symbol,
            "orderId": order_id,
            "recvWindow": "5000",
            "timestamp": timestamp,
        }
        payload = urlencode(params)
        signature = hmac.new(
            self.config.binance_api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params = {**params, "signature": signature}
        base_url = self.BINANCE_TESTNET_URL if self.config.use_testnet else self.BINANCE_PRODUCTION_URL
        return SignedOrderRequest(
            method="GET",
            url=f"{base_url}/api/v3/order",
            headers={"X-MBX-APIKEY": self.config.binance_api_key},
            params=signed_params,
            signature_payload=payload,
        )

    def _build_binance_account_request(self) -> SignedOrderRequest:
        timestamp = str(int(time.time() * 1000))
        params = {
            "recvWindow": "5000",
            "timestamp": timestamp,
        }
        payload = urlencode(params)
        signature = hmac.new(
            self.config.binance_api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params = {**params, "signature": signature}
        base_url = self.BINANCE_TESTNET_URL if self.config.use_testnet else self.BINANCE_PRODUCTION_URL
        return SignedOrderRequest(
            method="GET",
            url=f"{base_url}/api/v3/account",
            headers={"X-MBX-APIKEY": self.config.binance_api_key},
            params=signed_params,
            signature_payload=payload,
        )

    def _build_binance_my_trades(self, symbol: str, limit: int) -> SignedOrderRequest:
        timestamp = str(int(time.time() * 1000))
        params = {
            "symbol": symbol,
            "limit": str(max(1, min(int(limit), 1000))),
            "recvWindow": "5000",
            "timestamp": timestamp,
        }
        payload = urlencode(params)
        signature = hmac.new(
            self.config.binance_api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params = {**params, "signature": signature}
        base_url = self.BINANCE_TESTNET_URL if self.config.use_testnet else self.BINANCE_PRODUCTION_URL
        return SignedOrderRequest(
            method="GET",
            url=f"{base_url}/api/v3/myTrades",
            headers={"X-MBX-APIKEY": self.config.binance_api_key},
            params=signed_params,
            signature_payload=payload,
        )

    def _build_okx_order_request(self, order: OrderRequest, timestamp: str | None) -> SignedOrderRequest:
        timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        request_path = "/api/v5/trade/order"
        body = json.dumps(
            {
                "instId": format_okx_symbol(order.symbol),
                "tdMode": "cash",
                "side": order.side,
                "ordType": "limit",
                "sz": _format_number(order.quantity),
                "px": _format_number(order.price),
            },
            separators=(",", ":"),
        )
        payload = f"{timestamp}POST{request_path}{body}"
        signature = base64.b64encode(
            hmac.new(
                self.config.okx_api_secret.encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        headers = {
            "OK-ACCESS-KEY": self.config.okx_api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.config.okx_api_passphrase,
            "Content-Type": "application/json",
        }
        if self.config.mode == "testnet":
            headers["x-simulated-trading"] = "1"
        return SignedOrderRequest(
            method="POST",
            url=f"{self.OKX_URL}{request_path}",
            headers=headers,
            body=body,
            signature_payload=payload,
        )

    def _build_okx_order_lookup(self, symbol: str, order_id: str) -> SignedOrderRequest:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        request_path = "/api/v5/trade/order"
        params = {"instId": format_okx_symbol(symbol), "ordId": order_id}
        query = urlencode(params)
        path_with_query = f"{request_path}?{query}"
        payload = f"{timestamp}GET{path_with_query}"
        signature = base64.b64encode(
            hmac.new(self.config.okx_api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        return SignedOrderRequest(
            method="GET",
            url=f"{self.OKX_URL}{request_path}",
            headers=self._okx_headers(signature, timestamp),
            params=params,
            signature_payload=payload,
        )

    def _build_okx_cancel_order(self, symbol: str, order_id: str) -> SignedOrderRequest:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        request_path = "/api/v5/trade/cancel-order"
        body = json.dumps({"instId": format_okx_symbol(symbol), "ordId": order_id}, separators=(",", ":"))
        payload = f"{timestamp}POST{request_path}{body}"
        signature = base64.b64encode(
            hmac.new(self.config.okx_api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        return SignedOrderRequest(
            method="POST",
            url=f"{self.OKX_URL}{request_path}",
            headers=self._okx_headers(signature, timestamp),
            body=body,
            signature_payload=payload,
        )

    def _build_okx_account_balance(self) -> SignedOrderRequest:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        request_path = "/api/v5/account/balance"
        params: dict[str, str] = {}
        payload = f"{timestamp}GET{request_path}"
        signature = base64.b64encode(
            hmac.new(self.config.okx_api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        return SignedOrderRequest(
            method="GET",
            url=f"{self.OKX_URL}{request_path}",
            headers=self._okx_headers(signature, timestamp),
            params=params,
            signature_payload=payload,
        )

    def _build_okx_fills_history(self, symbol: str, limit: int) -> SignedOrderRequest:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        request_path = "/api/v5/trade/fills-history"
        params = {
            "instId": format_okx_symbol(symbol),
            "limit": str(max(1, min(int(limit), 100))),
        }
        query = urlencode(params)
        path_with_query = f"{request_path}?{query}"
        payload = f"{timestamp}GET{path_with_query}"
        signature = base64.b64encode(
            hmac.new(self.config.okx_api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        return SignedOrderRequest(
            method="GET",
            url=f"{self.OKX_URL}{request_path}",
            headers=self._okx_headers(signature, timestamp),
            params=params,
            signature_payload=payload,
        )

    def _okx_headers(self, signature: str, timestamp: str) -> dict[str, str]:
        headers = {
            "OK-ACCESS-KEY": self.config.okx_api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.config.okx_api_passphrase,
            "Content-Type": "application/json",
        }
        if self.config.mode == "testnet":
            headers["x-simulated-trading"] = "1"
        return headers

    def _build_bitget_order_request(self, order: OrderRequest, timestamp: str | None) -> SignedOrderRequest:
        timestamp = timestamp or str(int(time.time() * 1000))
        request_path = "/api/v2/spot/trade/place-order"
        body = json.dumps(
            {
                "symbol": order.symbol,
                "side": order.side,
                "orderType": "limit",
                "force": "gtc",
                "price": _format_number(order.price),
                "size": _format_number(order.quantity),
            },
            separators=(",", ":"),
        )
        return self._build_bitget_signed_request("POST", request_path, timestamp=timestamp, body=body)

    def _build_bitget_order_lookup(self, symbol: str, order_id: str) -> SignedOrderRequest:
        timestamp = str(int(time.time() * 1000))
        request_path = "/api/v2/spot/trade/orderInfo"
        params = {"symbol": symbol, "orderId": order_id}
        return self._build_bitget_signed_request("GET", request_path, timestamp=timestamp, params=params)

    def _build_bitget_cancel_order(self, symbol: str, order_id: str) -> SignedOrderRequest:
        timestamp = str(int(time.time() * 1000))
        request_path = "/api/v2/spot/trade/cancel-order"
        body = json.dumps({"symbol": symbol, "orderId": order_id}, separators=(",", ":"))
        return self._build_bitget_signed_request("POST", request_path, timestamp=timestamp, body=body)

    def _build_bitget_account_request(self, coin: str) -> SignedOrderRequest:
        timestamp = str(int(time.time() * 1000))
        request_path = "/api/v2/spot/account/assets"
        return self._build_bitget_signed_request("GET", request_path, timestamp=timestamp, params={"coin": coin})

    def _build_bitget_fills_history(self, symbol: str, limit: int) -> SignedOrderRequest:
        timestamp = str(int(time.time() * 1000))
        request_path = "/api/v2/spot/trade/fills"
        params = {"symbol": symbol, "limit": str(max(1, min(int(limit), 100)))}
        return self._build_bitget_signed_request("GET", request_path, timestamp=timestamp, params=params)

    def _build_bitget_signed_request(
        self,
        method: str,
        request_path: str,
        *,
        timestamp: str,
        params: dict[str, str] | None = None,
        body: str = "",
    ) -> SignedOrderRequest:
        params = dict(sorted((params or {}).items()))
        query = urlencode(params)
        path_with_query = f"{request_path}?{query}" if query else request_path
        payload = f"{timestamp}{method.upper()}{path_with_query}{body}"
        signature = base64.b64encode(
            hmac.new(
                self.config.bitget_api_secret.encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return SignedOrderRequest(
            method=method.upper(),
            url=f"{self.BITGET_URL}{request_path}",
            headers={
                "ACCESS-KEY": self.config.bitget_api_key,
                "ACCESS-SIGN": signature,
                "ACCESS-TIMESTAMP": timestamp,
                "ACCESS-PASSPHRASE": self.config.bitget_api_passphrase,
                "Content-Type": "application/json",
                "locale": "en-US",
            },
            params=params,
            body=body,
            signature_payload=payload,
        )

    def _submit_block_reason(self) -> str:
        if self.config.mode == "testnet":
            if self.exchange == "binance" and not self.config.use_testnet:
                return "testnet_endpoint_required"
            if self.exchange == "bitget":
                return "bitget_testnet_not_supported"
            return ""
        if self.config.mode == "live":
            if not self.config.allow_live:
                return "live_not_allowed"
            if self.config.live_dry_run:
                return "live_dry_run_enabled"
            if not self.config.enable_live_autotrade:
                return "live_autotrade_disabled"
            if self.exchange == "binance" and self.config.use_testnet:
                return "live_endpoint_points_to_testnet"
            if self.exchange == "bitget" and self.config.use_testnet:
                return "live_endpoint_points_to_testnet"
            if self.config.live_confirmation != expected_live_confirmation(self.config):
                return "live_confirmation_required"
            if not self.config.live_credentials_confirmed:
                return "live_credentials_not_confirmed"
            return ""
        return "testnet_or_live_mode_required"

    def _parse_order_response(self, payload: dict, symbol: str, side: str | None) -> ExchangeOrder:
        if self.exchange == "binance":
            if "code" in payload and int(_float_value(payload.get("code"))) != 0:
                return ExchangeOrder(
                    symbol=str(payload.get("symbol", symbol)),
                    side=_lower_side(payload.get("side", side)),
                    status="rejected",
                    reason="exchange_api_error",
                )
            quantity = _float_value(payload.get("executedQty") or payload.get("origQty"))
            return ExchangeOrder(
                symbol=str(payload.get("symbol", symbol)),
                side=_lower_side(payload.get("side", side)),
                quantity=quantity,
                price=_binance_execution_price(payload, quantity),
                status=_map_binance_status(str(payload.get("status", ""))),
                exchange_order_id=str(payload.get("orderId", "")),
            )
        if self.exchange == "bitget":
            return self._parse_bitget_order_response(payload, symbol, side)
        error = _okx_payload_error(payload)
        if error:
            return ExchangeOrder(
                symbol=format_okx_symbol(symbol),
                side=_lower_side(side),
                status="rejected",
                reason=error,
            )
        data = payload.get("data", [])
        item = data[0] if data else {}
        code = str(item.get("sCode", "0"))
        reason = "exchange_api_error" if code != "0" else ""
        quantity = _float_value(item.get("accFillSz") or item.get("sz"))
        return ExchangeOrder(
            symbol=format_okx_symbol(symbol),
            side=_lower_side(item.get("side", side)),
            quantity=quantity,
            price=_float_value(item.get("avgPx") or item.get("fillPx") or item.get("px")),
            status="rejected" if code != "0" else _map_okx_status(str(item.get("state", "live"))),
            exchange_order_id=str(item.get("ordId", "")),
            reason=reason,
        )

    def _parse_bitget_order_response(self, payload: dict, symbol: str, side: str | None) -> ExchangeOrder:
        error = _bitget_payload_error(payload)
        if error:
            return ExchangeOrder(symbol=symbol, side=_lower_side(side), status="rejected", reason=error)
        item = _first_payload_item(payload)
        order_id = str(item.get("orderId") or item.get("orderIdStr") or item.get("id") or "")
        if not order_id:
            return ExchangeOrder(symbol=symbol, side=_lower_side(side), status="rejected", reason="exchange_response_incomplete")
        quantity = _float_value(
            item.get("dealSize")
            or item.get("filledSize")
            or item.get("filledQuantity")
            or item.get("size")
            or item.get("quantity")
        )
        price = _bitget_execution_price(item, quantity)
        raw_status = str(item.get("status") or item.get("state") or "").strip()
        status = _map_bitget_status(raw_status)
        reason = ""
        if status == "rejected" and raw_status and raw_status.lower() not in {"fail", "rejected"}:
            reason = "exchange_order_status_unknown"
        if not raw_status:
            return ExchangeOrder(
                symbol=str(item.get("symbol") or symbol),
                side=_lower_side(item.get("side", side)),
                quantity=quantity,
                price=price,
                status="rejected",
                exchange_order_id=order_id,
                reason="exchange_response_incomplete",
            )
        return ExchangeOrder(
            symbol=str(item.get("symbol") or symbol),
            side=_lower_side(item.get("side", side)),
            quantity=quantity,
            price=price,
            status=status,
            exchange_order_id=order_id,
            reason=reason,
        )

    def _parse_bitget_cancel_response(self, payload: dict, symbol: str, order_id: str) -> ExchangeOrder:
        error = _bitget_payload_error(payload)
        if error:
            return ExchangeOrder(symbol=symbol, status="rejected", exchange_order_id=order_id, reason=error)
        item = _first_payload_item(payload)
        cancel_id = str(item.get("orderId") or item.get("orderIdStr") or order_id or "")
        if not cancel_id:
            return ExchangeOrder(symbol=symbol, status="rejected", exchange_order_id=order_id, reason="exchange_cancel_response_incomplete")
        return ExchangeOrder(
            symbol=str(item.get("symbol") or symbol),
            side=_lower_side(item.get("side")),
            status="canceled",
            exchange_order_id=cancel_id,
        )

    def _parse_binance_account_balance(
        self,
        payload: dict,
        symbol: str,
        base_asset: str,
        quote_asset: str,
    ) -> AccountBalance:
        if "code" in payload and int(_float_value(payload.get("code"))) != 0:
            return AccountBalance(
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                status="rejected",
                reason="exchange_api_error",
            )
        balances = {str(item.get("asset", "")): item for item in payload.get("balances", [])}
        base = balances.get(base_asset, {})
        quote = balances.get(quote_asset, {})
        return AccountBalance(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            asset_balance=_float_value(base.get("free")),
            asset_locked=_float_value(base.get("locked")),
            usdt_balance=_float_value(quote.get("free")),
            quote_locked=_float_value(quote.get("locked")),
            status="synced",
        )

    def _parse_okx_account_balance(
        self,
        payload: dict,
        symbol: str,
        base_asset: str,
        quote_asset: str,
    ) -> AccountBalance:
        error = _okx_payload_error(payload)
        if error:
            return AccountBalance(
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                status="rejected",
                reason=error,
            )
        details = []
        for item in payload.get("data", []):
            details.extend(item.get("details", []) or [])
        balances = {str(item.get("ccy", "")): item for item in details}
        base = balances.get(base_asset, {})
        quote = balances.get(quote_asset, {})
        return AccountBalance(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            asset_balance=_float_value(base.get("availBal") or base.get("availEq") or base.get("cashBal")),
            asset_locked=_locked_okx_balance(base),
            usdt_balance=_float_value(quote.get("availBal") or quote.get("availEq") or quote.get("cashBal")),
            quote_locked=_locked_okx_balance(quote),
            status="synced",
        )

    def _parse_bitget_account_balance(
        self,
        base_payload: dict,
        quote_payload: dict,
        symbol: str,
        base_asset: str,
        quote_asset: str,
    ) -> AccountBalance:
        base_error = _bitget_payload_error(base_payload)
        quote_error = _bitget_payload_error(quote_payload)
        if base_error or quote_error:
            return AccountBalance(
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                status="rejected",
                reason=base_error or quote_error,
            )
        base = _bitget_asset_item(base_payload, base_asset)
        quote = _bitget_asset_item(quote_payload, quote_asset)
        return AccountBalance(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            asset_balance=_bitget_available_balance(base),
            asset_locked=_bitget_locked_balance(base),
            usdt_balance=_bitget_available_balance(quote),
            quote_locked=_bitget_locked_balance(quote),
            status="synced",
        )

    def _parse_binance_trades(self, payload: list[dict], symbol: str) -> list[Fill]:
        fills: list[Fill] = []
        for item in payload:
            quantity = _float_value(item.get("qty"))
            price = _float_value(item.get("price"))
            if quantity <= 0 or price <= 0:
                continue
            fills.append(
                Fill(
                    symbol=str(item.get("symbol") or symbol),
                    side="buy" if bool(item.get("isBuyer")) else "sell",
                    quantity=quantity,
                    price=price,
                    status="filled",
                    exchange_order_id=str(item.get("orderId", "")),
                    exchange_trade_id=str(item.get("id", "")),
                    timestamp=int(_float_value(item.get("time"))),
                )
            )
        return fills

    def _parse_okx_trades(self, payload: dict, symbol: str) -> TradeHistoryResult:
        error = _okx_payload_error(payload)
        if error:
            return TradeHistoryResult(symbol=symbol, status="rejected", reason=error)
        fills: list[Fill] = []
        for item in payload.get("data", []) or []:
            quantity = _float_value(item.get("fillSz") or item.get("sz"))
            price = _float_value(item.get("fillPx") or item.get("px"))
            side = _lower_side(item.get("side"))
            if quantity <= 0 or price <= 0 or side is None:
                continue
            fills.append(
                Fill(
                    symbol=str(item.get("instId") or format_okx_symbol(symbol)).replace("-", ""),
                    side=side,
                    quantity=quantity,
                    price=price,
                    status="filled",
                    exchange_order_id=str(item.get("ordId", "")),
                    exchange_trade_id=str(item.get("tradeId") or item.get("billId") or ""),
                    timestamp=int(_float_value(item.get("ts"))),
                )
            )
        return TradeHistoryResult(symbol=symbol, status="synced", fills=fills)

    def _parse_bitget_trades(self, payload: dict, symbol: str) -> TradeHistoryResult:
        error = _bitget_payload_error(payload)
        if error:
            return TradeHistoryResult(symbol=symbol, status="rejected", reason=error)
        fills: list[Fill] = []
        data = payload.get("data", [])
        if isinstance(data, dict):
            data = data.get("fillList") or data.get("fills") or data.get("data") or []
        for item in data or []:
            quantity = _float_value(item.get("size") or item.get("quantity") or item.get("baseVolume"))
            price = _float_value(item.get("price") or item.get("fillPrice"))
            side = _lower_side(item.get("side"))
            if quantity <= 0 or price <= 0 or side is None:
                continue
            fills.append(
                Fill(
                    symbol=str(item.get("symbol") or symbol),
                    side=side,
                    quantity=quantity,
                    price=price,
                    status="filled",
                    exchange_order_id=str(item.get("orderId") or ""),
                    exchange_trade_id=str(item.get("tradeId") or item.get("fillId") or item.get("id") or ""),
                    timestamp=int(_float_value(item.get("cTime") or item.get("uTime") or item.get("ts"))),
                )
            )
        return TradeHistoryResult(symbol=symbol, status="synced", fills=fills)


def _binance_execution_price(payload: dict, quantity: float) -> float:
    quote_qty = _float_value(payload.get("cummulativeQuoteQty"))
    if quantity > 0 and quote_qty > 0:
        return quote_qty / quantity
    return _float_value(payload.get("price"))


def _bitget_execution_price(payload: dict, quantity: float) -> float:
    average = _float_value(payload.get("priceAvg") or payload.get("avgPrice") or payload.get("avgPx"))
    if average > 0:
        return average
    quote_qty = _float_value(payload.get("dealFunds") or payload.get("filledAmount") or payload.get("quoteVolume"))
    if quantity > 0 and quote_qty > 0:
        return quote_qty / quantity
    return _float_value(payload.get("price"))


def _float_value(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _base_asset(symbol: str) -> str:
    normalized = symbol.replace("-", "").replace("_", "").upper()
    return normalized[:-4] if normalized.endswith("USDT") and len(normalized) > 4 else normalized


def _http_error_reason(exc: requests.RequestException) -> str:
    if isinstance(exc, (requests.Timeout, requests.ConnectTimeout, requests.ReadTimeout)):
        return "exchange_timeout"
    response = getattr(exc, "response", None)
    binance_reason = _binance_http_error_reason(response)
    if binance_reason:
        return binance_reason
    bitget_reason = _bitget_http_error_reason(response)
    if bitget_reason:
        return bitget_reason
    status_code = getattr(response, "status_code", None)
    if status_code in {401, 403}:
        return f"exchange_http_{status_code}"
    if status_code == 429:
        return "exchange_rate_limited"
    if isinstance(status_code, int) and status_code >= 500:
        return "exchange_server_error"
    if status_code:
        return f"exchange_http_{status_code}"
    return "exchange_http_error"


def _binance_http_error_reason(response) -> str:
    if response is None:
        return ""
    try:
        payload = response.json()
    except (ValueError, TypeError, AttributeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    code = int(_float_value(payload.get("code")))
    if code == -1022:
        return "exchange_invalid_signature"
    if code == -1021:
        return "exchange_invalid_timestamp"
    return ""


def _bitget_http_error_reason(response) -> str:
    if response is None:
        return ""
    try:
        payload = response.json()
    except (ValueError, TypeError, AttributeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    code = str(payload.get("code") or "")
    mapping = {
        "40001": "exchange_invalid_timestamp",
        "40003": "exchange_invalid_signature",
        "40004": "exchange_invalid_passphrase",
        "40005": "exchange_invalid_signature",
        "40006": "exchange_invalid_api_key",
        "40009": "exchange_invalid_signature",
        "40014": "exchange_permission_denied",
        "43012": "exchange_insufficient_balance",
        "43028": "exchange_min_notional",
    }
    return mapping.get(code, "")


def _locked_okx_balance(item: dict) -> float:
    total = _float_value(item.get("cashBal") or item.get("eq"))
    available = _float_value(item.get("availBal") or item.get("availEq") or item.get("cashBal"))
    return max(0.0, total - available)


def _bitget_available_balance(item: dict) -> float:
    return _float_value(
        item.get("available")
        or item.get("availableBalance")
        or item.get("avail")
        or item.get("free")
        or item.get("balance")
    )


def _bitget_locked_balance(item: dict) -> float:
    locked = _float_value(item.get("frozen") or item.get("locked") or item.get("hold"))
    if locked > 0:
        return locked
    total = _float_value(item.get("balance") or item.get("total") or item.get("equity"))
    available = _bitget_available_balance(item)
    return max(0.0, total - available)


def _okx_payload_error(payload: dict) -> str:
    if "code" not in payload:
        return ""
    return "" if str(payload.get("code")) == "0" else "exchange_api_error"


def _bitget_payload_error(payload: dict) -> str:
    code = str(payload.get("code") or "00000")
    if code == "00000":
        return ""
    mapping = {
        "40001": "exchange_invalid_timestamp",
        "40003": "exchange_invalid_signature",
        "40004": "exchange_invalid_passphrase",
        "40005": "exchange_invalid_signature",
        "40006": "exchange_invalid_api_key",
        "40009": "exchange_invalid_signature",
        "40014": "exchange_permission_denied",
        "43012": "exchange_insufficient_balance",
        "43028": "exchange_min_notional",
    }
    return mapping.get(code, "exchange_api_error")


def _first_payload_item(payload: dict) -> dict:
    data = payload.get("data", {})
    if isinstance(data, list):
        return data[0] if data else {}
    if isinstance(data, dict):
        for key in ("order", "orderInfo", "entrustedList", "orderList"):
            value = data.get(key)
            if isinstance(value, list):
                return value[0] if value else {}
            if isinstance(value, dict):
                return value
        return data
    return {}


def _bitget_asset_item(payload: dict, coin: str) -> dict:
    data = payload.get("data", [])
    if isinstance(data, dict):
        candidates = data.get("assets") or data.get("data") or data.get("list") or [data]
    else:
        candidates = data
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("coin") or item.get("coinName") or item.get("asset") or "").upper() == coin.upper():
            return item
    return {}


def _lower_side(value) -> str | None:
    if value is None:
        return None
    text = str(value).lower()
    if text in {"buy", "sell"}:
        return text
    return None


def _map_binance_status(status: str) -> str:
    mapping = {
        "NEW": "submitted",
        "PARTIALLY_FILLED": "partially_filled",
        "FILLED": "filled",
        "CANCELED": "canceled",
        "REJECTED": "rejected",
        "EXPIRED": "rejected",
    }
    return mapping.get(status.upper(), "rejected")


def _map_okx_status(status: str) -> str:
    mapping = {
        "live": "submitted",
        "partially_filled": "partially_filled",
        "filled": "filled",
        "canceled": "canceled",
    }
    return mapping.get(status, "submitted")


def _map_bitget_status(status: str) -> str:
    normalized = status.strip().lower()
    mapping = {
        "init": "submitted",
        "new": "submitted",
        "live": "submitted",
        "open": "submitted",
        "not_trigger": "submitted",
        "partially_filled": "partially_filled",
        "partial-fill": "partially_filled",
        "partial_filled": "partially_filled",
        "partiallyfilled": "partially_filled",
        "filled": "filled",
        "full-fill": "filled",
        "full_filled": "filled",
        "fullfilled": "filled",
        "cancelled": "canceled",
        "canceled": "canceled",
        "fail": "rejected",
        "rejected": "rejected",
    }
    return mapping.get(normalized, "rejected")
