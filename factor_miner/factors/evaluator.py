"""因子评价工具：IC、IR、分组收益等."""

from typing import List, Optional

import numpy as np
import pandas as pd


class FactorEvaluator:
    """因子评价器."""

    def __init__(self, df: pd.DataFrame):
        """Args:
            df: 包含因子列和未来收益列的 DataFrame
        """
        self.df = df.copy()

    def add_forward_return(self, forward_period: int = 1, price_col: str = "close") -> pd.DataFrame:
        """添加未来收益率列."""
        self.df[f"fwd_return_{forward_period}"] = (
            self.df[price_col].shift(-forward_period) / self.df[price_col] - 1
        )
        return self.df

    def ic_analysis(self, factor_col: str, forward_col: str = "fwd_return_1") -> dict:
        """计算因子 IC 和 Rank IC."""
        valid = self.df[[factor_col, forward_col]].dropna()
        ic = valid[factor_col].corr(valid[forward_col])
        rank_ic = valid[factor_col].corr(valid[forward_col], method="spearman")
        return {
            "IC": ic,
            "RankIC": rank_ic,
            "IC_mean": ic,
            "RankIC_mean": rank_ic,
        }

    def quantile_return(
        self,
        factor_col: str,
        forward_col: str = "fwd_return_1",
        n_quantiles: int = 5,
    ) -> pd.DataFrame:
        """按因子分层后的未来收益."""
        df = self.df[[factor_col, forward_col]].dropna()
        df["group"] = pd.qcut(df[factor_col], n_quantiles, labels=False, duplicates="drop")
        return df.groupby("group")[forward_col].agg(["mean", "std", "count"])

    def summary(self, factor_cols: List[str], forward_periods: List[int] = [1, 5, 10]) -> pd.DataFrame:
        """对多个因子、多个未来收益周期生成评价摘要."""
        rows = []
        for fp in forward_periods:
            fwd_col = f"fwd_return_{fp}"
            self.add_forward_return(forward_period=fp)
            for fc in factor_cols:
                stats = self.ic_analysis(fc, fwd_col)
                rows.append(
                    {
                        "factor": fc,
                        "forward_period": fp,
                        **stats,
                    }
                )
        return pd.DataFrame(rows)
