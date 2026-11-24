"""交易接口层：模拟交易 + 实盘接口适配."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """订单结构."""

    symbol: str
    direction: str  # "buy" / "sell"
    size: int
    price: float
    order_type: str = "market"  # market / limit
    datetime: Optional[datetime] = None  # 订单发生时间


@dataclass
class Trade:
    """成交结构."""

    symbol: str
    direction: str
    size: int
    price: float          # 实际成交价（已含滑点）
    commission: float = 0.0
    datetime: Optional[datetime] = None  # 成交时间
    order_price: float = 0.0             # 下单时价格（未含滑点）
    pnl: Optional[float] = None          # 本次平仓盈亏（卖出时记录）

    def __repr__(self) -> str:
        dt = self.datetime.strftime("%Y-%m-%d") if self.datetime else "N/A"
        return (
            f"Trade({dt} {self.symbol} {self.direction.upper()} "
            f"size={self.size} price={self.price:.4f} commission={self.commission:.4f})"
        )


class BrokerInterface(ABC):
    """交易接口抽象基类."""

    @abstractmethod
    def send_order(self, order: Order) -> Optional[Trade]:
        raise NotImplementedError

    @abstractmethod
    def get_position(self, symbol: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def get_cash(self) -> float:
        raise NotImplementedError

    @abstractmethod
    def get_equity(self, prices: Dict[str, float]) -> float:
        raise NotImplementedError


class PaperBroker(BrokerInterface):
    """模拟交易账户.

    适合无门槛快速验证策略，支持股票和期货风格的仓位记录。
    成交记录包含：时间、代码、方向、成交量、成交价（含滑点）、手续费、平仓盈亏。
    """

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        commission: float = 0.0003,
        slippage: float = 0.001,
        sell_fee: float = 0.0,
    ):
        self.cash = initial_cash
        self.commission_rate = commission
        self.slippage = slippage
        self.sell_fee = sell_fee
        self.positions: Dict[str, int] = {}
        self.trades: List[Trade] = []
        self._cost_basis: Dict[str, float] = {}  # 记录持仓成本，用于计算平仓盈亏

    def send_order(self, order: Order) -> Optional[Trade]:
        """发送订单并模拟成交."""
        # 买入按卖一价成交（加价），卖出按买一价成交（降价）
        if order.direction == "buy":
            exec_price = order.price * (1 + self.slippage)
        else:
            exec_price = order.price * (1 - self.slippage)

        amount = exec_price * order.size
        commission = amount * (
            self.commission_rate + (self.sell_fee if order.direction == "sell" else 0.0)
        )

        if order.direction == "buy":
            total_cost = amount + commission
            if total_cost > self.cash:
                logger.warning(
                    "[%s] 资金不足，无法买入 %s %s 股，需要 %.2f，可用 %.2f",
                    order.datetime, order.symbol, order.size, total_cost, self.cash
                )
                return None
            self.cash -= total_cost
            old_size = self.positions.get(order.symbol, 0)
            old_cost = self._cost_basis.get(order.symbol, 0.0)
            new_size = old_size + order.size
            # 更新持仓成本（加权平均）
            self._cost_basis[order.symbol] = (
                (old_cost * old_size + exec_price * order.size) / new_size if new_size > 0 else 0.0
            )
            self.positions[order.symbol] = new_size
            pnl = None
        else:
            if self.positions.get(order.symbol, 0) < order.size:
                logger.warning(
                    "[%s] 仓位不足，无法卖出 %s %s 股，持仓 %s",
                    order.datetime, order.symbol, order.size, self.positions.get(order.symbol, 0)
                )
                return None
            self.cash += amount - commission
            self.positions[order.symbol] -= order.size
            cost_basis = self._cost_basis.get(order.symbol, exec_price)
            pnl = (exec_price - cost_basis) * order.size - commission
            if self.positions[order.symbol] == 0:
                self._cost_basis[order.symbol] = 0.0

        trade = Trade(
            symbol=order.symbol,
            direction=order.direction,
            size=order.size,
            price=exec_price,
            commission=commission,
            datetime=order.datetime,
            order_price=order.price,
            pnl=pnl,
        )
        self.trades.append(trade)
        logger.info("模拟成交: %s", trade)
        return trade

    def get_position(self, symbol: str) -> int:
        return self.positions.get(symbol, 0)

    def get_cash(self) -> float:
        return self.cash

    def get_equity(self, prices: Dict[str, float]) -> float:
        equity = self.cash
        for sym, size in self.positions.items():
            equity += size * prices.get(sym, 0)
        return equity

    def get_trades_df(self) -> pd.DataFrame:
        """返回交易记录 DataFrame，方便查看和验证."""
        if not self.trades:
            return pd.DataFrame()
        records = []
        for t in self.trades:
            records.append({
                "datetime": t.datetime,
                "symbol": t.symbol,
                "direction": t.direction,
                "size": t.size,
                "order_price": t.order_price,
                "exec_price": t.price,
                "slippage": t.price - t.order_price if t.direction == "buy" else t.order_price - t.price,
                "commission": t.commission,
                "pnl": t.pnl,
            })
        df = pd.DataFrame(records)
        if not df.empty and "datetime" in df.columns:
            df = df.sort_values("datetime").reset_index(drop=True)
        return df

    def reset(self):
        self.cash = 0
        self.positions.clear()
        self.trades.clear()
        self._cost_basis.clear()


class RealBrokerInterface(BrokerInterface):
    """实盘交易接口适配层（需接入真实柜台）.

    目前仅作为接口占位，实际接入需要：
    - 股票：QMT / 迅投 XtQuant / 同花顺 iFinD
    - 期货：CTP（vnpy / openctp）

    接入方式示例：
    1. 股票 QMT：安装 xtquant，调用 XtQuantAPI
    2. 期货 CTP：使用 vnpy 的 CtpGateway 或 openctp-ctp
    """

    def __init__(self, config: dict):
        self.config = config
        self.positions: Dict[str, int] = {}
        self.cash = 0.0
        self._gateway = None

    def connect(self):
        """连接实盘柜台，需在子类中实现."""
        logger.info("连接实盘柜台: %s", self.config.get("broker"))
        raise NotImplementedError("实盘接口需根据具体柜台实现")

    def send_order(self, order: Order) -> Optional[Trade]:
        raise NotImplementedError("实盘接口需根据具体柜台实现")

    def get_position(self, symbol: str) -> int:
        return self.positions.get(symbol, 0)

    def get_cash(self) -> float:
        return self.cash

    def get_equity(self, prices: Dict[str, float]) -> float:
        equity = self.cash
        for sym, size in self.positions.items():
            equity += size * prices.get(sym, 0)
        return equity
