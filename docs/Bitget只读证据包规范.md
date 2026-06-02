# Bitget 只读证据包规范

Bitget 只读证据包由以下命令生成：

```powershell
kxian-bot bitget-live-readiness --timeout-seconds 5 --evidence-out artifacts/bitget-live-readiness.json
```

也可以在 Dashboard 点击“下载只读证据”生成。Dashboard 路径不会触发账户查询、成交同步或任何下单动作。

## 顶层字段

| 字段 | 说明 |
| --- | --- |
| `schema` | 固定为 `kxian.bitget_live.evidence.v1` |
| `scope` | 固定 live / bitget / BTCUSDT / 4h / use_testnet=false |
| `credentials` | 只显示 `bitget_api_key`、`bitget_api_secret`、`bitget_api_passphrase` boolean |
| `profile` | 当前 live:bitget:BTCUSDT:4h profile 摘要 |
| `phase_summary` | 只读阶段归类，例如 `strategy_evidence_blocked` 或 `blocked_before_bitget_live_canary` |
| `readiness` | readiness 状态摘要 |
| `exchange_health` | 交易所连通状态摘要 |
| `live_setup_check` | live 只读准入摘要 |
| `launch_checklist` | live checklist 摘要，不包含订单 ID 原文 |
| `account_balance` | 仅显式 `--include-account` 时出现状态摘要 |
| `sync_fills` | 仅显式 `--sync-fills` 时出现计数摘要 |
| `audit` | git commit、dirty worktree、命令上下文、证据哈希 |
| `acceptance` | 当前只读阶段固定 `live_ready=false`、`canary_ready=false` |
| `redaction` | 脱敏策略声明 |
| `safety` | 所有会导致下单或修改 live 状态的动作均为 false |

## 脱敏要求

证据包不得包含：

- API key 原文或片段
- API secret 原文或片段
- API passphrase 原文或片段
- `ACCESS-PASSPHRASE` 原文
- signature 原文
- headers 原文
- exchange order id 原文
- trade id 原文

凭证存在性只能以 boolean 表达。订单与成交只能以状态、数量或计数摘要表达。

## 阶段解释

| phase_summary.phase | 含义 | 动作 |
| --- | --- | --- |
| `strategy_evidence_blocked` | 策略证据门禁未过 | 停止，只能继续离线研究 |
| `live_setup_blocked` | live 只读准入不合格 | 修复配置或凭证后重跑 |
| `readonly_gate_blocked` | 只读链路存在其他阻断 | 按输出 next steps 修复 |
| `blocked_before_bitget_live_canary` | 只读门禁已接近完成，但缺少本轮 canary 证据 | 仍不得自动下单，必须人工审批 |
| `live_review_ready` | checklist 通过 | 停止，等待人工复核，不扩大循环 |

无论处于哪个阶段，证据包中的 `will_submit_orders` 与 `canary_allowed` 都必须为 false。

