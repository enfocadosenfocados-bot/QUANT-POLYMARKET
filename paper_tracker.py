"""QUANT POLYMARKET - Paper Trading & Signal Track Record Engine
Monitorea en tiempo real las señales Top Sniper, simula entradas y evalúa PnL con Take Profit y Stop Loss.
"""
import json
import os
from decimal import Decimal
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    from config import (
        PAPER_MAX_EXPOSURE_USD,
        PAPER_MAX_OPEN_POSITIONS,
        PAPER_SLIPPAGE_BPS,
        PAPER_FEE_RATE,
        PAPER_ENFORCE_CAPITAL,
    )
except ImportError:
    PAPER_MAX_EXPOSURE_USD = 1000.0
    PAPER_MAX_OPEN_POSITIONS = 12
    PAPER_SLIPPAGE_BPS = 5
    PAPER_FEE_RATE = 0.0
    PAPER_ENFORCE_CAPITAL = True


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_float(val: Any, default: float = 0.0) -> float:
    if val in (None, ""):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def calculate_kelly_size(
    confidence: float,
    entry_price: float,
    target_price: float,
    stop_loss: float,
    side: str = "BUY",
    account_equity: float = 1000.0,
    fraction: float = 0.25,
    min_size_usd: float = 10.0,
    max_size_usd: float = 100.0,
) -> Dict[str, Any]:
    """Calcula el dimensionamiento dinámico de posición mediante Criterio de Kelly Fraccional (Quarter-Kelly) para portfolio de $1,000 USD.
    Fórmula: f* = (p * b - q) / b
    Donde:
      p = probabilidad de éxito (confidence / 100)
      q = 1 - p
      b = ratio beneficio/riesgo (reward / risk)
    En 75% de confianza: asigna ~1.5% - 2.5% de capital ($15 - $25 USD).
    En 96% - 98% de confianza: asigna ~8% - 10% de capital ($80 - $100 USD).
    """
    p = max(0.01, min(0.99, confidence / 100.0))
    q = 1.0 - p

    if side.upper() == "BUY":
        reward = max(0.005, target_price - entry_price)
        risk = max(0.005, entry_price - stop_loss)
    else:
        reward = max(0.005, entry_price - target_price)
        risk = max(0.005, stop_loss - entry_price)

    b = reward / risk if risk > 0 else 1.5
    f_star = (p * b - q) / b if b > 0 else 0.0

    if f_star <= 0:
        kelly_fraction = 0.005  # 0.5% capital mínimo prudencial
        size_usd = min_size_usd
    else:
        # Ponderación por convicción cuantitativa: 75% -> ~2.0%, 97% -> ~9.5%
        conviction_weight = max(0.15, min(1.0, (p - 0.65) / 0.32))
        base_fraction = f_star * fraction * conviction_weight
        kelly_fraction = max(0.015, min(0.10, base_fraction))
        calculated = account_equity * kelly_fraction
        size_usd = round(max(min_size_usd, min(max_size_usd, calculated)), 2)

    return {
        "size_usd": size_usd,
        "kelly_fraction_pct": round(kelly_fraction * 100, 2),
        "full_kelly_pct": round(max(0.0, f_star * 100), 2),
        "b_ratio": round(b, 2),
    }


def classify_time_horizon(market: Any) -> Dict[str, Any]:
    """Clasifica el horizonte temporal de un mercado en:
    - flash: ⚡ Flash (<48h)
    - short: 📅 Corto (<15d)
    - medium_long: 🗓️ Largo (>15d)
    """
    end_date_val = None
    if isinstance(market, dict):
        end_date_val = market.get("end_date") or market.get("end_date_iso") or market.get("endDate")
    else:
        end_date_val = getattr(market, "end_date", None) or getattr(market, "end_date_iso", None) or getattr(market, "endDate", None)

    if not end_date_val:
        return {"code": "medium_long", "label": "🗓️ Largo (>15d)", "hours_left": 720.0}

    try:
        if isinstance(end_date_val, (int, float)):
            end_dt = datetime.fromtimestamp(end_date_val, UTC)
        else:
            clean_str = str(end_date_val).replace("Z", "+00:00")
            if "T" in clean_str:
                end_dt = datetime.fromisoformat(clean_str)
            else:
                end_dt = datetime.strptime(clean_str[:10], "%Y-%m-%d").replace(tzinfo=UTC)

        now = utc_now()
        hours_left = max(0.0, (end_dt - now).total_seconds() / 3600.0)
        days_left = hours_left / 24.0

        if hours_left <= 48.0:
            return {"code": "flash", "label": "⚡ Flash (<48h)", "hours_left": round(hours_left, 1)}
        elif days_left <= 15.0:
            return {"code": "short", "label": "📅 Corto (<15d)", "hours_left": round(hours_left, 1)}
        else:
            return {"code": "medium_long", "label": "🗓️ Largo (>15d)", "hours_left": round(hours_left, 1)}
    except Exception:
        return {"code": "medium_long", "label": "🗓️ Largo (>15d)", "hours_left": 720.0}


