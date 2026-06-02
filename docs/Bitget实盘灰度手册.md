# Bitget 实盘灰度手册

本手册只覆盖 `Bitget Spot / BTCUSDT / 4h` 的小额实盘灰度。它不是 Binance Spot Testnet 闭环的替代品，也不把 Bitget 包装成测试网；当前 Bitget 路径是 live-only 灰度，目标是在人工确认后执行一次 5U 以内的 canary，再用查单、撤单、成交同步、账户同步和最终 checklist 复核。

## 安全边界

- 如果 `readiness` 仍被 `strategy_gate`、`sample_validation_gate`、`stress_gate`、`walk_forward_gate` 任一项阻断，必须停在只读研究阶段，不得执行 `approve-bitget-live-gray`、`trade-loop` 或任何 canary。
- 不使用 `mode=testnet + exchange=bitget`，该组合会被系统阻断。
- 不执行 `promote-profile-to-live` 作为 Bitget 灰度入口，改用 `approve-bitget-live-gray` 写入 Bitget 专属批准证据。
- 不用 `test-order` 做 Bitget live canary；Bitget live 下该命令会被阻断。
- 不用 `run-once` 做 Bitget live 执行；只允许 `trade-loop --max-iterations 1 --sleep-seconds 0`。
- 不启动无界 live loop，不允许 `--max-iterations` 为空或大于 1。
- 不在没有 open/submitted/partial/unknown 真实订单的情况下执行 `cancel-order`；只有人工确认需要清理残单时才允许使用。
- 不回显、不提交、不截图 API key、secret、passphrase、签名、请求头。
- 首次 canary 的单笔上限固定为 `KXIAN_MAX_LIVE_ORDER_USDT=5`。

## 生产 Key 准备

在 Bitget 生产环境创建新的现货 API key，只给最小必要权限：

- 允许读取账户。
- 允许现货交易。
- 禁止提现。
- 禁止不必要的资金划转和管理权限。
- 建议绑定当前机器或部署机器的 IP 白名单。
- 妥善保存 API key、API secret 和 API passphrase；不要放到聊天、截图、日志或提交记录里。

`.env` 由操作者手动填写，关键项如下：

```dotenv
KXIAN_MODE=live
KXIAN_EXCHANGE=bitget
KXIAN_SYMBOL=BTCUSDT
KXIAN_INTERVAL=4h
KXIAN_USE_TESTNET=false
KXIAN_MARKET_DATA_SOURCE=exchange

KXIAN_BITGET_API_KEY=
KXIAN_BITGET_API_SECRET=
KXIAN_BITGET_API_PASSPHRASE=

KXIAN_ALLOW_LIVE=true
KXIAN_LIVE_DRY_RUN=false
KXIAN_ENABLE_LIVE_AUTOTRADE=true
KXIAN_LIVE_CONFIRMATION=LIVE:bitget:BTCUSDT:4h
KXIAN_LIVE_CREDENTIALS_CONFIRMED=true
KXIAN_MAX_LIVE_ORDER_USDT=5
```

只有在确认生产 key 不是测试网 key、提现已禁用、权限最小化、最好已绑定 IP 白名单后，才能设置 `KXIAN_LIVE_CREDENTIALS_CONFIRMED=true`。

## 固定命令顺序

先拉取 Bitget 交易规则，避免 5U canary 低于最小下单额或精度不合规：

```powershell
kxian-bot trading-rules --symbol BTCUSDT --refresh-from-exchange
```

再做基础只读检查：

```powershell
kxian-bot readiness
kxian-bot exchange-health --timeout-seconds 5
```

也可以使用 Bitget 不下单验收命令一次性生成脱敏证据包：

```powershell
kxian-bot bitget-live-readiness --timeout-seconds 5 --evidence-out artifacts/bitget-live-readiness.json
```

该命令固定 `will_submit_orders=false`，不会执行 `approve-bitget-live-gray`、`trade-loop`、`run-once`、`test-order`、`promote-profile-to-live` 或 `cancel-order`。默认也不会访问账户余额或同步成交；只有显式增加 `--include-account` 或 `--sync-fills` 时，才会触达生产账户查询接口或写入本地成交同步结果。

写入 Bitget live 灰度批准证据：

```powershell
kxian-bot approve-bitget-live-gray --confirmation LIVE:bitget:BTCUSDT:4h --updated-by <operator>
```

