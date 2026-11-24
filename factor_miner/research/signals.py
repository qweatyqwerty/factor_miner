"""从行情计算因子、组合评分与收盘目标仓位。"""

from collections.abc import Mapping
from math import isfinite

import numpy as np
import pandas as pd

from factor_miner.factors import (
    MACDFactor, MomentumFactor, OBVFactor, RSIFactor, SMACrossFactor, VolatilityFactor,
)

FACTORS = {
    "momentum": MomentumFactor,
    "sma_cross": SMACrossFactor,
    "rsi": RSIFactor,
    "macd": MACDFactor,
    "volatility": VolatilityFactor,
    "obv": OBVFactor,
}


def integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} 必须为不小于 {minimum} 的整数")
    return value


def number(value, name, lower=None, upper=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} 必须为有限数值")
    if (lower is not None and value < lower) or (upper is not None and value > upper):
        raise ValueError(f"{name} 超出允许范围")
    return float(value)


def session_date(value, name):
    date = pd.Timestamp(value)
    if pd.isna(date) or date.tzinfo is not None:
        raise ValueError(f"{name} 需要无时区的交易日期")
    return date.normalize()


def prepare_prices(prices):
    """统一为 date/symbol 唯一索引，保留缺失报价与交易限制。"""
    prices = prices.copy()
    for column in ("date", "symbol", "open", "close"):
        if column not in prices:
            raise ValueError(f"行情缺少 {column} 列")
    prices["date"] = pd.to_datetime(prices["date"], errors="raise").dt.normalize()
    prices["symbol"] = prices["symbol"].astype("string").str.strip()
    if prices.empty or prices[["date", "symbol"]].isna().any().any() or prices["symbol"].eq("").any():
        raise ValueError("行情必须包含有效日期和代码")
    for column in ("open", "close", "settle", "volume"):
        if column not in prices:
            continue
        values = pd.to_numeric(prices[column], errors="raise").astype(float)
        if column == "settle":
            values = values.mask(values.eq(0))  # 本地缓存用 0 表示结算价缺失
        valid = np.isfinite(values) & (values.ge(0) if column == "volume" else values.gt(0))
        if (values.notna() & ~valid).any():
            raise ValueError(f"行情含无效 {column} 数值")
        prices[column] = values
    for column in ("can_buy", "can_sell"):
        if column in prices:
            values = prices[column].astype("string").str.strip().str.lower()
            flags = values.map({
                "true": True, "false": False, "1": True, "0": False, "1.0": True, "0.0": False,
            })
            if (values.notna() & flags.isna()).any():
                raise ValueError(f"{column} 只接受 0/1 或 true/false")
            prices[column] = flags.astype("boolean").fillna(False)
        else:
            prices[column] = True
    prices = prices.set_index(["date", "symbol"])
    if not prices.index.is_unique:
        raise ValueError("行情存在重复的 date/symbol")
    return prices.sort_index()


def _factor_values(prices, definitions):
    if not isinstance(definitions, Mapping) or not definitions:
        raise ValueError("至少配置一个因子")
    local = prices.swaplevel().sort_index()
    raw = pd.DataFrame(index=local.index)
    directions, weights = {}, {}
    for name, spec in definitions.items():
        if not isinstance(name, str) or not name or name == "composite" or not isinstance(spec, Mapping):
            raise ValueError("因子需使用唯一名称和参数映射")
        kind = spec.get("type")
        if kind not in FACTORS:
            raise ValueError(f"未知因子类型 {kind}，可选 {', '.join(FACTORS)}")
        params = spec.get("params", {})
        if not isinstance(params, Mapping):
            raise ValueError(f"{name}.params 必须为参数映射")
        for param, value in params.items():
            integer(value, f"{name}.{param}")
        directions[name] = number(spec.get("direction", 1), f"{name}.direction")
        if abs(directions[name]) != 1:
            raise ValueError(f"{name}.direction 必须为 1 或 -1")
        weights[name] = number(spec.get("weight", 1), f"{name}.weight", 0)
        factor = FACTORS[kind](**params)
        if kind == "sma_cross" and factor.short >= factor.long:
            raise ValueError(f"{name} 的短周期需小于长周期")
        if kind == "macd" and factor.fast >= factor.slow:
            raise ValueError(f"{name} 的快线周期需小于慢线周期")
        if kind == "obv" and ("volume" not in local or local["volume"].isna().any()):
            raise ValueError("OBV 因子需要完整 volume 列")
        computed = []
        for _, data in local.groupby(level="symbol", sort=False):
            close_available = data.loc[data["close"].notna()]
            computed.append(factor(close_available) if len(close_available) else data["close"])
        raw[name] = pd.concat(computed).replace([np.inf, -np.inf], np.nan)
    raw = raw.swaplevel().reindex(prices.index)
    return raw, pd.Series(directions), pd.Series(weights)