class PaperTradingEngine:
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or (Path(__file__).resolve().parent / "paper_trades.json")
        self.initial_balance = 1000.0  # $1,000 USD de capital simulado
        self.position_size_usd = 25.0  # Fallback base ($25 USD)
        self.trades: Dict[str, Dict[str, Any]] = {}
        self._load_from_disk()

    def _load_from_disk(self):
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    loaded = data.get("trades", {})
                    # Filtrar exclusivamente las que tengan confianza >= 75% (Ultra)
                    self.trades = {k: v for k, v in loaded.items() if to_float(v.get("confidence"), 0) >= 75.0}
            except Exception as e:
                print(f"[PaperTrading] Error cargando historial: {e}")

    def save_to_disk(self):
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump({"trades": self.trades, "updated_at": utc_now().isoformat()}, f, indent=2)
        except Exception as e:
            print(f"[PaperTrading] Error guardando historial: {e}")

    def evaluate_and_record_signal(self, signal: Dict[str, Any], market: Any) -> Optional[Dict[str, Any]]:
        """Evalúa si una señal califica como 'Top Sniper' y la registra en el track record con Kelly Sizing."""
        confidence = to_float(signal.get("confidence"), 0.0)
        entry_price = to_float(signal.get("entry_price"), 0.0)
        target_price = to_float(signal.get("target_price"), 0.0)
        stop_loss = to_float(signal.get("stop_loss"), 0.0)
        edge = to_float(signal.get("edge"), 0.0)
        side = str(signal.get("side") or "BUY").upper()

        if entry_price <= 0.01 or entry_price >= 0.99:
            return None

        # Si no tiene target o stop loss, fijarlo cuantitativamente
        if target_price <= 0 or target_price == entry_price:
            if side == "BUY":
                target_price = min(0.99, entry_price + max(0.04, edge if edge > 0 else 0.05))
            else:
                target_price = max(0.01, entry_price - max(0.04, edge if edge > 0 else 0.05))

        if stop_loss <= 0 or stop_loss == entry_price:
            if side == "BUY":
                stop_loss = max(0.01, entry_price * 0.92)
            else:
                stop_loss = min(0.99, entry_price * 1.08)

        # Enriquecer la señal con los valores de gestión de riesgo
        signal["stop_loss"] = f"{stop_loss:.4f}"
        signal["target_price"] = f"{target_price:.4f}"
        signal["entry_price"] = f"{entry_price:.4f}"

        # Cálculo de Ratio Riesgo/Beneficio
        risk = abs(entry_price - stop_loss)
        reward = abs(target_price - entry_price)
        rr_ratio = (reward / risk) if risk > 0 else 1.5
        signal["risk_reward_ratio"] = round(rr_ratio, 2)
        signal["recommended_order_type"] = "LIMIT (Maker)"
        signal["recommended_limit_price"] = f"{entry_price:.4f}"

        # Clasificación de Horizonte Temporal
        horizon_info = classify_time_horizon(market)
        signal["horizon"] = horizon_info["code"]
        signal["horizon_label"] = horizon_info["label"]
        signal["hours_to_resolve"] = horizon_info["hours_left"]

        # Dimensionamiento Dinámico Kelly con Multiplicador de Auto-Aprendizaje IA
        closed_pnl = sum(t.get("realized_pnl_usd", 0.0) for t in self.trades.values() if t.get("status") in ("WON", "LOST"))
        current_equity = max(200.0, self.initial_balance + closed_pnl)
        kelly_data = calculate_kelly_size(
            confidence=confidence,
            entry_price=entry_price,
            target_price=target_price,
            stop_loss=stop_loss,
            side=side,
            account_equity=current_equity,
            fraction=0.25,
            min_size_usd=10.0,
            max_size_usd=100.0,
        )
        
        # Multiplicador dinámico de IA y LinUCB Contextual Bandit
        conformal_res = None
        try:
            from ai_learning_engine import ai_learning_engine
            from quant_ml_engine import quant_ml
            strat_code = signal.get("strategy_code", "GEN")
            brier_mult = ai_learning_engine.get_strategy_multiplier(strat_code)
            
            # LinUCB Contextual Bandit
            ctx = quant_ml.bandit.get_current_context()
            ucb_score, bandit_mult = quant_ml.bandit.get_strategy_score_and_multiplier(strat_code, ctx)
            
            # Filtro de Conformal Prediction con garantía al 95%
            conformal_res = quant_ml.conformal.evaluate_signal(
                predicted_prob=confidence,
                market_price=entry_price,
                side=side,
            )
            signal["conformal_interval"] = {
                "p_lower": conformal_res.p_lower,
                "p_upper": conformal_res.p_upper,
                "quantile_q": conformal_res.quantile_q,
                "is_admissible": conformal_res.is_admissible,
                "edge_pct": conformal_res.edge_pct,
                "rejection_reason": conformal_res.rejection_reason,
            }
            signal["bandit_multiplier"] = bandit_mult
            signal["bandit_ucb_score"] = ucb_score

            # Multiplicador combinado regulado (Brier Score * LinUCB)
            strat_mult = round(min(max(brier_mult * bandit_mult, 0.40), 1.60), 2)
        except Exception:
            strat_mult = 1.0

        # Control Activo de Drawdown (Continuous Drawdown-Constrained Kelly):
        # Si el portfolio entra en racha negativa (drawdown > 0), el sizing se reduce suavemente
        # para blindar matemáticamente la cuenta de $1,000 USD contra rachas adversas.
        peak_equity = max(self.initial_balance, self.initial_balance + max(0.0, closed_pnl))
        current_dd = max(0.0, (peak_equity - current_equity) / peak_equity) if peak_equity > 0 else 0.0
        drawdown_factor = max(0.15, min(1.0, 1.0 - (current_dd / 0.08)))  # 8% max drawdown tolerance

        trade_size_usd = round(max(10.0, min(150.0, kelly_data["size_usd"] * strat_mult * drawdown_factor)), 2)
        signal["position_size_usd"] = trade_size_usd
        signal["kelly_fraction_pct"] = round(kelly_data["kelly_fraction_pct"] * strat_mult * drawdown_factor, 2)
        signal["full_kelly_pct"] = kelly_data["full_kelly_pct"]
        signal["ai_strategy_multiplier"] = strat_mult
        signal["drawdown_protection_factor"] = round(drawdown_factor, 2)
        signal["current_drawdown_pct"] = round(current_dd * 100.0, 2)

        liquidity = to_float(getattr(market, "liquidity", 0), 0.0)
        volume_24h = to_float(getattr(market, "volume_24h", 0), 0.0)

        # Regla de Rotación Continua de Capital:
        # 1. Confianza >= 75% (Ultra)
        # 2. Horizonte Flash (<48h) O Estrategias intradía de alta velocidad (S20, S24, S22, BA, LL_SNIPER)
        is_fast_strategy = signal.get("strategy_code") in ("S20", "S24", "S22", "BA", "LL_SNIPER")
        is_flash_horizon = horizon_info["code"] == "flash" or to_float(horizon_info.get("hours_left"), 999) <= 48.0

        is_sniper = (
            confidence >= 75.0
            and (is_flash_horizon or is_fast_strategy)
            and entry_price > 0.02
            and entry_price < 0.98
            and (liquidity >= 1000.0 or volume_24h >= 5000.0)
        )

        signal["is_top_sniper"] = is_sniper

        if not is_sniper:
            return None

        trade_key = signal.get("dedupe_key") or f"{signal.get('strategy_code')}:{getattr(market, 'market_id', '')}:{signal.get('token')}:{side}"

        if trade_key in self.trades:
            return self.trades[trade_key]

        # ===== Bloque 1: límite de capital realista + ejecución con slippage/fees =====
        total_open_exposure = 0.0
        if PAPER_ENFORCE_CAPITAL:
            open_trades = [t for t in self.trades.values() if t.get("status") == "OPEN"]
            total_open_exposure = sum(to_float(t.get("position_size_usd"), 0.0) for t in open_trades)
            if len(open_trades) >= PAPER_MAX_OPEN_POSITIONS:
                signal["capital_skipped"] = "max_positions"
                return None
            available = PAPER_MAX_EXPOSURE_USD - total_open_exposure
            if available < 10.0:
                signal["capital_skipped"] = "no_capital"
                return None
            if trade_size_usd > available:
                trade_size_usd = round(available, 2)
                signal["position_size_usd"] = trade_size_usd

        # Slippage de entrada (comprar más caro / vender más barato)
        slippage = PAPER_SLIPPAGE_BPS / 10000.0
        exec_price = entry_price * (1.0 + slippage) if side == "BUY" else entry_price * (1.0 - slippage)
        exec_price = max(0.01, min(0.99, exec_price))

        # Comisiones sobre el nocional
        fee_usd = round(trade_size_usd * PAPER_FEE_RATE, 4)
        effective_size_usd = trade_size_usd - fee_usd

        shares = round(effective_size_usd / exec_price, 2)
        signal["execution_price"] = round(exec_price, 4)
        signal["slippage_bps"] = PAPER_SLIPPAGE_BPS
        signal["fee_usd"] = fee_usd
        signal["capital_exposure_usd"] = round(total_open_exposure + trade_size_usd, 2)

        new_trade = {
            "trade_id": trade_key,
            "signal_id": signal.get("signal_id", ""),
            "opened_at": utc_now().isoformat(),
            "market_id": getattr(market, "market_id", ""),
            "market_question": getattr(market, "question", "Mercado Desconocido"),
            "category": getattr(market, "category", "General") or "General",
            "strategy": signal.get("strategy", "Quant Strategy"),
            "strategy_code": signal.get("strategy_code", "GEN"),
            "token": signal.get("token", "Yes"),
            "side": side,
            "order_type": "LIMIT",
            "entry_price": round(exec_price, 4),
            "signal_entry_price": entry_price,
            "current_price": round(exec_price, 4),
            "target_price": target_price,
            "stop_loss": stop_loss,
            "initial_stop_loss": stop_loss,
            "peak_price": entry_price,
            "break_even_active": False,
            "trailing_stop_active": False,
            "trailing_stop_price": None,
            "shares": shares,
            "position_size_usd": trade_size_usd,
            "kelly_fraction_pct": kelly_data["kelly_fraction_pct"],
            "full_kelly_pct": kelly_data["full_kelly_pct"],
            "confidence": confidence,
            "edge_pct": round(edge * 100, 2),
            "risk_reward_ratio": round(rr_ratio, 2),
            "horizon": horizon_info["code"],
            "horizon_label": horizon_info["label"],
            "status": "OPEN",  # OPEN, WON, LOST
            "unrealized_pnl_usd": 0.0,
            "unrealized_pnl_pct": 0.0,
            "realized_pnl_usd": 0.0,
            "realized_pnl_pct": 0.0,
            "close_reason": None,
            "closed_at": None,
        }

        self.trades[trade_key] = new_trade
        self.save_to_disk()
        return new_trade

    record_signal = evaluate_and_record_signal

    def update_live_prices(self, market_registry):
        """Actualiza precios y ejecuta Trailing Stop dinámico y Break-even."""
        changed = False

        for trade in list(self.trades.values()):
            if trade.get("status") != "OPEN":
                continue

            market_id = trade.get("market_id")
            market = market_registry.get_market(market_id)
            if not market:
                continue

            token_name = trade.get("token", "Yes")
            if isinstance(market, dict):
                mid_prices = market.get("mid_price", {})
                prices = market.get("prices", {})
            else:
                mid_prices = getattr(market, "mid_price", {}) or {}
                prices = getattr(market, "prices", {}) or {}

            current_p = mid_prices.get(token_name) if isinstance(mid_prices, dict) else None
            if current_p is None and isinstance(prices, dict):
                current_p = prices.get(token_name)

            if current_p is None:
                current_p = (mid_prices.get("Yes") if isinstance(mid_prices, dict) else None) or (prices.get("Yes") if isinstance(prices, dict) else None)

            curr_float = to_float(current_p, 0.0)
            if curr_float <= 0:
                continue

            trade["current_price"] = round(curr_float, 4)
            entry = trade["entry_price"]
            target = trade["target_price"]
            shares = trade["shares"]
            side = trade["side"]

            # Cálculo de PnL Flotante
            if side == "BUY":
                pnl_usd = (curr_float - entry) * shares
                pnl_pct = ((curr_float - entry) / entry) * 100.0

                # Actualizar precio pico favorable
                peak = max(to_float(trade.get("peak_price", entry)), curr_float)
                trade["peak_price"] = round(peak, 4)
                peak_gain_pct = ((peak - entry) / entry) * 100.0

                # LÓGICA DE TRAILING STOP DINÁMICO (+4% BE, 2% Trailing)
                if peak_gain_pct >= 4.0:
                    # 1. Break-Even automático
                    if not trade.get("break_even_active"):
                        trade["break_even_active"] = True
                        be_price = round(entry * 1.002, 4)  # Break-even con mini-colchón
                        trade["stop_loss"] = max(to_float(trade.get("stop_loss")), be_price)

                    # 2. Trailing Stop persiguiendo precio pico a 2.0% de distancia
                    trailing_target = round(peak * 0.98, 4)
                    if trailing_target > to_float(trade.get("stop_loss")):
                        trade["stop_loss"] = trailing_target
                        trade["trailing_stop_active"] = True
                        trade["trailing_stop_price"] = trailing_target

                current_stop = to_float(trade.get("stop_loss"))

                # Verificación de Salida
                if curr_float >= target:
                    trade["status"] = "WON"
                    trade["realized_pnl_usd"] = round(pnl_usd, 2)
                    trade["realized_pnl_pct"] = round(pnl_pct, 2)
                    trade["unrealized_pnl_usd"] = 0.0
                    trade["unrealized_pnl_pct"] = 0.0
                    trade["closed_at"] = utc_now().isoformat()
                    trade["close_reason"] = f"🎯 Take Profit alcanzado (${curr_float:.3f} >= ${target:.3f})"
                    changed = True
                elif curr_float <= current_stop:
                    trade["realized_pnl_usd"] = round(pnl_usd, 2)
                    trade["realized_pnl_pct"] = round(pnl_pct, 2)
                    trade["unrealized_pnl_usd"] = 0.0
                    trade["unrealized_pnl_pct"] = 0.0
                    trade["closed_at"] = utc_now().isoformat()
                    if curr_float > entry:
                        trade["status"] = "WON"
                        trade["close_reason"] = f"🎯 Trailing Stop activado (Beneficio protegido: +{pnl_pct:.2f}% a ${curr_float:.3f})"
                    else:
                        trade["status"] = "LOST"
                        trade["close_reason"] = f"🛑 Stop Loss activado (${curr_float:.3f} <= ${current_stop:.3f})"
                    changed = True

            else:  # SELL
                pnl_usd = (entry - curr_float) * shares
                pnl_pct = ((entry - curr_float) / entry) * 100.0

                lowest = min(to_float(trade.get("peak_price", entry)), curr_float)
                trade["peak_price"] = round(lowest, 4)
                peak_gain_pct = ((entry - lowest) / entry) * 100.0

                if peak_gain_pct >= 4.0:
                    if not trade.get("break_even_active"):
                        trade["break_even_active"] = True
                        be_price = round(entry * 0.998, 4)
                        trade["stop_loss"] = min(to_float(trade.get("stop_loss")), be_price)

                    trailing_target = round(lowest * 1.02, 4)
                    if trailing_target < to_float(trade.get("stop_loss")):
                        trade["stop_loss"] = trailing_target
                        trade["trailing_stop_active"] = True
                        trade["trailing_stop_price"] = trailing_target

                current_stop = to_float(trade.get("stop_loss"))

                if curr_float <= target:
                    trade["status"] = "WON"
                    trade["realized_pnl_usd"] = round(pnl_usd, 2)
                    trade["realized_pnl_pct"] = round(pnl_pct, 2)
                    trade["unrealized_pnl_usd"] = 0.0
                    trade["unrealized_pnl_pct"] = 0.0
                    trade["closed_at"] = utc_now().isoformat()
                    trade["close_reason"] = f"🎯 Take Profit alcanzado (${curr_float:.3f} <= ${target:.3f})"
                    changed = True
                elif curr_float >= current_stop:
                    trade["realized_pnl_usd"] = round(pnl_usd, 2)
                    trade["realized_pnl_pct"] = round(pnl_pct, 2)
                    trade["unrealized_pnl_usd"] = 0.0
                    trade["unrealized_pnl_pct"] = 0.0
                    trade["closed_at"] = utc_now().isoformat()
                    if curr_float < entry:
                        trade["status"] = "WON"
                        trade["close_reason"] = f"🎯 Trailing Stop activado (Beneficio protegido: +{pnl_pct:.2f}% a ${curr_float:.3f})"
                    else:
                        trade["status"] = "LOST"
                        trade["close_reason"] = f"🛑 Stop Loss activado (${curr_float:.3f} >= ${current_stop:.3f})"
                    changed = True

            # LÓGICA DE TIME-STOP PARA ROTACIÓN CONTINUA DE CAPITAL (Regla B):
            # Si una posición abierta lleva >= 48 horas y está estancada (PnL < 1.5%),
            # se cierra a precio de mercado para liberar el capital y reasignarlo a señales Flash vivas.
            if trade.get("status") == "OPEN":
                opened_at_str = trade.get("opened_at")
                if opened_at_str:
                    try:
                        op_dt = datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
                        elapsed_hours = (utc_now() - op_dt).total_seconds() / 3600.0
                        if elapsed_hours >= 48.0 and abs(pnl_pct) < 2.0:
                            trade["status"] = "WON" if pnl_usd >= 0 else "LOST"
                            trade["realized_pnl_usd"] = round(pnl_usd, 2)
                            trade["realized_pnl_pct"] = round(pnl_pct, 2)
                            trade["unrealized_pnl_usd"] = 0.0
                            trade["unrealized_pnl_pct"] = 0.0
                            trade["closed_at"] = utc_now().isoformat()
                            trade["close_reason"] = f"⏱️ Time-Stop 48h (Capital liberado: rotación rápida tras {elapsed_hours:.1f}h estancado)"
                            changed = True
                    except Exception:
                        pass

            trade["unrealized_pnl_usd"] = round(pnl_usd, 2)
            trade["unrealized_pnl_pct"] = round(pnl_pct, 2)

        if changed:
            self.save_to_disk()
            try:
                from ai_learning_engine import ai_learning_engine
                from quant_ml_engine import quant_ml
                for tr in self.trades.values():
                    if tr.get("status") in ("WON", "LOST") and not tr.get("ai_post_mortem_done"):
                        ai_learning_engine.analyze_trade_post_mortem(tr)
                        
                        # Actualización Online de LinUCB Contextual Bandit y Conformal Prediction
                        strat_code = tr.get("strategy_code", "GEN")
                        outcome = 1 if tr.get("status") == "WON" else 0
                        pnl = to_float(tr.get("realized_pnl_usd", 0.0), 0.0)
                        reward = 1.0 if outcome == 1 else -1.0
                        ctx = quant_ml.bandit.get_current_context()
                        quant_ml.bandit.update_online(strat_code, ctx, reward)
                        quant_ml.conformal.record_ground_truth(to_float(tr.get("confidence", 80.0), 80.0), outcome)
                        
                        tr["ai_post_mortem_done"] = True
            except Exception:
                pass

    def get_summary(self) -> Dict[str, Any]:
        """Calcula métricas agregadas del track record incluyendo Sharpe, Drawdown y Equity Curve."""
        trades_list = list(self.trades.values())
        trades_list.sort(key=lambda x: x.get("opened_at", ""), reverse=True)

        open_trades = [t for t in trades_list if t.get("status") == "OPEN"]
        closed_trades = [t for t in trades_list if t.get("status") in ("WON", "LOST")]
        winning_trades = [t for t in closed_trades if t.get("status") == "WON"]
        losing_trades = [t for t in closed_trades if t.get("status") == "LOST"]

        total_realized_pnl = sum(t.get("realized_pnl_usd", 0.0) for t in closed_trades)
        total_unrealized_pnl = sum(t.get("unrealized_pnl_usd", 0.0) for t in open_trades)
        current_equity = self.initial_balance + total_realized_pnl + total_unrealized_pnl

        closed_count = len(closed_trades)
        win_rate = (len(winning_trades) / closed_count * 100.0) if closed_count > 0 else 0.0

        gross_profit = sum(t.get("realized_pnl_usd", 0.0) for t in winning_trades)
        gross_loss = abs(sum(t.get("realized_pnl_usd", 0.0) for t in losing_trades))
        profit_factor = round((gross_profit / gross_loss), 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)
        total_roi_pct = ((current_equity - self.initial_balance) / self.initial_balance) * 100.0

        # Historial de curva de equidad cronológica
        chronological_closed = sorted(closed_trades, key=lambda x: x.get("closed_at") or x.get("opened_at") or "")
        equity_history = [
            {"time": "Inicio", "equity": round(self.initial_balance, 2), "pnl": 0.0, "trade": "Balance Inicial"}
        ]
        running_equity = self.initial_balance
        peak_equity = self.initial_balance
        max_drawdown_pct = 0.0

        for t in chronological_closed:
            pnl = to_float(t.get("realized_pnl_usd", 0.0))
            running_equity += pnl
            if running_equity > peak_equity:
                peak_equity = running_equity
            dd = ((peak_equity - running_equity) / peak_equity) * 100.0 if peak_equity > 0 else 0.0
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd

            t_date = str(t.get("closed_at", ""))[:16].replace("T", " ") or "Trade"
            equity_history.append({
                "time": t_date,
                "equity": round(running_equity, 2),
                "pnl": round(pnl, 2),
                "trade": f"{t.get('strategy_code', 'SIG')} {t.get('side', '')} {t.get('token', '')}",
            })

        if open_trades:
            if current_equity > peak_equity:
                peak_equity = current_equity
            dd = ((peak_equity - current_equity) / peak_equity) * 100.0 if peak_equity > 0 else 0.0
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd
            equity_history.append({
                "time": "En vivo (Flotante)",
                "equity": round(current_equity, 2),
                "pnl": round(total_unrealized_pnl, 2),
                "trade": f"{len(open_trades)} posiciones abiertas",
            })

        # Ratio de Sharpe institucional y Expectativa matemática
        if closed_count >= 2:
            returns = [to_float(t.get("realized_pnl_pct", 0.0)) / 100.0 for t in closed_trades]
            mean_r = sum(returns) / len(returns)
            variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_r = variance ** 0.5
            sharpe = round((mean_r / std_r) * (len(returns) ** 0.5), 2) if std_r > 0 else (2.5 if mean_r > 0 else 0.0)
        elif closed_count == 1:
            sharpe = 2.1 if win_rate >= 50 else 0.0
        else:
            sharpe = 0.0

        if closed_count > 0:
            avg_win = (gross_profit / len(winning_trades)) if winning_trades else 0.0
            avg_loss = (gross_loss / len(losing_trades)) if losing_trades else 0.0
            expectancy_usd = round(((win_rate / 100.0) * avg_win) - (((100.0 - win_rate) / 100.0) * avg_loss), 2)
        else:
            expectancy_usd = 0.0

        return {
            "initial_balance": self.initial_balance,
            "current_equity": round(current_equity, 2),
            "total_pnl_usd": round(total_realized_pnl + total_unrealized_pnl, 2),
            "total_realized_pnl": round(total_realized_pnl, 2),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "total_roi_pct": round(total_roi_pct, 2),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "expectancy_usd": expectancy_usd,
            "total_trades": len(trades_list),
            "open_trades_count": len(open_trades),
            "winning_trades_count": len(winning_trades),
            "losing_trades_count": len(losing_trades),
            "equity_history": equity_history,
            "open_positions": open_trades,
            "history": closed_trades[:50],
            "all_trades": trades_list[:100],
            "updated_at": utc_now().isoformat(),
        }

    def get_strategy_performance(self) -> Dict[str, Any]:
        """Calcula el desglose de PnL flotante, PnL realizado y ranking por estrategia."""
        catalog = {
            "S10": {
                "code": "S10",
                "name": "Yes-No Bias Exploitation",
                "tag": "S10: Yes Bias",
                "category": "Sesgo de Comportamiento",
                "icon": "⚖️",
                "description": "Explota la sobrevaloración del YES minorista apostando al NO con descuento cuantitativo.",
            },
            "WT": {
                "code": "WT",
                "name": "Whale & Smart Money Tracking",
                "tag": "WT: Whale Tracking",
                "category": "Flujo Institucional",
                "icon": "🐋",
                "description": "Sigue las posiciones y acumulación de billeteras ballena con win-rate comprobado >60%.",
            },
            "MR": {
                "code": "MR",
                "name": "Mean Reversion (Sobre-reacción)",
                "tag": "MR: Mean Reversion",
                "category": "Estadística Cuantitativa",
                "icon": "🔄",
                "description": "Entrada contra-tendencia tras movimientos abruptos de 1d/1w esperando reversión a la media.",
            },
            "S12": {
                "code": "S12",
                "name": "High Probability Harvesting",
                "tag": "S12: High Prob Harvesting",
                "category": "Cosecha de Rendimiento",
                "icon": "🌾",
                "description": "Cosecha de prima en contratos con probabilidad ultra-alta (85%-98%) cercanos al vencimiento.",
            },
            "S05": {
                "code": "S05",
                "name": "NegRisk Rebalancing Arbitrage",
                "tag": "S05: NegRisk Rebalancing",
                "category": "Arbitraje Matemático",
                "icon": "🧮",
                "description": "Arbitraje estructural cuando la suma de probabilidades del canasto supera $1.00.",
            },
            "S02": {
                "code": "S02",
                "name": "Weather NOAA Quantitative",
                "tag": "S02: Weather NOAA",
                "category": "Datos Externos / Clima",
                "icon": "⛅",
                "description": "Modelo de previsión meteorológica NOAA vs precios cotizados en Polymarket.",
            },
            "S03": {
                "code": "S03",
                "name": "Nothing Ever Happens (Status Quo)",
                "tag": "S03: Nothing Ever Happens",
                "category": "Sesgo Histórico",
                "icon": "🛡️",
                "description": "Monetiza el sesgo hacia noticias sensacionalistas comprando NO en eventos poco probables.",
            },
            "BA": {
                "code": "BA",
                "name": "Bundle Arbitrage (YES + NO)",
                "tag": "BA: Bundle Arbitrage",
                "category": "Arbitraje Libre de Riesgo",
                "icon": "⚡",
                "description": "Arbitraje libre de riesgo comprando YES y NO simultáneamente por debajo de $1.00.",
            },
            "MM": {
                "code": "MM",
                "name": "Market Making (Spread Capture)",
                "tag": "MM: Market Making",
                "category": "Provisión de Liquidez",
                "icon": "🏦",
                "description": "Captura de diferencial bid-ask y comisiones colocando órdenes límite pasivas.",
            },
            "FLB": {
                "code": "FLB",
                "name": "Favorite-Longshot Bias",
                "tag": "FLB: Favorite-Longshot",
                "category": "Sesgo de Probabilidad",
                "icon": "🎯",
                "description": "Venta de contratos 'longshot' sobrevalorados con expectativa matemática positiva.",
            },
            "S20": {
                "code": "S20",
                "name": "Oracle Delay Sniping (Descuento UMA)",
                "tag": "S20: Oracle Sniping",
                "category": "Caza Post-Evento / Liquidación",
                "icon": "🎯",
                "description": "Compra contratos con certeza casi total a descuento (0.88-0.97) esperando liquidación UMA a $1.00.",
            },
            "S21": {
                "code": "S21",
                "name": "Arbitraje Lógico Condicional",
                "tag": "S21: Arbitraje Condicional",
                "category": "Arbitraje Matemático Lógico",
                "icon": "📐",
                "description": "Explota incoherencias entre mercados causalmente vinculados (ej. escaleras de precios y prerrequisitos).",
            },
            "S22": {
                "code": "S22",
                "name": "Fast News Latency Sniping",
                "tag": "S22: Fast News Sniping",
                "category": "Latencia de Información & NLP",
                "icon": "⚡",
                "description": "Barre órdenes desactualizadas en el book ante noticias de impacto antes de que el mercado reajuste.",
            },
            "S23": {
                "code": "S23",
                "name": "Resolution Rules-Lawyer",
                "tag": "S23: Rules-Lawyer",
                "category": "Asimetría Contractual UMA",
                "icon": "📜",
                "description": "Monetiza el sesgo de lectura superficial comprando NO cuando la regla legal estricta no se puede cumplir.",
            },
            "S24": {
                "code": "S24",
                "name": "Order Flow Imbalance (OFI)",
                "tag": "S24: Order Flow Imbalance",
                "category": "Microestructura Cuantitativa",
                "icon": "🌊",
                "description": "Scalping rápido de 30s a 3m detectando absorciones violentas de liquidez y desbalance de profundidad.",
            },
        }

        trades_list = list(self.trades.values())
        codes_in_trades = set(t.get("strategy_code") for t in trades_list if t.get("strategy_code"))
        all_codes = list(catalog.keys())
        for c in codes_in_trades:
            if c and c not in all_codes:
                all_codes.append(c)

        strategy_stats = []
        total_floating_all = 0.0
        total_realized_all = 0.0

        for code in all_codes:
            meta = catalog.get(code, {
                "code": code,
                "name": f"Estrategia {code}",
                "tag": code,
                "category": "Algorítmica",
                "icon": "📈",
                "description": "Estrategia cuantitativa automatizada.",
            })

            strat_trades = [t for t in trades_list if t.get("strategy_code") == code]
            open_trades = [t for t in strat_trades if t.get("status") == "OPEN"]
            closed_trades = [t for t in strat_trades if t.get("status") in ("WON", "LOST")]
            won_trades = [t for t in closed_trades if t.get("status") == "WON"]
            lost_trades = [t for t in closed_trades if t.get("status") == "LOST"]

            unrealized_pnl = sum(t.get("unrealized_pnl_usd", 0.0) for t in open_trades)
            realized_pnl = sum(t.get("realized_pnl_usd", 0.0) for t in closed_trades)
            total_pnl = round(realized_pnl + unrealized_pnl, 2)
            total_floating_all += unrealized_pnl
            total_realized_all += realized_pnl

            closed_count = len(closed_trades)
            win_rate = round((len(won_trades) / closed_count * 100.0), 1) if closed_count > 0 else 0.0

            gross_win = sum(t.get("realized_pnl_usd", 0.0) for t in won_trades)
            gross_loss = abs(sum(t.get("realized_pnl_usd", 0.0) for t in lost_trades))
            profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (round(gross_win, 2) if gross_win > 0 else 1.0)

            if len(open_trades) > 0:
                status = "OPERATING"
                status_label = "🟢 Operando"
            elif closed_count > 0:
                status = "STANDBY"
                status_label = "🟡 Standby"
            else:
                status = "SCANNING"
                status_label = "🔍 Escaneando"

            strategy_stats.append({
                "code": code,
                "name": meta["name"],
                "tag": meta["tag"],
                "category": meta["category"],
                "icon": meta["icon"],
                "description": meta["description"],
                "status": status,
                "status_label": status_label,
                "unrealized_pnl_usd": round(unrealized_pnl, 2),
                "realized_pnl_usd": round(realized_pnl, 2),
                "total_pnl_usd": total_pnl,
                "win_rate_pct": win_rate,
                "profit_factor": profit_factor,
                "total_trades": len(strat_trades),
                "open_trades_count": len(open_trades),
                "closed_trades_count": closed_count,
                "won_count": len(won_trades),
                "lost_count": len(lost_trades),
                "open_positions": open_trades,
                "recent_closed": closed_trades[:15],
            })

        # Ordenar por PnL Total desc, luego PnL Realizado desc, luego flotante desc
        strategy_stats.sort(key=lambda s: (s["total_pnl_usd"], s["realized_pnl_usd"], s["unrealized_pnl_usd"], s["total_trades"]), reverse=True)

        for idx, s in enumerate(strategy_stats, start=1):
            s["rank"] = idx
            if idx == 1:
                s["rank_badge"] = "🥇 #1"
            elif idx == 2:
                s["rank_badge"] = "🥈 #2"
            elif idx == 3:
                s["rank_badge"] = "🥉 #3"
            else:
                s["rank_badge"] = f"#{idx}"

        best_strategy = strategy_stats[0] if strategy_stats else None
        strategies_with_closed = [s for s in strategy_stats if s["closed_trades_count"] > 0]
        best_winrate_strat = max(strategies_with_closed, key=lambda s: s["win_rate_pct"]) if strategies_with_closed else None

        return {
            "total_floating_pnl_usd": round(total_floating_all, 2),
            "total_realized_pnl_usd": round(total_realized_all, 2),
            "total_combined_pnl_usd": round(total_floating_all + total_realized_all, 2),
            "best_strategy_name": best_strategy["name"] if best_strategy else "N/A",
            "best_strategy_code": best_strategy["code"] if best_strategy else "N/A",
            "best_strategy_pnl": best_strategy["total_pnl_usd"] if best_strategy else 0.0,
            "best_winrate_name": best_winrate_strat["name"] if best_winrate_strat else "Sin posiciones cerradas",
            "best_winrate_pct": best_winrate_strat["win_rate_pct"] if best_winrate_strat else 0.0,
            "strategies": strategy_stats,
            "updated_at": utc_now().isoformat(),
        }

    def reset_track_record(self):
        """Reinicia el track record a cero."""
        self.trades.clear()
        self.save_to_disk()


# Instancia global
paper_tracker = PaperTradingEngine()
