"""Motor de estrategias quant para Polymarket"""
from decimal import Decimal
from typing import Dict, List, Optional, Any
import uuid

from config import STRATEGY_PARAMS
from market_registry import MarketSnapshot, order_price, order_size


class StrategyEngine:
    """Motor de cálculo de estrategias en tiempo real"""

    def __init__(self):
        self.params = STRATEGY_PARAMS

    @staticmethod
    def _clamp_probability(value: Decimal) -> Decimal:
        return max(Decimal("0.001"), min(Decimal("0.999"), value))

    @staticmethod
    def _safe_profit_bps(entry: Decimal, target: Decimal) -> int:
        if entry <= 0:
            return 0
        return int(abs((target - entry) / entry) * 10000)

    def calculate_all(self, market: MarketSnapshot) -> List[Dict]:
        """Calcular todas las estrategias para un mercado"""
        signals = []

        # Solo mercados activos con liquidez
        if market.closed or market.resolved:
            return signals

        # Estrategia A: Market Making
        sig = self._market_making(market)
        if sig:
            signals.append(sig)

        # Estrategia B: Bundle Arbitrage
        sig = self._bundle_arbitrage(market)
        if sig:
            signals.append(sig)

        # Estrategia C: Mean Reversion
        sig = self._mean_reversion(market)
        if sig:
            signals.append(sig)

        # Estrategia D: Favorite-Longshot Bias
        sig = self._favorite_longshot(market)
        if sig:
            signals.append(sig)

        # Estrategia E: External Data (placeholder - requiere fuentes externas)
        sig = self._external_data(market)
        if sig:
            signals.append(sig)

        # Estrategia F: Whale Tracking con Data API pública de trades/positions
        sig = self._whale_tracking(market)
        if sig:
            signals.append(sig)

        return signals

    def _market_making(self, m: MarketSnapshot) -> Optional[Dict]:
        """Estrategia A: Market Making intra-mercado"""
        p = self.params["market_making"]

        for outcome in m.outcomes:
            if outcome not in m.spread or outcome not in m.best_bid:
                continue

            spread = m.spread[outcome]
            spread_bps = int((spread / m.mid_price[outcome]) * 10000) if m.mid_price.get(outcome) else 0

            # Verificar condiciones
            if spread_bps < p["min_spread_bps"]:
                continue
            if m.volume_24h < Decimal(str(p["min_volume_24h"])):
                continue
            if m.neg_risk:
                continue

            # Calcular depth (suma de size en ±10% del mid)
            depth_bid = Decimal("0")
            depth_ask = Decimal("0")
            mid = m.mid_price.get(outcome, Decimal("0"))
            if mid == 0:
                continue

            ob = m.order_book.get(outcome, {})
            for bid in ob.get("bids", []):
                price = order_price(bid)
                size = order_size(bid)
                if price >= mid * Decimal("0.9"):
                    depth_bid += size * price

            for ask in ob.get("asks", []):
                price = order_price(ask)
                size = order_size(ask)
                if price <= mid * Decimal("1.1"):
                    depth_ask += size * price

            if depth_bid < Decimal(str(p["min_depth_usd"])) or depth_ask < Decimal(str(p["min_depth_usd"])):
                continue

            expected_profit = spread_bps - m.taker_fee_bps

            return {
                "signal_id": str(uuid.uuid4())[:8],
                "strategy": "A: Market Making",
                "strategy_code": "MM",
                "side": "BOTH",
                "token": outcome,
                "entry_price": str(m.mid_price[outcome]),
                "bid_price": str(m.best_bid[outcome] + m.tick_size),
                "ask_price": str(m.best_ask[outcome] - m.tick_size),
                "size": str(min(depth_bid, depth_ask) * Decimal("0.1")),
                "confidence": min(85, 50 + spread_bps // 2),
                "urgency": "MEDIUM",
                "expected_profit_bps": expected_profit,
                "trigger_reason": f"Spread de {spread_bps} bps en {outcome}. Depth: ${float(depth_bid):.0f} bid / ${float(depth_ask):.0f} ask",
                "status": "ACTIVE",
                "metrics": {
                    "spread_bps": spread_bps,
                    "depth_bid": str(depth_bid),
                    "depth_ask": str(depth_ask),
                    "volume_24h": str(m.volume_24h),
                }
            }
        return None

    def _bundle_arbitrage(self, m: MarketSnapshot) -> Optional[Dict]:
        """Estrategia B: Bundle Arbitrage (YES + NO != $1)"""
        p = self.params["bundle_arbitrage"]

        if len(m.outcomes) != 2 or "Yes" not in m.outcomes or "No" not in m.outcomes:
            return None

        yes_bid = m.best_bid.get("Yes")
        yes_ask = m.best_ask.get("Yes")
        no_bid = m.best_bid.get("No")
        no_ask = m.best_ask.get("No")

        if not all([yes_bid, yes_ask, no_bid, no_ask]):
            return None

        # Caso 1: Comprar ambos por menos de $1
        buy_bundle = yes_ask + no_ask
        if buy_bundle < Decimal("1.0") - Decimal(str(p["min_inefficiency"])):
            profit = Decimal("1.0") - buy_bundle
            max_size = min(
                order_size((m.order_book.get("Yes", {}).get("asks") or [{}])[0]),
                order_size((m.order_book.get("No", {}).get("asks") or [{}])[0])
            )
            return {
                "signal_id": str(uuid.uuid4())[:8],
                "strategy": "B: Bundle Arbitrage",
                "strategy_code": "BA",
                "side": "BUY_BUNDLE",
                "token": "BOTH",
                "entry_price": str(buy_bundle),
                "target_price": "1.00",
                "size": str(max_size),
                "confidence": 95,
                "urgency": "HIGH",
                "expected_profit_bps": int(profit * 10000),
                "trigger_reason": f"YES ask ({yes_ask}) + NO ask ({no_ask}) = {buy_bundle:.4f}. Profit: ${profit:.4f} por bundle",
                "status": "ACTIVE",
                "metrics": {
                    "yes_ask": str(yes_ask),
                    "no_ask": str(no_ask),
                    "bundle_sum": str(buy_bundle),
                    "profit_per_unit": str(profit),
                }
            }

        # Caso 2: Vender ambos por más de $1
        sell_bundle = yes_bid + no_bid
        if sell_bundle > Decimal("1.0") + Decimal(str(p["min_inefficiency"])):
            profit = sell_bundle - Decimal("1.0")
            max_size = min(
                order_size((m.order_book.get("Yes", {}).get("bids") or [{}])[0]),
                order_size((m.order_book.get("No", {}).get("bids") or [{}])[0])
            )
            return {
                "signal_id": str(uuid.uuid4())[:8],
                "strategy": "B: Bundle Arbitrage",
                "strategy_code": "BA",
                "side": "SELL_BUNDLE",
                "token": "BOTH",
                "entry_price": str(sell_bundle),
                "target_price": "1.00",
                "size": str(max_size),
                "confidence": 95,
                "urgency": "HIGH",
                "expected_profit_bps": int(profit * 10000),
                "trigger_reason": f"YES bid ({yes_bid}) + NO bid ({no_bid}) = {sell_bundle:.4f}. Profit: ${profit:.4f} por bundle",
                "status": "ACTIVE",
                "metrics": {
                    "yes_bid": str(yes_bid),
                    "no_bid": str(no_bid),
                    "bundle_sum": str(sell_bundle),
                    "profit_per_unit": str(profit),
                }
            }

        return None

    def _mean_reversion(self, m: MarketSnapshot) -> Optional[Dict]:
        """Estrategia C: Mean Reversion"""
        p = self.params["mean_reversion"]

        if m.liquidity < Decimal(str(p["min_liquidity"])):
            return None
        if m.volume_24h < Decimal(str(p["min_volume_24h"])):
            return None

        min_history_points = int(p.get("min_history_points", 5))

        # 1) Señal intradía con historial local. Antes exigía siempre 15m completos
        # y velocidad >5%; al arrancar localmente casi nunca había suficientes puntos.
        for outcome in m.outcomes:
            hist = m.price_history.get(outcome)
            if not hist:
                continue

            current = m.mid_price.get(outcome)
            if not current:
                continue

            if len(hist.prices) < min_history_points:
                continue

            z_score = hist.z_score(15, current)
            velocity = hist.velocity_1m()

            if z_score is None or velocity is None:
                continue

            if abs(z_score) < Decimal(str(p["z_score_threshold"])):
                continue
            if abs(velocity) < Decimal(str(p["price_velocity_threshold"])):
                continue

            sma = hist.sma(15)
            side = "BUY" if z_score < 0 else "SELL"
            entry = current
            target = sma if sma else current * (Decimal("1.02") if side == "BUY" else Decimal("0.98"))
            stop = entry * (Decimal("0.97") if side == "BUY" else Decimal("1.03"))

            return {
                "signal_id": str(uuid.uuid4())[:8],
                "strategy": "C: Mean Reversion",
                "strategy_code": "MR",
                "side": side,
                "token": outcome,
                "entry_price": str(entry),
                "target_price": str(target),
                "stop_loss": str(stop),
                "size": "100",
                "confidence": min(75, 50 + int(abs(z_score)) * 10),
                "urgency": "HIGH" if abs(z_score) > 3 else "MEDIUM",
                "expected_profit_bps": int(abs((target - entry) / entry) * 10000),
                "trigger_reason": f"Z-score: {float(z_score):.2f}, Velocidad 1m: {float(velocity)*100:.1f}%. Sobre-reacción detectada en {outcome}.",
                "status": "ACTIVE",
                "dedupe_key": f"MR:local:{m.market_id}:{outcome}:{side}",
                "metrics": {
                    "source": "local_price_history",
                    "z_score": float(z_score),
                    "velocity_1m": float(velocity),
                    "sma_15m": str(sma) if sma else "N/A",
                }
            }

        # 2) Fallback con cambios de Gamma. Útil justo al iniciar el scanner:
        # Gamma ya trae oneDay/oneWeek change aunque nuestro historial local esté vacío.
        fallback_token = "Yes" if "Yes" in m.outcomes else (m.outcomes[0] if m.outcomes else "Yes")
        current = m.gamma_last_trade_price
        if current is None:
            current = m.mid_price.get(fallback_token) or m.prices.get(fallback_token)
        if current is None or current <= Decimal("0.01") or current >= Decimal("0.99"):
            return None

        change_1d = m.gamma_one_day_price_change
        change_1w = m.gamma_one_week_price_change
        selected_change = None
        selected_window = None

        if change_1d is not None and abs(change_1d) >= Decimal(str(p.get("gamma_1d_change_threshold", 0.02))):
            selected_change = change_1d
            selected_window = "1d"
        elif change_1w is not None and abs(change_1w) >= Decimal(str(p.get("gamma_1w_change_threshold", 0.04))):
            selected_change = change_1w
            selected_window = "1w"

        if selected_change is None:
            return None

        side = "SELL" if selected_change > 0 else "BUY"
        reversion_fraction = Decimal(str(p.get("reversion_fraction", 0.50)))
        target = self._clamp_probability(current - (selected_change * reversion_fraction))
        stop = self._clamp_probability(current + (selected_change * Decimal("0.60")))
        confidence = min(78, 52 + int(abs(selected_change) * 1000))

        return {
            "signal_id": str(uuid.uuid4())[:8],
            "strategy": "C: Mean Reversion",
            "strategy_code": "MR",
            "side": side,
            "token": fallback_token,
            "entry_price": str(current),
            "target_price": str(target),
            "stop_loss": str(stop),
            "size": "100",
            "confidence": confidence,
            "urgency": "HIGH" if abs(selected_change) >= Decimal("0.08") else "MEDIUM",
            "expected_profit_bps": self._safe_profit_bps(current, target),
            "trigger_reason": f"Cambio Gamma {selected_window}: {float(selected_change)*100:.1f}¢ en mercado líquido. Fallback mean-reversion hacia {target}.",
            "status": "ACTIVE",
            "dedupe_key": f"MR:gamma:{m.market_id}:{fallback_token}:{selected_window}:{side}",
            "metrics": {
                "source": "gamma_price_change",
                "change_window": selected_window,
                "price_change": float(selected_change),
                "liquidity": str(m.liquidity),
                "volume_24h": str(m.volume_24h),
            }
        }
        return None

    def _favorite_longshot(self, m: MarketSnapshot) -> Optional[Dict]:
        """Estrategia D: Favorite-Longshot Bias"""
        p = self.params["favorite_longshot"]

        if m.volume_24h < Decimal(str(p["min_volume_24h"])):
            return None

        for outcome in m.outcomes:
            price = m.mid_price.get(outcome)
            if not price:
                continue

            hist = m.price_history.get(outcome)
            z_score = hist.z_score(15, price) if hist else None

            # FAVORITE: precio > 0.85, comprar si infravalorado temporalmente
            if price > Decimal(str(p["favorite_threshold"])):
                if z_score and z_score < Decimal("-1.5"):
                    return {
                        "signal_id": str(uuid.uuid4())[:8],
                        "strategy": "D: Favorite-Longshot",
                        "strategy_code": "FLB",
                        "side": "BUY",
                        "token": outcome,
                        "entry_price": str(price),
                        "target_price": str(price * Decimal("1.02")),
                        "stop_loss": str(price * Decimal("0.97")),
                        "size": "200",
                        "confidence": 60,
                        "urgency": "MEDIUM",
                        "expected_profit_bps": 200,
                        "trigger_reason": f"Favorito {outcome} a ${price} con z-score {float(z_score):.2f} (infravalorado temporal). Sesgo FLB.",
                        "status": "ACTIVE",
                        "metrics": {
                            "price": str(price),
                            "z_score": float(z_score),
                            "type": "favorite_undervalued",
                        }
                    }

            # LONGSHOT: precio < 0.15, vender si sobrevalorado
            if price < Decimal(str(p["longshot_threshold"])):
                if z_score and z_score > Decimal("2.0"):
                    return {
                        "signal_id": str(uuid.uuid4())[:8],
                        "strategy": "D: Favorite-Longshot",
                        "strategy_code": "FLB",
                        "side": "SELL",
                        "token": outcome,
                        "entry_price": str(price),
                        "target_price": str(price * Decimal("0.80")),
                        "stop_loss": str(price * Decimal("1.50")),
                        "size": "500",
                        "confidence": 55,
                        "urgency": "MEDIUM",
                        "expected_profit_bps": 2000,
                        "trigger_reason": f"Longshot {outcome} a ${price} con z-score {float(z_score):.2f} (sobrevalorado por euforia). Sesgo FLB.",
                        "status": "ACTIVE",
                        "metrics": {
                            "price": str(price),
                            "z_score": float(z_score),
                            "type": "longshot_overvalued",
                        }
                    }
        return None

    def _external_data(self, m: MarketSnapshot) -> Optional[Dict]:
        """Estrategia E: Latencia en datos externos (placeholder)"""
        # Esta estrategia requiere integración con fuentes externas (NOAA, ESPN, FRED)
        # Por ahora retorna None - se puede implementar conectando APIs externas
        return None

    def _whale_tracking(self, m: MarketSnapshot) -> Optional[Dict]:
        """Estrategia F: Whale Tracking con trades grandes enriquecidos."""
        p = self.params["whale_tracking"]
        min_position = Decimal(str(p.get("min_whale_position", 5000)))
        min_winrate = Decimal(str(p.get("min_whale_winrate", 0.60)))

        # El backend llena m.whale_signals desde Data API /trades + /positions.
        # Aquí solo convertimos la mejor señal smart-money en una señal operable.
        candidates = []
        for ws in m.whale_signals:
            try:
                winrate = Decimal(str(ws.get("wallet_winrate", 0)))
                max_position = Decimal(str(ws.get("wallet_max_position_size", 0)))
                current_value = Decimal(str(ws.get("wallet_current_value", 0)))
            except Exception:
                continue

            if max_position < min_position and current_value < min_position:
                continue
            if winrate < min_winrate:
                continue
            candidates.append(ws)

        if not candidates:
            return None

        best = sorted(
            candidates,
            key=lambda x: (
                float(x.get("wallet_winrate", 0)),
                float(x.get("wallet_max_position_size", 0)),
                float(x.get("notional", 0) or 0),
            ),
            reverse=True,
        )[0]

        token = str(best.get("outcome") or "Yes")
        side = str(best.get("side") or "BUY").upper()
        entry = m.mid_price.get(token) or m.prices.get(token) or Decimal(str(best.get("price", 0)))
        if entry <= 0:
            return None

        if side == "BUY":
            target = self._clamp_probability(entry * Decimal("1.08"))
            stop = self._clamp_probability(entry * Decimal("0.92"))
        else:
            target = self._clamp_probability(entry * Decimal("0.92"))
            stop = self._clamp_probability(entry * Decimal("1.08"))

        wallet = str(best.get("wallet") or "")
        winrate = float(best.get("wallet_winrate", 0))
        max_position = Decimal(str(best.get("wallet_max_position_size", 0)))
        notional = Decimal(str(best.get("notional", 0)))
        source = str(best.get("source") or "data_api_trades_positions")
        observed_size = Decimal(str(best.get("size") or best.get("amount") or 0))
        confidence = min(88, 55 + int(winrate * 25) + min(10, int(max_position / Decimal("10000"))))
        action_text = "mantiene" if "holders" in source else "hizo"

        return {
            "signal_id": str(uuid.uuid4())[:8],
            "strategy": "F: Whale Tracking",
            "strategy_code": "WT",
            "side": side,
            "token": token,
            "entry_price": str(entry),
            "target_price": str(target),
            "stop_loss": str(stop),
            "size": str(min(max(observed_size, max_position), Decimal("1000"))),
            "confidence": confidence,
            "urgency": "HIGH" if notional >= Decimal("1000") else "MEDIUM",
            "expected_profit_bps": self._safe_profit_bps(entry, target),
            "trigger_reason": f"Wallet {wallet[:8]}... con win-rate {winrate*100:.0f}% y posición máx {max_position:.0f} shares {action_text} {observed_size:.0f} shares en {token}. Señal smart-money.",
            "status": "ACTIVE",
            "dedupe_key": f"WT:{m.market_id}:{wallet}:{token}:{side}",
            "metrics": {
                "wallet": wallet,
                "wallet_winrate": winrate,
                "wallet_positions_checked": best.get("wallet_positions_checked", 0),
                "wallet_max_position_size": str(max_position),
                "wallet_current_value": str(best.get("wallet_current_value", 0)),
                "trade_notional": str(notional),
                "observed_size": str(observed_size),
                "source": source,
            }
        }


# Instancia global
engine = StrategyEngine()
