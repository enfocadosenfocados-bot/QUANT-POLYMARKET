"""Modo Híbrido - Órdenes "live" simuladas contra el libro real de Polymarket.

Objetivo: validar TODAS las estrategias sin arriesgar capital, pero con un
realismo de ejecución superior al paper clásico. En lugar de estimar el precio
de entrada con un slippage fijo (PAPER_SLIPPAGE_BPS), este módulo construye la
MISMA orden que enviaría ``live_execution.execute_order()`` y simula su fill
recorriendo los niveles reales del libro:

  - BUY  -> consume los ASKS reales (de más barato a más caro) hasta el límite.
  - SELL -> consume los BIDS reales (de más caro a más barato) hasta el límite.
  - Orden LIMIT: sólo cruza niveles que respetan el precio límite.
  - Fill parcial si la profundidad disponible no cubre el tamaño pedido.
  - Fee taker real por categoría; rebate maker si no cruza el spread; gas.

El resultado (VWAP de fill, slippage real, ratio de fill, niveles consumidos y
profundidad) se registra en el track record híbrido para compararlo contra paper
y decidir qué estrategia sobrevive al coste real de ejecución.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from config import (
    HYBRID_ALLOW_PARTIAL,
    HYBRID_MIN_FILL_RATIO,
    PAPER_GAS_COST_USD,
    POLYMARKET_DEFAULT_FEE_RATE,
    POLYMARKET_DEFAULT_MAKER_REBATE,
    POLYMARKET_FEE_RATE,
    POLYMARKET_MAKER_REBATE_RATE,
)

try:
    from market_registry import order_price, order_size
except ImportError:  # pragma: no cover - fallback defensivo
    def order_price(level: Any):
        return level.get("price") if isinstance(level, dict) else (level[0] if level else 0)

    def order_size(level: Any):
        return level.get("size") if isinstance(level, dict) else (level[1] if level and len(level) > 1 else 0)


def to_float(val: Any, default: float = 0.0) -> float:
    if val in (None, ""):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def extract_book_levels(market: Any, token: str, side: str) -> List[Dict[str, float]]:
    """Extrae y ordena los niveles del libro real que consume la orden.

    BUY consume asks (precio ascendente); SELL consume bids (precio descendente).
    """
    book = getattr(market, "order_book", None)
    if not isinstance(book, dict):
        return []

    entry = book.get(token)
    if not isinstance(entry, dict):
        # Fallback tolerante: usar el primer outcome disponible con libro.
        entry = next((v for v in book.values() if isinstance(v, dict)), None)
    if not isinstance(entry, dict):
        return []

    levels = entry.get("asks") if side == "BUY" else entry.get("bids")
    parsed: List[Dict[str, float]] = []
    for lv in (levels or []):
        price = to_float(order_price(lv))
        size = to_float(order_size(lv))
        if price > 0 and size > 0:
            parsed.append({"price": price, "size": size})
    parsed.sort(key=lambda x: x["price"], reverse=(side != "BUY"))
    return parsed


def walk_book(
    levels: List[Dict[str, float]],
    side: str,
    target_shares: float,
    limit_price: float | None = None,
) -> Dict[str, Any]:
    """Recorre el libro consumiendo liquidez hasta cubrir target_shares.

    Devuelve VWAP de fill, shares ejecutadas, coste, niveles usados y la
    profundidad total disponible en el lado recorrido.
    """
    filled = 0.0
    cost = 0.0
    used: List[Dict[str, float]] = []

    for lv in levels:
        if target_shares - filled <= 1e-9:
            break
        price = lv["price"]
        size = lv["size"]
        # Semántica de orden LIMIT: no cruzar niveles peores que el límite.
        if limit_price is not None and limit_price > 0:
            if side == "BUY" and price > limit_price + 1e-9:
                break
            if side == "SELL" and price < limit_price - 1e-9:
                break
        take = min(size, target_shares - filled)
        filled += take
        cost += take * price
        used.append({"price": round(price, 4), "size": round(take, 2)})

    depth_usd = sum(lv["price"] * lv["size"] for lv in levels)
    avg_price = (cost / filled) if filled > 0 else 0.0
    return {
        "filled_shares": round(filled, 2),
        "avg_price": avg_price,
        "cost_usd": cost,
        "levels_used": used,
        "levels_consumed": len(used),
        "book_depth_usd": round(depth_usd, 2),
    }


class SimulatedLiveExecutor:
    """Construye órdenes idénticas al ejecutor real y simula su fill en el libro."""

    def _order_payload(
        self, signal: Dict[str, Any], side: str, price: float, shares: float, order_type: str
    ) -> Dict[str, Any]:
        """Payload equivalente al de live_execution.execute_order (sin enviarse)."""
        return {
            "tokenID": signal.get("token_id") or signal.get("token"),
            "price": round(price, 4),
            "size": shares,
            "side": side,
            "feeRateBps": 0,
            "expiration": 0,
            "orderType": order_type,
            "nonce": int(time.time() * 1000),
            "simulated": True,
        }

    def execution(
        self,
        signal: Dict[str, Any],
        market: Any,
        size_usd: float,
        total_open_exposure: float = 0.0,
    ) -> Dict[str, Any]:
        """Simula la ejecución completa (fill + costes) de una señal sobre el libro real.

        Devuelve las claves que consume el motor de paper/híbrido más los campos
        de "orden live simulada" que se adjuntan al trade.
        """
        side = str(signal.get("side") or "BUY").upper()
        token = str(signal.get("token") or "Yes")
        entry_price = to_float(signal.get("entry_price"))
        is_maker = bool(signal.get("is_maker"))
        order_type = "GTC"

        if entry_price <= 0:
            return {"skip": True, "reason": "precio límite inválido", "trade_fields": {}}

        requested_usd = max(0.0, size_usd)
        requested_shares = round(requested_usd / entry_price, 2)
        levels = extract_book_levels(market, token, side)

        if is_maker:
            # Maker: la orden descansa en el libro y no cruza el spread -> fill al
            # precio límite, sin slippage, con rebate. Reportamos la profundidad
            # real presente en el lado de descanso para dejar constancia.
            resting = extract_book_levels(market, token, "SELL" if side == "BUY" else "BUY")
            fill = {
                "filled_shares": requested_shares,
                "avg_price": entry_price,
                "cost_usd": requested_usd,
                "levels_used": [{"price": round(entry_price, 4), "size": requested_shares}],
                "levels_consumed": 0,
                "book_depth_usd": round(sum(l["price"] * l["size"] for l in resting), 2),
            }
            status = "MAKER_FILLED"
            slippage_bps = 0.0
        elif not levels:
            return {"skip": True, "reason": "sin libro real disponible", "trade_fields": {}}
        else:
            fill = walk_book(levels, side, requested_shares, entry_price)
            if fill["filled_shares"] <= 0:
                return {"skip": True, "reason": "sin liquidez al precio límite", "trade_fields": {}}
            status = "FILLED" if fill["filled_shares"] >= requested_shares - 1e-6 else "PARTIAL"
            slippage_bps = (
                abs(fill["avg_price"] - entry_price) / entry_price * 10000.0 if entry_price > 0 else 0.0
            )

        fill_ratio = fill["filled_shares"] / requested_shares if requested_shares > 0 else 0.0
        if status == "PARTIAL" and not HYBRID_ALLOW_PARTIAL and fill_ratio < HYBRID_MIN_FILL_RATIO:
            return {
                "skip": True,
                "reason": f"fill parcial {fill_ratio:.0%} < mínimo",
                "trade_fields": {},
            }

        # El precio efectivo refleja la liquidez realmente consumida.
        exec_price = max(0.01, min(0.99, fill["avg_price"] or entry_price))
        executed_usd = round(min(requested_usd, fill["filled_shares"] * exec_price), 2)

        _cat = str(signal.get("market_category") or getattr(market, "category", "") or "other").lower()
        fee_rate = POLYMARKET_FEE_RATE.get(_cat, POLYMARKET_DEFAULT_FEE_RATE)

        if is_maker:
            rebate_rate = POLYMARKET_MAKER_REBATE_RATE.get(_cat, POLYMARKET_DEFAULT_MAKER_REBATE)
            fee_usd = 0.0
            rebate_usd = round(executed_usd * fee_rate * (1.0 - exec_price) * rebate_rate, 4)
            effective_size_usd = executed_usd + rebate_usd
        else:
            fee_usd = round(executed_usd * fee_rate * (1.0 - exec_price), 4)
            rebate_usd = 0.0
            effective_size_usd = max(0.0, executed_usd - fee_usd)

        exit_cost_usd = round(
            executed_usd * fee_rate * (1.0 - exec_price)
            + executed_usd * slippage_bps / 10000.0
            + PAPER_GAS_COST_USD,
            4,
        )

        order = self._order_payload(signal, side, entry_price, requested_shares, order_type)
        trade_fields = {
            "engine": "hybrid",
            "order_id": f"SIM-{order['nonce']}",
            "order_status": status,
            "order_payload": order,
            "requested_size_usd": round(requested_usd, 2),
            "requested_shares": requested_shares,
            "filled_shares": fill["filled_shares"],
            "fill_ratio": round(fill_ratio, 4),
            "book_avg_price": round(fill["avg_price"], 4),
            "book_depth_usd": fill["book_depth_usd"],
            "book_levels_consumed": fill["levels_consumed"],
            "book_levels_used": fill["levels_used"],
            "book_slippage_bps": round(slippage_bps, 2),
            "unfilled_usd": round(max(0.0, requested_usd - executed_usd), 2),
            "is_partial_fill": status == "PARTIAL",
        }

        return {
            "skip": False,
            "status": status,
            "slippage_bps": round(slippage_bps, 2),
            "exec_price": exec_price,
            "fee_usd": fee_usd,
            "rebate_usd": rebate_usd,
            "effective_size_usd": effective_size_usd,
            "fee_rate": fee_rate,
            "exit_cost_usd": exit_cost_usd,
            "capital_exposure_usd": round(total_open_exposure + executed_usd, 2),
            "trade_fields": trade_fields,
        }


# Instancia global usada por el motor híbrido
simulated_live_executor = SimulatedLiveExecutor()
