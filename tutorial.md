# 因子挖掘实验室 - 详细教程

> 本教程面向量化入门者，逐步讲解 `factor_miner` 框架的代码结构、运行原理和扩展方法。
> 建议配合实际代码文件一起阅读。

---

## 目录

1. [项目目标与整体架构](#1-项目目标与整体架构)
2. [环境准备与第一次运行](#2-环境准备与第一次运行)
3. [数据层：如何获取股票/期货行情](#3-数据层如何获取股票期货行情)
4. [因子层：如何计算和评价因子](#4-因子层如何计算和评价因子)
5. [回测引擎：模拟交易与绩效计算](#5-回测引擎模拟交易与绩效计算)
6. [交易接口：从模拟到实盘](#6-交易接口从模拟到实盘)
7. [示例代码逐行解读](#7-示例代码逐行解读)
8. [如何扩展自己的因子/策略](#8-如何扩展自己的因子策略)
9. [验证与调试技巧](#9-验证与调试技巧)
10. [常见问题](#10-常见问题)

---

## 1. 项目目标与整体架构

### 1.1 目标

这个框架想帮你快速完成：

- **获取数据**：免费获取 A 股和期货历史行情。
- **挖掘因子**：用统一接口计算动量、均线、RSI、MACD、波动率等常见因子。
- **评价因子**：用 IC、Rank IC、分层收益等指标判断因子有效性。
- **回测验证**：用模拟交易接口验证策略，输出每笔交易明细和绩效指标。
- **预留实盘**：为股票 QMT、期货 CTP 等实盘接口预留接入点。

### 1.2 模块划分

```
factor_miner/
├── data/           ← 数据获取（股票、期货）
├── factors/        ← 因子计算 + 因子评价
├── engine/         ← 回测引擎 + 交易接口（模拟/实盘）
└── utils.py        ← 配置、日志、工具函数
```

数据流：

```
行情数据 (akshare)
    ↓
StockAPI / FutureAPI
    ↓
pandas DataFrame [date, open, high, low, close, volume, ...]
    ↓
Factor.compute(df) → 因子值 Series
    ↓
FactorEvaluator → IC / 分层收益
    ↓
BacktestEngine + PaperBroker → 交易记录 + 绩效
```

---

## 2. 环境准备与第一次运行

### 2.1 使用指定环境

项目使用你指定的 Conda 环境：

```bash
D:\conda_envs\torch\python.exe --version
```

安装依赖（第一次）：

```bash
cd F:\实习\Lab\因子挖掘
D:\conda_envs\torch\python.exe -m pip install -r requirements.txt
```

> `ta-lib` 是可选的，如果安装失败可以跳过，当前代码没有依赖它。

### 2.2 快速跑通

```bash
# 股票因子示例
D:\conda_envs\torch\python.exe examples/run_stock_factor.py

# 期货因子示例
D:\conda_envs\torch\python.exe examples/run_future_factor.py

# 回测示例
D:\conda_envs\torch\python.exe examples/simple_backtest.py

# 单元测试
D:\conda_envs\torch\python.exe tests/test_factor.py
```

第一次运行会从网络下载数据并缓存到 `./data`，之后直接读缓存，速度会快很多。

---

## 3. 数据层：如何获取股票/期货行情

数据层代码位于 `factor_miner/data/`，核心是 `StockAPI` 和 `FutureAPI`。

### 3.1 股票数据接口 `StockAPI`

文件：`factor_miner/data/stock_api.py`

核心方法：

```python
api = StockAPI(cache_dir="./data")
df = api.get_daily(
    symbol="000001",          # 股票代码
    start_date="20230101",    # 开始日期
    end_date="20251231",      # 结束日期
    adjust="qfq",             # 前复权
    use_cache=True,           # 是否使用本地缓存
)
```

#### 内部实现步骤

1. **检查缓存**：如果本地 CSV 已存在，直接读取。
2. **调用 akshare**：`ak.stock_zh_a_hist(...)` 从东方财富获取日线。
3. **列名标准化**：akshare 返回中文列名，映射为英文标准列名。

```python
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
```

4. **处理 symbol**：akshare 会把 "000001" 解析成整数 `1`，代码中强制补零：

```python
df["symbol"] = df["symbol"].astype(str).str.zfill(6)
```

5. **保存缓存**：CSV 文件写入 `./data/stock_000001_20230101_20251231_qfq.csv`。

#### 为什么要统一列名？

因为上层的因子计算、回测引擎都约定使用 `date/open/high/low/close/volume` 这些英文列名。统一后，你写因子时不用关心数据来源。

### 3.2 期货数据接口 `FutureAPI`

文件：`factor_miner/data/future_api.py`

核心方法：

```python
api = FutureAPI(cache_dir="./data")
df = api.get_daily(
    symbol="RB2501",          # 期货合约代码
    start_date="20240101",
    end_date="20251231",
)
```

期货数据来自 `ak.futures_zh_daily_sina(...)`。

#### 主力连续合约

期货合约会过期，框架也支持获取主力连续合约：

```python
df = api.get_main_contract_history(
    variety="RB",             # 螺纹钢
    start_date="20240101",
    end_date="20251231",
)
```

内部会请求 `"RB0"`（新浪的主力连续合约代码）。

### 3.3 缓存机制

- 缓存目录：`./data`
- 缓存文件名包含代码、起止日期、复权类型，避免重复下载。
- 如果 akshare 接口后续报错，可以先删除 `./data` 里的 CSV，或升级 akshare：

```bash
D:\conda_envs\torch\python.exe -m pip install -U akshare
```

---

## 4. 因子层：如何计算和评价因子

因子层代码位于 `factor_miner/factors/`。

### 4.1 因子基类 `Factor`

文件：`factor_miner/factors/base.py`

所有因子都继承这个基类：

```python
class Factor(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def __call__(self, df: pd.DataFrame) -> pd.Series:
        result = self.compute(df)
        result.name = self.name
        return result
```

设计要点：

- `compute(df)`：传入行情 DataFrame，返回因子值 Series。
- `__call__`：让因子对象可以像函数一样调用，并自动设置 Series 名称。
- 行情列必须包含 `open/high/low/close/volume`，因子实现里只依赖这些列。

### 4.2 内置因子解析

文件：`factor_miner/factors/technical.py`

#### 动量因子

```python
class MomentumFactor(Factor):
    def __init__(self, window: int = 20):
        super().__init__(f"momentum_{window}")
        self.window = window

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change(self.window)
```

含义：今天收盘价 / N 天前收盘价 - 1，表示 N 日涨跌幅。

#### 均线交叉因子

```python
class SMACrossFactor(Factor):
    def __init__(self, short: int = 5, long: int = 20):
        super().__init__(f"sma_cross_{short}_{long}")
        self.short = short
        self.long = long

    def compute(self, df: pd.DataFrame) -> pd.Series:
        short_sma = df["close"].rolling(self.short).mean()
        long_sma = df["close"].rolling(self.long).mean()
        return short_sma - long_sma
```

含义：短期均线 - 长期均线。>0 表示短期强于长期，<0 表示短期弱于长期。

#### RSI 因子

```python
class RSIFactor(Factor):
    def compute(self, df: pd.DataFrame) -> pd.Series:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(self.window).mean()
        avg_loss = loss.rolling(self.window).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
```

RSI 取值 0~100，常用阈值 70（超买）/ 30（超卖）。

### 4.3 因子评价器 `FactorEvaluator`

文件：`factor_miner/factors/evaluator.py`

#### 什么是 IC？

IC（Information Coefficient）衡量因子值与未来收益的相关性：

- IC > 0：因子值越高，未来收益越高（正向预测能力）。
- IC < 0：因子值越高，未来收益越低（反向预测能力）。
- |IC| 越大，预测能力越强。

Rank IC 用秩相关系数（Spearman），对异常值更稳健。

#### 核心方法

```python
evaluator = FactorEvaluator(df)

# 添加未来 1 日收益
evaluator.add_forward_return(forward_period=1)

# 计算某个因子的 IC / Rank IC
stats = evaluator.ic_analysis(factor_col="momentum_20")

# 按因子分层，看每组未来收益
quantile_df = evaluator.quantile_return(factor_col="momentum_20", n_quantiles=5)

# 批量评价多个因子、多个周期
summary = evaluator.summary(
    factor_cols=["momentum_20", "sma_cross_5_20", "rsi_14"],
    forward_periods=[1, 5, 10],
)
```

输出示例：

```
        factor  forward_period        IC    RankIC
   momentum_20               1    -0.022    -0.016
sma_cross_5_20               1    -0.005    -0.022
        rsi_14               1     0.008    -0.016
```

---

## 5. 回测引擎：模拟交易与绩效计算

回测代码位于 `factor_miner/engine/`。

### 5.1 模拟交易账户 `PaperBroker`

文件：`factor_miner/engine/broker.py`

#### 数据结构

```python
@dataclass
class Order:
    symbol: str
    direction: str      # "buy" / "sell"
    size: int
    price: float
    order_type: str = "market"
    datetime: Optional[datetime] = None

@dataclass
class Trade:
    symbol: str
    direction: str
    size: int
    price: float        # 实际成交价（含滑点）
    commission: float
    datetime: Optional[datetime]
    order_price: float  # 下单价（不含滑点）
    pnl: Optional[float] # 平仓盈亏
```

#### 成交规则

```python
if order.direction == "buy":
    exec_price = order.price * (1 + self.slippage)
else:
    exec_price = order.price * (1 - self.slippage)

amount = exec_price * order.size
commission = amount * self.commission_rate
```

- 买入：成交价 = 信号价 × (1 + 滑点)，模拟以卖一价成交。
- 卖出：成交价 = 信号价 × (1 - 滑点)，模拟以买一价成交。
- 手续费 = 成交金额 × 手续费率。

#### 持仓成本与平仓盈亏

买入时更新加权平均成本：

```python
new_size = old_size + order.size
self._cost_basis[symbol] = (
    old_cost * old_size + exec_price * order.size
) / new_size
```

卖出时计算盈亏：

```python
pnl = (exec_price - cost_basis) * order.size - commission
```

这样你可以直观看到每一笔卖出是赚了还是亏了。

#### 查看交易记录

```python
broker = PaperBroker(...)
# ... 运行回测 ...
trades_df = broker.get_trades_df()
```

返回的 DataFrame 包含：

| 列名 | 含义 |
|------|------|
| datetime | 交易时间 |
| symbol | 股票代码 |
| direction | 买/卖 |
| size | 成交量 |
| order_price | 下单时价格 |
| exec_price | 实际成交价（含滑点） |
| slippage | 滑点金额 |
| commission | 手续费 |
| pnl | 平仓盈亏（买入为空） |

### 5.2 回测引擎 `BacktestEngine`

文件：`factor_miner/engine/backtest.py`

#### 设计思想

这是一个**事件驱动风格的简化回测引擎**：

- 每天读取一行行情。
- 根据信号判断今天是否发单。
- 模拟成交后更新仓位和现金。
- 记录每日资金曲线。

#### 信号约定

```python
signal > 0  →  买入（如果当前无仓）
signal < 0  →  卖出（如果当前有仓）
signal == 0 →  不动
```

#### 核心循环

```python
for i, row in df.iterrows():
    dt = row["date"]
    sig = row["signal"]
    price = row["close"]

    if sig > 0 and current_pos == 0:
        broker.send_order(Order(symbol, "buy", size, price, datetime=dt))
        current_pos = size
    elif sig < 0 and current_pos > 0:
        broker.send_order(Order(symbol, "sell", current_pos, price, datetime=dt))
        current_pos = 0

    equity = broker.get_equity({symbol: price})
    equity_curve.append({"date": dt, "equity": equity, "position": current_pos})
```

#### 绩效指标

```python
metrics = engine.metrics(result)
```

包含：

- `total_return`：总收益率
- `annual_return`：年化收益率
- `sharpe_ratio`：夏普比率
- `max_drawdown`：最大回撤
- `trades_count`：交易次数
- `final_equity`：最终资金

### 5.3 为什么回测绩效接近 0？

示例中 `initial_cash=1,000,000`，但 `stake_size=100` 股。每次只买 100 股，仓位占比很小，所以盈亏对总资金影响很小。

如果你想让策略有显著收益波动，可以修改 `config.yaml`：

```yaml
backtest:
  stake_size: 10000    # 每次买 1 万股
```

但注意：这也会增加风险，示例策略不一定能赚钱。

---

## 6. 交易接口：从模拟到实盘

### 6.1 模拟接口 `PaperBroker`

已经完整实现，直接用于回测验证。

### 6.2 实盘接口占位 `RealBrokerInterface`

文件：`factor_miner/engine/broker.py`

这是一个抽象接口的占位实现，提示你如何接入真实柜台：

- **股票实盘**：QMT、迅投 XtQuant、同花顺 iFinD
- **期货实盘**：CTP（通过 vnpy 或 openctp）

接入实盘需要：

1. 安装对应 SDK（如 `xtquant`、`vnpy`）。
2. 在 `RealBrokerInterface` 的子类中实现 `connect()` 和 `send_order()`。
3. 在 `config.yaml` 的 `trading` 段落填入账号、密码、柜台地址。

示例接入思路：

```python
class QMTBroker(RealBrokerInterface):
    def connect(self):
        # 调用 XtQuantAPI 登录
        pass

    def send_order(self, order: Order) -> Optional[Trade]:
        # 调用下单 API
        pass
```

---

## 7. 示例代码逐行解读

### 7.1 股票因子示例 `examples/run_stock_factor.py`

```python
# 1. 加载配置
config = load_config("config.yaml")
stock_cfg = config["stock"]

# 2. 创建数据接口并获取日线
api = StockAPI(cache_dir=config["project"]["data_dir"])
df = api.get_daily(
    symbol=stock_cfg["default_symbol"],
    start_date=stock_cfg["start_date"],
    end_date=stock_cfg["end_date"],
    adjust=stock_cfg.get("adjust", "qfq"),
)

# 3. 计算多个因子
factors = [
    MomentumFactor(window=20),
    SMACrossFactor(short=5, long=20),
    RSIFactor(window=14),
    MACDFactor(),
    VolatilityFactor(window=20),
]
for f in factors:
    df[f.name] = f(df)        # 等价于 df[f.name] = f.compute(df)

# 4. 因子评价
evaluator = FactorEvaluator(df)
summary = evaluator.summary(factor_names, forward_periods=[1, 5, 10])
print(summary)
```

### 7.2 回测示例 `examples/simple_backtest.py`

```python
# 1. 获取数据
df = api.get_daily(...)

# 2. 生成交易信号
factor = SMACrossFactor(short=5, long=20)
df["sma_cross"] = factor(df)
df["signal"] = np.where(df["sma_cross"] > 0, 1, -1)

# 3. 创建模拟账户并回测
broker = PaperBroker(initial_cash=..., commission=..., slippage=...)
engine = BacktestEngine(broker=broker, stake_size=...)
result = engine.run(df, df["signal"])

# 4. 查看交易记录和绩效
trades_df = engine.trade_summary()
metrics = engine.metrics(result)
```

### 7.3 期货示例 `examples/run_future_factor.py`

与股票类似，只是换成 `FutureAPI`。如果具体合约过期，会自动降级到主力连续合约：

```python
try:
    df = api.get_daily(symbol=future_cfg["default_symbol"], ...)
except Exception as e:
    df = api.get_main_contract_history(variety="RB", ...)
```

---

## 8. 如何扩展自己的因子/策略

### 8.1 添加一个新因子

在 `factor_miner/factors/technical.py` 中添加：

```python
class MyFactor(Factor):
    def __init__(self, window: int = 20):
        super().__init__(f"my_factor_{window}")
        self.window = window

    def compute(self, df: pd.DataFrame) -> pd.Series:
        # 你的计算逻辑，必须返回 Series
        return df["close"].rolling(self.window).mean() / df["close"]
```

然后在 `factor_miner/factors/__init__.py` 中导出：

```python
from .technical import MyFactor
```

示例中使用：

```python
from factor_miner.factors import MyFactor

df["my_factor_20"] = MyFactor(window=20)(df)
```

### 8.2 添加一个新策略

策略本质上就是生成 `signal` 列。新建 `examples/my_strategy.py`：

```python
import numpy as np
from factor_miner.data import StockAPI
from factor_miner.engine import BacktestEngine, PaperBroker
from factor_miner.factors import RSIFactor

api = StockAPI()
df = api.get_daily(symbol="000001", start_date="20230101", end_date="20251231")

# RSI 策略：RSI < 30 买入，RSI > 70 卖出
df["rsi_14"] = RSIFactor(window=14)(df)
df["signal"] = 0
df.loc[df["rsi_14"] < 30, "signal"] = 1
df.loc[df["rsi_14"] > 70, "signal"] = -1

broker = PaperBroker(initial_cash=1_000_000, commission=0.0003, slippage=0.001)
engine = BacktestEngine(broker=broker, stake_size=1000)
result = engine.run(df, df["signal"])
print(engine.metrics(result))
print(engine.trade_summary())
```

---

## 9. 验证与调试技巧

### 9.1 验证数据是否正确

```python
from factor_miner.data import StockAPI

api = StockAPI()
df = api.get_daily("000001", "20230101", "20251231")
print(df[["date", "symbol", "open", "high", "low", "close", "volume"]].head())
print(df.dtypes)
```

### 9.2 验证因子计算

```python
from factor_miner.factors import SMACrossFactor

df["sma_cross"] = SMACrossFactor(5, 20)(df)
# 手动检查某一天的 short_sma 和 long_sma
print(df[["date", "close", "sma_cross"]].dropna().head(10))
```

### 9.3 验证交易记录

回测后查看 `./results/trades.csv`：

```python
import pandas as pd
trades = pd.read_csv("results/trades.csv")
print(trades.head(10))
```

重点检查：

- 买入/卖出是否成对出现？
- 成交价是否符合滑点规则？
- 手续费 = 成交金额 × 手续费率 是否对？
- 平仓盈亏 = (卖出价 - 买入成本) × 数量 - 手续费 是否对？

### 9.4 用单元测试验证

`tests/test_factor.py` 展示了如何写测试：

```python
def test_momentum():
    df = make_sample_df()
    factor = MomentumFactor(window=5)
    s = factor(df)
    assert len(s) == len(df)
    assert s.iloc[:5].isna().all()          # 前 5 天无数据
    assert not s.iloc[6:].isna().any()
```

---

## 10. 常见问题

### Q1: 运行时报 `KeyError: 'close'`

通常是 akshare 返回列名变化或缓存文件损坏。解决：

```bash
rm -rf ./data/*.csv
D:\conda_envs\torch\python.exe -m pip install -U akshare
```

### Q2: 期货示例跑不通

期货合约会过期。打开 `config.yaml`，把 `future.default_symbol` 改成当前主力合约，例如 `RB2601`。

### Q3: 中文显示乱码

当前在部分终端（如 msys2 bash）下可能出现中文乱码。在 Windows CMD/PowerShell 或 Jupyter Notebook 中运行通常正常。不影响计算结果。

### Q4: 如何接入实盘交易？

目前框架只提供模拟交易。接入实盘需要：

1. 获取券商/期货公司提供的 API（QMT、CTP 等）。
2. 继承 `RealBrokerInterface`，实现 `connect()` 和 `send_order()`。
3. 在 `config.yaml` 中填写账号信息。
4. 先用模拟盘（paper trading）充分验证策略后再上实盘。

### Q5: 回测结果为什么收益几乎为 0？

因为 `stake_size=100` 股，相对 100 万本金仓位太小。可以修改 `config.yaml` 增大仓位，但请同时注意策略本身可能不赚钱。

---

## 结语

本框架的目标是让你**快速跑通数据 → 因子 → 回测**的完整链路。建议你：

1. 先跑通三个示例。
2. 阅读 `factor_miner/` 下各模块的源码。
3. 尝试修改参数或写一个新因子。
4. 理解交易记录的每一笔细节，确认程序正确后再扩展。

量化交易有风险，所有策略请务必先用模拟盘验证。