def _standardize(oriented, mode, settings):
    method = settings.get("normalization", "rank" if mode == "cross_section" else "zscore")
    if mode == "cross_section":
        grouped = oriented.groupby(level="date", sort=False)
        count = grouped.transform("count")
        if method == "rank":
            scores = 2 * (grouped.rank(method="average") - 1) / (count - 1) - 1
        elif method == "zscore":
            centered = oriented - grouped.transform("mean")
            spread = grouped.transform("std", ddof=0)
            scores = centered.div(spread.mask(spread.eq(0), 1))
        else:
            raise ValueError("截面标准化仅支持 rank 或 zscore")
        min_assets = integer(settings.get("min_assets", 3), "min_assets", 2)
        scores = scores.where(count.ge(min_assets))
    else:
        if method != "zscore":
            raise ValueError("时序标准化使用滚动 zscore")
        window = integer(settings.get("z_window", 30), "z_window", 2)
        history = oriented.shift(1).rolling(window, min_periods=window)
        spread = history.std(ddof=0)
        scores = (oriented - history.mean()).div(spread.where(spread.gt(0)))
        scores = scores.mask(oriented.notna() & spread.eq(0), 0)
    return scores.clip(-3, 3)


def _forward_returns(prices, horizon, market):
    # t 收盘信号，t+1 开盘入场，t+1+h 开盘结束。
    opens = prices["open"]
    entry = opens.where(prices["can_buy"]) if market == "stock" else opens
    exit_ = opens.where(prices["can_sell"]) if market == "stock" else opens
    return exit_.unstack("symbol").shift(-horizon - 1).div(entry.unstack("symbol").shift(-1)).sub(1)


def _correlation(x, y):
    valid = pd.concat([x, y], axis=1).dropna()
    if len(valid) < 2 or valid.iloc[:, 0].nunique() < 2 or valid.iloc[:, 1].nunique() < 2:
        return np.nan
    ranked = valid.rank()
    return ranked.iloc[:, 0].corr(ranked.iloc[:, 1])


def _daily_ic(scores, forward, minimum):
    data = {}
    for name in scores:
        values = scores[name].unstack("symbol").reindex_like(forward)
        paired = values.notna() & forward.notna()
        count = paired.to_numpy().sum(axis=1)
        center = (count[:, None] + 1) / 2
        # 同一因子、同一天先取成对有效值，再对并列项使用平均排名。
        x = np.nan_to_num(values.where(paired).rank(axis=1).to_numpy() - center)
        y = np.nan_to_num(forward.where(paired).rank(axis=1).to_numpy() - center)
        scale = np.divide(1.0, count - 1, out=np.zeros(len(forward)), where=count > 1)
        sx = np.sqrt(np.einsum("ij,ij->i", x, x) * scale)
        sy = np.sqrt(np.einsum("ij,ij->i", y, y) * scale)
        valid = (count >= minimum) & (sx > 0) & (sy > 0)
        ic = np.full(len(forward), np.nan)
        # 与 np.corrcoef 的除法顺序一致，保留组合评分的并列行为。
        np.divide(np.einsum("ij,ij->i", x, y) * scale, sx, out=ic, where=valid)
        np.divide(ic, sy, out=ic, where=valid)
        data[name] = ic.clip(-1, 1)
    return pd.DataFrame(data, index=forward.index)


