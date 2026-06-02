# Bitget 策略证据研究报告

## 结论

本轮只完成 Bitget / BTCUSDT 的只读策略证据研究，不进入实盘灰度。研究周期覆盖既定 `4h` 主线，并补充 `2h`、`1h` 公开行情样本筛选；其中 `2h` 由 Bitget 官方支持的 `1h` 现货历史 K 线在本地聚合得到，不直接向 Bitget 请求不支持的 `2h` granularity。

当前结论是：Bitget live-only 只读接入链路可用，生产凭证存在性、live-only endpoint、5U 灰度上限、open orders 清理状态均通过只读检查；但策略证据不足，`readiness` 仍被 `strategy_gate`、`sample_validation_gate`、`stress_gate`、`walk_forward_gate` 阻断。

当前不能完全投入使用的原因不是 Bitget key、余额或交易所连通性，而是策略尚未通过证据门禁。只要该阻断存在，就不能写入 live profile、不能批准灰度、不能执行 5U canary。

因此当前状态必须保持 `blocked_before_bitget_live_canary`。不得执行 `approve-bitget-live-gray`、`trade-loop`、`run-once`、`test-order`、`promote-profile-to-live`，也不得把 `screen-samples` 的失败预筛结果包装成上线证据。

2026-06-02 追加结论：`4h`、`2h`、`1h` 三个周期均未找到跨 5 段样本通过硬门禁的候选。当前阻断不是交易所接入问题，而是策略证据不足；不应写入 live profile，也不应进入 5U canary。

2026-06-02 追加只读研究 harness：CLI 新增全局 `--no-dotenv`，研究筛选可显式跳过项目 `.env` 自动加载，并通过 `screen-samples --exchange/--symbol/--interval` 固定离线证据 scope。注意 `--no-dotenv` 不会清空当前 shell 已有的 `KXIAN_*` 环境变量；完全隔离研究仍需使用干净 shell。新增研究专用现货策略 `adaptive_range_reclaim` 与 `volatility_regime_pullback_reclaim`，但它们都被标记为 research-only，`run-once`、`trade-loop` 会返回 `research_only_strategy_runtime_blocked`，包括 active profile 覆盖后的运行路径；任何 `--promote`、profile 晋升、Bitget live gray 批准路径都拒绝 research-only profile。

2026-06-02 追加样本治理：CLI 新增 `freeze-sample-manifest` 与 `strategy-research-evidence`，用于在研究前冻结 train / validation / final OOS 样本 SHA256，并把后续筛选结果绑定到 manifest。当前已触碰的旧 5 段样本只能作为研究集和失败归因集；如果没有新的未触碰 final OOS，不能生成 live profile，也不能把失败筛选结果包装成上线证据。

## 只读状态

2026-06-02 的只读复核结果：

- `kxian-bot exchange-health --timeout-seconds 5` 返回 `status=pass`，Bitget public market endpoint 和 public time endpoint 均可达。
- `kxian-bot readiness` 返回 `status=fail`，失败点集中在策略证据门禁。
- `kxian-bot launch-checklist --target live` 返回 `status=blocked`，`phase=blocked_before_bitget_live_canary`。
- 凭证输出只显示 boolean，没有回显 API key、secret、passphrase。
- 最新 checklist 中 `open_order_count=0`。

## 样本质量

研究样本来自 `artifacts/bitget_4h_samples`，该目录不进入 Git 提交。

| 样本 | K线数 | UTC 起止 | 重复时间戳 | 非 4h 缺口 | OHLC 异常 | 买入持有收益 |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| bitget-BTCUSDT-4h-2024-01-01_2024-06-28.csv | 1080 | 2024-01-01 00:00 到 2024-06-28 20:00 | 0 | 0 | 0 | 42.7462% |
| bitget-BTCUSDT-4h-2024-06-29_2024-12-25.csv | 1080 | 2024-06-29 00:00 到 2024-12-25 20:00 | 0 | 0 | 0 | 63.6253% |
| bitget-BTCUSDT-4h-2024-12-26_2025-06-23.csv | 1080 | 2024-12-26 00:00 到 2025-06-23 20:00 | 0 | 0 | 0 | 6.4038% |
| bitget-BTCUSDT-4h-2025-06-24_2025-12-20.csv | 1080 | 2025-06-24 00:00 到 2025-12-20 20:00 | 0 | 0 | 0 | -15.7883% |
| bitget-BTCUSDT-4h-2025-12-21_2026-05-31.csv | 972 | 2025-12-21 00:00 到 2026-05-31 20:00 | 0 | 0 | 0 | -16.3481% |

