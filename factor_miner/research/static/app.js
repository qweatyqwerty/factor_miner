"use strict";

const byId = (id) => document.getElementById(id);
const make = (tag, text) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  return element;
};
const profileNames = {
  stock_timing: "股票 · 原多因子择时",
  stock_timing_wider_exit: "股票 · 放宽退出阈值",
  stock_timing_slow: "股票 · 慢周期择时",
  stock_cross_section: "股票 · 滚动 IC 截面选股",
  stock_cross_section_buffered: "股票 · 带排名缓冲的截面选股",
  future_timing: "期货 · 多空择时",
};
const factorNames = {momentum: "动量", sma_cross: "均线差", rsi: "RSI", macd: "MACD", volatility: "波动率", obv: "OBV"};
const parameterNames = {window: "周期", short: "短周期", long: "长周期", fast: "快线", slow: "慢线", signal: "信号周期"};
const chartTitles = {equity: "累计收益", drawdown: "历史峰值回撤", gross_exposure_ratio: "总敞口占权益"};
const sameFormat = new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 2});
const pct = (value) => Number.isFinite(value) ? (value * 100).toFixed(2) + "%" : "—";
const num = (value) => Number.isFinite(value) ? sameFormat.format(value) : "—";
const day = (value) => value ? value.slice(0, 10) : "—";
const state = {catalog: null, result: null, busy: false, chart: "equity", detail: "performance", factorId: 0};

function option(value, label) {
  const result = make("option", label);
  result.value = value;
  return result;
}

function setStatus(message, error = false) {
  byId("status").textContent = message;
  byId("status").classList.toggle("error", error);
}

function control(label, input) {
  const wrapper = make("label");
  wrapper.append(make("span", label), input);
  return wrapper;
}

function numeric(value, step, min) {
  const input = make("input");
  input.type = "number";
  input.step = step;
  input.min = min;
  input.required = true;
  input.value = value;
  return input;
}

function field(container, settings, key, label, fallback, step = 1, min = 0) {
  const input = numeric(settings[key] ?? fallback, step, min);
  input.dataset.setting = key;
  container.append(control(label, input));
}

function choice(container, settings, key, label, values, fallback) {
  const input = make("select");
  for (const [id, name] of values) input.append(option(id, name));
  input.value = settings[key] ?? fallback;
  input.dataset.setting = key;
  container.append(control(label, input));
}

function addFactor(key, settings) {
  const card = make("div");
  card.className = "factor";
  card.dataset.factor = key;
  const header = make("div");
  header.className = "factor-header";
  const kinds = make("select");
  kinds.setAttribute("aria-label", "因子类型 " + key);
  for (const id of Object.keys(state.catalog.factor_types)) kinds.append(option(id, factorNames[id] ?? id));
  kinds.value = settings.type;
  kinds.dataset.factorType = "";
  const remove = make("button", "移除");
  remove.type = "button";
  remove.className = "remove-factor";
  remove.setAttribute("aria-label", "移除因子 " + key);
  remove.addEventListener("click", () => {
    if (byId("factors").children.length === 1) {
      setStatus("至少保留一个因子。", true);
      return;
    }
    card.remove();
    dirty();
  });
  header.append(kinds, remove);
  const grid = make("div");
  grid.className = "grid";
  const params = make("div");
  params.className = "grid";
  const weight = numeric(settings.weight ?? 1, "any", 0);
  weight.dataset.factorWeight = "";
  const direction = make("select");
  direction.append(option("1", "正向"), option("-1", "反向"));
  direction.value = settings.direction ?? 1;
  direction.dataset.factorDirection = "";
  function renderParams(overrides) {
    params.replaceChildren();
    for (const [name, value] of Object.entries(state.catalog.factor_types[kinds.value])) {
      const input = numeric(overrides[name] ?? value, 1, 1);
      input.dataset.param = name;
      params.append(control(parameterNames[name] ?? name, input));
    }
  }
  kinds.addEventListener("change", () => renderParams({}));
  grid.append(control("权重", weight), control("方向", direction));
  card.append(header, grid, params);
  renderParams(settings.params ?? {});
  byId("factors").append(card);
}

