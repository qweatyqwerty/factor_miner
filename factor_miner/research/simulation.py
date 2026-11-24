"""以次日开盘执行目标权重，记录实际成交、成本和日终估值。"""

from math import floor

import numpy as np
import pandas as pd

from factor_miner.engine.broker import Order, PaperBroker

from .signals import integer, number

TRADE_COLUMNS = [
    "date", "signal_date", "symbol", "side", "size", "open_price", "fill_price",
    "notional", "commission", "slippage_cost", "reason",
]
HOLDING_COLUMNS = ["date", "symbol", "quantity", "mark", "exposure"]


def _daily_row(date, equity, cash, exposure, margin, trades):
    return {
        "date": date,
        "equity": equity,
        "cash": cash,
        "gross_exposure": exposure,
        "margin_used": margin,
        "traded_notional": sum(trade["notional"] for trade in trades),
        "commission": sum(trade["commission"] for trade in trades),
        "slippage_cost": sum(trade["slippage_cost"] for trade in trades),
    }


def _frames(daily, fills, holdings):
    nav = pd.DataFrame(daily).set_index("date")
    previous = nav["equity"].shift(1).where(lambda values: values.gt(0))
    nav["daily_return"] = nav["equity"].div(previous).sub(1)
    nav["turnover"] = nav["traded_notional"].div(previous)
    nav["gross_exposure_ratio"] = nav["gross_exposure"].div(nav["equity"].where(nav["equity"].gt(0)))
    nav.iloc[0, nav.columns.get_indexer(["daily_return", "turnover"])] = 0.0
    nav["drawdown"] = nav["equity"].div(nav["equity"].cummax()).sub(1)
    return (
        nav,
        pd.DataFrame(fills, columns=TRADE_COLUMNS),
        pd.DataFrame(holdings, columns=HOLDING_COLUMNS),
    )


def _trade_row(date, signal_date, symbol, side, size, opening, fill, fee, multiplier, reason):
    return {
        "date": date,
        "signal_date": signal_date,
        "symbol": symbol,
        "side": side,
        "size": size,
        "open_price": opening,
        "fill_price": fill,
        "notional": size * fill * multiplier,
        "commission": fee,
        "slippage_cost": size * abs(fill - opening) * multiplier,
        "reason": reason,
    }


def _stock(prices, targets, settings, cash, commission, slippage):
    sell_fee = number(settings.get("sell_fee", 0), "sell_fee", 0, 0.1)
    lot = integer(settings.get("lot_size", 100), "lot_size")
    broker = PaperBroker(cash, commission, slippage, sell_fee=sell_fee)
    marks, pending = {}, {}
    daily, fills, holdings = [], [], []
    by_date = dict(tuple(prices.groupby(level="date", sort=False)))
    signal_date = None
    target_exposure = 0.0
    for date, target in targets.iterrows():
        market = by_date[date].droplevel("date")
        opens = market["open"].dropna().to_dict()
        marks.update(opens)
        open_equity = broker.get_equity(marks)
        buys, sells = [], []
        for symbol in sorted(pending.keys() & opens.keys()):
            current = broker.get_position(symbol)
            weight = pending[symbol]
            quantity = lot * floor(open_equity * weight / (opens[symbol] * lot))
            delta = quantity - current
            if delta > 0 and market.at[symbol, "can_buy"]:
                buys.append((symbol, delta))
            elif delta < 0 and market.at[symbol, "can_sell"]:
                sells.append((symbol, -delta))
            elif delta != 0:
                continue
            del pending[symbol]

        def send(symbol, side, size):
            trade = broker.send_order(Order(symbol, side, size, opens[symbol], datetime=date))
            if trade is None:
                raise RuntimeError(f"模拟账户拒绝已校验订单: {date.date()} {symbol} {side} {size}")
            return _trade_row(
                date, signal_date, symbol, side, size, opens[symbol], trade.price,
                trade.commission, 1, "target",
            )

        today = [send(symbol, "sell", size) for symbol, size in sells]
        buy_multiplier = (1 + slippage) * (1 + commission)
        total_cost = sum(size * opens[symbol] * buy_multiplier for symbol, size in buys)
        invested = broker.get_equity(marks) - broker.get_cash()
        headroom = max(0, open_equity * target_exposure - invested)
        available = min(broker.get_cash(), headroom * buy_multiplier)
        scale = min(1, available / total_cost) if total_cost > 0 else 0
        for symbol, size in buys:
            per_lot = opens[symbol] * lot * buy_multiplier
            desired_lots = floor(size * scale / lot)
            affordable_lots = floor(broker.get_cash() / per_lot)
            size = lot * min(desired_lots, affordable_lots)
            if size > 0:
                today.append(send(symbol, "buy", size))

        marks.update(market["close"].dropna().to_dict())
        equity = broker.get_equity(marks)
        exposure = 0.0
        for symbol, quantity in broker.positions.items():
            if quantity:
                value = quantity * marks[symbol]
                exposure += value
                holdings.append((date, symbol, quantity, marks[symbol], value))
        daily.append(_daily_row(date, equity, broker.get_cash(), exposure, 0, today))
        fills.extend(today)
        if target.notna().any():
            pending = target.dropna().to_dict()
            target_exposure = sum(pending.values())
            signal_date = date
    return _frames(daily, fills, holdings)


