"""期货因子计算示例."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from factor_miner.data import FutureAPI
from factor_miner.factors import MomentumFactor, SMACrossFactor, VolatilityFactor
from factor_miner.utils import load_config, setup_logging

logger = setup_logging("INFO")


def main():
    config = load_config("config.yaml")
    future_cfg = config["future"]

    # 1. 获取期货日线数据
    api = FutureAPI(cache_dir=config["project"]["data_dir"])
    try:
        df = api.get_daily(
            symbol=future_cfg["default_symbol"],
            start_date=future_cfg["start_date"],
            end_date=future_cfg["end_date"],
        )
    except Exception as e:
        logger.error(
            "获取期货 %s 失败，可能是合约已过期，尝试获取主力连续合约: %s",
            future_cfg["default_symbol"],
            e,
        )
        # 尝试获取螺纹钢主力连续 RB0
        df = api.get_main_contract_history(
            variety="RB",
            start_date=future_cfg["start_date"],
            end_date=future_cfg["end_date"],
        )

    logger.info("获取期货数据，共 %s 行", len(df))

    # 2. 计算因子
    df["momentum_10"] = MomentumFactor(window=10)(df)
    df["sma_cross_5_20"] = SMACrossFactor(short=5, long=20)(df)
    df["volatility_20"] = VolatilityFactor(window=20)(df)

    print("\n===== 期货因子示例 =====")
    print(df[["date", "open", "high", "low", "close", "momentum_10", "sma_cross_5_20", "volatility_20"]].tail(10).to_string(index=False))


if __name__ == "__main__":
    main()
