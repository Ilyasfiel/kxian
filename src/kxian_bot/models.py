from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Side = Literal["buy", "sell"]
Mode = Literal["paper", "testnet", "live"]
Exchange = Literal["binance", "okx", "bitget"]
OrderStatus = Literal["submitted", "filled", "partially_filled", "canceled", "rejected"]


class Candle(BaseModel):
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


class Signal(BaseModel):
    symbol: str
    side: Side
    price: float
    reason: str


class OrderRequest(BaseModel):
    symbol: str
    side: Side
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)


class TradingRule(BaseModel):
    exchange: Exchange
    symbol: str
    price_step: float = Field(gt=0)
    quantity_step: float = Field(gt=0)
    min_quantity: float = Field(default=0.0, ge=0)
    min_notional: float = Field(default=0.0, ge=0)


class Fill(BaseModel):
    symbol: str
    side: Side
    quantity: float
    price: float
    status: Literal["filled", "rejected"]
    reason: str = ""
    exchange_order_id: str = ""
    exchange_trade_id: str = ""
    timestamp: int = 0


class RiskDecision(BaseModel):
    allowed: bool
    reason: str = ""


class SignedOrderRequest(BaseModel):
    method: str
    url: str
    headers: dict[str, str]
    params: dict[str, Any] = Field(default_factory=dict)
    body: str = ""
    signature_payload: str

    def model_dump(self, *args, **kwargs) -> dict[str, Any]:
        payload = super().model_dump(*args, **kwargs)
        payload["headers"] = _redact_signed_headers(payload.get("headers", {}))
        payload["params"] = _redact_signed_params(payload.get("params", {}))
        if payload.get("signature_payload"):
            payload["signature_payload"] = "<redacted>"
        return payload

    def model_dump_json(self, *args, **kwargs) -> str:
        import json

        return json.dumps(self.model_dump(*args, **kwargs), separators=(",", ":"))


def _redact_signed_headers(headers: dict[str, str]) -> dict[str, str]:
    sensitive = {
        "X-MBX-APIKEY",
        "OK-ACCESS-KEY",
        "OK-ACCESS-SIGN",
        "OK-ACCESS-PASSPHRASE",
        "ACCESS-KEY",
        "ACCESS-SIGN",
        "ACCESS-PASSPHRASE",
    }
    return {
        key: "<redacted>" if key.upper() in sensitive else value
        for key, value in dict(headers or {}).items()
    }


def _redact_signed_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        key: "<redacted>" if str(key).lower() == "signature" else value
        for key, value in dict(params or {}).items()
    }


class ExchangeOrder(BaseModel):
    symbol: str
    side: Side | None = None
    quantity: float = 0.0
    price: float = 0.0
    status: OrderStatus
    exchange_order_id: str = ""
    reason: str = ""


class AccountBalance(BaseModel):
    symbol: str
    base_asset: str
    quote_asset: str
    usdt_balance: float = 0.0
    asset_balance: float = 0.0
    quote_locked: float = 0.0
    asset_locked: float = 0.0
    status: Literal["synced", "rejected"]
    reason: str = ""


class TradeHistoryResult(BaseModel):
    symbol: str
    fills: list[Fill] = Field(default_factory=list)
    status: Literal["synced", "rejected"]
    reason: str = ""


class BacktestTrade(BaseModel):
    timestamp: int
    symbol: str
    side: Side
    quantity: float
    signal_price: float
    execution_price: float
    fee: float
    slippage: float
    pnl: float
    reason: str


class BacktestResult(BaseModel):
    initial_equity: float
    trade_count: int
    final_equity: float
    return_pct: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    fees_paid: float
    slippage_paid: float
    usdt_balance: float
    asset_balance: float
    trades: list[BacktestTrade] = Field(default_factory=list)


class BacktestRunSummary(BaseModel):
    run_id: str
    exchange: Exchange
    symbol: str
    interval: str
    start_time: int
    end_time: int
    strategy: str
    parameters: dict[str, Any]
    candle_count: int
    initial_equity: float
    final_equity: float
    return_pct: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    trade_count: int
    fees_paid: float
    slippage_paid: float


class BatchBacktestResult(BaseModel):
    exchange: Exchange
    symbol: str
    interval: str
    start_time: int
    end_time: int
    candle_count: int
    total_combinations: int
    valid_combinations: int
    skipped_combinations: int
    sort_by: str
    results: list[BacktestRunSummary]


class StressBacktestRunSummary(BaseModel):
    run_id: str
    exchange: Exchange
    symbol: str
    interval: str
    start_time: int
    end_time: int
    strategy: str
    parameters: dict[str, Any]
    candle_count: int
    scenario_count: int
    passed_scenarios: int
    failed_scenarios: int
    pass_rate: float
    worst_return_pct: float
    worst_drawdown_pct: float
    worst_profit_factor: float
    min_trade_count: int
    scenarios: list[dict[str, Any]] = Field(default_factory=list)


class WalkForwardRunSummary(BaseModel):
    run_id: str
    exchange: Exchange
    symbol: str
    interval: str
    start_time: int
    end_time: int
    strategy: str
    parameters: dict[str, Any]
    candle_count: int
    segment_count: int
    passed_segments: int
    failed_segments: int
    pass_rate: float
    total_trade_count: int
    min_segment_trade_count: int
    worst_return_pct: float
    worst_drawdown_pct: float
    worst_profit_factor: float
    segments: list[dict[str, Any]] = Field(default_factory=list)


class LoopEvent(BaseModel):
    loop_id: str
    iteration: int
    status: str
    mode: Mode
    exchange: Exchange
    symbol: str
    interval: str
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
