"""回归覆盖标签可用性、实际成交时点和期货逐日盯市。"""

import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from factor_miner.research.signals import _correlation, _daily_ic, allocation, prepare_prices, timing_targets
from factor_miner.research.simulation import simulate
from factor_miner.research.workflow import _demo_prices, analyze


class ResearchTests(unittest.TestCase):
    def test_batch_rank_ic_matches_pairwise_ranking_with_missing_values_and_ties(self):
        columns = pd.Index(list("ABCDE"), name="symbol")
        dates = pd.date_range("2024-01-01", periods=4, name="date")
        forward = pd.DataFrame([
            [2.0, 2.0, np.nan, 1.0, 3.0],
            [0.0, 1.0, np.nan, np.nan, 3.0],
            [0.0, 1.0, 3.0, 4.0, 2.0],
            [2.0, 2.0, 2.0, 2.0, 2.0],
        ], index=dates, columns=columns)
        first = pd.DataFrame([
            [0.0, 1.0, 5.0, 1.0, np.nan],
            [0.0, 1.0, 5.0, 3.0, np.nan],
            [1.0, 1.0, 1.0, 1.0, 1.0],
            [4.0, 3.0, 2.0, 1.0, 0.0],
        ], index=dates, columns=columns)
        second = first.iloc[:, ::-1].set_axis(columns, axis=1)
        scores = pd.DataFrame({"first": first.stack(), "second": second.stack()})
        expected = {}
        for name, values in (("first", first), ("second", second)):
            expected[name] = [
                _correlation(values.loc[date], forward.loc[date])
                if (values.loc[date].notna() & forward.loc[date].notna()).sum() >= 3 else np.nan
                for date in dates
            ]
        assert_frame_equal(_daily_ic(scores, forward, 3), pd.DataFrame(expected, index=dates))

    def test_future_rows_do_not_change_cross_section_decisions(self):
        prices = _demo_prices()
        dates = sorted(prices["date"].unique())
        cutoff = dates[118]
        prices = prices.loc[prices["date"] <= dates[139]]
        settings = {
            "market": "stock", "mode": "cross_section", "weighting": "rolling_ic",
            "min_assets": 4, "ic_min_assets": 4, "ic_window": 15, "ic_min_periods": 5,
            "forward_period": 3, "rebalance_every": 4, "top_n": 2,
            "factors": {
                "fast": {"type": "momentum", "params": {"window": 3}},
                "slow": {"type": "momentum", "params": {"window": 12}},
            },
        }
        full = analyze(prices, settings)
        prefix = analyze(prices.loc[prices["date"] <= cutoff], settings)
        bounded = analyze(prices, {**settings, "evaluation_end": cutoff})
        assert_frame_equal(bounded["factors"], prefix["factors"])
        assert_frame_equal(bounded["metrics"], prefix["metrics"])
        self.assertGreater(full["factor_weights"].drop_duplicates().shape[0], 2)
        for key in ("factor_weights", "targets", "benchmark_targets", "equity"):
            assert_frame_equal(full[key].loc[:cutoff], prefix[key])
        signal_columns = ["raw_fast", "raw_slow", "score_fast", "score_slow", "score"]
        assert_frame_equal(full["factors"].loc[:cutoff, signal_columns], prefix["factors"][signal_columns])
        fills = full["trades"]
        self.assertTrue((fills["date"] > fills["signal_date"]).all())
        self.assertTrue(full["equity"]["cash"].ge(0).all())
        date, symbol = dates[20], "DEMO01"
        opens = prices.loc[prices["symbol"].eq(symbol)].set_index("date")["open"]
        expected = opens.loc[dates[24]] / opens.loc[dates[21]] - 1
        self.assertAlmostEqual(full["factors"].at[(date, symbol), "forward_return"], expected)

    def test_stock_negative_exit_keeps_position_until_exit_threshold(self):
        dates = pd.date_range("2024-01-01", periods=6)
        scores = pd.Series([0.6, 0.15, -0.10, -0.25, 0.2, 0.65], index=dates)
        settings = {"market": "stock", "entry": 0.6, "exit": -0.25}
        selected = timing_targets(scores, settings, 0.9).dropna()
        self.assertListEqual(list(selected.index), [dates[0], dates[3], dates[5]])
        self.assertListEqual(list(selected), [0.9, 0, 0.9])
        with self.assertRaisesRegex(ValueError, "exit"):
            timing_targets(scores, {**settings, "market": "future", "allow_short": True}, 0.9)

    def test_cross_section_buffer_retains_only_stocks_inside_exit_rank(self):
        dates = pd.date_range("2024-01-01", periods=3, name="date")
        scores = pd.DataFrame(
            [[4, 3, 2, 1], [2, 4, 3, 1], [1, 4, 3, 2]],
            index=dates, columns=pd.Index(list("ABCD"), name="symbol"),
        )
        detail = scores.stack().to_frame("score")
        settings = {
            "market": "stock", "mode": "cross_section", "top_n": 2,
            "rebalance_every": 1, "min_assets": 4, "max_exposure": 0.8,
        }
        original, original_benchmark, _ = allocation(detail, scores, settings)
        buffered, benchmark, _ = allocation(detail, scores, {**settings, "rank_buffer": 1})
        self.assertListEqual(list(buffered["A"]), [0.4, 0.4, 0.0])
        self.assertListEqual(list(buffered["C"]), [0.0, 0.0, 0.4])
        self.assertEqual(original.at[dates[1], "A"], 0.0)
        assert_frame_equal(benchmark, original_benchmark)

    def test_stock_suspension_and_costs(self):
        dates = pd.date_range("2024-01-01", periods=5)
        prices = prepare_prices(pd.DataFrame({
            "date": list(dates) * 2,
            "symbol": ["A"] * 5 + ["B"] * 5,
            "open": [10, 10, np.nan, 12, 13] + [5] * 5,
            "close": [10, 10, np.nan, 12, 13] + [5] * 5,
            "can_buy": [1.0] * 7 + [0.0, 1.0, 1.0],
        }))
        targets = pd.DataFrame(np.nan, index=dates, columns=["A", "B"])
        targets.loc[dates[0]] = [0.6, 0]
        targets.loc[dates[1]] = [0, 0.5]
        targets.loc[dates[4]] = [0, 0]
        settings = {
            "market": "stock", "initial_cash": 1000, "lot_size": 10,
            "commission": 0, "slippage": 0, "sell_fee": 0.01,
        }
        nav, trades, holdings = simulate(prices, targets, settings)
        self.assertListEqual(list(trades["date"]), [dates[1], dates[3], dates[3]])
        self.assertListEqual(list(trades["side"]), ["buy", "sell", "buy"])
        self.assertListEqual(list(trades["size"]), [60, 60, 110])
        self.assertListEqual(list(trades["signal_date"]), [dates[0], dates[1], dates[1]])
        self.assertAlmostEqual(nav.at[dates[2], "equity"], 1000)
        self.assertAlmostEqual(nav.at[dates[3], "equity"], 1112.8)
        self.assertAlmostEqual(nav.at[dates[3], "commission"], 7.2)
        self.assertEqual(holdings.iloc[-1]["symbol"], "B")
        assert_frame_equal(simulate(prices, targets, settings)[0], nav)

    def test_future_reversal_uses_multiplier_settlement_and_fixed_fee(self):
        dates = pd.date_range("2024-01-01", periods=5)
        prices = prepare_prices(pd.DataFrame({
            "date": dates, "symbol": "F",
            "open": [100, 100, 110, 90, 95],
            "close": [100, 102, 107, 92, 95],
            "settle": [100, 0, 105, 91, 95],
        }))
        targets = pd.DataFrame({"F": [0.5, -0.5, 0, np.nan, np.nan]}, index=dates)
        settings = {
            "market": "future", "initial_cash": 10000,
            "commission": 0, "slippage": 0, "contract_multiplier": 10,
            "margin_rate": 0.1, "max_contracts": 2, "fee_per_contract": 2,
        }
        nav, trades, holdings = simulate(prices, targets, settings)
        self.assertListEqual(list(trades["size"]), [2, 4, 2])
        self.assertListEqual(list(trades["side"]), ["buy", "sell", "buy"])
        self.assertListEqual(list(holdings["quantity"]), [2, -2])
        self.assertListEqual(list(nav["equity"]), [10000, 10036, 10288, 10584, 10584])
        self.assertAlmostEqual(nav.at[dates[2], "margin_used"], 210)
        self.assertAlmostEqual(nav.at[dates[2], "cash"], 10078)

    def test_future_margin_call_waits_for_tradable_open(self):
        dates = pd.date_range("2024-01-01", periods=5)
        prices = prepare_prices(pd.DataFrame({
            "date": dates, "symbol": "F", "open": [10, 10, 16, 16, 16],
            "close": [10, 16, 16, 16, 16], "can_buy": [1, 1, 0, 1, 1],
        }))
        targets = pd.DataFrame({"F": [-1.0, np.nan, np.nan, np.nan, np.nan]}, index=dates)
        settings = {
            "market": "future", "initial_cash": 1000, "commission": 0, "slippage": 0,
            "contract_multiplier": 10, "margin_rate": 0.8, "max_contracts": 10,
        }
        nav, trades, holdings = simulate(prices, targets, settings)
        self.assertListEqual(list(trades["reason"]), ["target", "margin"])
        self.assertEqual(trades.iloc[-1]["signal_date"], dates[1])
        self.assertEqual(trades.iloc[-1]["date"], dates[3])
        self.assertEqual(nav.at[dates[2], "margin_used"], 1280)
        self.assertEqual(nav.at[dates[3], "equity"], 400)
        self.assertEqual(nav.at[dates[3], "margin_used"], 0)
        self.assertListEqual(list(holdings["quantity"]), [-10, -10])

    def test_stock_label_omits_open_blocked_by_trade_flags(self):
        dates = pd.date_range("2024-01-01", periods=10)
        prices = pd.DataFrame({
            "date": dates, "symbol": "A", "open": range(10, 20), "close": range(10, 20),
            "can_buy": [1, 1, 1, 0, 1, 1, 1, 1, 1, 1],
            "can_sell": [1, 1, 1, 1, 0, 1, 1, 1, 1, 1],
        })
        settings = {
            "market": "stock", "mode": "timing", "z_window": 2,
            "factors": {"trend": {"type": "momentum", "params": {"window": 1}}},
        }
        labels = analyze(prices, settings)["factors"]["forward_return"]
        self.assertTrue(pd.isna(labels.loc[(dates[2], "A")]))
        self.assertAlmostEqual(labels.loc[(dates[3], "A")], 15 / 14 - 1)


if __name__ == "__main__":
    unittest.main()