def _future(prices, targets, settings, cash, commission, slippage):
    multiplier = number(settings["contract_multiplier"], "contract_multiplier", 0.000001)
    margin_rate = number(settings["margin_rate"], "margin_rate", 0.000001, 1)
    max_contracts = integer(settings.get("max_contracts", 10), "max_contracts")
    fee_per_contract = number(settings.get("fee_per_contract", 0), "fee_per_contract", 0)
    if targets.shape[1] != 1:
        raise ValueError("期货模拟只接受单合约")
    symbol = targets.columns[0]
    market = prices.droplevel("symbol")
    daily, fills, holdings = [], [], []
    settlement = None
    position = 0
    pending = signal_date = margin_call = None
    for date, target in targets.iterrows():
        bar = market.loc[date]
        opening = bar["open"]
        mark = bar.get("settle", np.nan)
        if pd.isna(mark):
            mark = bar["close"] if pd.notna(bar["close"]) else opening
        if pd.isna(mark):
            mark = settlement

        today = []
        if pd.notna(opening):
            open_equity = cash + position * multiplier * (opening - settlement) if position else cash
            required = abs(position) * opening * multiplier * margin_rate
            if position and open_equity < required and margin_call is None:
                margin_call = date
            if margin_call is not None or pending is not None:
                forced = margin_call is not None
                fee_bound = opening * multiplier * ((1 + slippage) * commission + slippage)
                fee_bound += fee_per_contract
                per_contract = opening * multiplier
                max_by_margin = floor(max(0, open_equity - abs(position) * fee_bound)
                                      / (per_contract * margin_rate + fee_bound))
                if forced:
                    desired = 0
                else:
                    desired = int(np.sign(pending)) * min(
                        floor(max(0, open_equity) * abs(pending) / per_contract),
                        max_by_margin, max_contracts,
                    )
                delta = desired - position
                side = "buy" if delta > 0 else "sell"
                if delta and bar[f"can_{side}"]:
                    size = abs(delta)
                    fill = opening * (1 + slippage if delta > 0 else 1 - slippage)
                    fee = size * (fill * multiplier * commission + fee_per_contract)
                    cash += position * multiplier * (opening - settlement) if position else 0
                    cash += delta * multiplier * (opening - fill) - fee
                    position = desired
                    settlement = opening
                    today.append(_trade_row(
                        date, margin_call if forced else signal_date, symbol, side, size, opening,
                        fill, fee, multiplier, "margin" if forced else "target",
                    ))
                if not delta or today:
                    pending = margin_call = None

        exposure = 0.0
        if position:
            cash += position * multiplier * (mark - settlement)
            exposure = abs(position) * mark * multiplier
            holdings.append((date, symbol, position, mark, position * mark * multiplier))
        settlement = mark
        margin = exposure * margin_rate
        daily.append(_daily_row(date, cash, cash - margin, exposure, margin, today))
        fills.extend(today)
        if position and cash < margin and margin_call is None:
            margin_call = date
        if target.notna().any() and margin_call is None:
            pending = target.iloc[0]
            signal_date = date
    return _frames(daily, fills, holdings)


def simulate(prices, targets, settings):
    """每次使用独立模拟账户，可重复运行同一输入。"""
    cash = number(settings.get("initial_cash", 1_000_000), "initial_cash", 0.01)
    commission = number(settings.get("commission", 0.0003), "commission", 0, 0.1)
    slippage = number(settings.get("slippage", 0.001), "slippage", 0, 0.1)
    market = settings["market"]
    if market == "stock":
        return _stock(prices, targets, settings, cash, commission, slippage)
    if market == "future":
        return _future(prices, targets, settings, cash, commission, slippage)
    raise ValueError("market 必须为 stock 或 future")


def metrics(nav, trades, annualization=252):
    """以起始资金为基准；Sharpe 使用零无风险利率。"""
    frequency = integer(annualization, "annualization")
    return_ratio = nav["equity"].iloc[-1] / nav["equity"].iloc[0]
    sample = nav["daily_return"].iloc[1:].dropna()
    volatility = sample.std()
    periods = len(nav) - 1
    return {
        "sessions": len(nav),
        "initial_equity": nav["equity"].iloc[0],
        "final_equity": nav["equity"].iloc[-1],
        "total_return": return_ratio - 1,
        "annual_return": return_ratio ** (frequency / periods) - 1
        if periods and return_ratio >= 0 else np.nan,
        "annual_volatility": volatility * np.sqrt(frequency),
        "sharpe": sample.mean() / volatility * np.sqrt(frequency) if volatility > 0 else np.nan,
        "max_drawdown": nav["drawdown"].min(),
        "avg_gross_exposure": nav["gross_exposure_ratio"].mean(),
        "turnover": nav["turnover"].sum(),
        "trades": len(trades),
        "commission": nav["commission"].sum(),
        "slippage_cost": nav["slippage_cost"].sum(),
    }
