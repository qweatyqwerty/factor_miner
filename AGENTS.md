# Agent 指南

## 项目概述

轻量级股票/期货因子挖掘与回测框架，基于 Python + akshare + backtrader。

## 环境

- Python: `D:\conda_envs\torch\python.exe`
- 安装依赖：`D:\conda_envs\torch\python.exe -m pip install -r requirements.txt`

## 目录结构

```
.
├── config.yaml              # 全局配置
├── requirements.txt         # Python 依赖
├── run.py                   # 统一入口
├── factor_miner/            # 核心框架
│   ├── data/                # 数据获取（akshare 股票/期货）
│   ├── factors/             # 因子计算与评价
│   ├── engine/              # 回测引擎与模拟交易接口
│   └── utils.py             # 工具函数
└── examples/                # 可运行示例
```

## 常用命令

```bash
# 股票因子示例
D:\conda_envs\torch\python.exe examples/run_stock_factor.py

# 期货因子示例
D:\conda_envs\torch\python.exe examples/run_future_factor.py

# 简单回测
D:\conda_envs\torch\python.exe examples/simple_backtest.py

# 统一入口
D:\conda_envs\torch\python.exe run.py --task stock_factor
D:\conda_envs\torch\python.exe run.py --task future_factor
D:\conda_envs\torch\python.exe run.py --task backtest

# 单元测试
D:\conda_envs\torch\python.exe tests/test_factor.py
```

## 代码规范

- 使用 pandas 处理数据，行情列统一为英文小写：`date`, `open`, `high`, `low`, `close`, `volume`, `amount`。
- 因子类继承 `factor_miner.factors.base.Factor`，实现 `compute` 方法。
- 新增示例放在 `examples/` 目录。
- 实盘交易接口在 `factor_miner/engine/broker.py` 的 `RealBrokerInterface` 中扩展。

## 注意事项

- akshare 接口依赖东方财富等网站，如遇报错请先升级 akshare。
- 期货合约代码会过期，config.yaml 中的 `future.default_symbol` 需按当前主力合约更新。
- `ta-lib` 在 Windows 上需要预装 C 库，当前代码未依赖它，仅列在 requirements.txt 中作为可选。
