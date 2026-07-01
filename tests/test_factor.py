"""因子计算单元测试."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from factor_miner.factors import MomentumFactor, RSIFactor, SMACrossFactor


def make_sample_df(n: int = 100) -> pd.DataFrame:
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    price = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame(
        {
            "date": dates,
            "open": price * 0.99,
            "high": price * 1.02,
            "low": price * 0.98,
            "close": price,
            "volume": np.random.randint(1000, 10000, n),
        }
    )
    return df


def test_momentum():
    df = make_sample_df()
    factor = MomentumFactor(window=5)
    s = factor(df)
    assert len(s) == len(df)
    assert s.iloc[:5].isna().all()
    assert not s.iloc[6:].isna().any()


def test_sma_cross():
    df = make_sample_df()
    factor = SMACrossFactor(short=5, long=20)
    s = factor(df)
    assert len(s) == len(df)
    # 前 (long-1)=19 个因为长期均线未就绪而为 NaN
    assert s.iloc[:19].isna().all()


def test_rsi():
    df = make_sample_df()
    factor = RSIFactor(window=14)
    s = factor(df)
    assert len(s) == len(df)
    assert s.min() >= 0
    assert s.max() <= 100


if __name__ == "__main__":
    test_momentum()
    test_sma_cross()
    test_rsi()
    print("所有测试通过")