阶段特征很明确：前两段偏强趋势，第三段偏震荡，后两段偏下跌。旧 4h long-only 参数在后三段被打穿，不能继续靠扩大同类参数网格强推。

## 失败矩阵

既有失败矩阵 `artifacts/bitget_4h_failure_matrix_probe.json` 显示：

- 32 组 momentum / defensive 组合中，`prefilter_pass_count=0`。
- 失败原因集中在 `strategy_gate_return_too_low` 25 次、`strategy_gate_insufficient_trades` 7 次。
- 失败样本集中在 2024-12-26 到 2025-06-23、2025-12-21 到 2026-05-31、2025-06-24 到 2025-12-20。
- best failed candidate 只能说明“失败候选里相对不差”，不能作为 profile 或 live readiness 证据。

本轮固定预算预筛 `artifacts/bitget_strategy_budget_screen_20260602.json` 显示：

- 策略假设：`regime_filtered_ma_cross`、`regime_breakout`、`regime_adaptive_long`、`defensive_trend`、`momentum_breakout`。
- 预算：总网格 2700 组，本轮最多评估 500 组。
- 结果：`status=fail`，`prefilter_pass_count=0`，`decision=blocked`。
- 失败原因：`strategy_gate_insufficient_trades` 419 次，`strategy_gate_return_too_low` 81 次。
- best failed candidate 只有 4 笔交易，统计置信度不足，不能进入完整验证。

2026-06-02 追加 4h 全量分页预筛：

- 使用 6 个策略族：`defensive_trend`、`regime_filtered_ma_cross`、`regime_breakout`、`regime_adaptive_long`、`volatility_breakout_trend`、`panic_rebound`。
- 通过 `--skip-combinations` 和 `--max-combinations 500` 分页覆盖 4h 参数网格，所有分页 `prefilter_pass_count=0`。
- 主要失败仍集中在 `strategy_gate_return_too_low` 与 `strategy_gate_insufficient_trades`。
- 结论：4h 主线没有可晋级候选，不允许 promote。

2026-06-02 追加 2h / 1h 公开行情研究：

| 周期 | 样本来源 | 样本数 | K线数 | 有效预筛文件 | 通过候选 | 主要失败原因 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 2h | Bitget 1h 官方现货历史 K 线本地聚合 | 5 | 10572 | 25 | 0 | `strategy_gate_return_too_low`、少量 `strategy_gate_insufficient_trades` |
| 1h | Bitget 官方现货历史 K 线 | 5 | 21144 | 10 | 0 | `strategy_gate_return_too_low`、少量 `strategy_gate_insufficient_trades` |

2h 研究覆盖的策略包括：`moving_average_cross`、`donchian_breakout`、`trend_pullback`、`mean_reversion`、`rsi_mean_reversion`、`momentum_breakout`、`bollinger_mean_reversion`、`regime_breakout`、`regime_filtered_ma_cross`、`trend_filtered_ma_cross`、`defensive_trend`、`panic_rebound`、`regime_adaptive_long`、`volatility_breakout_trend`、`downtrend_breakdown_short`。其中交易数足够的候选普遍收益为负；收益或利润因子看似过线的候选交易数过少，不能作为实盘证据。

1h 研究覆盖的策略包括：`moving_average_cross`、`trend_filtered_ma_cross`、`mean_reversion`、`bollinger_mean_reversion`、`regime_breakout`、`regime_adaptive_long`、`volatility_breakout_trend`、`downtrend_breakdown_short`、`donchian_breakout`、`defensive_trend`。其中 `trend_filtered_ma_cross`、`regime_breakout` 有个别失败候选表现接近，但交易数不足或跨样本最低收益仍无法通过硬门禁。

因此，当前不能进入 `select-samples` 正式验证阶段；也没有任何候选具备 profile 写入资格。

2026-06-02 追加 `adaptive_range_reclaim` 首批固定预算预筛：

| 周期 | 命令安全边界 | 样本数 | 评估组合 | 通过候选 | best failed candidate | 结论 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 1h | `--no-dotenv`、离线 CSV、`exchange=bitget` | 5 | 40 / 128 | 0 | 586 笔、return -7.9583%、PF 0.4646 | 收益过低 |
| 2h | `--no-dotenv`、离线 CSV、`exchange=bitget` | 5 | 40 / 128 | 0 | 334 笔、return -4.8238%、PF 0.4700 | 收益过低 |
| 4h | `--no-dotenv`、离线 CSV、`exchange=bitget` | 5 | 40 / 128 | 0 | 202 笔、return -1.3889%、PF 0.9290 | 收益过低 |

