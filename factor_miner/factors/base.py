"""因子基类."""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class Factor(ABC):
    """因子基类.

    所有因子需继承此类，并实现 `compute` 方法。
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """计算因子值.

        Args:
            df: 标准行情 DataFrame，必须包含 date, open, high, low, close, volume 列

        Returns:
            Series，索引与 df 对齐
        """
        raise NotImplementedError

    def __call__(self, df: pd.DataFrame) -> pd.Series:
        result = self.compute(df)
        result.name = self.name
        return result
