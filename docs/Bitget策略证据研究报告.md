# Bitget 策略证据研究报告

## 结论

本轮只完成 Bitget / BTCUSDT / 4h 的只读策略证据研究，不进入实盘灰度。

当前结论是：Bitget live-only 接入链路可用，生产凭证存在性、live-only endpoint、5U 灰度上限、open orders 清理状态均通过只读检查；但策略证据不足，`readiness` 仍被 `strategy_gate`、`sample_validation_gate`、`stress_gate`、`walk_forward_gate` 阻断。

因此当前状态必须保持 `blocked_before_bitget_live_canary`。不得执行 `approve-bitget-live-gray`、`trade-loop`、`run-once`、`test-order`、`promote-profile-to-live`，也不得把 `screen-samples` 的失败预筛结果包装成上线证据。

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

## 策略假设

旧方向暂停：不继续围绕 BTCUSDT / 4h / long-only 的旧均线参数做无限微调。

后续只允许按明确假设推进：

- 趋势过滤假设：只在明确上行结构中做多，震荡和下行阶段空仓。
- 震荡回避假设：识别 choppy 阶段后降低交易频率或完全跳过。
- 防守入场假设：牺牲交易频率换取更低回撤，但必须满足最低交易数门禁。
- 多周期确认假设：4h 信号引入更高周期趋势确认，避免单周期噪声。
- 研究-only 空头假设：可用于解释下跌段，但在现货实盘路径中不能直接作为可上线做空策略。

Bitget 现货灰度只允许现货语义。任何做空、杠杆、合约策略都只能作为研究解释，不得混入 5U 现货 canary 证据。

## 数据切分

由于前期筛选已经多次触碰全部 5 段样本，当前样本集中已经没有严格意义上的 pristine OOS 窗口。为了避免过拟合，当前 5 段只能作为内部研究集和失败归因集。

下一阶段应重新下载或等待新增历史窗口，并在跑任何新策略前冻结切分：

- 训练集：用于策略假设和参数搜索。
- 验证集：用于淘汰候选，不允许反复回调阈值。
- 样本外集：候选完全定型后只能触碰一次。

如果没有新的未触碰样本外窗口，不允许生成 live profile。

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
- 旧策略族和本轮固定预算新假设预筛均未通过。
- 策略 profile 缺失是合理阻断，不应绕过。
- 项目必须停在 `blocked_before_bitget_live_canary`。

下一次只有在新策略完整验证通过、profile 生成、`readiness` 通过、`launch-checklist --target live` 只剩 canary 人工确认时，才允许重新请求一次 5U canary 授权。

## 后续增强建议

下一阶段建议优先做 P0 工程增强：

- Bitget live 脱敏证据包：导出配置摘要、endpoint、readiness、live setup、launch checklist、open orders、账户同步、成交同步、canary 生命周期和内容哈希，不包含 key、secret、passphrase、signature、headers 原文。
- Bitget 只读验收一键命令：固定串联 readiness、exchange-health、live-setup-check、launch-checklist，并输出 `will_submit_orders=false`；默认不访问账户余额、不同步成交，只有显式增加 `--include-account` 或 `--sync-fills` 时才触达账户查询或写入本地成交同步摘要。
- 独立审计事件表：记录命令名、scope、执行者、结果、失败原因、证据哈希、是否只读、是否可能下单。

P1 可继续增强 Dashboard 的 Bitget live-only 步骤条和证据下载按钮。按钮必须有 loading、disabled、`aria-busy`、成功/失败 toast 和固定结果区反馈。

P2 可增加 canary 一次性 approval、冷却期、运行前后快照对比，以及带哈希链的不可变审计导出。
