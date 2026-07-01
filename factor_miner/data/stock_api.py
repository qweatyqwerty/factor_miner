"""股票数据获取接口（基于 akshare）."""

import csv
import logging
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


class StockAPI:
    """股票行情数据接口.

    支持：
    - A 股历史 K 线（日线/周线）
    - 实时行情快照
    - 个股基本信息
    """

    def __init__(self, cache_dir: str = "./data"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_daily(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """获取日线行情.

        Args:
            symbol: 股票代码，如 "000001"
            start_date: 开始日期，如 "20230101"
            end_date: 结束日期，如 "20231231"
            adjust: 复权类型，qfq 前复权 / hfq 后复权 / 不复权
            use_cache: 是否使用本地缓存

        Returns:
            DataFrame，列：date, open, high, low, close, volume, amount, amplitude, pct_change, change_amount, turnover
        """
        cache_file = self.cache_dir / f"stock_{symbol}_{start_date}_{end_date}_{adjust}.csv"
        if use_cache and cache_file.exists():
            logger.info("读取缓存: %s", cache_file)
            df = pd.read_csv(
                cache_file,
                parse_dates=["date"],
                encoding="utf-8-sig",
                dtype={"symbol": str},
            )
            if "symbol" in df.columns:
                df["symbol"] = df["symbol"].str.zfill(6)
            return df

        logger.info("从 akshare 下载股票 %s 日线数据", symbol)
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        # 统一列名（适配 akshare 中文列名）
        rename_map = {
            "日期": "date",
            "股票代码": "symbol",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "振幅": "amplitude",
            "涨跌幅": "pct_change",
            "涨跌额": "change_amount",
            "换手率": "turnover",
        }
        df = df.rename(columns=rename_map)
        # 兜底：英文列名转小写
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].astype(str).str.zfill(6)

        if use_cache:
            # quoting=QUOTE_NONNUMERIC 会让字符串列带引号保存，避免 symbol 前导零丢失
            df.to_csv(
                cache_file,
                index=False,
                encoding="utf-8-sig",
                quoting=csv.QUOTE_NONNUMERIC,
            )
            logger.info("保存缓存: %s", cache_file)
        return df

    def get_realtime_quote(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """获取实时行情快照.

        Args:
            symbol: 股票代码，None 则返回全部 A 股快照
        """
        logger.info("获取 A 股实时行情快照")
        df = ak.stock_zh_a_spot_em()
        if symbol:
            df = df[df["代码"] == symbol]
        return df

    def get_stock_list(self) -> pd.DataFrame:
        """获取 A 股股票列表."""
        return ak.stock_zh_a_spot_em()
