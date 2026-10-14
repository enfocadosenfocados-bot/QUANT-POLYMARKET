"""Test funcional del Modo Híbrido (órdenes live simuladas contra el libro real)."""
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid_execution import simulated_live_executor, walk_book  # noqa: E402
from paper_tracker import HybridTradingEngine, PaperTradingEngine  # noqa: E402


class FakeMarket:
    market_id = "mkt-1"
    question = "¿Sube BTC por encima de 100k?"
    category = "crypto"
    liquidity = Decimal("50000")
    volume_24h = Decimal("20000")
    end_date = None
    order_book = {
        "Yes": {
            "bids": [{"price": "0.44", "size": "100"}, {"price": "0.42", "size": "400"}],
            "asks": [{"price": "0.46", "size": "50"}, {"price": "0.48", "size": "500"}],
        }
    }
    mid_price = {"Yes": Decimal("0.45")}
    prices = {"Yes": Decimal("0.45")}


def signal(**over):
    base = {
        "strategy_code": "S10",
        "strategy": "Yes-No Bias Exploitation",
        "token": "Yes",
        "side": "BUY",
        "confidence": 80.0,
        "entry_price": "0.4600",
        "target_price": "0.5600",
        "stop_loss": "0.4200",
        "edge": 0.06,
        "dedupe_key": "S10:mkt-1:Yes:BUY",
    }
    base.update(over)
    return base


def main():
    m = FakeMarket()

    # 1) walk_book: la orden LIMIT sólo cruza niveles <= límite
    wb = walk_book(
        [{"price": 0.46, "size": 50}, {"price": 0.48, "size": 500}], "BUY", 108, 0.46
    )
    assert wb["filled_shares"] == 50, wb
    assert abs(wb["avg_price"] - 0.46) < 1e-9, wb
    assert wb["levels_consumed"] == 1, wb

    # 2) Taker: fill parcial por falta de profundidad al límite
    ex = simulated_live_executor.execution(signal(), m, 50.0)
    assert ex["skip"] is False, ex
    assert ex["status"] == "PARTIAL", ex
    assert ex["trade_fields"]["order_status"] == "PARTIAL"
    assert 0.0 < ex["trade_fields"]["fill_ratio"] < 1.0, ex
    assert ex["trade_fields"]["order_payload"]["side"] == "BUY"
    assert ex["trade_fields"]["order_payload"]["simulated"] is True

    # 3) Taker con libro profundo: FILLED y VWAP real por encima del mejor ask
    m2 = FakeMarket()
    m2.order_book = {
        "Yes": {
            "bids": [{"price": "0.44", "size": "100"}],
            "asks": [{"price": "0.45", "size": "10"}, {"price": "0.46", "size": "10000"}],
        }
    }
    ex2 = simulated_live_executor.execution(signal(entry_price="0.4600"), m2, 20.0)
    assert ex2["status"] == "FILLED", ex2
    assert ex2["trade_fields"]["fill_ratio"] == 1.0, ex2
    assert ex2["exec_price"] < 0.4600, ex2  # compró parte al mejor ask 0.45
    assert ex2["trade_fields"]["book_levels_consumed"] == 2, ex2

    # 4) Maker: fill al límite, sin fee taker y con rebate positivo
    ex3 = simulated_live_executor.execution(signal(is_maker=True), m, 50.0)
    assert ex3["status"] == "MAKER_FILLED", ex3
    assert ex3["fee_usd"] == 0.0 and ex3["rebate_usd"] > 0, ex3
    assert ex3["slippage_bps"] == 0.0, ex3

    # 5) Sin libro -> skip (no rompe el bot)
    class NoBook(FakeMarket):
        order_book = {}

    ex4 = simulated_live_executor.execution(signal(), NoBook(), 50.0)
    assert ex4["skip"] is True, ex4

    # 6) Motor completo: misma pipeline que paper + orden live simulada
    storage = Path("/tmp/hybrid_test_trades.json")
    orders = Path("/tmp/hybrid_test_orders.json")
    for p in (storage, orders):
        p.unlink(missing_ok=True)

    hy = HybridTradingEngine(storage_path=storage, orders_path=orders)
    trade = hy.evaluate_and_record_signal(signal(), FakeMarket())
    assert trade is not None, "el híbrido debió registrar el trade"
    assert trade["engine"] == "hybrid", trade.get("engine")
    assert trade["order_status"] in ("FILLED", "PARTIAL", "MAKER_FILLED"), trade
    assert trade["order_id"].startswith("SIM-"), trade["order_id"]
    assert trade["entry_price"] == trade["book_avg_price"], (trade["entry_price"], trade["book_avg_price"])
    assert orders.exists(), "el log de órdenes simuladas debe persistirse"
    logged = json.loads(orders.read_text(encoding="utf-8"))
    assert len(logged["orders"]) == 1, logged
    assert logged["orders"][0]["status"] == trade["order_status"]
    assert hy.get_hybrid_stats()["orders_logged"] == 1

    # 7) Regresión: el paper clásico NO cambia su comportamiento
    pstorage = Path("/tmp/paper_test_trades.json")
    pstorage.unlink(missing_ok=True)
    pt = PaperTradingEngine(storage_path=pstorage, budget_mode="per_strategy")
    ptrade = pt.evaluate_and_record_signal(signal(dedupe_key="S10:p:Yes:BUY"), FakeMarket())
    assert ptrade is not None, "el paper debe seguir registrando igual"
    assert ptrade["engine"] == "paper"
    assert "order_status" not in ptrade
    # El paper usa el precio de señal + slippage fijo; el híbrido, el libro real.
    assert ptrade["entry_price"] != ptrade["book_avg_price"] if "book_avg_price" in ptrade else True

    print("OK 1 walk_book        ->", wb)
    print("OK 2 taker parcial    -> status=%s ratio=%.2f slip=%.2fbps" % (
        ex["status"], ex["trade_fields"]["fill_ratio"], ex["slippage_bps"]))
    print("OK 3 taker filled     -> exec=%.4f niveles=%d" % (
        ex2["exec_price"], ex2["trade_fields"]["book_levels_consumed"]))
    print("OK 4 maker            -> rebate=$%.4f" % ex3["rebate_usd"])
    print("OK 5 sin libro        ->", ex4["reason"])
    print("OK 6 motor hibrido    ->", {k: trade[k] for k in
          ("strategy_code", "order_status", "fill_ratio", "entry_price", "book_slippage_bps")})
    print("OK 7 regresion paper  ->", {k: ptrade[k] for k in
          ("strategy_code", "entry_price", "execution_price", "engine")})
    print("    paper entry=%.4f (slippage fijo) vs hibrido entry=%.4f (libro real)" % (
        ptrade["entry_price"], trade["entry_price"]))
    print("\n[TODOS LOS TEST DEL MODO HIBRIDO PASARON]")


if __name__ == "__main__":
    main()
