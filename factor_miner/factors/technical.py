"""常用技术指标因子."""

import numpy as np
import pandas as pd

from .base import Factor


class MomentumFactor(Factor):
    """动量因子：N 日收益率."""

    def __init__(self, window: int = 20):
        super().__init__(f"momentum_{window}")
        self.window = window

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change(self.window)


class SMACrossFactor(Factor):
    """均线交叉因子：短期均线 - 长期均线."""

    def __init__(self, short: int = 5, long: int = 20):
        super().__init__(f"sma_cross_{short}_{long}")
        self.short = short
        self.long = long

    def compute(self, df: pd.DataFrame) -> pd.Series:
        short_sma = df["close"].rolling(self.short).mean()
        long_sma = df["close"].rolling(self.long).mean()
        return short_sma - long_sma


class RSIFactor(Factor):
    """RSI 相对强弱指标因子."""

    def __init__(self, window: int = 14):
        super().__init__(f"rsi_{window}")
        self.window = window

    def compute(self, df: pd.DataFrame) -> pd.Series:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(self.window).mean()
        avg_loss = loss.rolling(self.window).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi


class MACDFactor(Factor):
    """MACD 因子：DIF - DEA."""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__(f"macd_{fast}_{slow}_{signal}")
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ema_fast = df["close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.signal, adjust=False).mean()
        return dif - dea


class VolatilityFactor(Factor):
    """波动率因子：N 日收益率标准差."""

    def __init__(self, window: int = 20):
        super().__init__(f"volatility_{window}")
        self.window = window

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return np.log(df["close"] / df["close"].shift(1)).rolling(self.window).std() * np.sqrt(252)


class OBVFactor(Factor):
    """OBV 能量潮因子."""

    def __init__(self):
        super().__init__("obv")

    def compute(self, df: pd.DataFrame) -> pd.Series:
        sign = np.sign(df["close"].diff()).fillna(0)
        obv = (sign * df["volume"]).cumsum()
        return obv
