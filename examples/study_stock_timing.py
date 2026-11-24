"""Compare fixed stock strategies on earlier years and on later held-out data."""

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factor_miner.research.signals import allocation, combine, prepare_prices, timing_targets
from factor_miner.research.simulation import metrics, simulate
from factor_miner.utils import load_config
from fetch_stock_study import COHORTS

PERIODS = {
    "development": ("2020-01-01", "2022-12-31"),
    "test": ("2023-01-01", "2025-12-31"),
}
METHODS = (
    "baseline", "wider_exit", "trend_filter", "slower_score",
    "multi_horizon", "multi_horizon_vol", "buy_hold",
)
COSTS = {"commission": 0.0003, "slippage": 0.001, "sell_fee": 0.0005}
TIMING_PROFILES = {
    "baseline": "stock_timing",
    "wider_exit": "stock_timing_wider_exit",
    "slower_score": "stock_timing_slow",
}


def signals(prices, baseline, slower, wider):
    default_scores, *_ = combine(prices, baseline)
    slow_scores, *_ = combine(prices, slower)
    wider_scores, *_ = combine(prices, wider)
    close = prices["close"].droplevel("symbol")
    trend = close.div(close.rolling(120).mean()).sub(1)
    tests = pd.concat([trend, close.pct_change(63), close.pct_change(126)], axis=1)
    votes = tests.gt(0).sum(axis=1).where(tests.notna().all(axis=1))
    annual_vol = close.pct_change().rolling(20).std() * np.sqrt(252)
    return pd.DataFrame({
        "score": default_scores["score"].droplevel("symbol"),
        "slow_score": slow_scores["score"].droplevel("symbol"),
        "wider_score": wider_scores["score"].droplevel("symbol"),
        "trend": trend,
        "votes": votes,
        "volatility": annual_vol,
    })


def targets(features, symbol, method, profiles):
    target = pd.Series(np.nan, index=features.index, name=symbol)
    settings = profiles.get(method, profiles["baseline"])
    max_weight = min(settings.get("max_exposure", 0.95), settings.get("max_weight", 1))
    if method == "buy_hold":
        target.iloc[0] = max_weight
        return target.to_frame()
    if method in {"multi_horizon", "multi_horizon_vol"}:
        schedule = features.iloc[::5].dropna(subset=["votes", "volatility"])
        previous = None
        for date, row in schedule.iterrows():
            holding = row["votes"] >= 2
            size = max_weight
            if method == "multi_horizon_vol" and row["volatility"] > 0:
                size = min(max_weight, 0.20 / row["volatility"])
            desired = size if holding else 0.0
            if previous is None or (desired == 0) != (previous == 0) or abs(desired - previous) >= 0.10:
                target.loc[date] = desired
                previous = desired
        return target.to_frame()

    column = {"slower_score": "slow_score", "wider_exit": "wider_score"}.get(method, "score")
    score = features[column]
    if method == "trend_filter":
        score = score.mask(features["trend"].lt(0) & score.notna(), -np.inf).where(features["trend"].notna())
    return timing_targets(score.rename(symbol), settings, max_weight).to_frame()


def run_sleeve(prices, targets, baseline, cost_multiple):
    cost = {name: rate * cost_multiple for name, rate in COSTS.items()}
    nav, trades, _ = simulate(prices, targets, {**baseline, **cost})
    target_fills = trades.loc[trades["reason"].eq("target")]
    assert target_fills["date"].gt(target_fills["signal_date"]).all()
    assert nav["cash"].ge(-1e-8).all()
    return nav, trades


