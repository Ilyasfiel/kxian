from __future__ import annotations


OPS_DASHBOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>量化运维控制台</title>
  <style>
    :root {
      --bg: #080b10;
      --surface-0: #0b1017;
      --surface-1: #111821;
      --surface-2: #17202b;
      --surface-3: #202b38;
      --line: #2f3a46;
      --line-soft: rgba(143, 161, 180, 0.18);
      --text: #edf3f8;
      --muted: #9aa8b6;
      --soft: #c7d1dc;
      --green: #2ea043;
      --cyan: #3fb1ed;
      --amber: #d29922;
      --red: #f85149;
      --violet: #bc8cff;
      --row: 32px;
      --mono: "JetBrains Mono", "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
      --ui: Inter, "Segoe UI", Arial, sans-serif;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      min-width: 1180px;
      color: var(--text);
      background: var(--bg);
      font-family: var(--ui);
      font-size: 13px;
      line-height: 1.35;
      letter-spacing: 0;
      overflow: hidden;
    }
    button, input, select, textarea {
      font: inherit;
      letter-spacing: 0;
    }
    button {
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--soft);
      height: 32px;
      padding: 0 10px;
      cursor: pointer;
    }
    button:hover { border-color: var(--cyan); color: var(--text); }
    button:focus-visible, select:focus-visible, input:focus-visible, textarea:focus-visible {
      outline: 2px solid var(--cyan);
      outline-offset: 2px;
    }
    button.primary {
      background: var(--green);
      border-color: var(--green);
      color: #061008;
      font-weight: 700;
    }
    button.warn {
      background: rgba(210, 153, 34, 0.16);
      border-color: rgba(210, 153, 34, 0.62);
      color: #ffd88a;
    }
    button.danger {
      background: rgba(248, 81, 73, 0.14);
      border-color: rgba(248, 81, 73, 0.7);
      color: #ffb7b2;
    }
    .language-control {
      position: fixed;
      top: 12px;
      right: 12px;
      z-index: 50;
      height: 32px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 0 6px 0 10px;
      border: 1px solid rgba(63, 177, 237, 0.52);
      background: rgba(8, 19, 27, 0.96);
      box-shadow: 0 12px 28px rgba(0, 0, 0, 0.36);
      white-space: nowrap;
    }
    .language-label {
      color: var(--soft);
      font: 800 11px var(--mono);
      text-transform: uppercase;
    }
    .lang-switch {
      height: 32px;
      display: inline-grid;
      grid-template-columns: 1fr 1fr;
      border-left: 1px solid rgba(63, 177, 237, 0.38);
    }
    .lang-switch button {
      min-width: 48px;
      height: 30px;
      border: 0;
      background: transparent;
      color: var(--muted);
      font-family: var(--mono);
      font-weight: 800;
    }
    .lang-switch button + button {
      border-left: 1px solid rgba(63, 177, 237, 0.3);
    }
    .lang-switch button.active {
      color: #071018;
      background: #a8e3ff;
    }
    select, input, textarea {
      background: #080d13;
      border: 1px solid var(--line);
      color: var(--text);
      height: 32px;
      padding: 0 9px;
      min-width: 0;
    }
    textarea {
      width: 100%;
      height: 70px;
      resize: none;
      padding: 8px;
      font-family: var(--mono);
      font-size: 12px;
      color: var(--muted);
    }
    .app {
      height: 100vh;
      display: grid;
      grid-template-columns: 56px 260px minmax(520px, 1fr) 316px;
      grid-template-rows: 48px 76px minmax(0, 1fr);
      gap: 8px;
      padding: 8px;
      background:
        linear-gradient(var(--line-soft) 1px, transparent 1px),
        linear-gradient(90deg, var(--line-soft) 1px, transparent 1px),
        var(--bg);
      background-size: 32px 32px;
    }
    .rail, .topbar, .strip, .nav, .panel, .inspector {
      background: rgba(17, 24, 33, 0.98);
      border: 1px solid var(--line);
    }
    .rail {
      grid-row: 1 / 4;
      display: grid;
      grid-template-rows: 44px repeat(7, 40px) 1fr 40px;
      gap: 6px;
      padding: 6px;
    }
    .brand {
      display: grid;
      place-items: center;
      background: #07130d;
      border: 1px solid rgba(46, 160, 67, 0.7);
      color: #8ff7a3;
      font: 800 15px var(--mono);
    }
    .rail-btn {
      display: grid;
      place-items: center;
      height: 40px;
      border: 1px solid transparent;
      color: var(--muted);
      background: transparent;
      font: 700 12px var(--mono);
    }
    .rail-btn.active {
      border-color: var(--green);
      color: #8ff7a3;
      background: rgba(46, 160, 67, 0.12);
    }
    .topbar {
      grid-column: 2 / 5;
      display: grid;
      grid-template-columns: 160px 180px minmax(220px, 1fr) auto auto auto auto;
      gap: 8px;
      align-items: center;
      padding: 7px 8px;
    }
    .cmd {
      width: 100%;
      font-family: var(--mono);
    }
    .top-pill {
      height: 32px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 0 10px;
      border: 1px solid var(--line);
      background: #0b1118;
      color: var(--soft);
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      display: inline-block;
      border-radius: 50%;
      background: var(--muted);
    }
    .dot.green { background: var(--green); }
    .dot.cyan { background: var(--cyan); }
    .dot.amber { background: var(--amber); }
    .dot.red { background: var(--red); }
    .strip {
      grid-column: 2 / 5;
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 1px;
      padding: 0;
      overflow: hidden;
    }
    .metric {
      min-width: 0;
      padding: 10px 12px;
      background: var(--surface-0);
      border-right: 1px solid var(--line-soft);
    }
    .metric:last-child { border-right: 0; }
    .label {
      color: var(--muted);
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .value {
      margin-top: 4px;
      color: var(--text);
      font: 650 19px var(--mono);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .value.good { color: #8ff7a3; }
    .value.bad { color: #ff9c96; }
    .value.warn { color: #ffd88a; }
    .nav {
      grid-column: 2;
      grid-row: 3;
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto minmax(0, 1fr);
      overflow: hidden;
    }
    .nav-head, .panel-head, .inspector-head {
      height: 38px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 0 10px;
      border-bottom: 1px solid var(--line);
      background: #0c1219;
    }
    .nav-head h2, .panel-head h2, .inspector-head h2 {
      margin: 0;
      font-size: 13px;
      font-weight: 800;
      white-space: nowrap;
    }
    .nav-list {
      min-height: 0;
      overflow: auto;
    }
    .nav-row {
      min-height: 44px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      padding: 7px 10px;
      border-bottom: 1px solid var(--line-soft);
    }
    .nav-row.active {
      background: rgba(63, 177, 237, 0.1);
      box-shadow: inset 2px 0 0 var(--cyan);
    }
    .row-title {
      min-width: 0;
      font-weight: 750;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .row-meta {
      margin-top: 2px;
      color: var(--muted);
      font: 12px var(--mono);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      height: 22px;
      border: 1px solid var(--line);
      padding: 0 7px;
      color: var(--soft);
      background: #0a1016;
      font: 700 10px var(--mono);
      white-space: nowrap;
    }
    .chip.green { border-color: rgba(46, 160, 67, 0.7); color: #8ff7a3; background: rgba(46, 160, 67, 0.1); }
    .chip.cyan { border-color: rgba(63, 177, 237, 0.7); color: #a8e3ff; background: rgba(63, 177, 237, 0.1); }
    .chip.amber { border-color: rgba(210, 153, 34, 0.72); color: #ffd88a; background: rgba(210, 153, 34, 0.11); }
    .chip.red { border-color: rgba(248, 81, 73, 0.72); color: #ffb7b2; background: rgba(248, 81, 73, 0.1); }
    .main {
      grid-column: 3;
      grid-row: 3;
      min-width: 0;
      min-height: 0;
      display: grid;
      grid-template-rows: minmax(285px, 1.15fr) minmax(210px, 0.85fr) minmax(170px, 0.62fr);
      gap: 8px;
    }
    .panel {
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      display: grid;
      grid-template-rows: 38px minmax(0, 1fr);
    }
    .canvas-wrap {
      position: relative;
      min-height: 0;
      background: #080d13;
    }
    canvas {
      width: 100%;
      height: 100%;
      display: block;
    }
    .chart-meta {
      position: absolute;
      top: 10px;
      left: 10px;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      pointer-events: none;
    }
    .time-tabs {
      display: inline-flex;
      border: 1px solid var(--line);
      height: 26px;
      background: #090f15;
    }
    .time-tabs span {
      display: grid;
      place-items: center;
      width: 38px;
      border-right: 1px solid var(--line);
      color: var(--muted);
      font: 700 10px var(--mono);
    }
    .time-tabs span:last-child { border-right: 0; }
    .time-tabs .active { color: var(--cyan); background: rgba(63, 177, 237, 0.08); }
    .panel-grid {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(260px, 0.8fr);
      gap: 8px;
    }
    .table-wrap {
      min-height: 0;
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 12px;
    }
    th, td {
      height: var(--row);
      padding: 0 8px;
      border-bottom: 1px solid var(--line-soft);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      text-align: left;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #0c1219;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
    }
    td.num, th.num {
      text-align: right;
      font-family: var(--mono);
    }
    .mono { font-family: var(--mono); }
    .good { color: #8ff7a3; }
    .bad { color: #ff9c96; }
    .warn-text { color: #ffd88a; }
    .cyan-text { color: #a8e3ff; }
    .events {
      min-height: 0;
      overflow: auto;
      padding: 6px 0;
      background: #080d13;
    }
    .event {
      display: grid;
      grid-template-columns: 112px 54px 78px minmax(0, 1fr);
      gap: 8px;
      align-items: center;
      min-height: 28px;
      padding: 0 10px;
      border-bottom: 1px solid rgba(143, 161, 180, 0.1);
      font-family: var(--mono);
      font-size: 11px;
    }
    .event span { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .inspector {
      grid-column: 4;
      grid-row: 3;
      min-height: 0;
      display: grid;
      grid-template-rows: 38px auto auto auto minmax(0, 1fr) auto;
      overflow: auto;
    }
    .inspect-section {
      padding: 10px;
      border-bottom: 1px solid var(--line-soft);
    }
    .inspect-section h3 {
      margin: 0 0 8px;
      font-size: 11px;
      text-transform: uppercase;
      color: var(--muted);
    }
    .kv {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      min-height: 27px;
      align-items: center;
      border-bottom: 1px solid rgba(143, 161, 180, 0.09);
      font-size: 12px;
    }
    .kv:last-child { border-bottom: 0; }
    .kv b { font-family: var(--mono); font-weight: 600; }
    .bar {
      height: 6px;
      background: #070c11;
      border: 1px solid var(--line-soft);
      overflow: hidden;
    }
    .bar > span {
      display: block;
      height: 100%;
      width: 0%;
      background: var(--green);
    }
    .bar.warn > span { background: var(--amber); }
    .check-list {
      display: grid;
      gap: 6px;
      max-height: 92px;
      overflow: auto;
    }
    .check-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      min-height: 26px;
      padding-bottom: 6px;
      border-bottom: 1px solid rgba(143, 161, 180, 0.09);
      font-size: 11px;
    }
    .check-row:last-child { border-bottom: 0; padding-bottom: 0; }
    .check-title {
      min-width: 0;
      font-family: var(--mono);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .check-msg {
      margin-top: 2px;
      color: var(--muted);
      font-size: 10px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .testnet-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 10px;
    }
    .testnet-actions button {
      width: 100%;
      min-height: 34px;
      font-size: 11px;
    }
    .next-steps {
      display: grid;
      gap: 5px;
      margin-top: 8px;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.35;
    }
    .next-steps span {
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      padding: 10px;
      border-top: 1px solid var(--line);
      background: #0c1219;
    }
    .empty {
      padding: 12px;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 12px;
    }
    .toast {
      position: fixed;
      right: 16px;
      bottom: 16px;
      display: none;
      max-width: 460px;
      padding: 10px 12px;
      border: 1px solid var(--cyan);
      background: #08131b;
      color: var(--text);
      font-family: var(--mono);
      z-index: 10;
    }
    @media (max-width: 1240px) {
      .app { grid-template-columns: 56px 238px minmax(500px, 1fr) 292px; }
      .value { font-size: 16px; }
      th, td { padding: 0 6px; }
    }
  </style>
</head>
<body>
  <main class="app">
    <nav class="rail" aria-label="主导航" data-i18n-attr="aria-label:primaryNav">
      <div class="brand">KX</div>
      <button class="rail-btn active" title="仪表盘" data-i18n-attr="title:navDashboard">DB</button>
      <button class="rail-btn" title="实时监控" data-i18n-attr="title:navLiveMonitor">LM</button>
      <button class="rail-btn" title="策略工厂" data-i18n-attr="title:navStrategyFactory">SF</button>
      <button class="rail-btn" title="安全与 API" data-i18n-attr="title:navSecurityApi">SA</button>
      <button class="rail-btn" title="回测" data-i18n-attr="title:navBacktests">BT</button>
      <button class="rail-btn" title="审计" data-i18n-attr="title:navAudit">AU</button>
      <button class="rail-btn" title="设置" data-i18n-attr="title:settings">ST</button>
      <span></span>
      <button class="rail-btn" title="只读" data-i18n-attr="title:readOnly">RO</button>
    </nav>

    <header class="topbar">
      <select aria-label="环境" data-i18n-attr="aria-label:env">
        <option data-i18n="envProdPaper">生产 / 模拟盘</option>
        <option data-i18n="envStaging">预发布</option>
        <option data-i18n="envLocalDev">本地开发</option>
      </select>
      <div class="top-pill"><span class="dot green"></span><span id="exchangeStatus">本地数据库</span></div>
      <input class="cmd" id="commandInput" value="/dashboard overview --read-only" aria-label="命令输入" data-i18n-attr="aria-label:commandInput" />
      <div class="top-pill"><span class="dot cyan"></span><span id="syncStatus">同步中</span></div>
      <div class="language-control" aria-label="语言切换" data-i18n-attr="aria-label:langSwitch">
        <span class="language-label" data-i18n="language">语言</span>
        <div id="languageSwitch" class="lang-switch" role="group">
          <button type="button" data-lang-option="zh" aria-pressed="true" data-i18n="chinese" data-i18n-attr="title:switchToChinese">中文</button>
          <button type="button" data-lang-option="en" aria-pressed="false" data-i18n="english" data-i18n-attr="title:switchToEnglish">English</button>
        </div>
      </div>
      <button id="reloadButton" title="重新读取数据" data-i18n="reload" data-i18n-attr="title:reloadTitle">刷新</button>
      <button title="设置" data-i18n="settings" data-i18n-attr="title:settings">设置</button>
    </header>

    <section class="strip" aria-label="组合健康状态" data-i18n-attr="aria-label:portfolioHealth">
      <div class="metric"><div class="label" data-i18n="totalEquity">总权益</div><div class="value" id="totalEquity">$0.00</div></div>
      <div class="metric"><div class="label" data-i18n="runPnl">本次盈亏</div><div class="value" id="pnlValue">$0.00</div></div>
      <div class="metric"><div class="label" data-i18n="grossExposure">总敞口</div><div class="value" id="grossExposure">$0.00</div></div>
      <div class="metric"><div class="label" data-i18n="riskBudgetUsed">风险预算</div><div class="value warn" id="riskBudget">0%</div></div>
      <div class="metric"><div class="label" data-i18n="marginHealth">保证金健康</div><div class="value good" id="marginHealth">0%</div></div>
      <div class="metric"><div class="label" data-i18n="openAlerts">未处理告警</div><div class="value warn" id="openAlerts">0</div></div>
    </section>

    <aside class="nav">
      <div class="nav-head">
        <h2 data-i18n="marketWatch">市场监控</h2>
        <span class="chip cyan" data-i18n="live">实时</span>
      </div>
      <div class="nav-list" id="marketList"></div>
      <div class="nav-head">
        <h2 data-i18n="strategyRuns">策略结果</h2>
        <span class="chip" id="runCountChip">0</span>
      </div>
      <div class="nav-list" id="strategyList"></div>
    </aside>

    <section class="main">
      <section class="panel">
        <div class="panel-head">
          <h2 id="chartTitle" data-i18n="chartTitleEmpty">价格带</h2>
          <div class="time-tabs" aria-label="时间范围" data-i18n-attr="aria-label:timeRange">
            <span>1M</span><span class="active">5M</span><span>1H</span><span>1D</span>
          </div>
        </div>
        <div class="canvas-wrap">
          <canvas id="priceChart" width="920" height="330"></canvas>
          <div class="chart-meta">
            <span class="chip green" id="candleChip">0 根K线</span>
            <span class="chip cyan" id="lastCloseChip">收盘 -</span>
            <span class="chip" id="rangeChip">区间 -</span>
          </div>
        </div>
      </section>

      <section class="panel-grid">
        <section class="panel">
          <div class="panel-head">
            <h2 data-i18n="backtestLeaderboard">回测排行榜</h2>
            <span class="chip violet" data-i18n="sortReturn">按收益排序</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th data-i18n="run">运行</th><th data-i18n="pair">交易对</th><th class="num" data-i18n="return">收益</th><th class="num" data-i18n="dd">回撤</th><th class="num" data-i18n="pf">盈亏比</th><th class="num" data-i18n="trades">交易数</th>
                </tr>
              </thead>
              <tbody id="runsTable"></tbody>
            </table>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head">
            <h2 data-i18n="executionStream">执行流</h2>
            <span class="chip cyan" data-i18n="readOnly">只读</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th data-i18n="source">来源</th><th data-i18n="symbol">标的</th><th data-i18n="side">方向</th><th class="num" data-i18n="price">价格</th><th data-i18n="status">状态</th></tr>
              </thead>
              <tbody id="execTable"></tbody>
            </table>
          </div>
        </section>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2 data-i18n="operationalEvents">运行事件流</h2>
          <span class="chip" id="eventCountChip">0 事件</span>
        </div>
        <div class="events" id="events"></div>
      </section>
    </section>

    <aside class="inspector">
      <div class="inspector-head">
        <h2 data-i18n="riskInspector">风险检查器</h2>
        <span class="chip green" data-i18n="safe">安全</span>
      </div>
      <section class="inspect-section">
        <h3 data-i18n="selectedRun">当前运行</h3>
        <div class="kv"><span data-i18n="runId">运行 ID</span><b id="selectedRunId">-</b></div>
        <div class="kv"><span data-i18n="strategy">策略</span><b id="selectedStrategy">-</b></div>
        <div class="kv"><span data-i18n="symbol">标的</span><b id="selectedSymbol">-</b></div>
        <div class="kv"><span data-i18n="trades">交易数</span><b id="selectedTrades">0</b></div>
      </section>
      <section class="inspect-section">
        <h3 data-i18n="riskConstraints">风险约束</h3>
        <div class="kv"><span data-i18n="maxDrawdown">最大回撤</span><b id="selectedDrawdown">0%</b></div>
        <div class="bar warn"><span id="drawdownBar"></span></div>
        <div class="kv"><span data-i18n="profitFactor">盈亏比</span><b id="selectedPf">0.000</b></div>
        <div class="kv"><span data-i18n="winRate">胜率</span><b id="selectedWinRate">0%</b></div>
      </section>
      <section class="inspect-section">
        <h3 data-i18n="marketDiagnostics">行情诊断</h3>
        <div class="kv"><span data-i18n="marketRegime">行情结构</span><b id="marketRegime">-</b></div>
        <div class="kv"><span data-i18n="costPressure">成本压力</span><b id="marketCostPressure">-</b></div>
        <div class="kv"><span data-i18n="buyHold">买入持有</span><b id="marketBuyHold">-</b></div>
        <div class="kv"><span data-i18n="benchmarkDrawdown">基准回撤</span><b id="marketBenchmarkDrawdown">-</b></div>
        <div class="kv"><span data-i18n="trendEfficiency">趋势效率</span><b id="marketTrendEfficiency">-</b></div>
        <div class="kv"><span data-i18n="roundTripFriction">往返成本</span><b id="marketFriction">-</b></div>
        <div class="kv"><span data-i18n="segmentBalance">分段涨跌</span><b id="marketSegmentBalance">-</b></div>
      </section>
      <section class="inspect-section">
        <h3 data-i18n="securityPosture">安全态势</h3>
        <div class="kv"><span data-i18n="mode">模式</span><b data-i18n="readOnly">只读</b></div>
        <div class="kv"><span data-i18n="liveOrders">实盘下单</span><b class="good" data-i18n="blocked">已阻止</b></div>
        <div class="kv"><span data-i18n="automationControl">自动交易控制</span><b id="automationControl" class="good">-</b></div>
        <div class="kv"><span data-i18n="apiKeys">API 密钥</span><b id="apiKeys">0</b></div>
        <div class="kv"><span data-i18n="auditEvents">审计事件</span><b id="auditEvents">0</b></div>
      </section>
      <section class="inspect-section">
        <h3 data-i18n="startupGate">启动门禁</h3>
        <div class="kv"><span data-i18n="automationReady">自动交易就绪</span><b id="preflightStatus" class="warn-text">-</b></div>
        <div class="kv"><span data-i18n="profile">配置</span><b id="preflightProfile">-</b></div>
        <div class="kv"><span data-i18n="profileSource">配置来源</span><b id="activeProfileSource">-</b></div>
        <div class="kv"><span data-i18n="maWindows">均线窗口</span><b id="activeProfileWindows">-</b></div>
        <div class="kv"><span data-i18n="protectiveExits">保护退出</span><b id="activeProfileExits">-</b></div>
        <div class="kv"><span data-i18n="profileEvidence">验证证据</span><b id="activeProfileEvidence">-</b></div>
        <div class="check-list" id="preflightChecks"></div>
      </section>
      <section class="inspect-section">
        <h3 data-i18n="testnetGate">测试网检查</h3>
        <div class="kv"><span data-i18n="readiness">就绪状态</span><b id="readinessStatus" class="warn-text">-</b></div>
        <div class="kv"><span data-i18n="credentialState">测试网密钥</span><b id="credentialStatus" class="warn-text">-</b></div>
        <div class="kv"><span data-i18n="automationFlag">自动交易开关</span><b id="testnetAutomationStatus" class="warn-text">-</b></div>
        <div class="kv"><span data-i18n="lastDryRun">最近 Dry-run</span><b id="dryRunStatus" class="warn-text">-</b></div>
        <div class="next-steps" id="testnetNextSteps"></div>
        <div class="testnet-actions">
          <button class="primary" id="dryRunButton" data-i18n="runTestnetDryRun">测试网 Dry-run</button>
          <button id="observeButton" data-i18n="runTestnetObserve">观察 3 轮</button>
        </div>
      </section>
      <section class="inspect-section">
        <h3 data-i18n="exchangeHealth">交易所连通性</h3>
        <div class="kv"><span data-i18n="publicMarketData">公开行情</span><b id="publicMarketHealth" class="warn-text">-</b></div>
        <div class="kv"><span data-i18n="tradingEndpoint">交易端点</span><b id="tradingEndpointHealth" class="warn-text">-</b></div>
        <div class="next-steps" id="exchangeHealthSteps"></div>
      </section>
      <section class="inspect-section">
        <h3 data-i18n="launchGate">上线门禁</h3>
        <div class="kv"><span data-i18n="testnetLaunch">测试网路径</span><b id="testnetLaunchStatus" class="warn-text">-</b></div>
        <div class="kv"><span data-i18n="testnetPhase">测试网阶段</span><b id="testnetLaunchPhase">-</b></div>
        <div class="kv"><span data-i18n="liveLaunch">实盘路径</span><b id="liveLaunchStatus" class="warn-text">-</b></div>
        <div class="kv"><span data-i18n="livePhase">实盘阶段</span><b id="liveLaunchPhase">-</b></div>
        <div class="kv"><span data-i18n="observationEvidence">观察证据</span><b id="launchObservationStatus" class="warn-text">-</b></div>
        <div class="next-steps" id="launchSteps"></div>
      </section>
      <section class="inspect-section">
        <h3 data-i18n="runTrades">运行成交</h3>
        <div class="table-wrap" style="max-height: 172px;">
          <table>
            <thead><tr><th data-i18n="time">时间</th><th data-i18n="side">方向</th><th class="num" data-i18n="exec">成交价</th><th class="num" data-i18n="pnl">盈亏</th></tr></thead>
            <tbody id="tradeTable"></tbody>
          </table>
        </div>
      </section>
      <section class="inspect-section">
        <h3 data-i18n="operatorNotes">操作备注</h3>
        <textarea readonly id="notes">本地控制台会读取 SQLite 里的 K 线、回测、成交、订单、填单、信号和风险快照；暂停按钮只会切换自动交易停机开关，不会直接下单。</textarea>
      </section>
      <div class="actions">
        <button id="backtestButton" data-i18n="runBacktest">运行回测</button>
        <button class="warn" id="simulateButton" data-i18n="simulate">模拟</button>
        <button class="danger" id="pauseButton" data-i18n="pauseBot">暂停机器人</button>
        <button class="primary" id="exportButton" data-i18n="exportJson">导出 JSON</button>
      </div>
    </aside>
  </main>
  <div class="toast" id="toast"></div>

  <script>
    const I18N = {
      zh: {
        appTitle: "量化运维控制台",
        langSwitch: "语言切换",
        language: "语言",
        chinese: "中文",
        english: "English",
        primaryNav: "主导航",
        env: "环境",
        envProdPaper: "生产 / 模拟盘",
        envStaging: "预发布",
        envLocalDev: "本地开发",
        commandInput: "命令输入",
        switchLanguage: "切换语言",
        switchToChinese: "切换到中文",
        switchToEnglish: "切换到英文",
        portfolioHealth: "组合健康状态",
        timeRange: "时间范围",
        navDashboard: "仪表盘",
        navLiveMonitor: "实时监控",
        navStrategyFactory: "策略工厂",
        navSecurityApi: "安全与 API",
        navBacktests: "回测",
        navAudit: "审计",
        reload: "刷新",
        reloadTitle: "重新读取数据",
        settings: "设置",
        totalEquity: "总权益",
        runPnl: "本次盈亏",
        grossExposure: "总敞口",
        riskBudgetUsed: "风险预算",
        marginHealth: "保证金健康",
        openAlerts: "未处理告警",
        marketWatch: "市场监控",
        chartTitleEmpty: "价格带",
        live: "实时",
        strategyRuns: "策略结果",
        backtestLeaderboard: "回测排行榜",
        sortReturn: "按收益排序",
        run: "运行",
        pair: "交易对",
        return: "收益",
        dd: "回撤",
        pf: "盈亏比",
        trades: "交易数",
        executionStream: "执行流",
        readOnly: "只读",
        source: "来源",
        symbol: "标的",
        side: "方向",
        price: "价格",
        status: "状态",
        operationalEvents: "运行事件流",
        events: "事件",
        riskInspector: "风险检查器",
        safe: "安全",
        selectedRun: "当前运行",
        runId: "运行 ID",
        strategy: "策略",
        riskConstraints: "风险约束",
        maxDrawdown: "最大回撤",
        profitFactor: "盈亏比",
        winRate: "胜率",
        marketDiagnostics: "行情诊断",
        marketRegime: "行情结构",
        costPressure: "成本压力",
        buyHold: "买入持有",
        benchmarkDrawdown: "基准回撤",
        trendEfficiency: "趋势效率",
        roundTripFriction: "往返成本",
        segmentBalance: "分段涨跌",
        regime_uptrend: "上行趋势",
        regime_downtrend: "下行趋势",
        regime_choppy: "震荡",
        regime_mixed: "混合",
        cost_low: "低",
        cost_medium: "中",
        cost_high: "高",
        cost_unknown: "未知",
        securityPosture: "安全态势",
        mode: "模式",
        liveOrders: "实盘下单",
        automationControl: "自动交易控制",
        blocked: "已阻止",
        apiKeys: "API 密钥",
        auditEvents: "审计事件",
        startupGate: "启动门禁",
        testnetGate: "测试网检查",
        readiness: "就绪状态",
        credentialState: "测试网密钥",
        automationFlag: "自动交易开关",
        lastDryRun: "最近 Dry-run",
        runTestnetDryRun: "测试网 Dry-run",
        runTestnetObserve: "观察 3 轮",
        exchangeHealth: "交易所连通性",
        publicMarketData: "公开行情",
        tradingEndpoint: "交易端点",
        dryRunStarted: "正在运行测试网 dry-run",
        dryRunPassed: "测试网 dry-run 通过",
        dryRunFailed: "测试网 dry-run 未通过",
        observeStarted: "正在观察测试网链路",
        observePassed: "测试网观察通过",
        observeFailed: "测试网观察未通过",
        dryRunUnavailable: "测试网 dry-run 暂不可用",
        launchGate: "上线门禁",
        testnetLaunch: "测试网路径",
        liveLaunch: "实盘路径",
        testnetPhase: "测试网阶段",
        livePhase: "实盘阶段",
        observationEvidence: "观察证据",
        nonOrderShort: "非下单",
        boundedOrderShort: "有界下单",
        missingShort: "缺失",
        passedShort: "通过",
        failedShort: "失败",
        runNonOrderTestnetObserve: "运行非下单测试网观察",
        runBoundedTestnetObserve: "运行有界下单测试网观察",
        promoteLiveAfterObservations: "两类测试网观察通过后晋升实盘配置",
        promoteTestnetProfile: "将通过验证的模拟盘配置晋升到测试网",
        present: "已配置",
        missing: "缺失",
        enabled: "已启用",
        disabled: "未启用",
        noNextSteps: "暂无后续步骤",
        noDryRunYet: "未运行",
        automationReady: "自动交易就绪",
        profile: "配置",
        profileSource: "配置来源",
        maWindows: "均线窗口",
        protectiveExits: "保护退出",
        profileEvidence: "验证证据",
        promotedProfile: "已晋升",
        configDefaults: "配置默认值",
        notPromoted: "未晋升",
        evidenceRuns: "条证据",
        stopLossShort: "止损",
        takeProfitShort: "止盈",
        trailingStopShort: "跟踪",
        off: "关闭",
        ready: "就绪",
        notReady: "未就绪",
        checkPass: "通过",
        checkFail: "失败",
        loading: "加载中",
        runTrades: "运行成交",
        time: "时间",
        exec: "成交价",
        pnl: "盈亏",
        operatorNotes: "操作备注",
        runBacktest: "运行回测",
        simulate: "模拟",
        pauseBot: "暂停机器人",
        resumeBot: "恢复机器人",
        exportJson: "导出 JSON",
        notes: "本地控制台会读取 SQLite 里的 K 线、回测、成交、订单、填单、信号和风险快照；暂停按钮只会切换自动交易停机开关，不会直接下单。",
        active: "运行中",
        cooling: "冷却中",
        pnlShort: "盈亏",
        ddShort: "回撤",
        stressShort: "压力",
        walkForwardShort: "步进",
        local: "本地",
        noMarketData: "无市场数据",
        runs: "结果",
        activeKeys: "个可用",
        synced: "已同步",
        candles: "根K线",
        localCoverage: "本地覆盖",
        localCandles: "本地K线",
        close: "收盘",
        range: "区间",
        bars: "根",
        vol: "量",
        noCandleMarkets: "还没有 K 线市场数据。可以先运行 download-history，或用 sample 数据跑一次回测。",
        noBacktestRuns: "还没有持久化的回测结果。",
        noRunsRecorded: "数据库里还没有回测运行记录。",
        noExecutions: "SQLite 里还没有订单、填单或策略信号。",
        noEvents: "还没有运行事件。",
        noTradesForRun: "这个运行没有成交记录。",
        noCandleData: "没有 K 线数据。可尝试：kxian-bot backtest --input-file sample_data/binance_btcusdt_1m.json",
        runLocally: "本地运行：kxian-bot backtest --input-file sample_data/binance_btcusdt_1m.json",
        simulateOnly: "模拟按钮目前只是界面操作；这个控制台保持只读。",
        pauseRequested: "自动交易已暂停",
        resumeRequested: "自动交易已恢复",
        langChanged: "已切换为中文",
        syncing: "同步中",
        buy: "买入",
        sell: "卖出",
        order: "订单",
        fill: "成交",
        signal: "信号",
        backtest: "回测",
        loop: "循环",
        risk: "风险",
        info: "信息",
        warn: "警告",
        error: "错误",
        execLevel: "执行",
        sqlite_schema: "数据库结构",
        trading_rules: "交易规则",
        automation_control: "自动交易控制",
        market_data: "行情数据",
        position_state: "持仓状态",
        strategy_gate: "策略门禁",
        stress_gate: "压力门禁",
        walk_forward_gate: "分段验证门禁",
        open_orders: "未结订单",
        loop_lock: "运行锁",
        execution_mode: "执行模式",
        required_tables_are_present: "必要的数据表已就绪",
        default_trading_rules_will_be_used: "将使用默认交易规则",
        automation_control_is_active: "自动交易控制正常",
        automation_is_paused: "自动交易已暂停",
        trading_rules_are_ready: "交易规则已就绪",
        trading_rules_are_invalid: "交易规则无效",
        missing_required_tables: "缺少必要的数据表",
        exchange_market_data_will_be_fetched_at_runtime: "运行时会从交易所拉取行情",
        enough_local_candles_for_strategy_window: "本地 K 线足够覆盖策略窗口",
        not_enough_local_candles: "本地 K 线数量不足",
        strategy_gate_is_not_required_for_this_mode: "当前模式不需要策略门禁",
        strategy_gate_disabled_for_controlled_smoke_test: "受控冒烟测试已关闭策略门禁",
        missing_matching_backtest_run: "缺少匹配的回测结果",
        matching_backtest_passes_gate: "匹配回测已通过门禁",
        matching_backtest_fails_gate: "匹配回测未通过门禁",
        stress_gate_is_not_required_for_this_mode: "当前模式不需要压力门禁",
        stress_gate_disabled_for_controlled_smoke_test: "受控冒烟测试已关闭压力门禁",
        missing_matching_stress_backtest_run: "缺少匹配的压力回测结果",
        matching_stress_backtest_passes_gate: "匹配压力回测已通过门禁",
        matching_stress_backtest_fails_gate: "匹配压力回测未通过门禁",
        walk_forward_gate_is_not_required_for_this_mode: "当前模式不需要分段验证门禁",
        walk_forward_gate_disabled_for_controlled_smoke_test: "受控冒烟测试已关闭分段验证门禁",
        missing_matching_walk_forward_run: "缺少匹配的分段验证结果",
        matching_walk_forward_run_passes_gate: "匹配分段验证已通过门禁",
        matching_walk_forward_run_fails_gate: "匹配分段验证未通过门禁",
        missing_exchange_credentials: "缺少交易所测试网密钥",
        preflight_failed: "启动门禁未通过",
        preflight_failed_after_sync: "同步后启动门禁未通过",
        fill_sync_failed: "成交同步失败",
        trade_history_sync_failed: "交易历史同步失败",
        local_fill_replay_completed: "本地成交回放已完成",
        local_position_entry_price_is_missing: "本地持仓入场价缺失",
        missing_local_entry_price: "缺少本地入场价",
        no_open_exchange_orders: "没有未结交易所订单",
        open_exchange_orders_must_be_refreshed_or_resolved: "未结交易所订单需要刷新或处理",
        no_active_strategy_loop: "没有正在运行的策略循环",
        another_strategy_loop_is_active: "已有另一个策略循环正在运行",
        execution_mode_is_ready: "执行模式已就绪",
        execution_mode_is_not_ready_for_automation: "执行模式还未准备好自动化",
        insufficient_trades: "交易次数不足",
        return_too_low: "收益过低",
        drawdown_too_high: "回撤过高",
        profit_factor_too_low: "盈亏比过低",
        stress_pass_rate_too_low: "压力场景通过率过低",
        stress_insufficient_trades: "压力场景交易次数不足",
        stress_return_too_low: "压力场景收益过低",
        stress_drawdown_too_high: "压力场景回撤过高",
        stress_profit_factor_too_low: "压力场景盈亏比过低",
        stress_gate_missing_backtest: "缺少压力回测",
        stress_gate_pass_rate_too_low: "压力门禁通过率过低",
        stress_gate_insufficient_trades: "压力门禁交易次数不足",
        stress_gate_return_too_low: "压力门禁收益过低",
        stress_gate_drawdown_too_high: "压力门禁回撤过高",
        stress_gate_profit_factor_too_low: "压力门禁盈亏比过低",
        walk_forward_insufficient_segments: "分段数量不足",
        walk_forward_pass_rate_too_low: "分段通过率过低",
        walk_forward_insufficient_trades: "分段验证交易次数不足",
        walk_forward_return_too_low: "分段验证收益过低",
        walk_forward_drawdown_too_high: "分段验证回撤过高",
        walk_forward_profit_factor_too_low: "分段验证盈亏比过低",
        walk_forward_gate_missing_run: "缺少分段验证",
        walk_forward_gate_insufficient_segments: "分段验证数量不足",
        walk_forward_gate_pass_rate_too_low: "分段验证通过率过低",
        walk_forward_gate_insufficient_trades: "分段验证交易次数不足",
        walk_forward_gate_return_too_low: "分段验证收益过低",
        walk_forward_gate_drawdown_too_high: "分段验证回撤过高",
        walk_forward_gate_profit_factor_too_low: "分段验证盈亏比过低",
        live_automation_not_enabled: "实盘自动化未启用",
        live_not_allowed: "实盘模式未授权",
        live_dry_run_enabled: "实盘仍处于 dry-run",
        live_autotrade_disabled: "实盘自动交易未启用",
        live_endpoint_points_to_testnet: "实盘端点仍指向测试网",
        live_confirmation_required: "缺少实盘确认口令",
        live_order_notional_exceeds_limit: "实盘单笔金额超过上限",
        testnet_launch_ready: "测试网可启动",
        testnet_launch_blocked: "测试网上线受阻",
        live_launch_ready: "实盘可启动",
        live_launch_blocked: "实盘上线受阻",
        blocked_before_testnet: "测试网前置阻断",
        ready_for_testnet_dry_run: "可跑测试网 dry-run",
        ready_for_bounded_testnet_order_observation: "可跑有界测试网下单观察",
        testnet_observed_ready_for_live_review: "测试网观察完成，待实盘复核",
        blocked_before_live: "实盘前置阻断",
        ready_for_bounded_live_loop: "可跑有界实盘循环",
        readiness_passes: "就绪检查通过",
        readiness_has_blocking_checks: "就绪检查仍有阻断项",
        active_strategy_profile_has_required_evidence: "策略配置证据齐全",
        active_strategy_profile_is_not_promotable: "策略配置暂不可晋升",
        active_strategy_profile_is_missing: "缺少活动策略配置",
        live_strategy_profile_has_not_been_promoted: "实盘策略配置尚未晋升",
        live_strategy_profile_is_promoted_with_testnet_evidence: "实盘配置已有测试网证据",
        live_strategy_profile_is_incomplete: "实盘配置证据不完整",
        testnet_observation_evidence_is_missing: "缺少测试网观察证据",
        testnet_observation_passed: "测试网观察通过",
        testnet_observation_is_not_acceptable: "测试网观察未通过",
        unsupported_launch_target: "不支持的上线目标",
        missing_active_profile: "缺少活动配置",
        missing_passing_sample_validation: "缺少通过的多样本验证",
        missing_testnet_promotion_evidence: "缺少测试网晋升证据",
        missing_live_profile: "缺少实盘配置",
        missing_live_promotion_evidence: "缺少实盘晋升证据",
        missing_testnet_observation_evidence: "缺少测试网观察证据",
        missing_testnet_observation: "缺少测试网观察",
        testnet_observation_not_passed: "测试网观察未通过",
        testnet_observation_scope_mismatch: "测试网观察范围不匹配",
        source_profile_missing_passing_testnet_observation: "来源配置缺少通过的非下单测试网观察",
        source_profile_missing_passing_testnet_order_observation: "来源配置缺少通过的有界下单测试网观察",
        source_profile_missing_testnet_promotion_evidence: "来源配置缺少测试网晋升证据",
        set_sandbox_api_credentials_for_the_selected_exchange: "配置所选交易所的测试网 API Key/Secret",
        run_kxian_bot_readiness: "运行 readiness，确认门禁状态",
        run_kxian_bot_testnet_dry_run: "运行测试网 dry-run",
        run_kxian_bot_testnet_dry_run_then_add_execute_loop_for_one_bounded_sandbox_iteration: "先运行测试网 dry-run，再用一次受限测试网循环验证下单路径",
        testnet_observe_passed: "测试网观察通过",
        testnet_mode_required: "需要使用测试网模式",
        testnet_or_live_mode_required: "需要测试网或实盘模式",
        binance_testnet_endpoint_required: "需要使用 Binance 测试网端点",
        testnet_autotrade_disabled: "测试网自动交易未启用",
        account_sync_failed: "账户余额同步失败",
        no_new_candle: "没有新 K 线",
        no_signal: "没有交易信号",
        no_size: "仓位尺寸为 0",
        automation_paused: "自动交易已暂停",
        bullish_ma_cross: "均线金叉",
        bearish_ma_cross: "均线死叉",
        stop_loss_triggered: "触发止损",
        take_profit_triggered: "触发止盈",
        trailing_stop_triggered: "触发跟踪止损",
        trend_pullback_buy: "趋势回踩买入",
        trend_pullback_sell: "趋势回踩卖出",
        mean_reversion_buy: "均值回归买入",
        mean_reversion_sell: "均值回归卖出",
        rsi_mean_reversion_buy: "RSI 均值回归买入",
        rsi_mean_reversion_sell: "RSI 均值回归卖出",
        momentum_breakout_buy: "动量突破买入",
        momentum_breakout_sell: "动量突破卖出",
        bollinger_mean_reversion_buy: "布林均值回归买入",
        bollinger_mean_reversion_sell: "布林均值回归卖出",
        regime_breakout_buy: "结构突破买入",
        regime_breakout_sell: "结构突破卖出",
        regime_filtered_ma_buy: "结构过滤均线买入",
        regime_filtered_ma_sell: "结构过滤均线卖出",
        trend_filtered_ma_buy: "过滤均线买入",
        trend_filtered_ma_sell: "过滤均线卖出",
        defensive_trend_buy: "防守趋势买入",
        defensive_trend_sell: "防守趋势卖出",
        panic_rebound_buy: "恐慌反弹买入",
        panic_rebound_sell: "恐慌反弹卖出",
        regime_adaptive_long_buy: "自适应做多买入",
        regime_adaptive_long_sell: "自适应做多卖出",
        volatility_breakout_trend_buy: "波动突破趋势买入",
        volatility_breakout_trend_sell: "波动突破趋势卖出",
        downtrend_breakdown_short_entry: "下行跌破合成做空开仓",
        downtrend_breakdown_short_exit: "下行跌破合成做空平仓",
        short_stop_loss_triggered: "合成做空触发止损",
        short_take_profit_triggered: "合成做空触发止盈",
        short_trailing_stop_triggered: "合成做空触发跟踪止损",
        end_of_backtest_short_cover: "回测结束合成做空平仓",
        research_only_strategy_not_promotable: "研究策略不能晋升为实盘配置",
        cooldown_active: "冷却中",
        position_already_open: "已有持仓，跳过买入",
        max_daily_trades_reached: "已达到每日交易次数上限",
        max_daily_loss_reached: "已达到每日亏损上限",
        below_min_order_usdt: "低于最小下单金额",
        insufficient_usdt: "USDT 余额不足",
        max_position_exceeded: "超过最大持仓限制",
        insufficient_asset: "资产余额不足",
        invalid_order: "订单无效",
        exchange_rule_zero_after_rounding: "按交易所规则取整后数量或价格为 0",
        exchange_rule_min_quantity: "低于交易所最小数量",
        exchange_rule_min_notional: "低于交易所最小名义金额",
        invalid_price_step: "价格步长无效",
        invalid_quantity_step: "数量步长无效",
        invalid_min_quantity: "最小数量无效",
        invalid_min_notional: "最小名义金额无效",
        loop_lock_active: "运行锁已被占用",
        marketdataerror: "行情数据错误",
        exchange_http_error: "交易所 HTTP 请求失败",
        exchange_http_401: "交易所认证失败，请检查 API Key",
        exchange_http_403: "交易所拒绝访问，请检查权限或 IP 白名单",
        exchange_rate_limited: "交易所限流，请稍后重试",
        exchange_server_error: "交易所服务异常",
        exchange_timeout: "交易所请求超时",
        filled: "已成交",
        idle: "空闲",
        rejected: "已拒绝",
        eventSignal: "{symbol} {side}，原因：{reason}",
        eventFill: "{symbol} {side} 数量 {quantity} @ {price}",
        eventRisk: "风险快照：{day}，今日交易 {trades} 次",
        eventBacktest: "{market} 收益 {returnPct}，交易 {trades} 次",
        eventLoop: "{market} 循环 {loop} 第 {iteration} 次：{status}",
        eventDetail: " - {detail}"
      },
      en: {
        appTitle: "Quant Ops Console",
        langSwitch: "Language switch",
        language: "Language",
        chinese: "中文",
        english: "English",
        primaryNav: "Primary",
        env: "Environment",
        envProdPaper: "PROD / PAPER",
        envStaging: "STAGING",
        envLocalDev: "LOCAL DEV",
        commandInput: "Command input",
        switchLanguage: "Switch language",
        switchToChinese: "Switch to Chinese",
        switchToEnglish: "Switch to English",
        portfolioHealth: "Portfolio health",
        timeRange: "Time range",
        navDashboard: "Dashboard",
        navLiveMonitor: "Live monitor",
        navStrategyFactory: "Strategy factory",
        navSecurityApi: "Security and API",
        navBacktests: "Backtests",
        navAudit: "Audit",
        reload: "Reload",
        reloadTitle: "Reload data",
        settings: "Settings",
        totalEquity: "Total Equity",
        runPnl: "24h / Run PnL",
        grossExposure: "Gross Exposure",
        riskBudgetUsed: "Risk Budget Used",
        marginHealth: "Margin Health",
        openAlerts: "Open Alerts",
        marketWatch: "Market Watch",
        chartTitleEmpty: "Price Tape",
        live: "LIVE",
        strategyRuns: "Strategy Runs",
        backtestLeaderboard: "Backtest Leaderboard",
        sortReturn: "SORT RETURN",
        run: "Run",
        pair: "Pair",
        return: "Return",
        dd: "DD",
        pf: "PF",
        trades: "Trades",
        executionStream: "Execution Stream",
        readOnly: "READ ONLY",
        source: "Source",
        symbol: "Symbol",
        side: "Side",
        price: "Price",
        status: "Status",
        operationalEvents: "Operational Event Stream",
        events: "EVENTS",
        riskInspector: "Risk Inspector",
        safe: "SAFE",
        selectedRun: "Selected Run",
        runId: "Run ID",
        strategy: "Strategy",
        riskConstraints: "Risk Constraints",
        maxDrawdown: "Max Drawdown",
        profitFactor: "Profit Factor",
        winRate: "Win Rate",
        marketDiagnostics: "Market Diagnostics",
        marketRegime: "Market Regime",
        costPressure: "Cost Pressure",
        buyHold: "Buy Hold",
        benchmarkDrawdown: "Benchmark DD",
        trendEfficiency: "Trend Efficiency",
        roundTripFriction: "Round-Trip Friction",
        segmentBalance: "Segment Balance",
        regime_uptrend: "UPTREND",
        regime_downtrend: "DOWNTREND",
        regime_choppy: "CHOPPY",
        regime_mixed: "MIXED",
        cost_low: "LOW",
        cost_medium: "MEDIUM",
        cost_high: "HIGH",
        cost_unknown: "UNKNOWN",
        securityPosture: "Security Posture",
        mode: "Mode",
        liveOrders: "Live Orders",
        automationControl: "Automation Control",
        blocked: "BLOCKED",
        apiKeys: "API Keys",
        auditEvents: "Audit Events",
        startupGate: "Startup Gate",
        testnetGate: "Testnet Checks",
        readiness: "Readiness",
        credentialState: "Testnet Keys",
        automationFlag: "Automation Flag",
        lastDryRun: "Latest Dry-run",
        runTestnetDryRun: "Run Testnet Dry-run",
        runTestnetObserve: "Observe 3 Cycles",
        exchangeHealth: "Exchange Health",
        publicMarketData: "Public Market Data",
        tradingEndpoint: "Trading Endpoint",
        dryRunStarted: "Running testnet dry-run",
        dryRunPassed: "Testnet dry-run passed",
        dryRunFailed: "Testnet dry-run failed",
        observeStarted: "Observing testnet flow",
        observePassed: "Testnet observation passed",
        observeFailed: "Testnet observation failed",
        dryRunUnavailable: "Testnet dry-run unavailable",
        launchGate: "Launch Gate",
        testnetLaunch: "Testnet Path",
        liveLaunch: "Live Path",
        testnetPhase: "Testnet Phase",
        livePhase: "Live Phase",
        observationEvidence: "Observation Evidence",
        nonOrderShort: "Non-order",
        boundedOrderShort: "Bounded order",
        missingShort: "Missing",
        passedShort: "Passed",
        failedShort: "Failed",
        runNonOrderTestnetObserve: "Run non-ordering testnet observation",
        runBoundedTestnetObserve: "Run bounded-order testnet observation",
        promoteLiveAfterObservations: "Promote the live profile after both testnet observations pass",
        promoteTestnetProfile: "Promote the validated paper profile to testnet",
        present: "Present",
        missing: "Missing",
        enabled: "Enabled",
        disabled: "Disabled",
        noNextSteps: "No next steps",
        noDryRunYet: "Not run",
        automationReady: "Automation Ready",
        profile: "Profile",
        profileSource: "Profile Source",
        maWindows: "MA Windows",
        protectiveExits: "Protective Exits",
        profileEvidence: "Evidence",
        promotedProfile: "PROMOTED",
        configDefaults: "CONFIG DEFAULT",
        notPromoted: "NOT PROMOTED",
        evidenceRuns: "evidence runs",
        stopLossShort: "SL",
        takeProfitShort: "TP",
        trailingStopShort: "TR",
        off: "OFF",
        ready: "READY",
        notReady: "NOT READY",
        checkPass: "PASS",
        checkFail: "FAIL",
        loading: "LOADING",
        runTrades: "Run Trades",
        time: "Time",
        exec: "Exec",
        pnl: "PnL",
        operatorNotes: "Operator Notes",
        runBacktest: "Run Backtest",
        simulate: "Simulate",
        pauseBot: "Pause Bot",
        resumeBot: "Resume Bot",
        exportJson: "Export JSON",
        notes: "Local dashboard reads SQLite candles, backtests, trades, orders, fills, signals, and risk snapshots. The pause button only toggles the automation kill switch; it does not place orders.",
        active: "ACTIVE",
        cooling: "COOLING",
        pnlShort: "PnL",
        ddShort: "DD",
        stressShort: "Stress",
        walkForwardShort: "WF",
        local: "LOCAL",
        noMarketData: "NO MARKET DATA",
        runs: "RUNS",
        activeKeys: " active",
        synced: "SYNCED",
        candles: "candles",
        localCoverage: "local coverage",
        localCandles: "local candles",
        close: "close",
        range: "range",
        bars: "bars",
        vol: "vol",
        noCandleMarkets: "No candle markets yet. Run download-history or a backtest with sample data.",
        noBacktestRuns: "No persisted backtest runs yet.",
        noRunsRecorded: "No backtest runs recorded.",
        noExecutions: "No orders, fills, or signals in SQLite yet.",
        noEvents: "No operational events yet.",
        noTradesForRun: "No trades for this run.",
        noCandleData: "No candle data available. Try: kxian-bot backtest --input-file sample_data/binance_btcusdt_1m.json",
        runLocally: "Run locally: kxian-bot backtest --input-file sample_data/binance_btcusdt_1m.json",
        simulateOnly: "Simulation action is UI-only in this read-only dashboard.",
        pauseRequested: "Automation paused",
        resumeRequested: "Automation resumed",
        langChanged: "Switched to English",
        syncing: "SYNCING",
        buy: "BUY",
        sell: "SELL",
        order: "ORDER",
        fill: "FILL",
        signal: "SIGNAL",
        backtest: "BACKTEST",
        loop: "LOOP",
        risk: "RISK",
        info: "INFO",
        warn: "WARN",
        error: "ERROR",
        execLevel: "EXEC",
        sqlite_schema: "SQLite Schema",
        trading_rules: "Trading Rules",
        automation_control: "Automation Control",
        market_data: "Market Data",
        position_state: "Position State",
        strategy_gate: "Strategy Gate",
        stress_gate: "Stress Gate",
        walk_forward_gate: "Walk-forward Gate",
        open_orders: "Open Orders",
        loop_lock: "Loop Lock",
        execution_mode: "Execution Mode",
        required_tables_are_present: "Required tables are present",
        default_trading_rules_will_be_used: "Default trading rules will be used",
        automation_control_is_active: "Automation control is active",
        automation_is_paused: "Automation is paused",
        trading_rules_are_ready: "Trading rules are ready",
        trading_rules_are_invalid: "Trading rules are invalid",
        missing_required_tables: "Missing required tables",
        exchange_market_data_will_be_fetched_at_runtime: "Exchange market data will be fetched at runtime",
        enough_local_candles_for_strategy_window: "Enough local candles for the strategy window",
        not_enough_local_candles: "Not enough local candles",
        strategy_gate_is_not_required_for_this_mode: "Strategy gate is not required for this mode",
        strategy_gate_disabled_for_controlled_smoke_test: "Strategy gate disabled for controlled smoke test",
        missing_matching_backtest_run: "Missing matching backtest run",
        matching_backtest_passes_gate: "Matching backtest passes the gate",
        matching_backtest_fails_gate: "Matching backtest fails the gate",
        stress_gate_is_not_required_for_this_mode: "Stress gate is not required for this mode",
        stress_gate_disabled_for_controlled_smoke_test: "Stress gate disabled for controlled smoke test",
        missing_matching_stress_backtest_run: "Missing matching stress backtest run",
        matching_stress_backtest_passes_gate: "Matching stress backtest passes the gate",
        matching_stress_backtest_fails_gate: "Matching stress backtest fails the gate",
        walk_forward_gate_is_not_required_for_this_mode: "Walk-forward gate is not required for this mode",
        walk_forward_gate_disabled_for_controlled_smoke_test: "Walk-forward gate disabled for controlled smoke test",
        missing_matching_walk_forward_run: "Missing matching walk-forward run",
        matching_walk_forward_run_passes_gate: "Matching walk-forward run passes the gate",
        matching_walk_forward_run_fails_gate: "Matching walk-forward run fails the gate",
        missing_exchange_credentials: "Missing exchange sandbox credentials",
        preflight_failed: "Startup gate failed",
        preflight_failed_after_sync: "Startup gate failed after sync",
        fill_sync_failed: "Fill sync failed",
        trade_history_sync_failed: "Trade history sync failed",
        local_fill_replay_completed: "Local fill replay completed",
        local_position_entry_price_is_missing: "Local position entry price is missing",
        missing_local_entry_price: "Missing local entry price",
        no_open_exchange_orders: "No open exchange orders",
        open_exchange_orders_must_be_refreshed_or_resolved: "Open exchange orders must be refreshed or resolved",
        no_active_strategy_loop: "No active strategy loop",
        another_strategy_loop_is_active: "Another strategy loop is active",
        execution_mode_is_ready: "Execution mode is ready",
        execution_mode_is_not_ready_for_automation: "Execution mode is not ready for automation",
        insufficient_trades: "Insufficient trades",
        return_too_low: "Return too low",
        drawdown_too_high: "Drawdown too high",
        profit_factor_too_low: "Profit factor too low",
        stress_pass_rate_too_low: "Stress pass rate too low",
        stress_insufficient_trades: "Insufficient stress trades",
        stress_return_too_low: "Stress return too low",
        stress_drawdown_too_high: "Stress drawdown too high",
        stress_profit_factor_too_low: "Stress profit factor too low",
        stress_gate_missing_backtest: "Missing stress backtest",
        stress_gate_pass_rate_too_low: "Stress gate pass rate too low",
        stress_gate_insufficient_trades: "Stress gate has insufficient trades",
        stress_gate_return_too_low: "Stress gate return too low",
        stress_gate_drawdown_too_high: "Stress gate drawdown too high",
        stress_gate_profit_factor_too_low: "Stress gate profit factor too low",
        walk_forward_insufficient_segments: "Insufficient walk-forward segments",
        walk_forward_pass_rate_too_low: "Walk-forward pass rate too low",
        walk_forward_insufficient_trades: "Insufficient walk-forward trades",
        walk_forward_return_too_low: "Walk-forward return too low",
        walk_forward_drawdown_too_high: "Walk-forward drawdown too high",
        walk_forward_profit_factor_too_low: "Walk-forward profit factor too low",
        walk_forward_gate_missing_run: "Missing walk-forward run",
        walk_forward_gate_insufficient_segments: "Walk-forward gate has insufficient segments",
        walk_forward_gate_pass_rate_too_low: "Walk-forward gate pass rate too low",
        walk_forward_gate_insufficient_trades: "Walk-forward gate has insufficient trades",
        walk_forward_gate_return_too_low: "Walk-forward gate return too low",
        walk_forward_gate_drawdown_too_high: "Walk-forward gate drawdown too high",
        walk_forward_gate_profit_factor_too_low: "Walk-forward gate profit factor too low",
        live_automation_not_enabled: "Live automation is not enabled",
        live_not_allowed: "Live mode is not authorized",
        live_dry_run_enabled: "Live dry-run is enabled",
        live_autotrade_disabled: "Live auto-trading is disabled",
        live_endpoint_points_to_testnet: "Live endpoint still points to testnet",
        live_confirmation_required: "Live confirmation is required",
        live_order_notional_exceeds_limit: "Live order notional exceeds limit",
        testnet_launch_ready: "Testnet ready",
        testnet_launch_blocked: "Testnet launch blocked",
        live_launch_ready: "Live ready",
        live_launch_blocked: "Live launch blocked",
        blocked_before_testnet: "Blocked before testnet",
        ready_for_testnet_dry_run: "Ready for testnet dry-run",
        ready_for_bounded_testnet_order_observation: "Ready for bounded testnet order observation",
        testnet_observed_ready_for_live_review: "Testnet observed, ready for live review",
        blocked_before_live: "Blocked before live",
        ready_for_bounded_live_loop: "Ready for bounded live loop",
        readiness_passes: "Readiness passes",
        readiness_has_blocking_checks: "Readiness has blocking checks",
        active_strategy_profile_has_required_evidence: "Active strategy profile has required evidence",
        active_strategy_profile_is_not_promotable: "Active strategy profile is not promotable",
        active_strategy_profile_is_missing: "Active strategy profile is missing",
        live_strategy_profile_has_not_been_promoted: "Live strategy profile has not been promoted",
        live_strategy_profile_is_promoted_with_testnet_evidence: "Live strategy profile is promoted with testnet evidence",
        live_strategy_profile_is_incomplete: "Live strategy profile is incomplete",
        testnet_observation_evidence_is_missing: "Testnet observation evidence is missing",
        testnet_observation_passed: "Testnet observation passed",
        testnet_observation_is_not_acceptable: "Testnet observation is not acceptable",
        unsupported_launch_target: "Unsupported launch target",
        missing_active_profile: "Missing active profile",
        missing_passing_sample_validation: "Missing passing multi-sample validation",
        missing_testnet_promotion_evidence: "Missing testnet promotion evidence",
        missing_live_profile: "Missing live profile",
        missing_live_promotion_evidence: "Missing live promotion evidence",
        missing_testnet_observation_evidence: "Missing testnet observation evidence",
        missing_testnet_observation: "Missing testnet observation",
        testnet_observation_not_passed: "Testnet observation did not pass",
        testnet_observation_scope_mismatch: "Testnet observation scope mismatch",
        source_profile_missing_passing_testnet_observation: "Source profile is missing a passing non-ordering testnet observation",
        source_profile_missing_passing_testnet_order_observation: "Source profile is missing a passing bounded-order testnet observation",
        source_profile_missing_testnet_promotion_evidence: "Source profile is missing testnet promotion evidence",
        set_sandbox_api_credentials_for_the_selected_exchange: "Set testnet API key/secret for the selected exchange",
        run_kxian_bot_readiness: "Run readiness and confirm the gate state",
        run_kxian_bot_testnet_dry_run: "Run the testnet dry-run",
        run_kxian_bot_testnet_dry_run_then_add_execute_loop_for_one_bounded_sandbox_iteration: "Run testnet dry-run, then add one bounded sandbox loop iteration",
        testnet_observe_passed: "Testnet observation passed",
        testnet_mode_required: "Testnet mode required",
        testnet_or_live_mode_required: "Testnet or live mode required",
        binance_testnet_endpoint_required: "Binance testnet endpoint required",
        testnet_autotrade_disabled: "Testnet auto-trading is disabled",
        account_sync_failed: "Account balance sync failed",
        no_new_candle: "No new candle",
        no_signal: "No signal",
        no_size: "No size",
        automation_paused: "Automation is paused",
        bullish_ma_cross: "Bullish MA cross",
        bearish_ma_cross: "Bearish MA cross",
        stop_loss_triggered: "Stop loss triggered",
        take_profit_triggered: "Take profit triggered",
        trailing_stop_triggered: "Trailing stop triggered",
        trend_pullback_buy: "Trend pullback buy",
        trend_pullback_sell: "Trend pullback sell",
        mean_reversion_buy: "Mean reversion buy",
        mean_reversion_sell: "Mean reversion sell",
        rsi_mean_reversion_buy: "RSI mean reversion buy",
        rsi_mean_reversion_sell: "RSI mean reversion sell",
        momentum_breakout_buy: "Momentum breakout buy",
        momentum_breakout_sell: "Momentum breakout sell",
        bollinger_mean_reversion_buy: "Bollinger mean reversion buy",
        bollinger_mean_reversion_sell: "Bollinger mean reversion sell",
        regime_breakout_buy: "Regime breakout buy",
        regime_breakout_sell: "Regime breakout sell",
        regime_filtered_ma_buy: "Regime-filtered MA buy",
        regime_filtered_ma_sell: "Regime-filtered MA sell",
        trend_filtered_ma_buy: "Trend-filtered MA buy",
        trend_filtered_ma_sell: "Trend-filtered MA sell",
        defensive_trend_buy: "Defensive trend buy",
        defensive_trend_sell: "Defensive trend sell",
        panic_rebound_buy: "Panic rebound buy",
        panic_rebound_sell: "Panic rebound sell",
        regime_adaptive_long_buy: "Regime-adaptive long buy",
        regime_adaptive_long_sell: "Regime-adaptive long sell",
        volatility_breakout_trend_buy: "Volatility breakout trend buy",
        volatility_breakout_trend_sell: "Volatility breakout trend sell",
        downtrend_breakdown_short_entry: "Downtrend breakdown synthetic short entry",
        downtrend_breakdown_short_exit: "Downtrend breakdown synthetic short cover",
        short_stop_loss_triggered: "Synthetic short stop loss triggered",
        short_take_profit_triggered: "Synthetic short take profit triggered",
        short_trailing_stop_triggered: "Synthetic short trailing stop triggered",
        end_of_backtest_short_cover: "End-of-backtest synthetic short cover",
        research_only_strategy_not_promotable: "Research-only strategy cannot be promoted",
        cooldown_active: "Cooldown active",
        position_already_open: "Position already open",
        max_daily_trades_reached: "Max daily trades reached",
        max_daily_loss_reached: "Max daily loss reached",
        below_min_order_usdt: "Below minimum order USDT",
        insufficient_usdt: "Insufficient USDT",
        max_position_exceeded: "Max position exceeded",
        insufficient_asset: "Insufficient asset",
        invalid_order: "Invalid order",
        exchange_rule_zero_after_rounding: "Zero quantity or price after exchange-rule rounding",
        exchange_rule_min_quantity: "Below exchange minimum quantity",
        exchange_rule_min_notional: "Below exchange minimum notional",
        invalid_price_step: "Invalid price step",
        invalid_quantity_step: "Invalid quantity step",
        invalid_min_quantity: "Invalid minimum quantity",
        invalid_min_notional: "Invalid minimum notional",
        loop_lock_active: "Loop lock active",
        marketdataerror: "Market data error",
        exchange_http_error: "Exchange HTTP request failed",
        exchange_http_401: "Exchange authentication failed; check the API key",
        exchange_http_403: "Exchange access denied; check permissions or IP allowlist",
        exchange_rate_limited: "Exchange rate limited; retry later",
        exchange_server_error: "Exchange server error",
        exchange_timeout: "Exchange request timed out",
        filled: "FILLED",
        idle: "IDLE",
        rejected: "REJECTED",
        eventSignal: "{symbol} {side} because {reason}",
        eventFill: "{symbol} {side} qty {quantity} @ {price}",
        eventRisk: "Risk snapshot day {day} trades {trades}",
        eventBacktest: "{market} return {returnPct} trades {trades}",
        eventLoop: "{market} loop {loop} #{iteration}: {status}",
        eventDetail: " - {detail}"
      }
    };

    const LANGUAGE_STORAGE_KEY = "kxian-dashboard-lang-v2";

    function persistLanguage(lang) {
      try {
        localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
      } catch (error) {
        // Local storage can be unavailable in hardened browser modes.
      }
    }

    function storedLanguage() {
      try {
        return localStorage.getItem(LANGUAGE_STORAGE_KEY);
      } catch (error) {
        return null;
      }
    }

    function preferredLanguage() {
      const urlLang = new URLSearchParams(window.location.search).get("lang");
      if (urlLang === "en" || urlLang === "zh") {
        persistLanguage(urlLang);
        return urlLang;
      }
      const storedLang = storedLanguage();
      if (storedLang === "en" || storedLang === "zh") return storedLang;
      return "zh";
    }

    const state = {
      ops: null,
      overview: null,
      preflight: null,
      readiness: null,
      exchangeHealth: null,
      dryRun: null,
      observation: null,
      launchTestnet: null,
      launchLive: null,
      selectedMarket: null,
      selectedRun: null,
      candles: [],
      lang: preferredLanguage()
    };

    const $ = (id) => document.getElementById(id);
    const escapeHtml = (value) => String(value ?? "-").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[char]));
    const t = (key) => (I18N[state.lang] && I18N[state.lang][key]) || I18N.en[key] || key;
    const normalizeKey = (value) => String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    const translateValue = (value) => {
      const key = normalizeKey(value);
      return key && I18N[state.lang] && I18N[state.lang][key] ? t(key) : value || "-";
    };
    const sentence = (key, values) => {
      let output = t(key);
      for (const [name, value] of Object.entries(values || {})) {
        output = output.replaceAll(`{${name}}`, String(value));
      }
      return output;
    };

    function sourceLabel(value) {
      const key = String(value || "").toLowerCase();
      if (key === "order") return t("order");
      if (key === "fill") return t("fill");
      if (key === "signal") return t("signal");
      if (key === "backtest") return t("backtest");
      if (key === "loop") return t("loop");
      if (key === "risk") return t("risk");
      return value || "-";
    }

    function sideLabel(value) {
      const key = String(value || "").toLowerCase();
      if (key === "buy") return t("buy");
      if (key === "sell") return t("sell");
      return value || "-";
    }

    function levelLabel(value) {
      const key = String(value || "").toLowerCase();
      if (key === "info") return t("info");
      if (key === "warn") return t("warn");
      if (key === "error") return t("error");
      if (key === "exec") return t("execLevel");
      return value || "-";
    }

    function statusLabel(value) {
      const key = String(value || "").toLowerCase();
      if (key === "active") return t("active");
      if (key === "cooling") return t("cooling");
      return translateValue(value);
    }

    function enumLabel(prefix, value) {
      const key = `${prefix}_${String(value || "unknown").toLowerCase()}`;
      return (I18N[state.lang] && I18N[state.lang][key]) || value || "-";
    }

    function checkLabel(value) {
      return translateValue(value);
    }

    function messageLabel(value) {
      return translateValue(value);
    }

    function checkMessage(check) {
      const base = messageLabel(check.message);
      if (check.name !== "market_data") return base;
      const details = check.details || {};
      const candleCount = details.local_coverage_candles ?? details.local_candles ?? details.candles;
      const days = Number(details.local_coverage_days);
      const parts = [];
      if (Number.isFinite(Number(candleCount))) {
        parts.push(`${t("localCandles")} ${num(candleCount, 0)}`);
      }
      if (Number(details.local_outlier_candles) > 0) {
        parts.push(`outliers ${num(details.local_outlier_candles, 0)}`);
      }
      if (Number.isFinite(days) && days > 0) {
        parts.push(`${t("localCoverage")} ${num(days, 1)}d`);
      }
      if (details.local_first_open_time && details.local_last_open_time) {
        parts.push(`${time(details.local_first_open_time)}-${time(details.local_last_open_time)}`);
      }
      return parts.length ? `${base} · ${parts.join(" / ")}` : base;
    }

    function automationPaused() {
      return Boolean(state.preflight?.checks?.find((check) => check.name === "automation_control")?.details?.paused);
    }

    function updateAutomationControl() {
      const paused = automationPaused();
      const controlEl = $("automationControl");
      const button = $("pauseButton");
      if (controlEl) {
        controlEl.className = paused ? "bad" : "good";
        controlEl.textContent = paused ? t("automation_is_paused") : t("automation_control_is_active");
      }
      if (button) {
        button.dataset.action = paused ? "resume" : "pause";
        button.textContent = paused ? t("resumeBot") : t("pauseBot");
      }
    }

    function eventMessage(event) {
      const source = String(event.source || "").toLowerCase();
      const payload = event.payload || {};
      if (source === "signal") {
        return sentence("eventSignal", {
          symbol: payload.symbol || event.symbol || "-",
          side: sideLabel(payload.side),
          reason: messageLabel(payload.reason)
        });
      }
      if (source === "fill") {
        return sentence("eventFill", {
          symbol: payload.symbol || "-",
          side: sideLabel(payload.side),
          quantity: payload.quantity ?? "-",
          price: payload.price ?? "-"
        });
      }
      if (source === "risk") {
        return sentence("eventRisk", {
          day: payload.day_key || "-",
          trades: payload.trades_today ?? 0
        });
      }
      if (source === "backtest") {
        return sentence("eventBacktest", {
          market: `${payload.symbol || "-"}${payload.interval ? `/${payload.interval}` : ""}`,
          returnPct: pct(payload.return_pct || 0, 3),
          trades: payload.trade_count ?? 0
        });
      }
      if (source === "loop") {
        const status = statusLabel(payload.status || event.status || "");
        const detail = messageLabel(payload.reason || payload.message || "");
        return sentence("eventLoop", {
          market: `${payload.exchange || ""} ${payload.symbol || ""}${payload.interval ? `/${payload.interval}` : ""}`.trim() || "-",
          loop: String(payload.loop_id || "").slice(0, 8) || "-",
          iteration: payload.iteration ?? "-",
          status
        }) + (detail && detail !== "-" ? sentence("eventDetail", { detail }) : "");
      }
      return event.message || "-";
    }

    function applyLanguage() {
      document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
      document.title = t("appTitle");
      document.querySelectorAll("[data-i18n]").forEach((node) => {
        node.textContent = t(node.dataset.i18n);
      });
      document.querySelectorAll("[data-i18n-attr]").forEach((node) => {
        for (const pair of node.dataset.i18nAttr.split(";")) {
          const [attr, key] = pair.split(":");
          if (attr && key) node.setAttribute(attr, t(key));
        }
      });
      document.querySelectorAll("[data-lang-option]").forEach((node) => {
        const isActive = node.dataset.langOption === state.lang;
        node.classList.toggle("active", isActive);
        node.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
      $("notes").value = t("notes");
      if (!state.ops) $("syncStatus").textContent = t("syncing");
      if (state.ops) renderOps();
      renderPreflight();
      renderReadiness();
      renderExchangeHealth();
      renderLaunchChecklist();
      updateAutomationControl();
      updateChartTitle();
      if (state.candles) updateCandleLabels();
      drawChart(state.candles);
    }

    async function fetchJson(url) {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Request failed: ${url}`);
      return response.json();
    }

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(`Request failed: ${url}`);
      return response.json();
    }

    function money(value, digits = 2) {
      const num = Number(value);
      if (!Number.isFinite(num)) return "$0.00";
      return `${num < 0 ? "-" : ""}$${Math.abs(num).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
    }

    function num(value, digits = 2) {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return "-";
      return parsed.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }

    function pct(value, digits = 2) {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) return "0.00%";
      return `${parsed >= 0 ? "+" : ""}${parsed.toFixed(digits)}%`;
    }

    function time(ms) {
      const parsed = Number(ms);
      if (!parsed) return "-";
      const date = new Date(parsed);
      return date.toISOString().slice(5, 16).replace("T", " ");
    }

    function clsFor(value) {
      return Number(value) >= 0 ? "good" : "bad";
    }

    async function boot() {
      const [overview, ops, preflight, readiness, exchangeHealth, launchTestnet, launchLive] = await Promise.all([
        fetchJson("/api/overview"),
        fetchJson("/api/ops"),
        fetchJson("/api/preflight"),
        fetchJson("/api/readiness"),
        fetchJson("/api/exchange-health?mode=testnet&timeout=2"),
        fetchJson("/api/launch-checklist?target=testnet"),
        fetchJson("/api/launch-checklist?target=live")
      ]);
      state.overview = overview;
      state.ops = ops;
      state.preflight = preflight;
      state.readiness = readiness;
      state.exchangeHealth = exchangeHealth;
      state.launchTestnet = launchTestnet;
      state.launchLive = launchLive;
      state.selectedMarket = (ops.markets && ops.markets[0]) || null;
      state.selectedRun = (ops.runs && ops.runs[0]) || null;
      renderOps();
      renderPreflight();
      renderReadiness();
      renderExchangeHealth();
      renderLaunchChecklist();
      updateAutomationControl();
      await loadCandles();
      if (state.selectedRun) await loadTrades(state.selectedRun.run_id);
      $("syncStatus").textContent = `${t("synced")} ${new Date().toLocaleTimeString()}`;
    }

    function renderOps() {
      const { health, markets, strategies, runs, orders, fills, signals, events, security, market_diagnostics } = state.ops;
      $("totalEquity").textContent = money(health.total_equity);
      $("pnlValue").textContent = `${money(health.pnl)} ${pct(health.return_pct)}`;
      $("pnlValue").className = `value ${clsFor(health.pnl)}`;
      $("grossExposure").textContent = money(health.gross_exposure);
      $("riskBudget").textContent = `${num(health.risk_budget_used, 1)}%`;
      $("marginHealth").textContent = `${num(health.margin_health, 1)}%`;
      $("openAlerts").textContent = String(health.open_alerts);
      $("runCountChip").textContent = `${runs.length} ${t("runs")}`;
      $("exchangeStatus").textContent = markets.length ? `${markets[0].exchange.toUpperCase()} ${t("local")}` : t("noMarketData");
      $("apiKeys").textContent = `${security.api_keys_active}${t("activeKeys")}`;
      $("auditEvents").textContent = String(security.audit_events);

      renderMarkets(markets || []);
      renderStrategies(strategies || []);
      renderRuns(runs || []);
      renderExecutions(orders || [], fills || [], signals || []);
      renderEvents(events || []);
      renderInspector();
      renderMarketDiagnostics(market_diagnostics);
    }

    function renderPreflight() {
      const statusEl = $("preflightStatus");
      const profileEl = $("preflightProfile");
      const listEl = $("preflightChecks");
      if (!statusEl || !profileEl || !listEl) return;
      const preflight = state.preflight;
      if (!preflight) {
        statusEl.className = "warn-text";
        statusEl.textContent = t("loading");
        profileEl.textContent = "-";
        listEl.innerHTML = "";
        return;
      }
      const passed = preflight.status === "pass";
      statusEl.className = passed ? "good" : "bad";
      statusEl.textContent = passed ? t("ready") : t("notReady");
      profileEl.textContent = `${preflight.mode} / ${preflight.exchange} / ${preflight.symbol} / ${preflight.interval}`;
      listEl.innerHTML = "";
      for (const check of preflight.checks || []) {
        const row = document.createElement("div");
        const ok = check.status === "pass";
        row.className = "check-row";
        row.innerHTML = `
          <span>
            <span class="check-title">${escapeHtml(checkLabel(check.name))}</span>
            <span class="check-msg">${escapeHtml(checkMessage(check))}</span>
          </span>
          <span class="chip ${ok ? "green" : "red"}">${escapeHtml(ok ? t("checkPass") : t("checkFail"))}</span>
        `;
        listEl.appendChild(row);
      }
      updateAutomationControl();
      renderActiveProfile();
    }

    function renderActiveProfile() {
      const profile = state.ops?.active_profile || null;
      const sourceEl = $("activeProfileSource");
      const windowsEl = $("activeProfileWindows");
      const exitsEl = $("activeProfileExits");
      const evidenceEl = $("activeProfileEvidence");
      if (!sourceEl || !windowsEl || !exitsEl || !evidenceEl) return;
      if (!profile) {
        sourceEl.className = "warn-text";
        sourceEl.textContent = t("notPromoted");
        windowsEl.textContent = "-";
        exitsEl.textContent = "-";
        evidenceEl.textContent = "-";
        return;
      }
      const parameters = profile.parameters || {};
      const evidence = profile.evidence || {};
      const evidenceCount = ["backtest", "stress", "walk_forward"].filter((key) => evidence[key]?.run_id).length;
      sourceEl.className = profile.source === "sqlite" ? "good" : "warn-text";
      sourceEl.textContent = profile.source === "sqlite" ? t("promotedProfile") : t("configDefaults");
      windowsEl.textContent = `${parameters.short_window ?? "-"} / ${parameters.long_window ?? "-"}`;
      exitsEl.textContent = [
        `${t("stopLossShort")} ${profilePct(parameters.stop_loss_pct)}`,
        `${t("takeProfitShort")} ${profilePct(parameters.take_profit_pct)}`,
        `${t("trailingStopShort")} ${profilePct(parameters.trailing_stop_pct)}`
      ].join(" ");
      evidenceEl.className = evidenceCount >= 3 ? "good" : "warn-text";
      evidenceEl.textContent = `${evidenceCount} ${t("evidenceRuns")}`;
    }

    function renderReadiness() {
      const statusEl = $("readinessStatus");
      const credentialEl = $("credentialStatus");
      const automationEl = $("testnetAutomationStatus");
      const dryRunEl = $("dryRunStatus");
      const nextStepsEl = $("testnetNextSteps");
      if (!statusEl || !credentialEl || !automationEl || !dryRunEl || !nextStepsEl) return;

      const readiness = state.readiness;
      if (!readiness) {
        statusEl.className = "warn-text";
        statusEl.textContent = t("loading");
        credentialEl.textContent = "-";
        automationEl.textContent = "-";
        dryRunEl.textContent = state.dryRun ? dryRunLabel(state.dryRun) : t("noDryRunYet");
        nextStepsEl.innerHTML = "";
        return;
      }

      const observation = state.observation;
      const readinessPassed = readiness.status === "pass";
      statusEl.className = readinessPassed ? "good" : "bad";
      statusEl.textContent = readinessPassed ? t("ready") : t("notReady");

      const credentialCheck = readinessCheck("credentials");
      credentialEl.className = credentialCheck?.status === "pass" ? "good" : "bad";
      credentialEl.textContent = credentialCheck?.status === "pass" ? t("present") : t("missing");

      const automationCheck = readinessCheck("automation");
      automationEl.className = automationCheck?.status === "pass" ? "good" : "warn-text";
      automationEl.textContent = automationCheck?.status === "pass" ? t("enabled") : t("disabled");

      dryRunEl.className = observation ? dryRunClass(observation) : dryRunClass(state.dryRun);
      dryRunEl.textContent = observation ? observationLabel(observation) : (state.dryRun ? dryRunLabel(state.dryRun) : t("noDryRunYet"));

      const steps = observationSteps(observation) || state.dryRun?.next_steps || readiness.next_steps || [];
      if (!steps.length) {
        nextStepsEl.innerHTML = `<span>${escapeHtml(t("noNextSteps"))}</span>`;
        return;
      }
      nextStepsEl.innerHTML = steps.slice(0, 3)
        .map((step) => `<span>${escapeHtml(messageLabel(step))}</span>`)
        .join("");
    }

    function renderExchangeHealth() {
      const publicEl = $("publicMarketHealth");
      const tradingEl = $("tradingEndpointHealth");
      const stepsEl = $("exchangeHealthSteps");
      if (!publicEl || !tradingEl || !stepsEl) return;
      const health = state.exchangeHealth;
      if (!health) {
        publicEl.className = "warn-text";
        tradingEl.className = "warn-text";
        publicEl.textContent = t("loading");
        tradingEl.textContent = t("loading");
        stepsEl.innerHTML = "";
        return;
      }
      const publicCheck = exchangeHealthCheck("public_market_data");
      const tradingCheck = exchangeHealthCheck("trading_endpoint");
      renderExchangeHealthCheck(publicEl, publicCheck);
      renderExchangeHealthCheck(tradingEl, tradingCheck);
      const steps = health.next_steps || [];
      stepsEl.innerHTML = steps.slice(0, 3)
        .map((step) => `<span>${escapeHtml(messageLabel(step))}</span>`)
        .join("");
    }

    function renderExchangeHealthCheck(element, check) {
      if (!check) {
        element.className = "warn-text";
        element.textContent = "-";
        return;
      }
      element.className = check.status === "pass" ? "good" : "bad";
      element.textContent = messageLabel(check.message || check.details?.reason || check.status);
    }

    function exchangeHealthCheck(name) {
      return (state.exchangeHealth?.checks || []).find((check) => check.name === name) || null;
    }

    async function refreshLaunchChecklist() {
      const [exchangeHealth, launchTestnet, launchLive] = await Promise.all([
        fetchJson("/api/exchange-health?mode=testnet&timeout=2"),
        fetchJson("/api/launch-checklist?target=testnet"),
        fetchJson("/api/launch-checklist?target=live")
      ]);
      state.exchangeHealth = exchangeHealth;
      state.launchTestnet = launchTestnet;
      state.launchLive = launchLive;
      renderExchangeHealth();
      renderLaunchChecklist();
    }

    function renderLaunchChecklist() {
      const testnetStatusEl = $("testnetLaunchStatus");
      const testnetPhaseEl = $("testnetLaunchPhase");
      const liveStatusEl = $("liveLaunchStatus");
      const livePhaseEl = $("liveLaunchPhase");
      const observationEl = $("launchObservationStatus");
      const stepsEl = $("launchSteps");
      if (!testnetStatusEl || !testnetPhaseEl || !liveStatusEl || !livePhaseEl || !observationEl || !stepsEl) return;

      const testnet = state.launchTestnet;
      const live = state.launchLive;
      testnetStatusEl.className = launchStatusClass(testnet);
      testnetStatusEl.textContent = launchStatusLabel(testnet);
      testnetPhaseEl.textContent = testnet?.phase ? messageLabel(testnet.phase) : "-";
      liveStatusEl.className = launchStatusClass(live);
      liveStatusEl.textContent = launchStatusLabel(live);
      livePhaseEl.textContent = live?.phase ? messageLabel(live.phase) : "-";

      const observations = live?.testnet_observation || testnet?.testnet_observation || {};
      const nonOrder = observations.non_ordering || null;
      const boundedOrder = observations.bounded_order || null;
      observationEl.className = observationEvidenceClass(nonOrder, boundedOrder);
      observationEl.textContent = [
        `${t("nonOrderShort")} ${observationEvidenceLabel(nonOrder)}`,
        `${t("boundedOrderShort")} ${observationEvidenceLabel(boundedOrder)}`
      ].join(" / ");

      const steps = dedupeSteps([...(testnet?.next_steps || []), ...(live?.next_steps || [])]);
      if (!steps.length) {
        stepsEl.innerHTML = `<span>${escapeHtml(t("noNextSteps"))}</span>`;
        return;
      }
      stepsEl.innerHTML = steps.slice(0, 3)
        .map((step) => `<span>${escapeHtml(stepLabel(step))}</span>`)
        .join("");
    }

    function launchStatusClass(checklist) {
      if (!checklist) return "warn-text";
      return checklist.status === "pass" ? "good" : "bad";
    }

    function launchStatusLabel(checklist) {
      if (!checklist) return t("loading");
      if (checklist.status === "pass") return messageLabel(checklist.reason || "ready");
      return messageLabel(checklist.reason || checklist.status || "notReady");
    }

    function observationEvidenceLabel(observation) {
      if (!observation) return t("missingShort");
      const cycles = Number(observation.cycles_completed || 0);
      const suffix = cycles > 0 ? ` ${cycles}` : "";
      return observation.status === "pass" ? `${t("passedShort")}${suffix}` : `${t("failedShort")}${suffix}`;
    }

    function observationEvidenceClass(nonOrder, boundedOrder) {
      if (nonOrder?.status === "pass" && boundedOrder?.status === "pass") return "good";
      if (nonOrder?.status === "fail" || boundedOrder?.status === "fail") return "bad";
      return "warn-text";
    }

    function dedupeSteps(steps) {
      return [...new Set((steps || []).filter(Boolean))];
    }

    function stepLabel(step) {
      const translated = messageLabel(step);
      if (translated !== step) return translated;
      const raw = String(step || "");
      if (raw.includes("testnet-observe") && raw.includes("--execute-loop")) return t("runBoundedTestnetObserve");
      if (raw.includes("testnet-observe")) return t("runNonOrderTestnetObserve");
      if (raw.includes("promote-profile-to-live")) return t("promoteLiveAfterObservations");
      if (raw.includes("promote-profile-to-testnet")) return t("promoteTestnetProfile");
      return raw || "-";
    }

    function readinessCheck(name) {
      return (state.readiness?.checks || []).find((check) => check.name === name) || null;
    }

    function dryRunClass(result) {
      if (!result) return "warn-text";
      return result.status === "pass" ? "good" : "bad";
    }

    function dryRunLabel(result) {
      if (!result) return t("noDryRunYet");
      if (result.status === "pass") return t("ready");
      return messageLabel(result.reason || result.status || "dryRunUnavailable");
    }

    function observationLabel(result) {
      if (!result) return t("noDryRunYet");
      const summary = `${result.cycles_completed || 0}/${result.cycles_requested || 0}`;
      if (result.status === "pass") return `${t("observePassed")} ${summary}`;
      const last = (result.results || [])[Math.max(0, (result.results || []).length - 1)] || {};
      return `${t("observeFailed")} ${summary}: ${messageLabel(last.reason || result.status || "dryRunUnavailable")}`;
    }

    function observationSteps(result) {
      if (!result || !Array.isArray(result.results) || !result.results.length) return null;
      const last = result.results[result.results.length - 1];
      return last?.result?.next_steps || null;
    }

    function renderMarkets(markets) {
      const root = $("marketList");
      root.innerHTML = "";
      if (!markets.length) {
        root.innerHTML = `<div class="empty">${t("noCandleMarkets")}</div>`;
        return;
      }
      for (const market of markets) {
        const row = document.createElement("button");
        row.className = `nav-row ${state.selectedMarket === market ? "active" : ""}`;
        row.type = "button";
        row.innerHTML = `
          <span>
            <span class="row-title">${escapeHtml(String(market.exchange || "").toUpperCase())} ${escapeHtml(market.symbol)}</span>
            <span class="row-meta">${escapeHtml(market.interval)} / ${escapeHtml(market.candle_count)} ${escapeHtml(t("bars"))} / ${escapeHtml(t("vol"))} ${escapeHtml(num(market.volume, 2))}</span>
          </span>
          <span class="chip ${Number(market.change_pct) >= 0 ? "green" : "red"}">${escapeHtml(pct(market.change_pct, 2))}</span>
        `;
        row.addEventListener("click", async () => {
          state.selectedMarket = market;
          renderMarkets(markets);
          await loadCandles();
        });
        root.appendChild(row);
      }
    }

    function renderStrategies(strategies) {
      const root = $("strategyList");
      root.innerHTML = "";
      if (!strategies.length) {
        root.innerHTML = `<div class="empty">${t("noBacktestRuns")}</div>`;
        return;
      }
      for (const strategy of strategies) {
        const row = document.createElement("div");
        row.className = "nav-row";
        const tone = strategy.status === "ACTIVE" ? "green" : "amber";
        const statusLabel = strategy.status === "ACTIVE" ? t("active") : t("cooling");
        row.innerHTML = `
          <span>
            <span class="row-title">${escapeHtml(strategy.name)} / ${escapeHtml(strategy.symbol)}</span>
            <span class="row-meta">${escapeHtml(t("pnlShort"))} ${escapeHtml(money(strategy.pnl))} / ${escapeHtml(t("ddShort"))} ${escapeHtml(pct(-Math.abs(strategy.drawdown_pct), 2))} / ${escapeHtml(t("stressShort"))} ${escapeHtml(strategy.stress_pass_rate === null || strategy.stress_pass_rate === undefined ? "-" : pct(strategy.stress_pass_rate, 1))} / ${escapeHtml(t("walkForwardShort"))} ${escapeHtml(strategy.walk_forward_pass_rate === null || strategy.walk_forward_pass_rate === undefined ? "-" : pct(strategy.walk_forward_pass_rate, 1))}</span>
          </span>
          <span class="chip ${tone}">${escapeHtml(statusLabel)}</span>
        `;
        root.appendChild(row);
      }
    }

    function renderRuns(runs) {
      const body = $("runsTable");
      body.innerHTML = "";
      if (!runs.length) {
        body.innerHTML = `<tr><td colspan="6" class="empty">${t("noRunsRecorded")}</td></tr>`;
        return;
      }
      for (const run of runs.slice(0, 12)) {
        const metrics = run.metrics || {};
        const tr = document.createElement("tr");
        tr.tabIndex = 0;
        tr.innerHTML = `
          <td class="mono">${escapeHtml(run.run_id)}</td>
          <td>${escapeHtml(run.exchange)} ${escapeHtml(run.symbol)}</td>
          <td class="num ${clsFor(metrics.return_pct)}">${escapeHtml(pct(metrics.return_pct, 3))}</td>
          <td class="num bad">${escapeHtml(pct(-Math.abs(metrics.max_drawdown_pct || 0), 2))}</td>
          <td class="num">${escapeHtml(num(metrics.profit_factor, 3))}</td>
          <td class="num">${escapeHtml(metrics.trade_count || 0)}</td>
        `;
        tr.addEventListener("click", () => selectRun(run));
        tr.addEventListener("keydown", (event) => {
          if (event.key === "Enter") selectRun(run);
        });
        body.appendChild(tr);
      }
    }

    function renderExecutions(orders, fills, signals) {
      const body = $("execTable");
      const rows = [
        ...orders.map(item => ({ source: "order", symbol: item.symbol, side: item.side || "-", price: item.price, status: item.status })),
        ...fills.map(item => ({ source: "fill", symbol: item.symbol, side: item.side, price: item.price, status: item.status })),
        ...signals.map(item => ({ source: "signal", symbol: item.symbol, side: item.side, price: item.price, status: item.reason }))
      ].slice(-14).reverse();
      body.innerHTML = "";
      if (!rows.length) {
        body.innerHTML = `<tr><td colspan="5" class="empty">${t("noExecutions")}</td></tr>`;
        return;
      }
      for (const row of rows) {
        const tone = String(row.status).includes("reject") ? "red" : row.source === "signal" ? "cyan" : "green";
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${escapeHtml(sourceLabel(row.source))}</td>
          <td>${escapeHtml(row.symbol || "-")}</td>
          <td>${escapeHtml(sideLabel(row.side))}</td>
          <td class="num">${escapeHtml(num(row.price, 4))}</td>
          <td><span class="chip ${tone}">${escapeHtml(messageLabel(row.status))}</span></td>
        `;
        body.appendChild(tr);
      }
    }

    function renderEvents(events) {
      const root = $("events");
      $("eventCountChip").textContent = `${events.length} ${t("events")}`;
      root.innerHTML = "";
      if (!events.length) {
        root.innerHTML = `<div class="empty">${t("noEvents")}</div>`;
        return;
      }
      for (const event of events) {
        const tone = event.level === "ERROR" ? "red" : event.level === "WARN" ? "amber" : event.level === "EXEC" ? "green" : "cyan";
        const row = document.createElement("div");
        row.className = "event";
        row.innerHTML = `
          <span>${escapeHtml(time(event.timestamp))}</span>
          <span class="chip ${tone}">${escapeHtml(levelLabel(event.level))}</span>
          <span>${escapeHtml(sourceLabel(event.source))}</span>
          <span>${escapeHtml(eventMessage(event))}</span>
        `;
        root.appendChild(row);
      }
    }

    function renderInspector() {
      const run = state.selectedRun;
      if (!run) {
        $("selectedRunId").textContent = "-";
        $("selectedStrategy").textContent = "-";
        $("selectedSymbol").textContent = "-";
        $("selectedTrades").textContent = "0";
        return;
      }
      const metrics = run.metrics || {};
      $("selectedRunId").textContent = run.run_id;
      $("selectedStrategy").textContent = run.strategy || "-";
      $("selectedSymbol").textContent = `${run.exchange} ${run.symbol}`;
      $("selectedTrades").textContent = String(metrics.trade_count || 0);
      $("selectedDrawdown").textContent = pct(-Math.abs(metrics.max_drawdown_pct || 0), 2);
      $("selectedPf").textContent = num(metrics.profit_factor, 3);
      $("selectedWinRate").textContent = pct(metrics.win_rate || 0, 2);
      $("drawdownBar").style.width = `${Math.min(100, Math.abs(Number(metrics.max_drawdown_pct || 0)) * 8)}%`;
    }

    function renderMarketDiagnostics(diagnostics) {
      const classification = diagnostics?.classification || {};
      const costPressure = String(classification.cost_pressure || "unknown");
      const costTone = costPressure === "high" ? "bad" : costPressure === "medium" ? "warn-text" : costPressure === "low" ? "good" : "warn-text";
      const regimeTone = classification.regime === "uptrend" ? "good" : classification.regime === "downtrend" ? "bad" : "warn-text";
      $("marketRegime").className = regimeTone;
      $("marketRegime").textContent = enumLabel("regime", classification.regime);
      $("marketCostPressure").className = costTone;
      $("marketCostPressure").textContent = enumLabel("cost", costPressure);
      $("marketBuyHold").className = clsFor(diagnostics?.buy_hold_return_pct || 0);
      $("marketBuyHold").textContent = pct(diagnostics?.buy_hold_return_pct || 0, 3);
      $("marketBenchmarkDrawdown").className = "bad";
      $("marketBenchmarkDrawdown").textContent = pct(-Math.abs(Number(diagnostics?.buy_hold_max_drawdown_pct || 0)), 2);
      $("marketTrendEfficiency").textContent = num(diagnostics?.trend_efficiency || 0, 4);
      $("marketFriction").className = costTone;
      $("marketFriction").textContent = pct(diagnostics?.round_trip_friction_pct || 0, 3);
      $("marketSegmentBalance").textContent = `${classification.positive_segments || 0}+ / ${classification.negative_segments || 0}-`;
    }

    function profilePct(value) {
      const parsed = Number(value || 0);
      if (!Number.isFinite(parsed) || parsed <= 0) return t("off");
      return `${parsed.toFixed(2)}%`;
    }

    async function selectRun(run) {
      state.selectedRun = run;
      renderInspector();
      await loadTrades(run.run_id);
    }

    async function loadCandles() {
      if (!state.selectedMarket) {
        state.candles = [];
        updateChartTitle();
        drawChart([]);
        return;
      }
      const market = state.selectedMarket;
      const params = new URLSearchParams({
        exchange: market.exchange,
        symbol: market.symbol,
        interval: market.interval,
        limit: "420"
      });
      const data = await fetchJson(`/api/candles?${params}`);
      state.candles = data.candles || [];
      updateChartTitle(data);
      updateCandleLabels();
      drawChart(state.candles);
    }

    function updateChartTitle(market) {
      const target = market || state.selectedMarket;
      if (target && target.exchange && target.symbol && target.interval) {
        $("chartTitle").textContent = `${String(target.exchange).toUpperCase()} ${target.symbol} / ${target.interval}`;
        return;
      }
      $("chartTitle").textContent = t("chartTitleEmpty");
    }

    function updateCandleLabels() {
      const candles = state.candles || [];
      $("candleChip").textContent = `${candles.length} ${t("candles")}`;
      const last = candles[candles.length - 1];
      $("lastCloseChip").textContent = last ? `${t("close")} ${num(last.close, 4)}` : `${t("close")} -`;
      if (candles.length) {
        const lows = candles.map(c => Number(c.low));
        const highs = candles.map(c => Number(c.high));
        $("rangeChip").textContent = `${t("range")} ${num(Math.min(...lows), 2)}-${num(Math.max(...highs), 2)}`;
      } else {
        $("rangeChip").textContent = `${t("range")} -`;
      }
    }

    async function loadTrades(runId) {
      const body = $("tradeTable");
      body.innerHTML = "";
      if (!runId) return;
      const data = await fetchJson(`/api/trades?run_id=${encodeURIComponent(runId)}`);
      const trades = data.trades || [];
      if (!trades.length) {
        body.innerHTML = `<tr><td colspan="4" class="empty">${t("noTradesForRun")}</td></tr>`;
        return;
      }
      for (const trade of trades.slice(-18).reverse()) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${escapeHtml(time(trade.timestamp))}</td>
          <td class="${trade.side === "buy" ? "good" : "bad"}">${escapeHtml(sideLabel(trade.side))}</td>
          <td class="num">${escapeHtml(num(trade.execution_price, 4))}</td>
          <td class="num ${clsFor(trade.pnl)}">${escapeHtml(num(trade.pnl, 4))}</td>
        `;
        body.appendChild(tr);
      }
    }

    function drawChart(candles) {
      const canvas = $("priceChart");
      const ctx = canvas.getContext("2d");
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      const width = rect.width;
      const height = rect.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#080d13";
      ctx.fillRect(0, 0, width, height);

      const pad = { left: 52, right: 16, top: 46, bottom: 30 };
      const plotW = Math.max(10, width - pad.left - pad.right);
      const plotH = Math.max(10, height - pad.top - pad.bottom);

      ctx.strokeStyle = "rgba(143, 161, 180, 0.16)";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 5; i++) {
        const y = pad.top + (plotH * i) / 5;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
      }
      for (let i = 0; i <= 8; i++) {
        const x = pad.left + (plotW * i) / 8;
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, height - pad.bottom);
        ctx.stroke();
      }

      if (!candles.length) {
        ctx.fillStyle = "#9aa8b6";
        ctx.font = "13px Cascadia Mono, monospace";
        ctx.fillText(t("noCandleData"), 20, 74);
        return;
      }

      const lows = candles.map(c => Number(c.low));
      const highs = candles.map(c => Number(c.high));
      const min = Math.min(...lows);
      const max = Math.max(...highs);
      const span = Math.max(max - min, 1e-9);
      const x = (index) => pad.left + (index / Math.max(candles.length - 1, 1)) * plotW;
      const y = (price) => pad.top + ((max - price) / span) * plotH;

      ctx.fillStyle = "#9aa8b6";
      ctx.font = "11px Cascadia Mono, monospace";
      for (let i = 0; i <= 5; i++) {
        const price = max - (span * i) / 5;
        ctx.fillText(num(price, 2), 6, pad.top + (plotH * i) / 5 + 4);
      }

      const candleW = Math.max(2, Math.min(9, (plotW / candles.length) * 0.64));
      for (let i = 0; i < candles.length; i++) {
        const candle = candles[i];
        const xx = x(i);
        const open = Number(candle.open);
        const close = Number(candle.close);
        const high = Number(candle.high);
        const low = Number(candle.low);
        const up = close >= open;
        ctx.strokeStyle = up ? "#2ea043" : "#f85149";
        ctx.fillStyle = up ? "#2ea043" : "#f85149";
        ctx.beginPath();
        ctx.moveTo(xx, y(high));
        ctx.lineTo(xx, y(low));
        ctx.stroke();
        const top = y(Math.max(open, close));
        const bottom = y(Math.min(open, close));
        ctx.fillRect(xx - candleW / 2, top, candleW, Math.max(2, bottom - top));
      }

      ctx.strokeStyle = "#3fb1ed";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      candles.forEach((candle, index) => {
        const xx = x(index);
        const yy = y(Number(candle.close));
        if (index === 0) ctx.moveTo(xx, yy);
        else ctx.lineTo(xx, yy);
      });
      ctx.stroke();
    }

    function toast(message) {
      const el = $("toast");
      el.textContent = message;
      el.style.display = "block";
      window.clearTimeout(toast.timer);
      toast.timer = window.setTimeout(() => { el.style.display = "none"; }, 2800);
    }

    $("reloadButton").addEventListener("click", () => {
      boot().catch((error) => toast(error.message || String(error)));
    });
    document.querySelectorAll("[data-lang-option]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.langOption === state.lang) return;
        state.lang = button.dataset.langOption === "en" ? "en" : "zh";
        persistLanguage(state.lang);
        applyLanguage();
        toast(t("langChanged"));
      });
    });
    $("backtestButton").addEventListener("click", () => toast(t("runLocally")));
    $("simulateButton").addEventListener("click", () => toast(t("simulateOnly")));
    $("pauseButton").addEventListener("click", async () => {
      const action = $("pauseButton").dataset.action === "resume" ? "resume" : "pause";
      try {
        const data = await postJson("/api/automation-control", { action, reason: `dashboard_${action}` });
        if (data.status !== "ok") throw new Error(messageLabel(data.reason || "invalid_control_action"));
        state.preflight = data.preflight;
        renderPreflight();
        toast(action === "pause" ? t("pauseRequested") : t("resumeRequested"));
      } catch (error) {
        toast(error.message || String(error));
      }
    });
    $("dryRunButton").addEventListener("click", async () => {
      const button = $("dryRunButton");
      button.disabled = true;
      toast(t("dryRunStarted"));
      try {
        const data = await postJson("/api/testnet-dry-run", {
          execute_loop: false,
          sync_limit: 500,
          sleep_seconds: 0
        });
        state.dryRun = data;
        if (data.preflight) state.preflight = data.preflight;
        renderPreflight();
        renderReadiness();
        await refreshLaunchChecklist();
        toast(data.status === "pass" ? t("dryRunPassed") : `${t("dryRunFailed")}: ${messageLabel(data.reason || data.status)}`);
      } catch (error) {
        toast(error.message || String(error));
      } finally {
        button.disabled = false;
      }
    });
    $("observeButton").addEventListener("click", async () => {
      const button = $("observeButton");
      button.disabled = true;
      toast(t("observeStarted"));
      try {
        const data = await postJson("/api/testnet-observe", {
          cycles: 3,
          execute_loop: false,
          sync_limit: 500,
          sleep_seconds: 0,
          continue_on_failure: true
        });
        state.observation = data;
        const last = (data.results || [])[Math.max(0, (data.results || []).length - 1)] || {};
        if (last.result?.preflight) state.preflight = last.result.preflight;
        renderPreflight();
        renderReadiness();
        await refreshLaunchChecklist();
        state.ops = await fetchJson("/api/ops");
        renderOps();
        toast(data.status === "pass" ? t("observePassed") : `${t("observeFailed")}: ${messageLabel(last.reason || data.status)}`);
      } catch (error) {
        toast(error.message || String(error));
      } finally {
        button.disabled = false;
      }
    });
    $("exportButton").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(state.ops, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "kxian-ops-dashboard.json";
      link.click();
      URL.revokeObjectURL(link.href);
    });
    window.addEventListener("resize", () => drawChart(state.candles));

    applyLanguage();
    boot().catch((error) => {
      document.body.textContent = "";
      const errorBlock = document.createElement("pre");
      errorBlock.style.cssText = "margin:0;padding:24px;color:#ff9c96;background:#080b10;height:100vh;white-space:pre-wrap;";
      errorBlock.textContent = error.stack || String(error);
      document.body.appendChild(errorBlock);
    });
  </script>
</body>
</html>
"""
