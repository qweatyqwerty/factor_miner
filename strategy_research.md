# 多因子研究与回测指南

## 运行策略

在项目根目录运行。股票择时和期货择时默认读取项目已有的历史缓存。截面选股使用多只股票，可传入自己的历史行情，也可通过 `--demo` 使用固定种子的八标的合成面板。

```powershell
D:\conda_envs\torch\python.exe run.py --task strategy --profile stock_timing
D:\conda_envs\torch\python.exe run.py --task strategy --profile future_timing
D:\conda_envs\torch\python.exe run.py --task strategy --profile stock_cross_section --demo
D:\conda_envs\torch\python.exe run.py --task strategy --profile stock_cross_section --prices .\data\stock_panel.csv --output-dir .\results\custom_panel
```

`--config` 可指定实验配置。未传入 `--prices` 或 `--demo` 时，沿用现有行情接口并优先读取匹配的本地缓存。默认结果目录按策略和运行时间创建。手动指定的 `--output-dir` 必须是新目录。

股票与期货择时可用 `--symbol` 选择单标的。例子使用多股票本地行情，前段数据只参与指标预热。

```powershell
D:\conda_envs\torch\python.exe run.py --task strategy --profile stock_timing_slow --prices .\data\stock_study_sina_hfq_2019_20261030.csv --symbol 300750 --evaluation-start 2026-01-01 --evaluation-end 2026-10-30
```

## 本地策略研究台

`run.py --task dashboard` 启动本地策略研究台，默认地址为 `http://127.0.0.1:8765`。它读取 `project.data_dir` 中的 CSV。期货文件命名使用 `future_` 前缀，股票可以使用 `stock_` 前缀。文件新增后刷新浏览器。

从预设开始，可在表单里调整评估区间、因子周期、方向、组合方法、目标仓位和模拟交易成本。结果包含相同成本口径的基准、收益与回撤曲线、成交和因子诊断。截止区间外的行情仍按统一入口的口径截断。终端按 Ctrl+C 停止服务，`--port` 可指定其他端口。

导出的 `dashboard_strategy.yaml` 可作为 `--config` 使用。复跑时在项目目录用 `--task strategy --prices <同一行情文件>`，择时再加 `--symbol <界面所选代码>`。合成演示使用 `--demo`。净值和成交可以在界面直接导出 CSV。

## 本地行情格式

| 列 | 含义 |
| --- | --- |
| `date`、`symbol` | 交易日和证券代码。同一代码同一日只能有一行。CSV 按字符串读取代码，保留前导零。单标的配置允许省略 `symbol`。 |
| `open`、`close` | 数值为正的开盘价、收盘价，分别用于仿真成交和因子计算。空值表示缺失。 |
| `settle` | 期货结算价。空值和缓存中的 0 使用收盘价替代。 |
| `volume` | 成交量。选用 OBV 时必填。 |
| `can_buy`、`can_sell` | 可选的开盘交易约束，支持 `0/1` 和 `true/false`。整列省略时默认允许，提供后单元格留空代表禁止。 |

截面配置可以从 CSV 读取其中所有代码。直接使用行情接口时，代码取自配置中的 `symbols`。交易日历取所有输入日期的并集，行情缺行的标的当日无开盘报价。应按历史成分和证券可用性准备面板，复权口径在同一标的内保持一致。演示配置中的固定股票名单没有历史成分变更记录。

## 因子组合