def pool(sleeves, initial_cash):
    """Aggregate independent accounts with equal initial funding and no cash transfers."""
    dates = pd.DatetimeIndex(
        sorted({date for nav, _ in sleeves for date in nav.index}), name="date",
    )
    result = pd.DataFrame(index=dates)
    for name in ("equity", "cash", "gross_exposure"):
        start = 0 if name == "gross_exposure" else initial_cash
        result[name] = sum(nav[name].reindex(dates).ffill().fillna(start) for nav, _ in sleeves)
    for name in ("commission", "slippage_cost", "traded_notional"):
        result[name] = sum(nav[name].reindex(dates, fill_value=0) for nav, _ in sleeves)
    previous = result["equity"].shift()
    result["daily_return"] = result["equity"].div(previous).sub(1).fillna(0)
    result["turnover"] = result["traded_notional"].div(previous).fillna(0)
    result["drawdown"] = result["equity"].div(result["equity"].cummax()).sub(1)
    result["gross_exposure_ratio"] = result["gross_exposure"].div(result["equity"])
    return result, pd.concat([trades for _, trades in sleeves], ignore_index=True)


def compare(frame, config, periods):
    profiles = {
        method: {**config["backtest"], **config["research"]["profiles"][profile]}
        for method, profile in TIMING_PROFILES.items()
    }
    baseline = profiles["baseline"]
    initial_cash = baseline["initial_cash"]
    prepared = {
        symbol: prepare_prices(rows)
        for symbol, rows in frame.groupby("symbol", sort=True)
    }
    expected = {symbol for cohort in COHORTS.values() for symbol in cohort}
    if set(prepared) != expected:
        raise ValueError(f"Unexpected symbol set: {sorted(set(prepared) ^ expected)}")
    features = {
        symbol: signals(data, baseline, profiles["slower_score"], profiles["wider_exit"])
        for symbol, data in prepared.items()
    }
    rows, portfolios, curves, orders = [], [], [], []

    def run_period(phase, cohorts, multiples):
        first, last = periods[phase]
        chosen = {symbol for cohort in cohorts.values() for symbol in cohort}
        window = {symbol: prepared[symbol].loc[first:last] for symbol in chosen}
        if any(len(data) < 2 for data in window.values()):
            raise ValueError(f"{phase} window lacks two daily bars for at least one stock")
        for method in METHODS:
            placement = {
                symbol: targets(features[symbol].loc[first:last], symbol, method, profiles)
                for symbol in chosen
            }
            for multiple in multiples:
                outcomes = {
                    symbol: run_sleeve(window[symbol], placement[symbol], baseline, multiple)
                    for symbol in sorted(chosen)
                }
                names = {"period": phase, "method": method, "cost_multiple": multiple}
                for symbol, (nav, fills) in outcomes.items():
                    rows.append({**names, "symbol": symbol, **metrics(nav, fills)})
                for cohort, symbols in cohorts.items():
                    nav, fills = pool([outcomes[symbol] for symbol in symbols], initial_cash)
                    portfolios.append({**names, "cohort": cohort, **metrics(nav, fills)})
                    curves.append(nav.reset_index().assign(**names, cohort=cohort))
                orders.extend(fills.assign(**names) for _, fills in outcomes.values())

    run_period("development", {"development": COHORTS["development"]}, (1,))
    selection = max(
        (row for row in portfolios if row["method"] != "buy_hold"),
        key=lambda row: row["total_return"],
    )["method"]

    new_stocks = COHORTS["development"] + COHORTS["unseen_stocks"]
    run_period("test", {**COHORTS, "all_new_stocks": new_stocks}, (1, 2))

    per_stock = pd.DataFrame(rows)
    for comparator in ("baseline", "buy_hold"):
        keys = ["period", "cost_multiple", "symbol"]
        base = per_stock.loc[per_stock["method"].eq(comparator), keys + ["total_return"]]
        difference = f"excess_vs_{comparator}"
        per_stock = per_stock.merge(base.rename(columns={"total_return": difference}), on=keys)
        per_stock[difference] = per_stock["total_return"] - per_stock[difference]

    return selection, {
        "stock_metrics": per_stock,
        "portfolio_metrics": pd.DataFrame(portfolios),
        "portfolio_equity": pd.concat(curves, ignore_index=True),
        "timing_trades": pd.concat(orders, ignore_index=True),
    }


