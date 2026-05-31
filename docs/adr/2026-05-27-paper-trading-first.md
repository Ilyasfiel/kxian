# ADR: Paper Trading First

## Status

Accepted

## Context

The user wants software that watches crypto K-lines and can trade automatically to earn USDT. Any direct live-trading implementation can create immediate financial loss if the strategy, market data, credentials, or exchange integration is wrong.

## Decision

The system defaults to paper trading. Live trading is disabled unless an explicit runtime flag is enabled and valid exchange credentials are configured.

## Consequences

- Safer iteration on strategy and execution logic
- Clear separation between strategy validation and capital deployment
- Slightly slower path to real trading, but materially lower operator risk
