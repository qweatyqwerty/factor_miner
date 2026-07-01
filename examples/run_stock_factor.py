"""股票因子计算示例."""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from factor_miner.data import StockAPI
from factor_miner.factors import (
    MACDFactor,
    MomentumFactor,
    RSIFactor,
    SMACrossFactor,
    VolatilityFactor,
)
from factor_miner.factors.evaluator import FactorEvaluator
from factor_miner.utils import load_config, setup_logging

logger = setup_logging("INFO")


def main():
    config = load_config("config.yaml")
    stock_cfg = config["stock"]

    # 1. 获取股票日线数据
    api = StockAPI(cache_dir=config["project"]["data_dir"])
    df = api.get_daily(
        symbol=stock_cfg["default_symbol"],
        start_date=stock_cfg["start_date"],
        end_date=stock_cfg["end_date"],
        adjust=stock_cfg.get("adjust", "qfq"),
    )
    logger.info("获取 %s 日线数据，共 %s 行", stock_cfg["default_symbol"], len(df))

    # 2. 计算多个因子
    factors = [
        MomentumFactor(window=20),
        SMACrossFactor(short=5, long=20),
        RSIFactor(window=14),
        MACDFactor(),
        VolatilityFactor(window=20),
    ]
    factor_names = []
    for f in factors:
        df[f.name] = f(df)
        factor_names.append(f.name)

    # 3. 因子评价
    evaluator = FactorEvaluator(df)
    summary = evaluator.summary(factor_names, forward_periods=[1, 5, 10])
    print("\n===== 因子 IC 评价 =====")
    print(summary.to_string(index=False))

    print("\n===== 最新因子值 =====")
    print(df[["date", "close"] + factor_names].tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