def combine(prices, settings):
    """返回因子明细、每日权重、截面 Rank IC 与标签。"""
    mode = settings["mode"]
    if mode not in {"cross_section", "timing"}:
        raise ValueError("mode 必须为 cross_section 或 timing")
    if mode == "timing" and prices.index.get_level_values("symbol").nunique() != 1:
        raise ValueError("时序策略仅接受一只标的")
    raw, directions, fixed = _factor_values(prices, settings["factors"])
    method = settings.get("weighting", "equal")
    if method not in {"equal", "fixed", "rolling_ic"}:
        raise ValueError("weighting 必须为 equal、fixed 或 rolling_ic")
    if method == "rolling_ic" and mode != "cross_section":
        raise ValueError("rolling_ic 权重适用于股票截面")
    prior = pd.Series(1.0, index=fixed.index) if method == "equal" else fixed
    if prior.sum() <= 0:
        raise ValueError("因子权重之和必须大于 0")
    prior = prior / prior.sum()
    scores = _standardize(raw * directions, mode, settings)
    horizon = integer(settings.get("forward_period", 1), "forward_period")
    forward = _forward_returns(prices, horizon, settings["market"])
    dates = forward.index
    weights = pd.DataFrame(np.tile(prior, (len(dates), 1)), index=dates, columns=raw.columns)
    ic = pd.DataFrame(index=dates)
    if mode == "cross_section":
        minimum = integer(settings.get("ic_min_assets", 5), "ic_min_assets", 3)
        ic = _daily_ic(scores, forward, minimum)
        if method == "rolling_ic":
            window = integer(settings.get("ic_window", 60), "ic_window")
            samples = integer(settings.get("ic_min_periods", 20), "ic_min_periods")
            if samples > window:
                raise ValueError("ic_min_periods 不能超过 ic_window")
            # 结束开盘价到 t 收盘已经可见，提前 h+1 个交易日的标签才成熟。
            known = ic.shift(horizon + 1).rolling(window, min_periods=samples).mean()
            positive = known.clip(lower=0) * prior
            total = positive.sum(axis=1)
            ready = known.loc[:, prior.gt(0)].notna().all(axis=1) & total.gt(0)
            weights.loc[ready] = positive.loc[ready].div(total.loc[ready], axis=0).fillna(0)
    aligned = weights.reindex(scores.index.get_level_values("date")).set_axis(scores.index)
    valid = (scores.notna() | aligned.eq(0)).all(axis=1)
    score = scores.fillna(0).mul(aligned).sum(axis=1).where(valid & prices["close"].notna())
    detail = pd.concat([raw.add_prefix("raw_"), scores.add_prefix("score_")], axis=1)
    detail["score"] = score
    detail["forward_return"] = forward.stack().reindex(detail.index)
    return detail, weights, ic, forward


def timing_targets(scores, settings, weight):
    """将有滞回的择时分数转换为仓位变更指令。"""
    short = settings.get("allow_short", False)
    if not isinstance(short, bool) or (short and settings["market"] != "future"):
        raise ValueError("allow_short 为布尔值，仅期货可启用")
    entry = number(settings.get("entry", 0.5), "entry", 0, 3)
    exit_ = number(settings.get("exit", 0), "exit", 0 if short else -3, 3)
    if entry <= exit_:
        raise ValueError("entry 必须大于 exit")
    targets = pd.Series(np.nan, index=scores.index, name=scores.name)
    state = None
    for date, value in scores.dropna().items():
        if value >= entry:
            new_state = 1
        elif short and value <= -entry:
            new_state = -1
        elif (state == 1 and value > exit_) or (state == -1 and value < -exit_):
            new_state = state
        else:
            new_state = 0
        if new_state != state:
            targets.loc[date] = new_state * weight
        state = new_state
    return targets


