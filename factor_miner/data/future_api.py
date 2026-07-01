"""期货数据获取接口（基于 akshare）."""

import logging
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


class FutureAPI:
    """期货行情数据接口.

    支持：
    - 期货历史日线行情
    - 期货主力合约列表
    - 期货实时行情快照
    """

    def __init__(self, cache_dir: str = "./data"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_daily(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """获取期货日线行情.

        Args:
            symbol: 合约代码，如 "RB2501"
            start_date: 开始日期，如 "20240101"
            end_date: 结束日期，如 "20241231"
            use_cache: 是否使用本地缓存

        Returns:
            DataFrame，列：date, open, high, low, close, volume, hold, settle 等
        """
        cache_file = self.cache_dir / f"future_{symbol}_{start_date}_{end_date}.csv"
        if use_cache and cache_file.exists():
            logger.info("读取缓存: %s", cache_file)
            df = pd.read_csv(cache_file, parse_dates=["date"], encoding="utf-8-sig")
            return df

        logger.info("从 akshare 下载期货 %s 日线数据", symbol)
        # 日线数据接口
        df = ak.futures_zh_daily_sina(symbol=symbol)

        # 过滤日期
        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

        # 列名统一（兼容中文列名）
        rename_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "持仓量": "hold",
            "结算价": "settle",
        }
        df = df.rename(columns=rename_map)
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        if use_cache:
            df.to_csv(cache_file, index=False, encoding="utf-8-sig")
            logger.info("保存缓存: %s", cache_file)
        return df

    def get_main_contracts(self, exchange: Optional[str] = None) -> pd.DataFrame:
        """获取期货主力合约列表.

        Args:
            exchange: 交易所简称，如 "dce", "shfe", "czce", "cffex"
        """
        logger.info("获取期货主力合约列表")
        df = ak.futures_zh_realtime(exchange=exchange or "国内期货")
        return df

    def get_realtime_quote(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """获取期货实时行情快照."""
        logger.info("获取期货实时行情快照")
        df = ak.futures_zh_realtime(exchange="国内期货")
        if symbol:
            df = df[df["symbol"] == symbol]
        return df

    def get_main_contract_history(
        self,
        variety: str,
        start_date: str,
        end_date: str,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """获取期货品种主力连续合约历史行情（基于 akshare 连续合约接口）.

        Args:
            variety: 品种代码，如 "RB"
        """
        cache_file = self.cache_dir / f"future_main_{variety}_{start_date}_{end_date}.csv"
        if use_cache and cache_file.exists():
            logger.info("读取缓存: %s", cache_file)
            return pd.read_csv(cache_file, parse_dates=["date"])

        logger.info("从 akshare 下载期货主力连续 %s 数据", variety)
        # 例如螺纹钢主力连续为 "RB0"
        df = ak.futures_zh_daily_sina(symbol=f"{variety}0")
        df["date"] = pd.to_datetime(df["date"])
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

        if use_cache:
            df.to_csv(cache_file, index=False)
            logger.info("保存缓存: %s", cache_file)
        return df
