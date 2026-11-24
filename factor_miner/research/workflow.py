"""配置化研究入口及可复核的 CSV 产物。"""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .signals import allocation, combine, diagnostics, prepare_prices, session_date
from .simulation import metrics, simulate


def _demo_prices():
    """固定随机种子的合成股票面板，用于离线验证截面流程。"""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2023-01-03", periods=500)
    market = rng.normal(0.0002, 0.008, len(dates))
    frames = []
    for index in range(8):
        overnight = rng.normal(0, 0.003, len(dates))
        cycle = 0.003 * np.sin(np.arange(len(dates)) / 23 + index)
        intraday = market + cycle + rng.normal(0, 0.011, len(dates))
        close = (15 + index) * np.exp(np.cumsum(overnight + intraday))
        frames.append(pd.DataFrame({
            "date": dates,
            "symbol": f"DEMO{index + 1:02d}",
            "open": close / np.exp(intraday),
            "close": close,
        }))
    return pd.concat(frames, ignore_index=True)


def _load_prices(config, settings, csv_path, demo):
    market = settings["market"]
    if market not in {"stock", "future"}:
        raise ValueError("market 必须为 stock 或 future")
    market_cfg = config[market]
    symbols = settings.get("symbols", [market_cfg["default_symbol"]])
    if not isinstance(symbols, list) or not symbols or any(
        not isinstance(symbol, str) or not symbol.strip() for symbol in symbols
    ) or len(symbols) != len(set(symbols)):
        raise ValueError("symbols 需为非空且不重复的字符串列表，请将股票代码加引号")
    if demo:
        if market != "stock" or settings["mode"] != "cross_section":
            raise ValueError("--demo 用于股票截面策略")
        return _demo_prices(), "synthetic_demo"
    if csv_path:
        frame = pd.read_csv(csv_path, dtype={"symbol": "string"}, encoding="utf-8-sig")
        if "symbol" not in frame and len(symbols) == 1:
            frame["symbol"] = symbols[0]
        return frame, str(Path(csv_path).resolve())

    from factor_miner.data import FutureAPI, StockAPI

    api = (StockAPI if market == "stock" else FutureAPI)(config["project"]["data_dir"])
    options = {key: market_cfg[key] for key in ("start_date", "end_date")}
    if market == "stock":
        options["adjust"] = market_cfg.get("adjust", "qfq")
    frames = []
    for symbol in symbols:
        frame = api.get_daily(symbol=symbol, **options)
        if frame.empty:
            raise ValueError(f"{symbol} 在所选区间没有行情")
        frames.append(frame.assign(symbol=symbol))
    return pd.concat(frames, ignore_index=True), "project_cache_or_akshare"


def analyze(prices, settings):
    """运行组合诊断、策略模拟和使用相同成本参数的基准。"""
    prices = prepare_prices(prices)
    evaluation_end = settings.get("evaluation_end")
    if evaluation_end is not None:
        end = session_date(evaluation_end, "evaluation_end")
        prices = prices.loc[:end]
        if prices.empty:
            raise ValueError("evaluation_end 之前没有行情")
    detail, weights, ic, forward = combine(prices, settings)
    targets, benchmark, start = allocation(detail, forward, settings)
    active = targets.loc[start:]
    nav, trades, holdings = simulate(prices, active, settings)
    baseline, baseline_trades, baseline_holdings = simulate(prices, benchmark.loc[start:], settings)
    daily_ic, ic_summary, quantiles = diagnostics(detail, weights, ic, forward, settings, start)

    annualization = settings.get("annualization", 252)
    comparison = pd.DataFrame.from_dict({
        "strategy": metrics(nav, trades, annualization),
        "benchmark": metrics(baseline, baseline_trades, annualization),
    }, orient="index").rename_axis("portfolio")
    return {
        "factors": prices.join(detail),
        "factor_weights": weights,
        "rank_ic": daily_ic,
        "ic_summary": ic_summary,
        "quantile_returns": quantiles,
        "targets": targets,
        "benchmark_targets": benchmark,
        "equity": nav,
        "trades": trades,
        "holdings": holdings,
        "benchmark_equity": baseline,
        "benchmark_trades": baseline_trades,
        "benchmark_holdings": baseline_holdings,
        "metrics": comparison,
    }


def run_profile(config, profile=None, csv_path=None, demo=False, output_dir=None, *,
                symbol=None, evaluation_start=None, evaluation_end=None):
    research = config.get("research", {})
    profiles = research.get("profiles", {})
    profile = profile or research.get("default_profile")
    if profile not in profiles:
        raise ValueError(f"未知策略配置 {profile}，可选 {', '.join(profiles) or '无'}")
    settings = {**config.get("backtest", {}), **profiles[profile]}
    for key, value in (("evaluation_start", evaluation_start), ("evaluation_end", evaluation_end)):
        if value is not None:
            settings[key] = session_date(value, key).date().isoformat()
    if symbol is not None:
        if settings["mode"] != "timing":
            raise ValueError("--symbol 仅用于单标的择时策略")
        symbol = symbol.strip()
        settings["symbols"] = [symbol]
    prices, source = _load_prices(config, settings, csv_path, demo)
    if symbol is not None:
        prices = prices.loc[prices["symbol"].astype("string").str.strip().eq(symbol)]
        if prices.empty:
            raise ValueError(f"行情中无标的 {symbol}")
    tables = analyze(prices, settings)
    if output_dir:
        destination = Path(output_dir)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = Path(config["project"]["result_dir"]) / "strategy" / profile / stamp
    destination.mkdir(parents=True, exist_ok=False)
    for label, table in tables.items():
        table.to_csv(
            destination / f"{label}.csv",
            index=label not in {"trades", "holdings", "benchmark_trades", "benchmark_holdings"},
            encoding="utf-8-sig",
        )
    panel = tables["factors"].index
    dates = panel.get_level_values("date")
    metadata = {
        "profile": profile,
        "source": source,
        "input_rows": len(panel),
        "symbols": panel.get_level_values("symbol").unique().tolist(),
        "first_date": dates.min().date().isoformat(),
        "last_date": dates.max().date().isoformat(),
        "settings": settings,
    }
    (destination / "run.yaml").write_text(
        yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return destination, tables["metrics"]
