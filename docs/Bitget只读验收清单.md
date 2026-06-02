# Bitget 只读验收清单

本清单只覆盖 `Bitget Spot / BTCUSDT / 4h` 的 live-only 只读验收。它不会下单，不会批准灰度，不会读取或回显 API key、secret、passphrase 原文。

## 固定范围

| 项目 | 固定值 |
| --- | --- |
| mode | `live` |
| exchange | `bitget` |
| symbol | `BTCUSDT` |
| interval | `4h` |
| use_testnet | `false` |
| 单笔 canary 上限 | `KXIAN_MAX_LIVE_ORDER_USDT=5` |

## 逐步判定表

| 步骤 | 命令 | 允许继续 | 必须中止 | 下一步 |
| --- | --- | --- | --- | --- |
| 1 | `kxian-bot readiness` | 只剩策略证据或 canary 证据阻断，且 scope 为 Bitget live | scope、凭证、live confirmation、risk、open orders 异常 | 修复阻断项后重跑 |
| 2 | `kxian-bot exchange-health --timeout-seconds 5` | `status=pass`，交易端点为 Bitget 生产端点 | timeout、5xx、权限错误、误指测试网或其他交易所 | 停止，排查网络或配置 |
| 3 | `kxian-bot live-setup-check --timeout-seconds 5` | `will_submit_orders=false`，所有只读检查可解释 | key/passphrase 缺失、5U 上限不合规、live 确认不匹配 | 停止，修正 `.env` |
| 4 | `kxian-bot bitget-live-readiness --timeout-seconds 5 --evidence-out artifacts/bitget-live-readiness.json` | 输出脱敏证据，`will_submit_orders=false` | 输出包含密钥原文、scope 不匹配、只读命令触发下单 | 停止，视为安全缺陷 |
| 5 | `kxian-bot launch-checklist --target live` | 如果只差 `blocked_before_bitget_live_canary`，保持只读阻断 | strategy/profile/open orders/readiness 失败 | 先补策略证据，不进入 canary |

## 只读命令边界

`bitget-live-readiness` 默认不会访问账户余额，也不会同步成交。只有显式添加：

```powershell
kxian-bot bitget-live-readiness --include-account
kxian-bot bitget-live-readiness --sync-fills
```

才会触达生产账户查询接口或写入本地成交同步摘要。`--sync-fills` 不提交订单，但会写入本地同步结果；执行前必须确认这是本轮验收需要的动作。

## 继续条件

只有同时满足以下条件，才可以进入下一阶段人工讨论：

- `mode=live`
- `exchange=bitget`
- `symbol=BTCUSDT`
- `interval=4h`
- `use_testnet=false`
- `will_submit_orders=false`
- 凭证仅显示 boolean
- `KXIAN_MAX_LIVE_ORDER_USDT=5`
- open/submitted/partial/unknown 订单为 0
- `strategy_gate`、`sample_validation_gate`、`stress_gate`、`walk_forward_gate` 均已通过

只要任一策略证据门禁未通过，必须停在只读研究阶段，不得执行 `approve-bitget-live-gray`、`trade-loop`、`run-once`、`test-order`、`promote-profile-to-live`。

