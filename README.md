# Kxian Bot

Kxian Bot is a small Python trading bot skeleton for watching crypto K-lines, generating signals, backtesting, and executing paper trades.

## Safety

- Default mode is `paper`
- Live trading is blocked unless `KXIAN_ALLOW_LIVE=true`
- Public market data can use Binance or OKX K-line endpoints
- Strategy automation submits exchange orders only in `paper` mode by default
- Bounded testnet order automation requires `KXIAN_ENABLE_TESTNET_AUTOTRADE=true`; non-ordering testnet checks can run first with it disabled
- Live strategy automation requires `KXIAN_ALLOW_LIVE=true`, `KXIAN_LIVE_DRY_RUN=false`, `KXIAN_ENABLE_LIVE_AUTOTRADE=true`, `KXIAN_USE_TESTNET=false`, `KXIAN_LIVE_CONFIRMATION=LIVE:<exchange>:<symbol>:<interval>`, and `KXIAN_LIVE_CREDENTIALS_CONFIRMED=true`
- Live orders are capped by `KXIAN_MAX_LIVE_ORDER_USDT` before they can leave the bot

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
Copy-Item .env.example .env
# For sandbox automation, use the safer testnet template instead:
Copy-Item .env.testnet.example .env
```

## Persistence

Runtime data is stored in SQLite at `KXIAN_DB_PATH`, defaulting to `data/kxian.sqlite3`. The database records testnet order results, strategy signals, fills, backtest trades, and risk-state snapshots. API secrets are not written to the database.

## Run tests

```powershell
python -m pytest -v
```

## Backtest

```powershell
kxian-bot backtest --limit 200
```

Each backtest returns a `run_id` and persists a matching summary in `backtest_runs`, so the strategy gate can use it before testnet automation.

Backtests include configurable fees and slippage:

```powershell
$env:KXIAN_FEE_RATE="0.001"
$env:KXIAN_SLIPPAGE_RATE="0.0005"
kxian-bot backtest --limit 200
```

Run a stress backtest before enabling automatic testnet orders:

```powershell
kxian-bot stress-backtest --limit 1000
```

`stress-backtest` reruns the current strategy under five fee/slippage scenarios up to `2x` friction, stores the summary in `stress_backtest_runs`, and reports the worst return, worst drawdown, worst profit factor, minimum trade count, and scenario pass rate.

Run a walk-forward split to check whether performance survives across time segments instead of relying on one lucky period:

```powershell
kxian-bot walk-forward --limit 3000 --segments 6
```

`walk-forward` splits the current candle sample into chronological segments, runs the current strategy on each segment, stores the summary in `walk_forward_runs`, and reports segment pass rate, total trades, worst segment return, worst drawdown, and worst profit factor.

To compare walk-forward stability across several chronological sample files without promoting anything:

```powershell
kxian-bot walk-forward-samples --input-files data/BTCUSDT-1m-2024-01.csv,data/BTCUSDT-1m-2024-02.csv --resample-interval 15m --limit 1000 --segments 6 --summary-only
```

`walk-forward-samples` reports each sample's walk-forward gate, failed segments, pass rate, total trades, and worst segment metrics. Use it after a candidate passes ordinary backtest and stress checks but still needs segment-level diagnosis.

To run the full promotion gate in one command:

```powershell
kxian-bot validate-strategy --limit 3000 --segments 6
```

`validate-strategy` loads one candle sample, runs the fee/slippage-adjusted backtest, stress scenarios, and walk-forward split against that same sample, persists all three evidence records, and exits with code 2 if any gate fails.

To require the same active strategy to pass several market samples:

```powershell
kxian-bot validate-samples --input-files data/BTCUSDT-1m-2024-01.csv,data/BTCUSDT-1m-2024-02.csv --resample-interval 15m --limit 1000 --segments 6
```

`validate-samples` runs the full validation gate for every comma-separated file and only returns `pass` when every sample passes. Its output summarizes each sample without full trade rows, making it a safer final check before promotion or testnet automation.

Before tuning strategies, inspect the market sample itself:

```powershell
kxian-bot market-diagnostics --input-file data/BTCUSDT-1m.csv --resample-interval 15m --limit 1000 --segments 6
```

`market-diagnostics` reports buy-and-hold return, buy-and-hold drawdown, candle volatility, trend efficiency, segment returns, and fee/slippage friction versus the average candle move. Use it to spot choppy samples, high cost pressure, or one-regime data before trusting a strategy grid.

To use OKX public K-lines:

```powershell
$env:KXIAN_EXCHANGE="okx"
kxian-bot backtest --limit 200
```

## Offline backtest

```powershell
kxian-bot backtest --input-file sample_data/binance_btcusdt_1m.json
```

Offline files can be Binance kline JSON, OKX candle JSON, or CSV with OHLCV headers such as `timestamp,open,high,low,close,volume`. Timestamps may be milliseconds, seconds, or ISO datetimes.

To replay the same sample through the SQLite market-data source, import it first:

```powershell
kxian-bot import-candles --input-file sample_data/binance_btcusdt_1m.json --exchange binance --symbol BTCUSDT --interval 1m
```

For exchange-exported CSV history:

```powershell
kxian-bot import-candles --input-file data/BTCUSDT-1m.csv --exchange binance --symbol BTCUSDT --interval 1m
kxian-bot validate-strategy --input-file data/BTCUSDT-1m.csv --segments 6
```

To search a moving-average parameter grid and validate the best candidates with the same stress and walk-forward gates:

```powershell
kxian-bot select-strategy --input-file data/BTCUSDT-1m.csv --short-windows 5,10,20 --long-windows 30,50,100 --segments 6 --top 10
```

`select-strategy` ranks candidate parameters after full validation and returns `selected` only when a candidate passes the strategy, stress, and walk-forward gates. It can compare multiple strategy types and protective-exit grids in the same run:

```powershell
kxian-bot select-strategy --input-file data/BTCUSDT-1m.csv --strategies moving_average_cross,donchian_breakout,trend_pullback,mean_reversion,rsi_mean_reversion,momentum_breakout,bollinger_mean_reversion,regime_breakout,regime_filtered_ma_cross,trend_filtered_ma_cross,defensive_trend,panic_rebound,regime_adaptive_long,volatility_breakout_trend,downtrend_breakdown_short --short-windows 5,10,20 --long-windows 30,50,100 --stop-loss-pcts 0,1,2 --take-profit-pcts 0,2,4 --trailing-stop-pcts 0,1.5 --segments 6 --top 10
```

For promotion candidates, prefer multi-sample selection so the same parameters must survive several market files before they can be saved:

```powershell
kxian-bot select-samples --input-files data/BTCUSDT-1m-2024-01.csv,data/BTCUSDT-1m-2024-02.csv --strategies moving_average_cross,donchian_breakout,trend_pullback,mean_reversion,rsi_mean_reversion,momentum_breakout,bollinger_mean_reversion,regime_breakout,regime_filtered_ma_cross,trend_filtered_ma_cross,defensive_trend,panic_rebound,regime_adaptive_long,volatility_breakout_trend,downtrend_breakdown_short --short-windows 5,10,20 --long-windows 30,50,100 --stop-loss-pcts 0,1,2 --take-profit-pcts 0,2,4 --trailing-stop-pcts 0,1.5 --segments 6 --top 10
```

`select-samples` first ranks candidates by fee-adjusted backtest behavior across every sample, then fully validates the top candidates with stress and walk-forward on every sample. It returns `selected` only when one parameter set passes all samples.

To avoid guessing the trading interval manually, compare several resampled intervals in one run:

```powershell
kxian-bot select-sample-intervals --input-files data/BTCUSDT-1m-2024-01.csv,data/BTCUSDT-1m-2024-02.csv --resample-intervals raw,5m,15m,30m,1h --strategies moving_average_cross,donchian_breakout,trend_pullback,mean_reversion,rsi_mean_reversion,momentum_breakout,bollinger_mean_reversion,regime_breakout,regime_filtered_ma_cross,trend_filtered_ma_cross,defensive_trend,panic_rebound,regime_adaptive_long,volatility_breakout_trend,downtrend_breakdown_short --short-windows 3,5,8 --long-windows 12,20,30 --stop-loss-pcts 0,1,2 --take-profit-pcts 0,2,4 --trailing-stop-pcts 0,1.5 --segments 6 --top 10
```

`select-sample-intervals` wraps `select-samples` for each interval and ranks only fully validated multi-sample results. If you pass `--promote`, the active strategy profile is saved under the selected runtime interval, so a `15m` validation promotes a `15m` profile instead of silently running the same evidence on `1m`.

For large research grids, run a fast multi-sample prefilter before spending time on stress and walk-forward validation:

```powershell
kxian-bot screen-samples --input-files data/BTCUSDT-1m-2024-01.csv,data/BTCUSDT-1m-2024-02.csv --limit 720 --resample-intervals 1h,4h --strategies moving_average_cross,donchian_breakout,momentum_breakout,bollinger_mean_reversion,regime_breakout,regime_filtered_ma_cross,defensive_trend,panic_rebound,regime_adaptive_long,volatility_breakout_trend,downtrend_breakdown_short --short-windows 5,8 --long-windows 20,30 --stop-loss-pcts 0,2 --take-profit-pcts 0,4 --trailing-stop-pcts 0,2 --segments 3 --top 10 --max-combinations 200 --skip-combinations 0 --summary-only
```

`screen-samples` loads each input file once, compares the requested intervals, and ranks candidates by the fee-adjusted strategy gate across every sample. It is screen-only: it does not run stress or walk-forward, does not persist validation evidence, and never promotes a profile. Use `--summary-only` for readable research output, `--max-combinations` to cap large research grids, `--skip-combinations` to page through the next slice, and start with a bounded `--limit` before expanding the grid. For low-frequency interval research, `--screen-min-trades` can relax only the prefilter trade-count threshold; formal `select-samples`, `validate-samples`, promotion, and readiness gates still use `KXIAN_MIN_GATE_TRADES`. Re-run any interesting candidate with `select-samples` before considering testnet automation.

`mean_reversion` buys when price reclaims a short-term lower deviation band while the longer trend filter is not collapsing, then exits near the upper band or when the longer filter breaks. It is intended for choppy samples and must still pass the same stress and walk-forward gates before promotion.

`rsi_mean_reversion` buys only after RSI recovers from oversold while price stays near a non-collapsing longer trend, then exits when RSI is overbought or price loses the trend filter. It broadens the choppy-market candidate set without changing the validation gates.

`momentum_breakout` buys short-channel breakouts only when the fast average is above a non-falling longer trend, then exits on short-channel breakdowns, fast-average rollover, or trend loss. It adds a higher-frequency trend-following candidate without loosening any gates.

`bollinger_mean_reversion` buys when price reclaims a lower Bollinger-style band while the longer trend filter is not collapsing, then exits near the middle band or when the trend floor breaks. It adds another choppy-market candidate with explicit exits.

`defensive_trend` buys only when a rising long filter, fast-average leadership, orderly trend efficiency, shallow pullback, and a reclaim or breakout all line up. It exits quickly when the fast average, trend floor, or risk-off pullback breaks, so weak regimes can stay in cash instead of forcing long exposure.

`panic_rebound` buys only after a statistically stretched washout starts reclaiming short-term momentum, then exits into recovery targets, stalled rebounds, or renewed breakdowns. It is a long-only candidate for weak or choppy regimes; it still needs full multi-sample validation before promotion.

`regime_adaptive_long` switches among supported trend entries, choppy-market reclaims, and tightly filtered panic rebounds while remaining spot long-only. It is designed to stay in cash during hostile downtrends unless a rebound setup meets the same mechanical rules.

`regime_filtered_ma_cross` buys only when a bullish moving-average cross appears inside a rising, orderly, tradable-volatility regime with long/context averages aligned. It exits on bearish crosses, trend-floor loss, or context rollover, and is meant to filter out choppy false MA crosses.

`volatility_breakout_trend` buys only when a rising trend, orderly trend efficiency, tradable volatility, and a volatility-scaled channel breakout agree. It explicitly avoids overextended breakouts and exits on fast-trend failure, trend-floor loss, or volatility spike reversals.

`downtrend_breakdown_short` is a research-only synthetic short candidate. It treats `sell` as short entry and `buy` as cover inside the backtest engine so downside edges can be studied, but promotion is blocked until a real margin or futures execution path exists.

When the source file is a high-frequency export, resample it before validation to test lower-noise trading intervals without downloading another file:

```powershell
kxian-bot select-strategy --input-file data/BTCUSDT-1m.csv --resample-interval 15m --strategies moving_average_cross,donchian_breakout,trend_pullback,mean_reversion,rsi_mean_reversion,momentum_breakout,bollinger_mean_reversion,regime_breakout,regime_filtered_ma_cross,trend_filtered_ma_cross,defensive_trend,panic_rebound,regime_adaptive_long,volatility_breakout_trend,downtrend_breakdown_short --short-windows 3,5,8 --long-windows 12,20,30 --segments 6 --top 10
```

`--resample-interval` is available on `backtest`, `stress-backtest`, `walk-forward`, `validate-strategy`, `validate-samples`, `market-diagnostics`, `select-strategy`, and `select-samples`. Use `select-sample-intervals --resample-intervals raw,5m,15m,30m,1h` to compare multiple intervals in one pass. Resampling aggregates OHLCV candles before applying `--limit`, so `--limit 1000 --resample-interval 15m` uses the latest 1000 aggregated candles.

When a selected candidate passes, promote it into the active runtime profile:

```powershell
kxian-bot select-strategy --input-file data/BTCUSDT-1m.csv --short-windows 5,10,20 --long-windows 30,50,100 --segments 6 --top 10 --promote
kxian-bot strategy-profile
```

The active strategy profile is scoped to the current mode, exchange, symbol, and interval. `run-once`, `trade-loop`, `preflight`, and `readiness` use that promoted profile, including protective-exit percentages, so startup checks and live runtime parameters stay aligned.

Before enabling testnet automation, explicitly promote the validated paper profile into the testnet scope:

```powershell
$env:KXIAN_INTERVAL="4h"
kxian-bot promote-profile-to-testnet --updated-by operator
$env:KXIAN_MODE="testnet"
$env:KXIAN_ENABLE_TESTNET_AUTOTRADE="true"
kxian-bot readiness
kxian-bot launch-checklist --target testnet
```

`promote-profile-to-testnet` supports `paper -> testnet` and requires passing multi-sample validation evidence on the source profile. `promote-profile-to-live` only supports `testnet -> live`, and it requires that the testnet source profile already carries promotion evidence from paper.

## Trading rules

Before submitting testnet orders, make sure the bot knows the exchange's price tick, quantity step, and minimum order value for the symbol:

```powershell
kxian-bot trading-rules --symbol BTCUSDT --price-step 0.01 --quantity-step 0.00001 --min-notional 10
```

Orders are rounded down to these rules before submission. If the rounded order falls below the minimum quantity or notional value, the loop rejects it locally instead of sending an exchange order that is likely to fail.

## Historical data download

Download public spot OHLCV history into SQLite before running longer backtests:

```powershell
kxian-bot download-history --exchange binance --symbol BTCUSDT --interval 1m --start 2024-01-01 --end 2024-02-01
```

OKX uses the same command shape:

```powershell
kxian-bot download-history --exchange okx --symbol BTCUSDT --interval 1m --start 2024-01-01 --end 2024-02-01 --limit-per-request 300
```

The downloader stores normalized candles in `candles` with a unique `(exchange, symbol, interval, open_time)` key, so reruns upsert existing data instead of duplicating it.

If the exchange API is slow or blocked, download Binance Vision monthly ZIP archives into a local directory and import them offline:

```powershell
kxian-bot import-candle-archives --input-dir data --pattern "*.zip" --exchange binance --symbol BTCUSDT --interval 1m
```

The importer sorts matching archives, upserts every candle, and reports total files, imported candles, changed rows, and the resulting first/last open time. Use `--recursive` when archives are nested under symbol or interval folders.

Prepare chronological validation samples from downloaded SQLite candles, or let `--source auto` fetch the missing range first:

```powershell
kxian-bot prepare-samples --exchange binance --symbol BTCUSDT --interval 1m --start 2024-01-01 --end 2024-07-01 --sample-days 30 --output-dir data/samples --source auto --limit-per-request 1000 --min-candles 1000
```

`prepare-samples` writes one CSV per time window and returns `input_files_arg` plus a ready-to-run `select-sample-intervals` command. Use this before promotion so the strategy has to survive multiple chronological samples instead of one lucky month.

For a conservative one-command research pass, prepare samples and run multi-interval candidate selection together:

```powershell
kxian-bot research-strategy --exchange binance --symbol BTCUSDT --interval 1m --start 2024-01-01 --end 2024-07-01 --sample-days 30 --output-dir data/samples --source auto --limit-per-request 1000 --min-candles 1000 --resample-intervals raw,5m,15m,30m,1h --strategies moving_average_cross,donchian_breakout,trend_pullback,mean_reversion,rsi_mean_reversion,momentum_breakout,bollinger_mean_reversion,regime_breakout,regime_filtered_ma_cross,trend_filtered_ma_cross,defensive_trend,panic_rebound,regime_adaptive_long,volatility_breakout_trend,downtrend_breakdown_short --short-windows 3,5,8 --long-windows 12,20,30 --stop-loss-pcts 0,1,2 --take-profit-pcts 0,2,4 --trailing-stop-pcts 0,1.5 --segments 6 --top 10
```

`research-strategy` is research-only unless `--promote` is passed. If no interval passes all gates, it exits with code `2` and leaves the active strategy profile untouched. Its `summary` field highlights the best candidate, selected runtime interval, most common failure reasons, a `decision` of `promotable` or `blocked`, diagnostics, and recommended next actions so you can adjust data coverage, intervals, or parameter grids without digging through the full nested result.
Research-only strategies such as `downtrend_breakdown_short` may appear in research output, but `--promote` returns `research_only_strategy_not_promotable` and leaves the active profile untouched.
Add `--summary-only` when you only want the compact decision output instead of the full prepare/selection tree.

## Batch backtest

Run a moving-average parameter grid against downloaded local history:

```powershell
kxian-bot batch-backtest --exchange binance --symbol BTCUSDT --interval 1m --start 2024-01-01 --end 2024-02-01 --short-windows 5,10,20 --long-windows 30,50,100 --top 20 --sort-by return_pct
```

Supported sort fields are `return_pct`, `profit_factor`, and `max_drawdown_pct`. Invalid combinations where `short_window >= long_window` are skipped automatically. Each run is persisted in `backtest_runs`; per-trade details still go to `backtest_trades`.

Batch results are for robustness screening, not parameter curve-fitting. Prefer stable parameter regions, enough trades, and out-of-sample periods before considering testnet automation.

## Local dashboard

Start the read-only browser dashboard:

```powershell
kxian-bot dashboard --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000`. The dashboard reads the same SQLite database and shows local K-lines, recent batch backtest rankings, stress pass-rate evidence, walk-forward evidence, and trade records. It does not place orders.
The right-side inspector also shows the startup preflight gate, including whether automation is ready and which checks are passing or blocking startup.
The testnet panel includes `Testnet Dry-run` for one credential/preflight/fill-sync check and `Observe 6 Cycles` for repeated non-ordering sandbox observation. Both actions report missing credentials and next steps without printing secret values.
The dashboard opens in Chinese by default. Use the language switch in the top-right corner to toggle Chinese and English. It also accepts `?lang=zh` or `?lang=en` and stores your last explicit choice in browser local storage.

## Paper trade loop

Before running automation, check local readiness:

```powershell
kxian-bot readiness
kxian-bot preflight
kxian-bot exchange-health --timeout-seconds 5
```

`readiness` is a static pre-run audit. It does not contact the exchange and it only reports whether credentials are present, not their values. Use it to see missing sandbox credentials, unsafe endpoint choices, disabled automation flags, hard risk-setting failures, and the next command to run.

The preflight report checks the SQLite schema, automation pause control, trading-rule readiness, market-data availability, strategy-gate evidence, multi-sample validation evidence, stress-gate evidence, walk-forward evidence, open exchange orders, and execution-mode safety settings.

`exchange-health` is the explicit network audit. It checks the market-data endpoint the strategy will actually use and the selected testnet/live trading endpoint with a short timeout, classifies timeouts, HTTP auth/permission failures, rate limits, server errors, and unexpected responses without printing secrets. Binance `testnet` uses the testnet K-line endpoint when `KXIAN_USE_TESTNET=true`; `paper` and `live` continue to use the production public K-line endpoint unless you switch to SQLite replay. `testnet` and `live` `run-once` / `trade-loop` enforce this health check after the launch checklist passes, so automation will not start on a host that cannot reach the exchange APIs.

The automation pause control is persisted in SQLite and blocks both `preflight` and `run-once` / `trade-loop` before any new strategy order is created:

```powershell
kxian-bot pause --reason operator_review
kxian-bot automation-status
kxian-bot resume --reason ready
```

The dashboard pause button toggles the same control. It is a kill switch for new automated strategy orders; it does not directly place or cancel exchange orders.

```powershell
kxian-bot run-once
```

Run a continuous paper-trading loop against live public exchange data:

```powershell
kxian-bot trade-loop
```

`trade-loop` runs the same preflight checks by default before starting. In `testnet` and `live` modes it also enforces the matching `launch-checklist` and `exchange-health` before creating a runner. If readiness, launch checklist, or exchange connectivity fails, it exits with code 2 and prints a JSON payload with `reason: "preflight_failed"` or `reason: "launch_checklist_blocked"` plus the failed checks and next steps. For a controlled local paper/offline smoke test only, you can bypass startup checks:

```powershell
kxian-bot trade-loop --max-iterations 1 --sleep-seconds 0 --skip-preflight
```

Do not use `--skip-preflight` for Bitget live, Binance/OKX live, or any path that can submit exchange orders. It is only for local smoke rehearsal where the operator has already forced a non-live/offline scope.

For a bounded smoke test that will not run forever:

```powershell
kxian-bot trade-loop --max-iterations 5 --sleep-seconds 1
```

During continuous operation, `trade-loop` counts consecutive runtime failures such as exchange exceptions and unsafe rejected execution states. After `KXIAN_MAX_CONSECUTIVE_LOOP_ERRORS` failures in a row, default `3`, it records `loop_circuit_breaker_tripped`, pauses the current mode/exchange/symbol/interval automation control, releases the loop lock, and exits with code 2 so an operator can inspect the dashboard before resuming.

For the current testnet close-loop, create bounded sandbox evidence through the runbook commands `testnet-dry-run --execute-loop` and `testnet-observe --execute-loop`; do not treat `ready_for_testnet_dry_run` as final acceptance. A generic bounded `testnet` `trade-loop`, for example `--max-iterations 1`, is an operational primitive behind that controlled path. An unbounded `testnet` `trade-loop` requires the stronger `testnet_observed_ready_for_live_review` phase, meaning both non-ordering and bounded-order testnet observations have passed. `live` loops require `launch-checklist --target live` to reach `ready_for_bounded_live_loop`.

If public exchange data is blocked or unavailable, replay candles already stored in SQLite:

```powershell
$env:KXIAN_MARKET_DATA_SOURCE="sqlite"
kxian-bot import-candles --input-file sample_data/binance_btcusdt_1m.json --exchange binance --symbol BTCUSDT --interval 1m
kxian-bot trade-loop --max-iterations 20 --sleep-seconds 0
```

For a one-command offline paper rehearsal that imports candles, runs preflight, executes a bounded strategy loop, and prints auditable row-count evidence:

```powershell
kxian-bot paper-dry-run --input-file sample_data/ohlcv_smoke.csv --max-iterations 1 --sleep-seconds 0
```

`paper-dry-run` forces `paper` mode and the SQLite market-data source for the rehearsal. It does not contact an exchange or place real orders. Use it whenever public market data is blocked, before moving the same strategy toward testnet automation.

The loop records each iteration in `loop_events`, so the dashboard can show heartbeats, errors, idle cycles, and fills. Keep the default `paper` mode until backtests and paper results are robust; profitability is never guaranteed.
Paper and testnet modes restore local shadow balances from persisted `fills` on startup, so a restarted loop can continue managing an existing position instead of forgetting it.
The strategy loop is single-position long by default: if a buy signal arrives while an asset position is already open, the loop skips it with `position_already_open` instead of pyramiding. Risk checks also count the current position value plus the new buy notional against `KXIAN_MAX_POSITION_USDT`.
The runner also restores the latest persisted `risk_state` for the current mode, exchange, symbol, and interval, so cooldowns, daily trade counts, and the daily loss baseline continue after a restart instead of resetting mid-session.
Only one strategy loop can run for the same mode, exchange, symbol, and interval at a time. The loop writes a SQLite heartbeat lock and releases it on normal exit; `KXIAN_LOOP_LOCK_STALE_SECONDS` controls when a stale lock can be taken over after a crash.
Optional protective exits can close an existing long position before the next strategy sell signal. Set `KXIAN_STOP_LOSS_PCT`, `KXIAN_TAKE_PROFIT_PCT`, and/or `KXIAN_TRAILING_STOP_PCT` to a positive percentage; the runner restores the average entry price from filled orders, persists the trailing peak price per mode/exchange/symbol/interval, and emits `stop_loss_triggered`, `take_profit_triggered`, or `trailing_stop_triggered` sell signals when the latest candle crosses the threshold. The same exits are included in `backtest`, `stress-backtest`, `walk-forward`, and `batch-backtest` so validation matches live behavior.

## 实盘灰度准入

实盘只能在单独人工复核后进入小额灰度，分两条路径：

- 通用实盘灰度：详见 `docs/实盘灰度操作手册.md`
- Bitget 实盘灰度：详见 `docs/Bitget实盘灰度手册.md`

`live-setup-check` 是只读准入检查：它强制 live 视图为 `mode=live`、`use_testnet=false`、`market_data_source=exchange`，聚合 readiness、`launch-checklist --target live`、生产端点健康、生产 key 人工确认和首轮 canary 金额上限，并固定返回 `will_submit_orders=false`。

```powershell
kxian-bot live-setup-check --timeout-seconds 5
```

只有当 `live-setup-check` 返回 `status=pass`、`phase=ready_for_bounded_live_canary`，且 `launch-checklist --target live` 返回 `phase=ready_for_bounded_live_loop` 后，操作者才可以人工批准一次 `trade-loop --max-iterations 1 --sleep-seconds 0` 小额 canary。该检查不会执行 `promote-profile-to-live`，不会发起订单，也不会回显 API key/secret。

实盘自动化仍然执行同一套 preflight 门禁，会刷新未完成订单、同步账户和成交、拒绝未知成本价持仓，并把订单、成交、循环事件和风险状态记录到 SQLite。`promote-profile-to-live` 和 `launch-checklist --target live` 都要求同一交易所、交易对、周期已经通过非下单测试网观察和 bounded 测试网下单观察。

单轮 canary 后必须复核账户、成交、挂单和 checklist；任何异常都按 `docs/实盘灰度操作手册.md` 回退，不允许继续扩大运行。

Bitget 路径额外要求 `KXIAN_EXCHANGE=bitget`、`KXIAN_USE_TESTNET=false`、`KXIAN_MAX_LIVE_ORDER_USDT=5`、`KXIAN_LIVE_CONFIRMATION=LIVE:bitget:BTCUSDT:4h`，并先执行 `trading-rules --refresh-from-exchange` 和 `approve-bitget-live-gray`。Bitget 灰度期间不使用 `test-order` 或 `run-once`，只允许一次 bounded `trade-loop --max-iterations 1 --sleep-seconds 0`。

## Testnet manual orders

Use `testnet` mode for manual test exchange requests. This is separate from `live` and should use testnet/demo API keys only.

```powershell
Copy-Item .env.testnet.example .env
# Fill .env manually with Spot Testnet credentials before running the commands below.
# Do not paste production API keys and do not commit .env.
$env:KXIAN_MODE="testnet"
$env:KXIAN_EXCHANGE="binance"
kxian-bot testnet-setup-check
kxian-bot test-order --side buy --quantity 0.001 --price 10000
kxian-bot order-status --order-id 12345
kxian-bot cancel-order --order-id 12345
kxian-bot account-balance
kxian-bot sync-fills
kxian-bot readiness
kxian-bot testnet-dry-run
```

For OKX demo trading, use `KXIAN_EXCHANGE=okx` and demo credentials. Requests include `x-simulated-trading: 1`.

## Testnet strategy automation

After paper trading is stable, you can let the strategy loop submit testnet/demo orders. This still does not use real money, but it can place orders on the configured exchange sandbox account.
The direct `trade-loop` example below is an operational reference, not the current close-loop acceptance path. For this stage, create evidence through `testnet-dry-run` and `testnet-observe --cycles 6` before any longer loop.

```powershell
$env:KXIAN_MODE="testnet"
$env:KXIAN_EXCHANGE="binance"
$env:KXIAN_USE_TESTNET="true"
$env:KXIAN_ENABLE_TESTNET_AUTOTRADE="true"
$env:KXIAN_BINANCE_API_KEY="your_testnet_key"
$env:KXIAN_BINANCE_API_SECRET="your_testnet_secret"
kxian-bot trade-loop --max-iterations 5 --sleep-seconds 1
```

With `KXIAN_ENABLE_TESTNET_AUTOTRADE=false`, the strategy records a rejected exchange order with reason `testnet_autotrade_disabled` instead of submitting to the exchange. The loop also waits when an existing submitted or partially filled order is already open for the same symbol.
With `KXIAN_ENABLE_TESTNET_AUTOTRADE=true`, each testnet loop first syncs account balances from the exchange sandbox. If the account sync fails, the loop stops that iteration with `account_sync_failed` or `exchange_http_error` instead of submitting a new order.
At the start of each testnet loop, open orders are refreshed through `order-status`; filled orders are recorded into `fills`, and the loop only submits a new strategy order after the latest stored exchange status is no longer open.
After restart, testnet automation replays filled testnet orders from SQLite to rebuild the local shadow position used for sizing and protective exits. Keep SQLite in sync with the sandbox account before relying on automated exits.
If the exchange sandbox reports an open asset position but the local replay has no average entry price, testnet automation stops with `missing_local_entry_price` instead of managing an unknown-cost position.
Run `kxian-bot sync-fills` to import recent sandbox fills into SQLite when local history is missing; fills with the same exchange trade ID are skipped so repeated syncs are idempotent.
Run `kxian-bot testnet-dry-run` before enabling a longer testnet loop. It runs `preflight`, `account-balance`, and `sync-fills`, then runs preflight again after syncing. It does not submit a strategy loop order unless you explicitly add `--execute-loop`, which runs exactly one bounded `trade-loop` iteration through the controlled observation path.
If sandbox credentials are missing, `testnet-dry-run` exits with structured JSON reason `missing_exchange_credentials` and only reports boolean credential presence. Exchange request failures are also classified as `exchange_http_401`, `exchange_http_403`, `exchange_rate_limited`, `exchange_server_error`, `exchange_timeout`, or generic `exchange_http_error` without printing secret values.
Use `kxian-bot testnet-setup-check` after editing `.env`. It forces a testnet view of the current configuration, reports credential presence as booleans, checks exchange connectivity, readiness, and the launch checklist, and exits with code `2` until the sandbox setup is ready. It never prints API key or secret values.
After a single dry run passes, use `kxian-bot testnet-observe` for repeated sandbox observation. By default it repeats the same dry run without submitting strategy orders and stops on the first failed cycle. Add `--execute-loop` only after the non-ordering observation is stable and you want each cycle to run one bounded sandbox strategy iteration.
By default, testnet automation also requires matching persisted `backtest`, multi-sample validation, `stress-backtest`, and `walk-forward` results for the same exchange, symbol, interval, short window, and long window. Set `KXIAN_REQUIRE_STRATEGY_GATE=false`, `KXIAN_REQUIRE_SAMPLE_VALIDATION_GATE=false`, `KXIAN_REQUIRE_STRESS_GATE=false`, or `KXIAN_REQUIRE_WALK_FORWARD_GATE=false` only for controlled smoke tests.

Recommended testnet promotion order:

For this close-loop, use `docs/测试网闭环操作手册.md` as the authority and start the fixed acceptance sequence at `strategy-profile`. The research command below is optional prior strategy-selection context, not part of the fixed `Binance testnet / BTCUSDT / 4h` acceptance sequence.

```powershell
kxian-bot strategy-profile
kxian-bot testnet-setup-check
kxian-bot readiness
kxian-bot launch-checklist --target testnet
kxian-bot exchange-health --timeout-seconds 5
kxian-bot testnet-dry-run
kxian-bot testnet-observe --cycles 6 --sleep-seconds 60
kxian-bot testnet-dry-run --execute-loop --sleep-seconds 0
kxian-bot testnet-observe --cycles 6 --sleep-seconds 60 --execute-loop
kxian-bot launch-checklist --target testnet
```

This close-loop stops at `launch-checklist --target testnet` with `status=pass` and `phase=testnet_observed_ready_for_live_review`. Do not run `promote-profile-to-live`, do not start live mode, and do not enable live switches in this stage.

## Notes

This project is not investment advice. It provides a safe starting point for validating a strategy before any real-money deployment.

## Risk controls

The paper runner enforces these process-local risk settings:

- `KXIAN_RISK_PER_TRADE`
- `KXIAN_MAX_POSITION_USDT`
- `KXIAN_MIN_ORDER_USDT`
- `KXIAN_MAX_DAILY_TRADES`
- `KXIAN_MAX_DAILY_LOSS_USDT`
- `KXIAN_COOLDOWN_SECONDS`
- `KXIAN_ALLOW_SELL_WITHOUT_POSITION`
- `KXIAN_STOP_LOSS_PCT`
- `KXIAN_TAKE_PROFIT_PCT`
- `KXIAN_TRAILING_STOP_PCT`

## Strategy validation gates

Do not move a strategy to testnet automation until a fee-adjusted backtest has enough evidence to be worth testing:

- Prefer at least 100 trades before trusting win rate or profit factor.
- Require positive return after fees and slippage, not just before costs.
- Keep maximum drawdown small enough that you would tolerate it with real capital.
- Inspect losing streaks and avoid strategies that rely on one or two lucky trades.
- Re-run with higher slippage before assuming the result is robust. `kxian-bot stress-backtest` does this automatically for the current strategy.
- Split history by time before assuming the result is stable. `kxian-bot walk-forward --segments 6` checks whether the same settings survive multiple chronological slices.
- Use `kxian-bot prepare-samples` to build several chronological CSV samples from SQLite or exchange history before selecting a strategy.
- Use `kxian-bot research-strategy` for a single conservative command that prepares samples, runs multi-interval selection, and only promotes when `--promote` is explicit and all gates pass.
- Prefer `kxian-bot validate-samples --input-files file1.csv,file2.csv --limit 3000 --segments 6` before testnet promotion because it requires the backtest, stress, and walk-forward gates to pass on every market sample.
- Use `kxian-bot select-sample-intervals --promote` when the source data is high-frequency. It compares raw and resampled intervals and promotes evidence under the selected runtime interval.
- Use `kxian-bot select-samples --promote` to screen a parameter grid across several market samples and save the selected candidate as the active profile before testnet promotion. If it exits with `no_candidate_passed_validation`, do not promote that sample set to testnet automation.
- Keep `KXIAN_REQUIRE_SAMPLE_VALIDATION_GATE=true` for testnet automation unless you are deliberately running a short smoke test.
- Keep `KXIAN_REQUIRE_STRESS_GATE=true` for testnet automation unless you are deliberately running a short smoke test.
- Keep `KXIAN_REQUIRE_WALK_FORWARD_GATE=true` for testnet automation unless you are deliberately running a short smoke test.


