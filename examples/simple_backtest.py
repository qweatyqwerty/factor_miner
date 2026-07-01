"""简单均线策略回测示例（带详细交易记录）."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

from factor_miner.data import StockAPI
from factor_miner.engine import BacktestEngine, PaperBroker
from factor_miner.factors import SMACrossFactor
from factor_miner.utils import load_config, setup_logging

logger = setup_logging("INFO")


def main():
    config = load_config("config.yaml")
    stock_cfg = config["stock"]
    bt_cfg = config["backtest"]

    # 1. 加载数据
    api = StockAPI(cache_dir=config["project"]["data_dir"])
    df = api.get_daily(
        symbol=stock_cfg["default_symbol"],
        start_date=stock_cfg["start_date"],
        end_date=stock_cfg["end_date"],
        adjust=stock_cfg.get("adjust", "qfq"),
    )
    logger.info("加载 %s 数据，共 %d 行", stock_cfg["default_symbol"], len(df))

    # 2. 生成信号：5日线上穿20日线买入，下穿卖出
    factor = SMACrossFactor(short=5, long=20)
    df["sma_cross"] = factor(df)
    df["signal"] = np.where(df["sma_cross"] > 0, 1, -1)

    # 3. 回测
    broker = PaperBroker(
        initial_cash=bt_cfg["initial_cash"],
        commission=bt_cfg["commission"],
        slippage=bt_cfg["slippage"],
    )
    engine = BacktestEngine(broker=broker, stake_size=bt_cfg["stake_size"])
    result = engine.run(df, df["signal"])
    metrics = engine.metrics(result)

    # 4. 输出交易记录（便于验证正确性）
    trades_df = engine.trade_summary()
    print("\n===== 交易记录 =====")
    if trades_df.empty:
        print("无交易")
    else:
        # 格式化浮点数，方便阅读
        fmt_cols = ["order_price", "exec_price", "slippage", "commission", "pnl"]
        display = trades_df.copy()
        for c in fmt_cols:
            if c in display.columns:
                display[c] = display[c].apply(lambda x: f"{x:.4f}" if pd.notna(x) else "")
        print(display.to_string(index=False))

    print("\n===== 回测绩效 =====")
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"{k}: {v:.6f}")
        else:
            print(f"{k}: {v}")

    # 5. 保存结果
    result_dir = Path(config["project"]["result_dir"])
    result_dir.mkdir(parents=True, exist_ok=True)
    result_file = result_dir / "backtest_result.csv"
    result.to_csv(result_file, index=False)
    logger.info("回测结果已保存: %s", result_file)

    trades_file = result_dir / "trades.csv"
    trades_df.to_csv(trades_file, index=False)
    logger.info("交易记录已保存: %s", trades_file)


if __name__ == "__main__":
    import pandas as pd

    main()
