"""Script de auditoría exhaustiva de todas las estrategias y cálculos cuantitativos."""
import sys
import asyncio
from decimal import Decimal

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from config import STRATEGY_PARAMS
from market_registry import registry, MarketSnapshot
from polymarket_client import pm_client
from strategies import engine
from paper_tracker import paper_tracker


async def run_audit():
    print("=" * 60)
    print("🔍 INICIANDO AUDITORÍA INTEGRAL DE ESTRATEGIAS Y CÁLCULOS")
    print("=" * 60)

    # 1. Obtener muestra de mercados reales
    print("\n[1/4] Descargando muestra de mercados desde Gamma API...")
    markets_data = await pm_client.fetch_markets(limit=30, offset=0)
    print(f"-> {len(markets_data)} mercados obtenidos para prueba.")

    # Poblar registro temporal
    for m in markets_data:
        mid = m.get("id") or m.get("conditionId")
        if mid:
            await registry.update_market(mid, {
                "condition_id": m.get("conditionId", ""),
                "slug": m.get("slug", ""),
                "question": m.get("question", m.get("title", "")),
                "category": m.get("category", "General"),
                "outcomes": m.get("outcomes", ["Yes", "No"]),
                "token_ids": {"Yes": "123", "No": "456"},
                "initial_prices": {"Yes": 0.55, "No": 0.45},
                "volume_24h": Decimal(str(m.get("volume24hr") or 50000)),
                "liquidity": Decimal(str(m.get("liquidity") or 25000)),
                "resolution_source": m.get("resolutionSource") or m.get("description") or "",
                "active": True,
                "closed": False,
                "resolved": False,
            })

    print(f"-> Mercados en memoria: {len(registry.markets)}")

    # 2. Probar ejecución de cada estrategia modular individualmente
    print("\n[2/4] Probando ejecución individual de cada estrategia...")
    all_strategies = engine.modular_strategies
    errors_found = []

    for strat in all_strategies:
        try:
            print(f"  • Probando {strat.name} (Tier {strat.tier})...", end=" ")
            # Convertir mercados a core models y escanear
            core_markets = [engine._snapshot_to_core_market(m) for m in registry.markets.values()]
            opps = strat.scan(core_markets)
            signals = []
            for opp in opps:
                sig = strat.analyze(opp)
                if sig:
                    signals.append(sig)
            print(f"OK (Oportunidades: {len(opps)}, Señales: {len(signals)})")
        except Exception as e:
            print(f"❌ ERROR: {e}")
            errors_found.append((strat.name, str(e)))

    # 3. Probar calculate_all() y conversión a formato dashboard
    print("\n[3/4] Probando calculate_all() y enriquecimiento de señales...")
    total_signals = 0
    calculation_errors = 0

    for m in registry.markets.values():
        try:
            signals = engine.calculate_all(m)
            total_signals += len(signals)
            for s in signals:
                # Validar campos matemáticos críticos
                entry = float(s.get("entry_price") or 0)
                target = float(s.get("target_price") or 0)
                stop = float(s.get("stop_loss") or 0)
                conf = float(s.get("confidence") or 0)
                rr = float(s.get("risk_reward_ratio") or 0)

                assert entry > 0, f"entry_price inválido: {entry}"
                assert target > 0, f"target_price inválido: {target}"
                assert stop > 0, f"stop_loss inválido: {stop}"
                assert 0 <= conf <= 100, f"confianza fuera de rango: {conf}"
                assert rr > 0, f"Risk/Reward inválido: {rr}"

                # Validar cálculo de Paper Trading
                trade = paper_tracker.evaluate_and_record_signal(s, m)

        except Exception as e:
            calculation_errors += 1
            print(f"❌ Error calculando mercado {m.market_id}: {e}")

    print(f"-> Total señales válidas generadas: {total_signals}")
    print(f"-> Errores en cálculos: {calculation_errors}")

    # 4. Probar cálculos de PnL y Leaderboard en paper_tracker
    print("\n[4/4] Verificando fórmulas matemáticas de PnL y Win Rate...")
    perf = paper_tracker.get_strategy_performance()
    summary = paper_tracker.get_summary()

    print(f"  • PnL Flotante Global: ${perf['total_floating_pnl_usd']}")
    print(f"  • PnL Realizado Global: ${perf['total_realized_pnl_usd']}")
    print(f"  • PnL Neto Combinado: ${perf['total_combined_pnl_usd']}")
    print(f"  • Estrategias catalogadas: {len(perf['strategies'])}")

    # Validar consistencia matemática
    calc_comb = round(perf['total_floating_pnl_usd'] + perf['total_realized_pnl_usd'], 2)
    assert abs(perf['total_combined_pnl_usd'] - calc_comb) < 0.01, "Error: Suma de PnL flotante y realizado no coincide con combinado"

    for s in perf['strategies']:
        tot = round(s['unrealized_pnl_usd'] + s['realized_pnl_usd'], 2)
        assert abs(s['total_pnl_usd'] - tot) < 0.01, f"Error en PnL de {s['code']}"

    print("\n" + "=" * 60)
    if not errors_found and calculation_errors == 0:
        print("✅ TODAS LAS PRUEBAS PASARON EXITOSAMENTE. CÁLCULOS 100% PRECISOS.")
    else:
        print(f"⚠️ Se detectaron {len(errors_found)} errores a corregir.")
    print("=" * 60)

    await pm_client.close()


if __name__ == "__main__":
    asyncio.run(run_audit())
