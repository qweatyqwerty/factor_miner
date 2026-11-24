"""Download Sina daily bars and apply its adjustment factors via AkShare."""

import argparse
from datetime import date
from pathlib import Path
from time import sleep

import pandas as pd
import requests

COHORTS = {
    "reference": ("000001",),
    "development": ("600036", "600519", "000333", "600900", "600276"),
    "unseen_stocks": ("000858", "000651", "601088", "300750", "002594", "601318"),
}
FIRST_DATE = "20190101"
DEFAULT_END = date(2025, 12, 31)


def download(code, adjustment, end_date):
    import akshare as ak

    for attempt in range(3):
        try:
            return ak.stock_zh_a_daily(code, FIRST_DATE, end_date.strftime("%Y%m%d"), adjust=adjustment)
        except (requests.RequestException, ValueError, KeyError):
            if attempt == 2:
                raise
            sleep(attempt + 1)


def fetch_symbol(symbol, end_date):
    code = ("sh" if symbol.startswith("6") else "sz") + symbol
    bars = download(code, "", end_date)
    factors = download(code, "hfq-factor", end_date)
    for frame in (bars, factors):
        frame["date"] = pd.to_datetime(frame["date"]).astype("datetime64[ns]")
        frame.sort_values("date", inplace=True)
    data = pd.merge_asof(bars, factors, on="date", direction="backward")
    first, last = pd.Timestamp(FIRST_DATE), pd.Timestamp(end_date)
    data = data.loc[data["date"].between(first, last)].copy()
    minimum = len(pd.bdate_range(first, last)) * 0.85
    if (data.empty or data["date"].duplicated().any() or len(data) < minimum
            or data["date"].max() < last - pd.Timedelta(days=10)):
        raise ValueError(f"{symbol} incomplete or duplicate history ({len(data)} rows)")
    prices = ["open", "close", "high", "low"]
    factor = pd.to_numeric(data["hfq_factor"], errors="raise")
    if not data[prices].gt(0).all().all() or not factor.gt(0).all():
        raise ValueError(f"{symbol} contains a missing or nonpositive price or adjustment factor")
    data["raw_open"] = data["open"]
    data["raw_close"] = data["close"]
    data["adjustment_factor"] = factor.div(factor.iloc[0])
    data[prices] = data[prices].mul(data["adjustment_factor"], axis=0)
    data["symbol"] = symbol
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, default=DEFAULT_END)
    args = parser.parse_args()
    if pd.Timestamp(args.end_date) < pd.Timestamp(FIRST_DATE):
        parser.error("--end-date must be on or after 2019-01-01")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    symbols = [symbol for cohort in COHORTS.values() for symbol in cohort]
    frames = []
    for symbol in symbols:
        frame = fetch_symbol(symbol, args.end_date)
        print(f"{symbol}: {len(frame)} rows", flush=True)
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    columns = [
        "date", "symbol", "open", "high", "low", "close", "volume",
        "raw_open", "raw_close", "adjustment_factor",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result[columns].to_csv(args.output, index=False, encoding="utf-8-sig", float_format="%.10f")
    print(result.groupby("symbol")["date"].agg(["min", "max", "size"]).to_string())


if __name__ == "__main__":
    main()