function selectedSettings() {
  return state.catalog.profiles[byId("profile").value];
}

function selectedDataset() {
  return state.catalog.datasets.find((source) => source.id === byId("dataset").value);
}

function configureDataset() {
  const source = selectedDataset();
  const settings = selectedSettings();
  const timing = settings.mode === "timing";
  byId("symbol-field").hidden = !timing;
  byId("run").disabled = state.busy || !source;
  if (!source) {
    byId("data-note").textContent = "行情目录没有可供此策略使用的 CSV。";
    return;
  }
  const symbol = byId("symbol");
  const previous = symbol.value;
  symbol.replaceChildren(...source.symbols.map((code) => option(code, code)));
  if (source.symbols.includes(previous)) symbol.value = previous;
  const label = source.synthetic ? "合成行情" : "历史行情";
  byId("data-note").textContent = label + " · " + source.symbols.length + " 个标的 · " + source.first + " 至 " + source.last;
  const guess = settings.evaluation_start;
  for (const id of ["start", "end"]) {
    const input = byId(id);
    input.min = source.first;
    input.max = source.last;
  }
  byId("start").value = guess && guess >= source.first && guess < source.last ? guess : source.first;
  byId("end").value = source.last;
}

function configureProfile() {
  const settings = selectedSettings();
  const cross = settings.mode === "cross_section";
  const options = state.catalog.datasets.filter((source) => !source.error &&
    source.market === settings.market && (cross ? source.symbols.length >= 2 : !source.synthetic));
  options.sort((a, b) => Number(a.synthetic) - Number(b.synthetic) ||
    b.symbols.length - a.symbols.length || b.last.localeCompare(a.last));
  const previous = byId("dataset").value;
  byId("dataset").replaceChildren(...options.map((source) =>
    option(source.id, source.synthetic ? "八标的合成演示" : source.id)));
  if (options.some((source) => source.id === previous)) byId("dataset").value = previous;
  configureDataset();

  const rules = byId("rules");
  rules.replaceChildren();
  const weightings = [["fixed", "固定权重"], ["equal", "等权"]];
  if (cross) weightings.push(["rolling_ic", "滚动 Rank IC"]);
  choice(rules, settings, "weighting", "组合权重", weightings, "equal");
  field(rules, settings, "max_exposure", "组合敞口上限", .95, "any");
  if (cross) {
    choice(rules, settings, "normalization", "横截面标准化", [["rank", "百分位排名"], ["zscore", "Z 分数"]], "rank");
    field(rules, settings, "top_n", "组合标的数", 5, 1, 1);
    field(rules, settings, "rank_buffer", "排名缓冲", 0);
    field(rules, settings, "rebalance_every", "调仓间隔（交易日）", 5, 1, 1);
    field(rules, settings, "max_weight", "单标的权重上限", settings.max_exposure ?? .95, "any");
    field(rules, settings, "forward_period", "收益标签期（交易日）", 1, 1, 1);
    field(rules, settings, "min_assets", "最少可评分标的", 3, 1, 2);
    field(rules, settings, "ic_min_assets", "IC 最少标的", 5, 1, 3);
    field(rules, settings, "ic_window", "IC 滚动窗口", 60, 1, 1);
    field(rules, settings, "ic_min_periods", "IC 最少样本", 20, 1, 1);
  } else {
    field(rules, settings, "entry", "入场分数", .5, "any");
    field(rules, settings, "exit", "退出分数", 0, "any", -3);
    field(rules, settings, "z_window", "标准化窗口", 30, 1, 2);
  }

  const costs = byId("costs");
  costs.replaceChildren();
  field(costs, settings, "initial_cash", "初始资金（元）", 1000000, "any", .01);
  field(costs, settings, "commission", "比例手续费", .0003, "any");
  field(costs, settings, "slippage", "滑点比例", .001, "any");
  if (settings.market === "stock") {
    field(costs, settings, "sell_fee", "卖出附加费率", 0, "any");
    field(costs, settings, "lot_size", "整手股数", 100, 1, 1);
  } else {
    field(costs, settings, "contract_multiplier", "合约乘数", 1, "any", .000001);
    field(costs, settings, "margin_rate", "保证金比例", .1, "any", .000001);
    field(costs, settings, "max_contracts", "持仓手数上限", 10, 1, 1);
    field(costs, settings, "fee_per_contract", "每手手续费（元）", 0, "any");
    const short = make("input");
    short.type = "checkbox";
    short.checked = settings.allow_short ?? false;
    short.dataset.setting = "allow_short";
    costs.append(control("允许做空", short));
  }
  byId("factors").replaceChildren();
  for (const [key, spec] of Object.entries(settings.factors)) addFactor(key, spec);
}