def allocation(detail, forward, settings):
    """目标权重按收盘日期索引，整行 NaN 表示没有新的调仓指令。"""
    score = detail["score"].unstack("symbol").reindex_like(forward)
    targets = pd.DataFrame(np.nan, index=score.index, columns=score.columns)
    benchmark = targets.copy()
    start = session_date(settings.get("evaluation_start") or score.index[0], "evaluation_start")
    eligible = score.loc[start:]
    if eligible.empty:
        raise ValueError("evaluation_start 之后没有行情")
    exposure = number(settings.get("max_exposure", 0.95), "max_exposure", 0, 1)
    cap = number(settings.get("max_weight", exposure), "max_weight", 0, 1)
    if settings["mode"] == "cross_section":
        if settings["market"] != "stock":
            raise ValueError("截面选股策略使用 stock")
        top = integer(settings.get("top_n", 5), "top_n")
        step = integer(settings.get("rebalance_every", 5), "rebalance_every")
        buffer = integer(settings.get("rank_buffer", 0), "rank_buffer", 0)
        minimum = integer(settings.get("min_assets", 3), "min_assets", 2)
        if score.shape[1] < minimum:
            raise ValueError(f"截面策略至少需要 {minimum} 只标的")
        selected = score.columns[:0]
        for date, scores in eligible.iloc[::step].iterrows():
            candidates = scores.dropna().sort_values(ascending=False, kind="stable")
            if len(candidates) < minimum:
                continue
            retained = candidates.index[:top + buffer].intersection(selected, sort=False)
            additions = candidates.index.difference(retained, sort=False)[:top - len(retained)]
            selected = retained.append(additions)
            targets.loc[date] = 0.0
            targets.loc[date, selected] = min(cap, exposure / len(selected))
            benchmark.loc[date] = 0.0
            benchmark.loc[date, candidates.index] = min(cap, exposure / len(candidates))
    else:
        weight = min(cap, exposure)
        scores = eligible.iloc[:, 0]
        targets.loc[eligible.index, scores.name] = timing_targets(scores, settings, weight)
        first_signal = scores.first_valid_index()
        if first_signal is not None:
            benchmark.loc[first_signal] = weight
    if not targets.notna().any().any():
        raise ValueError("回测窗口内没有可用的组合信号，请检查预热长度、覆盖率和调仓周期")
    if not targets.iloc[:-1].notna().any().any():
        raise ValueError("有效信号只出现在末日，缺少次日行情")
    return targets, benchmark, start


def diagnostics(detail, weights, ic, forward, settings, start):
    """输出逐日截面 Rank IC、各因子摘要与组合分组标签统计。"""
    sample = detail.loc[detail.index.get_level_values("date") >= start]
    labels = sample["forward_return"]
    columns = list(weights.columns)
    values = sample[[f"score_{c}" for c in columns] + ["score"]].copy()
    values.columns = columns + ["composite"]
    groups = integer(settings.get("quantiles", 5), "quantiles", 2)
    if settings["mode"] == "cross_section":
        minimum = settings.get("ic_min_assets", 5)
        composite = _daily_ic(detail[["score"]], forward, minimum)
        daily = pd.concat([ic, composite.rename(columns={"score": "composite"})], axis=1).loc[start:]
        summary = daily.agg(["count", "mean", "std"]).T
        summary["icir"] = summary["mean"].div(summary["std"].replace(0, np.nan))
        ranks = sample["score"].where(labels.notna()).groupby(level="date")
        bucket = np.ceil(ranks.rank(pct=True, method="average") * groups)
    else:
        daily = pd.DataFrame(index=pd.DatetimeIndex([], name="date"))
        summary = pd.DataFrame({
            "count": values.where(labels.notna(), axis=0).count(),
            "mean": np.nan,
            "std": np.nan,
            "icir": np.nan,
            "sample_rank_ic": [_correlation(values[c], labels) for c in values],
        })
        bucket = np.ceil(sample["score"].where(labels.notna()).rank(pct=True) * groups)
    summary.index.name = "factor"
    summary["coverage"] = values.notna().mean()
    summary["average_weight"] = weights.loc[start:].mean()
    quantiles = labels.groupby(bucket.rename("quantile")).agg(["mean", "std", "count"])
    return daily, summary, quantiles
