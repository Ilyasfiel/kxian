# Kxian Trading Bot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a crypto K-line watcher that can backtest a strategy, run automated paper trades, and keep a guarded path toward live trading.

**Architecture:** Use a small Python service with explicit layers for market data, strategy, risk controls, and broker execution. Default all execution to paper trading and require an explicit environment flag before any live order path can be enabled.

**Tech Stack:** Python 3.12, standard library, `requests`, `pydantic`, `pytest`

---

### Task 1: Bootstrap the project

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `.gitignore`
- Create: `.env.example`

**Step 1: Write the failing test**

No code test for bootstrap. Validate by importing package later.

**Step 2: Create minimal project metadata**

Add package metadata, dependencies, and test settings.

**Step 3: Add environment example and ignore rules**

Document paper trading defaults and secrets layout.

**Step 4: Verify**

Run: `python -m pytest`
Expected: test discovery works, possibly zero or initial tests pass.

### Task 2: Implement core domain models and config

**Files:**
- Create: `src/kxian_bot/config.py`
- Create: `src/kxian_bot/models.py`
- Create: `src/kxian_bot/__init__.py`
- Test: `tests/test_config.py`

**Step 1: Write failing tests**

Validate config defaults to paper mode and rejects live mode without required flags.

**Step 2: Implement config and typed models**

Add candle, signal, position, order, and runtime config models.

**Step 3: Verify**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

### Task 3: Implement market data and strategy engine

**Files:**
- Create: `src/kxian_bot/market_data.py`
- Create: `src/kxian_bot/indicators.py`
- Create: `src/kxian_bot/strategies/base.py`
- Create: `src/kxian_bot/strategies/moving_average_cross.py`
- Test: `tests/test_strategy.py`

**Step 1: Write failing tests**

Cover moving-average crossover buy and sell signal generation from candle history.

**Step 2: Implement market data parser and indicators**

Support Binance public klines response parsing into typed candles.

**Step 3: Implement strategy**

Add a simple MA cross strategy configurable by short and long windows.

**Step 4: Verify**

Run: `python -m pytest tests/test_strategy.py -v`
Expected: PASS

### Task 4: Implement risk manager and paper broker

**Files:**
- Create: `src/kxian_bot/risk.py`
- Create: `src/kxian_bot/brokers/base.py`
- Create: `src/kxian_bot/brokers/paper.py`
- Test: `tests/test_paper_broker.py`

**Step 1: Write failing tests**

Cover order sizing, max position exposure, and paper order fills updating balances.

**Step 2: Implement risk checks and broker**

Reject orders above configured risk thresholds and simulate fills at provided market price.

**Step 3: Verify**

Run: `python -m pytest tests/test_paper_broker.py -v`
Expected: PASS

### Task 5: Implement runner, backtest, and CLI

**Files:**
- Create: `src/kxian_bot/backtest.py`
- Create: `src/kxian_bot/runner.py`
- Create: `src/kxian_bot/cli.py`
- Test: `tests/test_backtest.py`

**Step 1: Write failing tests**

Cover a simple backtest path generating trades and equity metrics.

**Step 2: Implement event loop and backtest**

Allow running once for testability and continuously for live paper mode.

**Step 3: Verify**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: PASS

### Task 6: Document the safety model and usage

**Files:**
- Create: `docs/adr/2026-05-27-paper-trading-first.md`
- Modify: `README.md`

**Step 1: Document decisions**

Record why paper mode is default and what must be true before live trading is enabled.

**Step 2: Verify**

Review README commands and examples against current code.
