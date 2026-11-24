"""统一入口脚本."""

import argparse
import numpy as np

from factor_miner.engine import BacktestEngine, PaperBroker
from factor_miner.factors import (
    MomentumFactor,
    SMACrossFactor,
)
from factor_miner.utils import load_config, setup_logging

logger = setup_logging()


def run_stock_example(config: dict):
    """运行股票因子示例."""
    from factor_miner.data import StockAPI

    stock_cfg = config["stock"]
    api = StockAPI(cache_dir=config["project"]["data_dir"])
    df = api.get_daily(
        symbol=stock_cfg["default_symbol"],
        start_date=stock_cfg["start_date"],
        end_date=stock_cfg["end_date"],
        adjust=stock_cfg.get("adjust", "qfq"),
    )
    logger.info("股票数据: %s 行", len(df))

    # 计算因子
    factor = SMACrossFactor(short=5, long=20)
    df[factor.name] = factor(df)
    logger.info("因子示例 %s 计算完成", factor.name)
    print(df[["date", "close", factor.name]].tail(10))


def run_future_example(config: dict):
    """运行期货因子示例."""
    from factor_miner.data import FutureAPI

    future_cfg = config["future"]
    api = FutureAPI(cache_dir=config["project"]["data_dir"])
    df = api.get_daily(
        symbol=future_cfg["default_symbol"],
        start_date=future_cfg["start_date"],
        end_date=future_cfg["end_date"],
    )
    logger.info("期货数据: %s 行", len(df))

    factor = MomentumFactor(window=10)
    df[factor.name] = factor(df)
    logger.info("因子示例 %s 计算完成", factor.name)
    print(df[["date", "close", factor.name]].tail(10))


def run_backtest_example(config: dict):
    """运行简单回测示例."""
    from factor_miner.data import StockAPI

    stock_cfg = config["stock"]
    bt_cfg = config["backtest"]

    api = StockAPI(cache_dir=config["project"]["data_dir"])
    df = api.get_daily(
        symbol=stock_cfg["default_symbol"],
        start_date=stock_cfg["start_date"],
        end_date=stock_cfg["end_date"],
        adjust=stock_cfg.get("adjust", "qfq"),
    )

    # 均线交叉策略
    factor = SMACrossFactor(short=5, long=20)
    df["sma_cross"] = factor(df)
    df["signal"] = np.where(df["sma_cross"] > 0, 1, -1)

    broker = PaperBroker(
        initial_cash=bt_cfg["initial_cash"],
        commission=bt_cfg["commission"],
        slippage=bt_cfg["slippage"],
    )
    engine = BacktestEngine(broker=broker, stake_size=bt_cfg["stake_size"])
    result = engine.run(df, df["signal"])
    metrics = engine.metrics(result)

    trades_df = engine.trade_summary()
    print("\n===== 交易记录 =====")
    print(trades_df.to_string(index=False) if not trades_df.empty else "无交易")

    print("\n===== 回测绩效 =====")
    for k, v in metrics.items():
        print(f"{k}: {v}")


def main():
    parser = argparse.ArgumentParser(description="因子挖掘实验室")
    parser.add_argument(
        "--config", default="config.yaml", help="配置文件路径"
    )
    parser.add_argument(
        "--task",
        choices=["stock_factor", "future_factor", "backtest", "strategy", "dashboard"],
        default="stock_factor",
        help="运行任务",
    )
    parser.add_argument("--profile", help="strategy 任务使用的策略配置名称")
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--prices", help="strategy 任务使用的本地日线 CSV")
    sources.add_argument("--demo", action="store_true", help="使用合成股票面板运行截面策略")
    parser.add_argument("--output-dir", help="strategy 任务写入的新结果目录")
    parser.add_argument("--symbol", help="单标的择时选用的代码")
    parser.add_argument("--evaluation-start", help="回测起算日 YYYY-MM-DD，之前行情用于预热")
    parser.add_argument("--evaluation-end", help="回测末日 YYYY-MM-DD")
    parser.add_argument("--port", type=int, default=8765, help="本地研究界面端口")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config["project"].get("log_level", "INFO"))

    if args.task == "stock_factor":
        run_stock_example(config)
    elif args.task == "future_factor":
        run_future_example(config)
    elif args.task == "backtest":
        run_backtest_example(config)
    elif args.task == "strategy":
        from factor_miner.research.workflow import run_profile

        try:
            destination, metrics = run_profile(
                config, args.profile, args.prices, args.demo, args.output_dir,
                symbol=args.symbol, evaluation_start=args.evaluation_start,
                evaluation_end=args.evaluation_end,
            )
        except (ValueError, TypeError, KeyError, OSError) as error:
            parser.exit(2, f"策略回测失败: {error}\n")
        print(metrics.to_string(float_format=lambda value: f"{value:.6f}"))
        print(f"结果目录: {destination.resolve()}")
    elif args.task == "dashboard":
        from factor_miner.research.dashboard import serve

        try:
            serve(config, args.port)
        except (OSError, ValueError) as error:
            parser.exit(2, f"界面启动失败: {error}\n")


if __name__ == "__main__":
    main()
