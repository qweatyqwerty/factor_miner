"""轻量级回测引擎（基于向量化信号）."""

import logging
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from .broker import BrokerInterface, Order, PaperBroker

logger = logging.getLogger(__name__)


class BacktestEngine:
    """简单回测引擎.

    输入：
    - price_df: 包含 date, open, high, low, close, volume 列
    - signal_series: 与 price_df 等长的信号序列，>0 做多，<0 做空/平仓

    输出：
    - 资金曲线、交易记录、绩效指标
    """

    def __init__(
        self,
        broker: Optional[BrokerInterface] = None,
        stake_size: int = 100,
        long_only: bool = True,
    ):
        self.broker = broker or PaperBroker()
        self.stake_size = stake_size
        self.long_only = long_only
        self.equity_curve: List[Dict] = []

    def run(
        self,
        df: pd.DataFrame,
        signal: pd.Series,
        price_col: str = "close",
    ) -> pd.DataFrame:
        """运行回测.

        Args:
            df: 行情 DataFrame
            signal: 交易信号序列，正数买入，负数卖出
            price_col: 用于成交的价格列
        """
        df = df.copy()
        df["signal"] = signal
        df["position"] = 0

        current_pos = 0
        symbol = str(df.get("symbol", ["UNKNOWN"]).iloc[0])

        for i, row in df.iterrows():
            dt = row["date"]
            sig = row["signal"]
            price = row[price_col]

            # 简单阈值信号：当前无仓且信号>0则买入；有仓且信号<0则卖出
            if sig > 0 and current_pos == 0:
                trade = self.broker.send_order(
                    Order(
                        symbol=symbol,
                        direction="buy",
                        size=self.stake_size,
                        price=price,
                        datetime=pd.to_datetime(dt),
                    )
                )
                if trade:
                    current_pos = self.stake_size
            elif sig < 0 and current_pos > 0:
                trade = self.broker.send_order(
                    Order(
                        symbol=symbol,
                        direction="sell",
                        size=current_pos,
                        price=price,
                        datetime=pd.to_datetime(dt),
                    )
                )
                if trade:
                    current_pos = 0

            df.at[i, "position"] = current_pos
            equity = self.broker.get_equity({symbol: price})
            self.equity_curve.append(
                {"date": dt, "equity": equity, "position": current_pos}
            )

        equity_df = pd.DataFrame(self.equity_curve)
        df = df.merge(equity_df, on="date", how="left")
        return df

    def metrics(self, df: pd.DataFrame) -> Dict:
        """计算回测绩效指标."""
        equity = df["equity"].dropna()
        returns = equity.pct_change().dropna()

        total_return = equity.iloc[-1] / equity.iloc[0] - 1 if len(equity) > 1 else 0
        annual_return = (1 + total_return) ** (252 / len(equity)) - 1 if len(equity) > 1 else 0
        sharpe = np.sqrt(252) * returns.mean() / returns.std() if returns.std() != 0 else 0
        max_drawdown = ((equity / equity.cummax()) - 1).min()

        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "trades_count": len(self.broker.trades),
            "final_equity": equity.iloc[-1] if len(equity) else 0,
        }

    def trade_summary(self) -> pd.DataFrame:
        """返回交易记录表（如果 broker 支持）."""
        if hasattr(self.broker, "get_trades_df"):
            return self.broker.get_trades_df()
        return pd.DataFrame()
