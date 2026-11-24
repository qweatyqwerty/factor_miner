# 因子挖掘实验室

一个面向股票和期货的轻量级因子挖掘与回测框架，适合量化入门。

## 快速开始

### 1. 安装依赖

使用指定 conda 环境：

```bash
D:\conda_envs\torch\python.exe -m pip install -r requirements.txt
```

> `ta-lib` 在 Windows 上可能需要先安装 C 库，可参考 [TA-Lib 安装指南](https://github.com/TA-Lib/ta-lib-python)。如果安装失败，可先用 `talib` 的纯 Python 替代版本，或注释掉 `requirements.txt` 中的 `ta-lib`。

### 2. 跑通示例

```bash
# 查看命令帮助
D:\conda_envs\torch\python.exe run.py --help

# 运行股票因子示例
D:\conda_envs\torch\python.exe examples/run_stock_factor.py

# 运行期货因子示例
D:\conda_envs\torch\python.exe examples/run_future_factor.py

# 运行简单回测
D:\conda_envs\torch\python.exe examples/simple_backtest.py
```

### 3. 项目结构

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

## 数据接口

- **股票历史行情**：`factor_miner.data.stock_api`（基于 akshare）
- **期货历史行情**：`factor_miner.data.future_api`（基于 akshare）
- **本地缓存**：数据默认下载到 `./data` 目录，避免重复请求。

## 交易接口

- **模拟交易**：`factor_miner.engine.broker.PaperBroker`，无门槛，直接回测验证。
- **实盘接口**：已在 `factor_miner/engine/broker.py` 中预留接口层，可接入 QMT（股票）或 CTP/VNPY（期货），但需要真实账号和柜台配置。

## 内置因子

- 动量因子（Momentum）
- 均线因子（SMA/EMA Cross）
- RSI 因子
- 波动率因子（Volatility）
- MACD 因子

更多因子可在 `factor_miner/factors/technical.py` 中扩展。

## 多因子组合与策略回测

`run.py --task strategy` 提供股票多因子择时、截面选股和单合约期货多空择时。策略在收盘后评分，模拟订单从下一交易日开盘起执行，并输出基准对照、组合评分、目标仓位和实际成交。

```powershell
# 项目自带缓存
D:\conda_envs\torch\python.exe run.py --task strategy --profile stock_timing
D:\conda_envs\torch\python.exe run.py --task strategy --profile future_timing

# 离线验证截面流程
D:\conda_envs\torch\python.exe run.py --task strategy --profile stock_cross_section --demo
```

输入格式、权重算法、样本区间和成交口径见 [多因子研究与回测指南](strategy_research.md)。

可用 `stock_timing_slow` 和 `stock_timing_wider_exit` 对照原择时策略，也可用 `stock_cross_section_buffered` 检查排名缓冲对换手的影响。择时任务支持从多股票 CSV 用 `--symbol` 选择一只股票。用 `--evaluation-start` 和 `--evaluation-end` 固定评估区间。

## 本地策略研究台

在项目目录运行以下命令，打开 [本地研究台](http://127.0.0.1:8765)。可手动选择行情、因子、交易规则和费用，查看策略与基准的曲线，并导出配置和成交记录。

```powershell
D:\conda_envs\torch\python.exe run.py --task dashboard
```

## 常见问题

- `akshare` 接口会随东方财富等网站调整，如报错请升级：`D:\conda_envs\torch\python.exe -m pip install -U akshare`。
- 期货主力合约代码（如 `RB2501`）会随时间过期，运行失败时请改成当前主力合约。