function dirty() {
  if (!state.busy && state.catalog && selectedDataset()) setStatus("配置已调整，运行后更新结果。");
}

async function request(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error ?? "请求失败");
  return body;
}

async function run() {
  if (state.busy || !selectedDataset() || !byId("strategy-form").reportValidity()) return;
  const start = byId("start").value;
  const end = byId("end").value;
  if (start >= end) {
    setStatus("评估开始日期须早于结束日期。", true);
    return;
  }
  const settings = {evaluation_start: start, evaluation_end: end, factors: {}};
  for (const input of document.querySelectorAll("[data-setting]")) {
    settings[input.dataset.setting] = input.type === "number" ? input.valueAsNumber :
      input.type === "checkbox" ? input.checked : input.value;
  }
  for (const card of document.querySelectorAll("[data-factor]")) {
    const params = Object.fromEntries([...card.querySelectorAll("[data-param]")].map((input) =>
      [input.dataset.param, input.valueAsNumber]));
    settings.factors[card.dataset.factor] = {
      type: card.querySelector("[data-factor-type]").value, params,
      weight: card.querySelector("[data-factor-weight]").valueAsNumber,
      direction: Number(card.querySelector("[data-factor-direction]").value),
    };
  }
  state.busy = true;
  byId("run").disabled = true;
  const controls = [...byId("strategy-form").elements].filter((element) => element !== byId("run"));
  controls.forEach((element) => { element.disabled = true; });
  setStatus("正在运行回测…");
  try {
    state.result = await request("/api/run", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        profile: byId("profile").value, dataset: byId("dataset").value,
        symbol: byId("symbol").value, settings,
      }),
    });
    renderResult();
    setStatus("完成 · 引擎用时 " + state.result.seconds.toFixed(2) + " 秒");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.busy = false;
    byId("run").disabled = false;
    controls.forEach((element) => { element.disabled = false; });
  }
}

function renderResult() {
  const {metrics, curves, dataset, profile, symbol} = state.result;
  const [strategy, benchmark] = metrics;
  const dates = day(curves[0].date) + " – " + day(curves.at(-1).date);
  byId("run-description").textContent = (profileNames[profile] ?? profile) + " · " +
    (dataset === "demo" ? "合成演示" : symbol ?? dates) + (symbol || dataset === "demo" ? " · " + dates : "");
  const fields = [
    ["累计净收益", "total_return", pct, true],
    ["最大回撤", "max_drawdown", pct, false],
    ["年化夏普", "sharpe", num, false],
    ["累计换手", "turnover", (value) => num(value) + " 倍", false],
  ];
  const cards = fields.map(([label, fieldName, format, signed]) => {
    const card = make("div");
    card.className = "metric";
    const value = make("strong", format(strategy[fieldName]));
    if (signed) value.className = strategy[fieldName] < 0 ? "negative" : "positive";
    card.append(make("span", label), value, make("small", "基准 " + format(benchmark[fieldName])));
    return card;
  });
  byId("summary").replaceChildren(...cards);
  byId("exports").hidden = false;
  byId("chart-empty").hidden = true;
  byId("tooltip").hidden = true;
  renderDetail();
  drawChart();
}