本次只跑首批 40 组固定预算，不把失败结果扩展成结论外推。它只说明该研究假设在当前预算下没有进入 `select-samples` 的资格；后续若继续探索，只能扩大新的假设或重新冻结参数预算，不能降低门禁换取通过。

2026-06-02 追加 `volatility_regime_pullback_reclaim` 固定预算预筛：

| 周期 | 命令安全边界 | 样本数 | 评估组合 | 通过候选 | best failed candidate | 结论 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 1h | `--no-dotenv`、离线 CSV、`exchange=bitget` | 5 | 64 / 64 | 0 | 52 笔、min return -0.8556%、PF 0.2933、win rate 26.9231% | 收益过低 |
| 2h | `--no-dotenv`、离线 CSV、`exchange=bitget` | 5 | 64 / 64 | 0 | 40 笔、min return -0.8003%、PF 0.2851、win rate 35.0% | 收益过低 |
| 4h | `--no-dotenv`、离线 CSV、`exchange=bitget` | 5 | 64 / 64 | 0 | 44 笔、min return -0.2774%、PF 0.9476、win rate 31.8182% | 收益过低 |

该策略尝试把趋势质量、波动率区间、回踩回收和区间中轴回收组合起来，入口形态包括 `pullback_reclaim` 与 `range_mid_reclaim`。结果仍是 `prefilter_pass_count=0`，说明它在当前 5 段已触碰样本上没有进入完整 `select-samples` 的资格；不得把“4h 最佳失败候选接近盈亏平衡”解读成可灰度证据。

## 策略假设

旧方向暂停：不继续围绕 BTCUSDT / 4h / long-only 的旧均线参数做无限微调。

后续只允许按明确假设推进，且必须先解决“交易数足够时收益不过、收益接近时交易数不足”的结构性矛盾：

- 趋势过滤假设：只在明确上行结构中做多，震荡和下行阶段空仓。
- 震荡回避假设：识别 choppy 阶段后降低交易频率或完全跳过。
- 防守入场假设：牺牲交易频率换取更低回撤，但必须满足最低交易数门禁。
- 多周期确认假设：4h 信号引入更高周期趋势确认，避免单周期噪声。
- 研究-only 空头假设：可用于解释下跌段，但在现货实盘路径中不能直接作为可上线做空策略。
- 研究-only 区间回收假设：`adaptive_range_reclaim` 用于观察下跌或震荡后的回收形态，只能作为离线候选筛选器，不能写入 active profile，也不能进入现货执行入口。
- 研究-only 波动率状态回踩回收假设：`volatility_regime_pullback_reclaim` 用于观察趋势质量、可交易波动率和回踩/中轴回收的组合信号；当前预筛失败，只能保留为失败归因，不能写入 active profile，也不能进入现货执行入口。
- 低频突破改造假设：如果继续保留突破类策略，必须明确提高样本外交易数，避免 2 到 18 笔交易的统计置信度不足。
- 资金费率无关假设：当前是现货路径，不得引入合约资金费率或杠杆收益来美化结果。

Bitget 现货灰度只允许现货语义。任何做空、杠杆、合约策略都只能作为研究解释，不得混入 5U 现货 canary 证据。

## 数据切分

由于前期筛选已经多次触碰全部 5 段样本，当前样本集中已经没有严格意义上的 pristine OOS 窗口。为了避免过拟合，当前 5 段只能作为内部研究集和失败归因集。

下一阶段应重新下载或等待新增历史窗口，并在跑任何新策略前冻结切分：

- 训练集：用于策略假设和参数搜索。
- 验证集：用于淘汰候选，不允许反复回调阈值。
- 样本外集：候选完全定型后只能触碰一次。

如果没有新的未触碰样本外窗口，不允许生成 live profile。

冻结命令示例：