def cross_section_settings(config, test_period):
    settings = {**config["backtest"], **config["research"]["profiles"]["stock_cross_section"]}
    settings["evaluation_start"] = test_period[0]
    symbols = COHORTS["development"] + COHORTS["unseen_stocks"]
    timing = {**config["backtest"], **config["research"]["profiles"]["stock_timing"]}
    settings["initial_cash"] = timing["initial_cash"] * len(symbols)
    settings["symbols"] = list(symbols)
    return {
        "equal": {**settings, "weighting": "equal", "rank_buffer": 0},
        "rolling_ic": {**settings, "weighting": "rolling_ic", "rank_buffer": 0},
        "equal_buffered": {
            **settings, "weighting": "equal",
            "rank_buffer": config["research"]["profiles"]["stock_cross_section_buffered"]["rank_buffer"],
        },
    }


def compare_cross_section(frame, methods):
    basket = prepare_prices(frame.loc[frame["symbol"].isin(methods["equal"]["symbols"])])
    rows, equity = [], []
    scores = {}
    for method, settings in methods.items():
        weighting = settings["weighting"]
        if weighting not in scores:
            detail, _, _, forward = combine(basket, settings)
            scores[weighting] = (detail, forward)
        targets, benchmark, start = allocation(*scores[weighting], settings)
        active = basket.loc[start:]
        for multiple in (1, 2):
            tags = {
                "method": method, "weighting": weighting,
                "rank_buffer": settings["rank_buffer"], "cost_multiple": multiple,
            }
            for portfolio, weights in (("strategy", targets), ("benchmark", benchmark)):
                nav, fills = run_sleeve(active, weights.loc[start:], settings, multiple)
                rows.append({**tags, "portfolio": portfolio, **metrics(nav, fills)})
                equity.append(nav.reset_index().assign(**tags, portfolio=portfolio))
    return {"cross_section_metrics": pd.DataFrame(rows), "cross_section_equity": pd.concat(equity)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--test-start", type=date.fromisoformat, default=PERIODS["test"][0])
    parser.add_argument("--test-end", type=date.fromisoformat, default=PERIODS["test"][1])
    args = parser.parse_args()
    start, end = args.test_start.isoformat(), args.test_end.isoformat()
    if not PERIODS["development"][1] < start < end:
        parser.error("Test dates must follow 2022-12-31 and the end must follow the start")
    if args.output_dir.exists():
        parser.error(f"output directory already exists: {args.output_dir}")
    periods = {**PERIODS, "test": (start, end)}
    frame = pd.read_csv(args.prices, dtype={"symbol": "string"}, parse_dates=["date"])
    frame = frame.loc[frame["date"].between("2019-01-01", end)]
    config = load_config(args.config)
    selection, tables = compare(frame, config, periods)
    cross = cross_section_settings(config, periods["test"])
    tables.update(compare_cross_section(frame, cross))
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, table in tables.items():
        table.to_csv(args.output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "periods": periods, "cohorts": COHORTS, "costs": COSTS, "methods": METHODS,
        "cost_multiples": [1, 2],
        "chosen_on_development": selection, "price_rows": len(frame),
        "supplied_prices_sha256": hashlib.sha256(args.prices.read_bytes()).hexdigest(),
        "backtest": config["backtest"],
        "stock_timing": {
            method: config["research"]["profiles"][profile] for method, profile in TIMING_PROFILES.items()
        },
        "stock_cross_section": cross,
    }
    (args.output_dir / "study.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Chosen using 2020–2022 only: {selection}")
    portfolio = tables["portfolio_metrics"]
    print(portfolio.loc[portfolio["period"].eq("test") & portfolio["cohort"].eq("all_new_stocks"),
                        ["method", "cost_multiple", "total_return", "max_drawdown", "turnover"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