function renderTable(labels, rows) {
  const headline = make("tr");
  headline.append(...labels.map((label) => make("th", label)));
  const head = make("thead");
  head.append(headline);
  const content = make("tbody");
  for (const record of rows) {
    const row = make("tr");
    row.append(...record.map((value) => make("td", value)));
    content.append(row);
  }
  const table = make("table");
  table.append(head, content);
  byId("detail").replaceChildren(table);
}

function renderDetail() {
  if (!state.result) return;
  const note = byId("detail-note");
  note.textContent = "";
  if (state.detail === "trades") {
    note.textContent = state.result.trade_count ? "最近 " + state.result.trades.length + " 笔，共 " +
      state.result.trade_count + " 笔" : "本区间没有成交";
    renderTable(["成交日", "信号日", "标的", "方向", "数量", "成交价", "手续费"], state.result.trades.map((trade) =>
      [day(trade.date), day(trade.signal_date), trade.symbol, trade.side === "buy" ? "买" : "卖",
        num(trade.size), num(trade.fill_price), num(trade.commission)]));
  } else if (state.detail === "factors") {
    renderTable(["因子", "有效样本", "覆盖率", "平均权重", "Rank IC", "ICIR"], state.result.factors.map((row) =>
      [row.factor === "composite" ? "组合评分" : row.factor, num(row.count), pct(row.coverage),
        pct(row.average_weight), num(row.mean ?? row.sample_rank_ic), num(row.icir)]));
  } else {
    const fields = [
      ["累计净收益", "total_return", pct], ["年化收益", "annual_return", pct],
      ["年化波动率", "annual_volatility", pct], ["最大回撤", "max_drawdown", pct],
      ["平均总敞口", "avg_gross_exposure", pct], ["累计手续费", "commission", num],
      ["累计滑点成本", "slippage_cost", num], ["成交笔数", "trades", num],
    ];
    renderTable(["指标", "策略", "比较基准"],
      fields.map(([label, key, format]) => [label, ...state.result.metrics.map((value) => format(value[key]))]));
  }
}

function plotValues(side) {
  const rows = state.result.curves;
  const field = side + "_" + state.chart;
  return rows.map((row) => {
    const current = row[field];
    if (!Number.isFinite(current)) return null;
    return state.chart === "equity" ? current / rows[0][field] - 1 : current;
  });
}

