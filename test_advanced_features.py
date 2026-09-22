import unittest
from datetime import datetime, timedelta, UTC
from paper_tracker import calculate_kelly_size, classify_time_horizon, PaperTradingEngine

class TestAdvancedFeatures(unittest.TestCase):
    def test_kelly_sizing(self):
        k_high = calculate_kelly_size(
            confidence=97.0, entry_price=0.90, target_price=0.99, stop_loss=0.82, side="BUY", account_equity=10000.0, fraction=0.25
        )
        self.assertGreaterEqual(k_high["size_usd"], 500.0)
        self.assertLessEqual(k_high["size_usd"], 1000.0)
        print(f"[TEST Kelly High] Size: ${k_high['size_usd']} ({k_high['kelly_fraction_pct']}%)")

        k_low = calculate_kelly_size(
            confidence=75.0, entry_price=0.50, target_price=0.58, stop_loss=0.45, side="BUY", account_equity=10000.0, fraction=0.25
        )
        self.assertLess(k_low["size_usd"], k_high["size_usd"])
        self.assertGreaterEqual(k_low["size_usd"], 50.0)
        print(f"[TEST Kelly Low] Size: ${k_low['size_usd']} ({k_low['kelly_fraction_pct']}%)")

    def test_horizon_classification(self):
        now = datetime.now(UTC)
        flash_m = {"end_date_iso": (now + timedelta(hours=24)).isoformat()}
        self.assertEqual(classify_time_horizon(flash_m)["code"], "flash")
        short_m = {"end_date_iso": (now + timedelta(days=7)).isoformat()}
        self.assertEqual(classify_time_horizon(short_m)["code"], "short")
        long_m = {"end_date_iso": (now + timedelta(days=30)).isoformat()}
        self.assertEqual(classify_time_horizon(long_m)["code"], "medium_long")
        print("[TEST Horizon] Flash, Short, Long all correctly categorized.")

    def test_trailing_stop(self):
        engine = PaperTradingEngine()
        engine.trades.clear()
        
        sig = {
            "signal_id": "test_sig_1",
            "dedupe_key": "TEST:M1:Yes:BUY",
            "strategy": "Oracle Sniping",
            "strategy_code": "S20",
            "token": "Yes",
            "side": "BUY",
            "confidence": 95.0,
            "entry_price": "0.8000",
            "target_price": "0.9800",
            "stop_loss": "0.7200",
            "edge": 0.15,
        }
        class MockMarket:
            market_id = "M1"
            question = "Will event occur?"
            liquidity = 50000
            volume_24h = 100000
            category = "Politics"
            mid_price = {"Yes": 0.8000}
            prices = {"Yes": 0.8000}

        trade = engine.evaluate_and_record_signal(sig, MockMarket())
        self.assertIsNotNone(trade)
        self.assertEqual(trade["status"], "OPEN")
        self.assertFalse(trade["break_even_active"])

        class MockRegistry:
            def get_market(self, mid):
                m = MockMarket()
                m.mid_price = {"Yes": 0.8400}
                return m

        engine.update_live_prices(MockRegistry())
        updated_trade = engine.trades["TEST:M1:Yes:BUY"]
        self.assertTrue(updated_trade["break_even_active"])
        self.assertTrue(updated_trade["trailing_stop_active"])
        self.assertGreaterEqual(updated_trade["stop_loss"], 0.80)
        print(f"[TEST Trailing Stop] Peak: {updated_trade['peak_price']}, Stop: {updated_trade['stop_loss']}")

        class MockRegistryDrop:
            def get_market(self, mid):
                m = MockMarket()
                m.mid_price = {"Yes": 0.8150}
                return m

        engine.update_live_prices(MockRegistryDrop())
        closed_trade = engine.trades["TEST:M1:Yes:BUY"]
        self.assertEqual(closed_trade["status"], "WON")
        self.assertIn("Trailing Stop activado", closed_trade["close_reason"])
        print(f"[TEST Trailing Close] Status: {closed_trade['status']}, Reason: {closed_trade['close_reason']}")

    def test_summary_and_equity_curve(self):
        engine = PaperTradingEngine()
        summary = engine.get_summary()
        self.assertIn("equity_history", summary)
        self.assertIn("sharpe_ratio", summary)
        self.assertIn("max_drawdown_pct", summary)
        self.assertIn("expectancy_usd", summary)
        print(f"[TEST Summary] Sharpe: {summary['sharpe_ratio']}, MaxDD: {summary['max_drawdown_pct']}%, Points: {len(summary['equity_history'])}")

if __name__ == "__main__":
    unittest.main()
