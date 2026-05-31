$env:KXIAN_MODE = "paper"
$env:KXIAN_EXCHANGE = "binance"
$env:KXIAN_SYMBOL = "BTCUSDT"
$env:KXIAN_INTERVAL = "4h"
$env:KXIAN_USE_TESTNET = "true"
$env:KXIAN_ENABLE_TESTNET_AUTOTRADE = "false"
$env:KXIAN_SHORT_WINDOW = "10"
$env:KXIAN_LONG_WINDOW = "30"
$env:KXIAN_STOP_LOSS_PCT = "2"
$env:KXIAN_TAKE_PROFIT_PCT = "8"
$env:KXIAN_TRAILING_STOP_PCT = "4"
$env:KXIAN_COOLDOWN_SECONDS = "86400"

python -m kxian_bot.cli dashboard --host 127.0.0.1 --port 8001