function drawChart() {
  const canvas = byId("chart");
  const box = canvas.getBoundingClientRect();
  if (!state.result || box.width < 100 || box.height === 0) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = box.width * dpr;
  canvas.height = box.height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const plot = {left: 54, right: box.width - 16, top: 15, bottom: box.height - 28};
  const series = [plotValues("strategy"), plotValues("benchmark")];
  let min = 0, max = 0;
  for (const values of series) {
    for (const value of values) {
      if (value !== null) { min = Math.min(min, value); max = Math.max(max, value); }
    }
  }
  const pad = Math.max((max - min) * .08, .006);
  min -= pad;
  max += pad;
  const last = state.result.curves.length - 1;
  const x = (i) => plot.left + (plot.right - plot.left) * i / Math.max(1, last);
  const y = (value) => plot.bottom - (plot.bottom - plot.top) * (value - min) / (max - min);
  ctx.font = "11px Segoe UI, sans-serif";
  ctx.fillStyle = "#657064";
  ctx.strokeStyle = "#e5ebe1";
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const value = min + (max - min) * i / 4;
    const line = y(value);
    ctx.beginPath(); ctx.moveTo(plot.left, line); ctx.lineTo(plot.right, line); ctx.stroke();
    ctx.fillText((value * 100).toFixed(1) + "%", plot.left - 7, line);
  }
  const ticks = box.width >= 530 ? 4 : 2;
  for (let i = 0; i <= ticks; i++) {
    const index = Math.round(last * i / ticks);
    ctx.textAlign = i === 0 ? "left" : i === ticks ? "right" : "center";
    ctx.fillText(day(state.result.curves[index].date), x(index), plot.bottom + 16);
  }
  series.forEach((values, side) => {
    ctx.strokeStyle = side === 0 ? "#246759" : "#697d9a";
    ctx.lineWidth = side === 0 ? 2 : 1.7;
    ctx.beginPath();
    let drawing = false;
    values.forEach((value, index) => {
      if (value === null) drawing = false;
      else {
        if (drawing) ctx.lineTo(x(index), y(value));
        else ctx.moveTo(x(index), y(value));
        drawing = true;
      }
    });
    ctx.stroke();
  });
  canvas.onpointermove = (event) => {
    const tooltip = byId("tooltip");
    if (event.offsetX < plot.left || event.offsetX > plot.right || event.offsetY > plot.bottom) {
      tooltip.hidden = true;
      return;
    }
    const index = Math.round(last * (event.offsetX - plot.left) / (plot.right - plot.left));
    tooltip.textContent = [day(state.result.curves[index].date), "策略  " + pct(series[0][index]),
      "基准  " + pct(series[1][index])].join("\n");
    tooltip.style.left = Math.max(0, Math.min(x(index) + 12, box.width - 140)) + "px";
    tooltip.style.top = Math.min(event.offsetY + 12, box.height - 78) + "px";
    tooltip.hidden = false;
  };
  canvas.onpointerleave = () => { byId("tooltip").hidden = true; };
}

function download(key) {
  if (!state.result) return;
  const filename = {yaml: "dashboard_strategy.yaml", curves_csv: "equity.csv", trades_csv: "trades.csv"}[key];
  const parts = key === "yaml" ? [state.result[key]] : ["\ufeff", state.result[key]];
  const url = URL.createObjectURL(new Blob(parts, {type: "text/plain;charset=utf-8"}));
  const link = make("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

byId("strategy-form").addEventListener("submit", (event) => { event.preventDefault(); run(); });
byId("strategy-form").addEventListener("change", dirty);
byId("profile").addEventListener("change", configureProfile);
byId("dataset").addEventListener("change", configureDataset);
byId("add-factor").addEventListener("click", () => {
  let key;
  do { key = "factor_" + ++state.factorId; }
  while ([...byId("factors").children].some((card) => card.dataset.factor === key));
  addFactor(key, {type: "momentum"});
  dirty();
});
for (const key of ["chart", "detail"]) {
  const buttons = document.querySelectorAll("[data-" + key + "]");
  for (const button of buttons) button.addEventListener("click", () => {
    state[key] = button.dataset[key];
    for (const other of buttons) other.setAttribute("aria-pressed", String(other === button));
    if (key === "chart") {
      byId("chart-title").textContent = chartTitles[state.chart];
      byId("tooltip").hidden = true;
      drawChart();
    } else renderDetail();
  });
}
for (const button of document.querySelectorAll("[data-export]")) {
  button.addEventListener("click", () => download(button.dataset.export));
}
new ResizeObserver(drawChart).observe(byId("plot"));

async function initialize() {
  try {
    state.catalog = await request("/api/catalog");
    for (const id of Object.keys(state.catalog.profiles)) byId("profile").append(option(id, profileNames[id] ?? id));
    if ("stock_cross_section_buffered" in state.catalog.profiles) byId("profile").value = "stock_cross_section_buffered";
    configureProfile();
    if (selectedDataset()) run();
  } catch (error) {
    setStatus("加载失败 · " + error.message, true);
  }
}
initialize();
