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

## 常见问题

- `akshare` 接口会随东方财富等网站调整，如报错请升级：`D:\conda_envs\torch\python.exe -m pip install -U akshare`。
- 期货主力合约代码（如 `RB2501`）会随时间过期，运行失败时请改成当前主力合约。
