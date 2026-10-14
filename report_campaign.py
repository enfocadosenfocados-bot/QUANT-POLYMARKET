#!/usr/bin/env python3
"""Reporte offline de la campaña demo (>15d).

Lee la copia exportada por ``backup_manager.py`` en ``track_record/`` y emite un
veredicto por estrategia para decidir cuáles pasan a operar en real.

Uso:
    python report_campaign.py                       # usa ./track_record
    python report_campaign.py /ruta/track_record    # usa una copia descargada
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VERDICT_ICON = {
    "CANDIDATA_REAL": "✅",
    "PROMETEDORA": "🟡",
    "MUESTRA_INSUFICIENTE": "⏳",
    "DESCARTAR": "❌",
}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> int:
    if len(sys.argv) > 1:
        base = Path(sys.argv[1]).resolve()
    else:
        base = Path(__file__).resolve().parent / "track_record"

    ranking = load(base / "strategy_ranking.json", {})
    manifest = load(base / "manifest.json", {})
    strategies = ranking.get("strategies", [])

    if not strategies:
        print(f"[!] No hay ranking en {base}. ¿Se ejecutó algún ciclo de backup?")
        return 1

    day = manifest.get("campaign_day", 0.0)
    counts = manifest.get("trade_counts", {})
    name = ranking.get("campaign", manifest.get("campaign_name", "demo"))

    lines = [
        f"# Campaña demo: {name}",
        "",
        f"- Día de campaña: **{day}** (mínimo objetivo: {manifest.get('campaign_min_days', 15)})",
        f"- Campaña completa: {'SÍ' if manifest.get('campaign_complete') else 'NO'}",
        f"- Trades: {counts.get('total', 0)} "
        f"(realista={counts.get('realistic', 0)}, research={counts.get('research', 0)}, "
        f"híbrido={counts.get('hybrid', 0)})",
        f"- Estrategias analizadas: {len(strategies)}",
        "",
        "| # | Estrategia | Trades | Cerrados | Win% | PnL neto $ | Veredicto |",
        "|---|-----------|--------|----------|------|------------|-----------|",
    ]
    for i, s in enumerate(strategies, 1):
        v = s.get("verdict", "?")
        icon = VERDICT_ICON.get(v, "•")
        lines.append(
            f"| {i} | {s.get('strategy_code')} — {s.get('strategy_name', '')} "
            f"| {s.get('total', 0)} | {s.get('closed', 0)} | {s.get('win_rate_pct', 0)} "
            f"| {s.get('net_pnl_usd', 0)} | {icon} {v} |"
        )

    hybrid_rows = [
        s for s in strategies
        if (s.get("by_source") or {}).get("hybrid", {}).get("total")
    ]
    if hybrid_rows:
        lines += [
            "",
            "## Modo Híbrido (órdenes live simuladas contra el libro real)",
            "",
            "| Estrategia | Trades | Slippage libro (bps) | Fills parciales | PnL research $ | PnL híbrido $ | Δ ejecución $ |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in hybrid_rows:
            hy = s["by_source"].get("hybrid", {})
            rs = s["by_source"].get("research", {})
            delta = round(hy.get("net_pnl_usd", 0.0) - rs.get("net_pnl_usd", 0.0), 2)
            slip = s.get("avg_book_slippage_bps")
            lines.append(
                f"| {s.get('strategy_code')} — {s.get('strategy_name', '')} "
                f"| {hy.get('total', 0)} "
                f"| {slip if slip is not None else '—'} "
                f"| {s.get('partial_fills', 0)} "
                f"| {rs.get('net_pnl_usd', 0.0)} "
                f"| {hy.get('net_pnl_usd', 0.0)} "
                f"| {delta:+} |"
            )
        lines.append("")
        lines.append("Δ ejecución = PnL híbrido − PnL research (mismo pipeline, fill real de libro).")

    report = "\n".join(lines)
    print(report)
    out = base / "CAMPAIGN_REPORT.md"
    out.write_text(report + "\n", encoding="utf-8")
    print(f"\n[i] Reporte escrito en {out}")

    ready = [s for s in strategies if s.get("verdict") == "CANDIDATA_REAL"]
    if ready:
        print("\n[+] Candidatas a operar en real:")
        for s in ready:
            print(f"    - {s['strategy_code']} ({s['win_rate_pct']}% WR, ${s['net_pnl_usd']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