- `factors` 复用现有动量、均线、RSI、MACD、波动率及 OBV。每个因子可以配置参数、方向 `1/-1` 和非负先验权重。
- 截面归一化支持当日百分位排名映射至 `[-1, 1]`，或当日截面 Z 分数。时序归一化使用此前 `z_window` 个日期的均值和标准差。Z 分数截断至 `[-3, 3]`。有效权重为正的因子缺失时，该标的不产生组合评分。
- `equal` 使用等权，`fixed` 归一化配置权重，`rolling_ic` 使用历史截面 Spearman Rank IC 的滚动均值。后者将正均值乘上先验权重再归一化，样本不足或没有正均值时回退到先验权重。标签为信号 `t` 后的 `t+1` 开盘到 `t+1+h` 开盘收益，结束开盘价到期后才用于更新权重。 [Alphalens Rank IC 文档](https://quantopian.github.io/alphalens/alphalens.html#alphalens.performance.factor_information_coefficient)
- `evaluation_start` 决定策略和基准的起算日。更早行情用来预热指标并累积已到期的 IC 标签。`evaluation_end` 截断超出评估末日的行情，也限定诊断标签可用的范围。

### Rank IC 计算性能

截面 Rank IC 先取因子与收益标签的成对有效值，再按交易日批量计算平均排名和 Pearson 相关系数。并列项共享平均名次，常量截面和不足最少标的数的日期仍返回空值。计算顺序保持与此前的相关系数一致，避免浮点误差改变组合分数的并列结果。 [Alphalens Rank IC 实现](https://github.com/quantopian/alphalens/blob/master/alphalens/performance.py)

本地用 12 只股票、22,726 行行情和滚动 Rank IC 配置，各运行三次。完整回测的中位耗时由 9.62 秒降至 1.06 秒，14 张结果表逐项一致。

## 策略和交易口径

| 策略 | 目标仓位 | 对照 |
| --- | --- | --- |
| `stock_timing` | 单股多因子分数达到入场阈值时开多，跌至退出阈值时平仓。持仓目标采用可配置的净值敞口。 | 首次有效评分后按同一目标敞口买入持有 |
| `stock_timing_wider_exit` | 原因子与入场阈值不变，退出阈值为 -0.25。 | 同上 |
| `stock_timing_slow` | 使用 63 日动量、20/80 日均线差与 20 日波动率，滚动标准化窗口 63 日，入场 0.55，退出 -0.20。 | 同上 |
| `stock_cross_section` | 每 `rebalance_every` 个交易日收盘筛选高分的 `top_n` 只股票，等权并执行单股权重及组合敞口上限。并列按代码排序。 | 相同调仓日期，对全部有评分标的等权 |
| `stock_cross_section_buffered` | 因子等权，上一期入选股票的排名仍在 `top_n + rank_buffer` 以内时优先留在组合。空位按当期评分补足，组合仍最多持有 `top_n` 个目标标的。 | 同上 |
| `future_timing` | 支持正负分数产生多头、空头、平仓和反手指令。按合约乘数、保证金率及最大手数计算持仓。 | 首次有效评分后按同一参数开多持有 |

收盘指令最早在次日可交易开盘执行。限制或缺价时保留待执行指令，新的目标覆盖旧目标。股票先卖后买，按整手、现金和可用敞口缩减买单，因资金或整手限制未成交的数量等待下一次目标更新。持仓缺少新报价时沿用最近可用估值。敞口限制用于调仓的目标和开盘买单，持仓市值会随行情变化。 [Backtrader 市价单时点说明](https://www.backtrader.com/docu/order-creation-execution/order-creation-execution/)

股票费用包含成交额比例手续费、方向性滑点和可配置卖出附加费。复权行情下的成交价和整手计算属于研究近似。涨跌停或停复牌限制应通过输入行情与交易标志提供。模型没有逐笔流动性、排队成交和公司行为现金流水。

期货使用结算价逐日盯市，缺失时按收盘价估值，按成交额费率及每手固定费用计费。保证金不足时进入平仓流程，在可执行开盘尝试平掉持仓。样例中的保证金和费用参数是模拟参数。跨合约换月、交割和柜台逐笔保证金规则需另行建模。样本末日开放仓位按最后已知价格估值。

## 结果复核

| 输出 | 内容 |
| --- | --- |
| `run.yaml` | 配置、数据来源、样本日期和代码 |
| `factors.csv`、`factor_weights.csv` | 输入行情、原值、定向归一化分数、组合分数、未来收益标签及逐日因子权重 |
| `rank_ic.csv`、`ic_summary.csv`、`quantile_returns.csv` | 截面逐日 Rank IC、IC 均值及 ICIR、覆盖率、平均权重和组合分组收益。时序模式提供样本内 Rank IC。分组收益使用原始价格收益标签。 |
| `targets.csv`、`benchmark_targets.csv` | 以信号日记录的目标仓位，空白表示无新指令，0 表示空仓目标 |
| `equity.csv`、`trades.csv`、`holdings.csv` | 每日权益、手续费、滑点、换手、敞口、成交信号日及持仓。基准有对应的 `benchmark_*` 文件。 |
| `metrics.csv` | 策略与基准的总收益、年化收益、年化波动、零无风险利率 Sharpe、最大回撤、换手与成本 |

换手率按当日双边成交额除以上一日权益累计。期货持仓表的敞口带方向，权益表的总敞口为绝对值。人工复核可先检查 `trades.csv` 的信号日、成交日和价格，再对照 `equity.csv` 的持仓估值和费用。

## 多股票复测

`examples/fetch_stock_study.py` 下载固定样本的新浪日线和后复权因子。`examples/study_stock_timing.py` 使用 2019 年数据预热、2020–2022 年开发，并在后续指定区间按固定参数检验。每只股票独立分配资金，另以同组初始总资金测试截面规则。单边佣金、滑点和卖出附加成本统一按实验脚本内的口径评估，并同时运行成本翻倍情景。

```powershell
D:\conda_envs\torch\python.exe examples/fetch_stock_study.py --end-date 2026-10-30 --output .\data\stock_study_sina_hfq_2019_20261030.csv
D:\conda_envs\torch\python.exe examples/study_stock_timing.py --prices .\data\stock_study_sina_hfq_2019_20261030.csv --test-start 2026-01-01 --test-end 2026-10-30 --output-dir .\results\stock_study_2026_reproduced
```

### 两段实测

使用 11 只对照股票，平安银行单列。2026 年区间含 1 月 5 日至 10 月 30 日的 198 个交易日。模型按收盘指令、次日可交易开盘撮合，使用归一化的新浪后复权价格和固定成本。固定样本包含存续股票，在该样本之外的表现仍需验证。 [新浪财经行情示例](https://finance.sina.com.cn/realstock/company/sz000001/nc.shtml)

| 区间 | 原多因子择时 | 放宽退出阈值 | 慢周期组合 | 买入持有 |
| --- | ---: | ---: | ---: | ---: |
| 2023–2025 年累计净收益 | 4.47% | 6.98% | 22.76% | 36.89% |
| 2026 年前十个月累计净收益 | -1.10% | -3.04% | -3.88% | -4.31% |

| 区间 | 等权因子 Top-3 | 同规则加两名缓冲 | 加缓冲且成本翻倍 | 全部股票定期等权 |
| --- | ---: | ---: | ---: | ---: |
| 2023–2025 年累计净收益 | 11.11% | 38.13% | 22.58% | 39.87% |
| 2026 年前十个月累计净收益 | 0.83% | 3.98% | 1.74% | -5.10% |

排名缓冲使截面累计换手分别下降约 40% 和 56%。慢周期组合在 2026 年继续降低换手，净收益低于原策略。

逐股净收益、组合日净值、成本敏感性、成交记录及行情快照校验值位于 `results/stock_study_2023_2025` 和 `results/stock_study_2026`。

```powershell
D:\conda_envs\torch\python.exe -m unittest discover -s tests -p test_research.py -v
D:\conda_envs\torch\python.exe tests\test_factor.py
```