```powershell
kxian-bot --no-dotenv freeze-sample-manifest `
  --exchange bitget `
  --symbol BTCUSDT `
  --interval 4h `
  --train-files artifacts/samples/train/*.csv `
  --validation-files artifacts/samples/validation/*.csv `
  --final-oos-files artifacts/samples/final-oos/*.csv `
  --output-file artifacts/样本清单.json
```

研究证据命令示例：

```powershell
kxian-bot --no-dotenv strategy-research-evidence `
  --manifest artifacts/样本清单.json `
  --hypothesis-id H-BITGET-001 `
  --hypothesis "BTCUSDT 4h 回踩回收在趋势过滤后降低噪声" `
  --strategy volatility_regime_pullback_reclaim `
  --command "kxian-bot --no-dotenv screen-samples ..." `
  --result-file artifacts/screen-result.json `
  --max-combinations 500 `
  --skip-combinations 0 `
  --evidence-out artifacts/研究证据-H-BITGET-001.json
```

## 研究预算

固定预算如下：

- 每个新策略假设最多 500 组预筛组合。
- 每轮最多 3 个策略假设。
- 只有 `prefilter_pass_count > 0` 时，才进入 `select-samples` 完整验证。
- 完整验证必须同时覆盖 sample validation、stress、walk-forward、参数邻近稳定性。
- 如果主要失败继续集中在 `return_too_low` 或 `insufficient_trades`，停止该假设，不扩大同类网格。
- 严禁降低 `strategy_gate`、`sample_validation_gate`、`stress_gate`、`walk_forward_gate` 换取通过。

## 安全边界

当前允许的命令范围：

- `kxian-bot readiness`
- `kxian-bot launch-checklist --target live`
- `kxian-bot exchange-health --timeout-seconds 5`
- `kxian-bot screen-samples --summary-only`
- `kxian-bot --no-dotenv screen-samples --exchange bitget --symbol BTCUSDT --interval <1h|2h|4h> --summary-only`
- `kxian-bot select-samples`，但不得带 `--promote`
- `kxian-bot backtest`
- `kxian-bot stress-backtest`
- `kxian-bot walk-forward`
- `kxian-bot walk-forward-samples`
- `kxian-bot validate-strategy`
- `kxian-bot validate-samples`

当前禁止的命令范围：

- `kxian-bot approve-bitget-live-gray`
- `kxian-bot trade-loop`
- `kxian-bot run-once`
- 使用 `adaptive_range_reclaim`、`volatility_regime_pullback_reclaim` 或其他 research-only 策略执行 `run-once` / `trade-loop`
- 将 research-only profile 晋升到 testnet/live，或用于 Bitget live gray 批准
- `kxian-bot test-order`
- `kxian-bot promote-profile-to-live`
- 任何带 `--promote` 的失败候选推进命令
- 任何真实下单路径
- `cancel-order`，包括 `kxian-bot cancel-order`，除非已经发现 open/submitted/partial/unknown 真实订单，并经人工确认需要清理

只有 `strategy_gate`、`sample_validation_gate`、`stress_gate`、`walk_forward_gate` 全部通过后，才重新讨论 5U canary。

## 完成标准

当前阶段的完成标准不是“完成 5U canary”，而是明确证明是否具备进入 canary 的前置证据。

本轮完成后的状态是：

- Bitget 接入可用。
- 样本质量没有发现基础结构问题。
- 旧策略族和本轮固定预算新假设预筛均未通过，包括 `adaptive_range_reclaim` 与 `volatility_regime_pullback_reclaim`。
- 策略 profile 缺失是合理阻断，不应绕过。
- 项目必须停在 `blocked_before_bitget_live_canary`。

下一次只有在新策略完整验证通过、profile 生成、`readiness` 通过、`launch-checklist --target live` 只剩 canary 人工确认时，才允许重新请求一次 5U canary 授权。

## 已补齐与后续增强

本轮已补齐：

- 研究命令安全边界：只读研究命令允许使用 `validate_execution=False` 加载配置，避免临时研究周期被 live confirmation 短语误卡；真实执行命令继续保留 live confirmation 硬门禁。
- Bitget 2h 行情适配：由于 Bitget 现货历史 K 线不支持直接请求 `2h` granularity，系统使用 `1h` 公开 K 线本地聚合成 `2h`，并用测试断言不会把 `2h` 直接提交到 Bitget 公共行情接口。
- Bitget live 脱敏证据包：导出配置摘要、endpoint、readiness、live setup、launch checklist、open orders、账户同步、成交同步、canary 生命周期和内容哈希，不包含 key、secret、passphrase、signature、headers 原文。
- Bitget 只读验收一键命令：固定串联 readiness、exchange-health、live-setup-check、launch-checklist，并输出 `will_submit_orders=false`；默认不访问账户余额、不同步成交，只有显式增加 `--include-account` 或 `--sync-fills` 时才触达账户查询或写入本地成交同步摘要。
- Dashboard Bitget live-only 状态条和证据下载按钮：按钮有 loading、disabled、`aria-busy`、成功/失败 toast 和固定结果区反馈，不提供 canary 或下单入口。

下一阶段建议优先做 P0 工程增强：

- 新策略假设开发：先补一个只读研究专用策略族或策略组合，不触碰实盘执行；只有在 1h/2h/4h 多段样本全部过 `strategy_gate` 后，再进入 `select-samples`。
- 独立审计事件表：记录命令名、scope、执行者、结果、失败原因、证据哈希、是否只读、是否可能下单。

P2 可增加 canary 一次性 approval、冷却期、运行前后快照对比，以及带哈希链的不可变审计导出。