然后执行 canary 前只读准入检查：

```powershell
kxian-bot live-setup-check --timeout-seconds 5
```

允许继续的结果：

```text
status=pass
phase=ready_for_bounded_live_canary
will_submit_orders=false
exchange=bitget
symbol=BTCUSDT
interval=4h
```

此时 `launch-checklist --target live` 可能仍然因为 `missing_bitget_live_canary_order` 而处于 `blocked_before_bitget_live_canary`。这是正常的 canary 前状态，不代表可以跑多轮，只代表允许人工批准一次单轮 canary。

人工最后确认后，只执行一次：

```powershell
kxian-bot trade-loop --max-iterations 1 --sleep-seconds 0
```

执行后立即复核：

```powershell
kxian-bot order-status --order-id <exchange_order_id>
kxian-bot sync-fills
kxian-bot account-balance
kxian-bot launch-checklist --target live
```

如果订单处于 open、submitted、partially filled、未知状态或无法确认状态，先清理再复核：

```powershell
kxian-bot order-status --order-id <exchange_order_id>
kxian-bot cancel-order --order-id <exchange_order_id>
kxian-bot sync-fills
kxian-bot account-balance
kxian-bot launch-checklist --target live
```

最终通过标准：

```text
status=pass
phase=ready_for_bounded_live_loop
```

达到这里立即停止，不扩大循环。

## 阻断条件

以下情况必须停止，不执行 canary：

- `mode` 不是 `live`。
- `exchange` 不是 `bitget`。
- `use_testnet=true`。
- Bitget key、secret、passphrase 任一缺失。
- `KXIAN_LIVE_CREDENTIALS_CONFIRMED` 不是 `true`。
- `KXIAN_MAX_LIVE_ORDER_USDT` 大于 5。
- `KXIAN_LIVE_CONFIRMATION` 不是 `LIVE:bitget:BTCUSDT:4h`。
- `trading-rules --refresh-from-exchange` 失败或规则字段缺失。
- `exchange-health` 不是 Bitget 生产端点。
- 存在 open 或 partial 订单。
- canary 前 `live-setup-check` 没有返回 `status=pass`。

以下情况必须停止扩大灰度：

- 订单状态为 open、submitted、partially filled 或 unknown。
- 非安全 rejected，例如签名错误、权限错误、时间戳错误。
- 交易所 5xx、超时后订单状态不明。
- `sync-fills` 失败。
- `account-balance` 失败。
- open orders 不为 0。
- 最终 `launch-checklist --target live` 未通过。

## 可接受结果

单轮 canary 后，以下结果可以进入最终 checklist 复核：

- 真实订单最终 `filled`。
- 真实订单最终 `canceled`。
- 没有信号，记录为安全拒绝，例如 `no_signal` 或 `no_new_candle`。
- 本地安全规则拒绝，例如 `live_order_notional_exceeds_limit`、`exchange_rule_min_notional`、`exchange_rule_min_quantity`、`exchange_insufficient_balance`。

最终 checklist 只接受灰度批准时间之后产生的 Bitget live canary 证据；旧订单不能冒充新一轮验收。

## 人工核对表

| 项目 | 必须满足 |
| --- | --- |
| 交易所 | Bitget Spot |
| 交易对 | BTCUSDT |
| 周期 | 4h |
| 生产 key | 已确认不是测试网 key |
| 提现权限 | 已禁用 |
| IP 白名单 | 已配置或已记录未配置原因 |
| passphrase | 已手动填写且不外泄 |
| 单笔上限 | `KXIAN_MAX_LIVE_ORDER_USDT=5` |
| 执行命令 | 只允许 `trade-loop --max-iterations 1 --sleep-seconds 0` |
| 最终停止点 | `launch-checklist --target live` 返回 `status=pass`、`phase=ready_for_bounded_live_loop` |

## 后续优化

- `bitget-live-readiness --evidence-out` 已可生成不下单脱敏证据包；后续增强 approval id、canary 生命周期、成交同步和账户同步的更细粒度摘要。
- 增加专用 `bitget-live-canary` 编排命令，把只读检查、单轮执行和复核输出串起来，但执行前仍需显式确认。
- Dashboard 增加 Bitget 灰度步骤条和证据下载。
- 将“提现已禁用、IP 白名单已确认”写入结构化审批证据。
- 增加浏览器级 Dashboard 测试、告警通知、不可变审计导出和 secret scan。
