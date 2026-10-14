"""QUANT POLYMARKET - Visor y verificador OFFLINE del track record.

Pensado para cuando ya NO tienes la VPS: descarga la copia de respaldo
(repo privado / S3 / R2 / webhook) y ejecuta:

    python3 ver_track_record.py                    # usa ./track_record
    python3 ver_track_record.py /ruta/descargada    # carpeta descargada

Muestra, sin necesidad del bot ni de conexión:

  1. Integridad: SHA-256/bytes de cada archivo contra ``manifest.json``.
  2. Estado de la campaña: día, objetivo y trades por motor.
  3. Ranking por estrategia con el desglose por origen.
  4. Modo Híbrido: órdenes live simuladas (fills, parciales, rechazos,
     fill ratio medio y slippage real del libro).
  5. Detalle de las últimas órdenes simuladas.

Solo usa la librería estándar.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_orders(track_dir: Path) -> List[Dict[str, Any]]:
    """Lee las órdenes simuladas del formato más fiable disponible.

    Prioridad: ledger append-only (.jsonl) > CSV > JSON completo.
    """
    jsonl = track_dir / "hybrid_orders.jsonl"
    if jsonl.exists():
        orders: List[Dict[str, Any]] = []
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                orders.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if orders:
            return orders

    csv_path = track_dir / "hybrid_orders.csv"
    if csv_path.exists():
        with open(csv_path, encoding="utf-8", newline="") as f:
            return [dict(r) for r in csv.DictReader(f)]

    raw = _read_json(track_dir / "hybrid_orders.json", {})
    if isinstance(raw, dict):
        return [o for o in raw.get("orders", []) if isinstance(o, dict)]
    return [o for o in (raw or []) if isinstance(o, dict)]


def _num(value: Any) -> float:
    try:
        if value in (None, "", "None"):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def check_integrity(track_dir: Path, manifest: Dict[str, Any]) -> bool:
    print("=" * 78)
    print("1) INTEGRIDAD DEL RESPALDO (SHA-256 vs manifest.json)")
    print("=" * 78)
    declared = manifest.get("files") or {}
    if not declared:
        print("  ! manifest.json sin lista de archivos: no se puede verificar.")
        return True

    ok = True
    for name in sorted(declared):
        info = declared[name] or {}
        path = track_dir / name
        if not path.exists():
            print(f"  x FALTA       {name}")
            ok = False
            continue
        size = path.stat().st_size
        digest = _sha256(path)
        if info.get("sha256") and digest != info.get("sha256"):
            print(f"  x CORRUPTO    {name} ({size} bytes, hash distinto)")
            ok = False
        elif info.get("bytes") is not None and size != info.get("bytes"):
            print(f"  ~ TAMANO      {name} ({size} bytes, esperado {info.get('bytes')})")
        else:
            print(f"  + OK          {name} ({size:,} bytes)")
    return ok


def report_campaign(manifest: Dict[str, Any]) -> None:
    print()
    print("=" * 78)
    print("2) ESTADO DE LA CAMPANA")
    print("=" * 78)
    if not manifest:
        print("  ! No hay manifest.json en la carpeta indicada.")
        return
    counts = manifest.get("trade_counts") or {}
    day = manifest.get("campaign_day")
    complete = manifest.get("campaign_complete")
    print(f"  Campana          : {manifest.get('campaign_name', '-')}")
    print(f"  Inicio           : {manifest.get('campaign_start', '-')}")
    print(f"  Ultima copia     : {manifest.get('updated_at', '-')}")
    print(f"  Dia de campana   : {day}")
    print(f"  Campana completa : {'SI' if complete else 'NO (en curso)'}")
    print(f"  Estrategias      : {manifest.get('strategies', '-')}")
    print(f"  Trades totales   : {counts.get('total', 0)}")
    print(f"    - realista     : {counts.get('realistic', 0)}")
    print(f"    - research     : {counts.get('research', 0)}")
    print(f"    - hibrido      : {counts.get('hybrid', 0)}   <- ordenes live simuladas")


def report_ranking(track_dir: Path) -> None:
    print()
    print("=" * 78)
    print("3) RANKING POR ESTRATEGIA")
    print("=" * 78)
    ranking = _read_json(track_dir / "strategy_ranking.json", {})
    strategies = (ranking or {}).get("strategies") or []
    if not strategies:
        print("  (sin datos: aun no hay estrategias evaluadas)")
        return
    print(f"  {'COD':<6}{'TRADES':>7}{'CIERRES':>9}{'WIN%':>8}"
          f"{'PNL HIB':>10}{'PNL TOT':>10}  VEREDICTO")
    for s in strategies:
        hybrid = ((s.get("by_source") or {}).get("hybrid") or {})
        print(f"  {str(s.get('strategy_code', '?')):<6}"
              f"{s.get('total', 0):>7}{s.get('closed', 0):>9}"
              f"{_num(s.get('win_rate_pct')):>8.1f}"
              f"{_num(hybrid.get('net_pnl_usd')):>10.2f}"
              f"{_num(s.get('net_pnl_usd')):>10.2f}  {s.get('verdict', '-')}")
    print("\n  PNL HIB = resultado con ejecucion real del libro (modo hibrido).")
    print("  PNL TOT = resultado combinado de todos los motores.")


def report_orders(orders: List[Dict[str, Any]], detail: int = 15) -> None:
    print()
    print("=" * 78)
    print("4) ORDENES LIVE SIMULADAS (MODO HIBRIDO)")
    print("=" * 78)
    if not orders:
        print("  (sin ordenes registradas todavia)")
        return

    filled = partial = maker = 0
    ratios: List[float] = []
    slips: List[float] = []
    requested = 0.0
    for o in orders:
        status = str(o.get("status") or "UNKNOWN").upper()
        fill = o.get("fill") or {}
        ratio = _num(fill.get("fill_ratio") if fill.get("fill_ratio") is not None
                     else o.get("fill_ratio"))
        slip = fill.get("slippage_bps", o.get("slippage_bps"))
        requested += _num(o.get("requested_size_usd"))
        if status == "FILLED":
            filled += 1
        elif status == "PARTIAL":
            partial += 1
        elif status == "MAKER_FILLED":
            maker += 1
        if ratio:
            ratios.append(ratio)
        if slip not in (None, ""):
            slips.append(_num(slip))

    print(f"  Ordenes totales      : {len(orders)}")
    print(f"    - FILLED           : {filled}")
    print(f"    - PARTIAL          : {partial}")
    print(f"    - MAKER_FILLED     : {maker}")
    print(f"    - REJECTED/otros   : {len(orders) - filled - partial - maker}")
    print(f"  Capital simulado     : ${requested:,.2f} (sin riesgo real)")
    avg_ratio = sum(ratios) / len(ratios) if ratios else 0.0
    avg_slip = sum(slips) / len(slips) if slips else 0.0
    warn = "  <- liquidez justa" if ratios and avg_ratio < 0.9 else ""
    print(f"  Fill ratio medio     : {avg_ratio:.4f}{warn}")
    print(f"  Slippage medio libro : {avg_slip:.2f} bps")

    print()
    print(f"5) ULTIMAS {min(detail, len(orders))} ORDENES")
    print("-" * 78)
    print(f"  {'CUANDO':<20}{'ESTRAT':<7}{'LADO':<5}{'PRECIO':>8}"
          f"{'FILL%':>7}{'SLIP':>7}  ESTADO / ID")
    for o in orders[-detail:]:
        fill = o.get("fill") or {}
        price = fill.get("exec_price") or o.get("signal_entry_price")
        ratio = _num(fill.get("fill_ratio") if fill.get("fill_ratio") is not None
                     else o.get("fill_ratio"))
        slip = fill.get("slippage_bps", o.get("slippage_bps"))
        when = str(o.get("recorded_at") or "-")[:19]
        print(f"  {when:<20}{str(o.get('strategy_code', '-')):<7}"
              f"{str(o.get('side', '-')):<5}{_num(price):>8.4f}"
              f"{ratio * 100:>7.1f}{_num(slip):>7.1f}  {o.get('status', '-')}"
              f" / {o.get('order_id', '-')}")


def report_rejections(track_dir: Path, manifest: Dict[str, Any]) -> None:
    """Motivos de rechazo del Modo Híbrido (por qué no se ejecutan órdenes)."""
    hybrid = (manifest or {}).get("hybrid") or {}
    counts = {str(k): int(v) for k, v in (hybrid.get("rejection_reasons") or {}).items()}

    if not counts:
        # Compatibilidad con copias antiguas: mirar el log o el CSV.
        raw = _read_json(track_dir / "hybrid_orders.json", {}) or {}
        all_orders = raw.get("orders") if isinstance(raw, dict) else raw
        all_orders = [o for o in (all_orders or []) if isinstance(o, dict)]
        if not all_orders:
            csv_path = track_dir / "hybrid_orders.csv"
            if csv_path.exists():
                with open(csv_path, encoding="utf-8", newline="") as f:
                    all_orders = [dict(r) for r in csv.DictReader(f)]
        for o in all_orders:
            if str(o.get("status") or "").upper() != "REJECTED":
                continue
            reason = o.get("reason") or "sin motivo"
            counts[reason] = counts.get(reason, 0) + 1

    if not counts:
        return

    print()
    print("=" * 78)
    print("6) DIAGNOSTICO: POR QUE NO SE EJECUTAN ORDENES")
    print("=" * 78)
    total = sum(counts.values())
    executed = hybrid.get("orders_executed")
    if executed is not None:
        print(f"  Ordenes ejecutadas : {executed}")
    print(f"  Ordenes rechazadas : {total}")
    for reason, n in sorted(counts.items(), key=lambda kv: -kv[1])[:6]:
        print(f"    {n:>6}  {reason}")
    if counts.get("sin libro real disponible"):
        print("\n  'sin libro real disponible' = en ese instante no habia order book para")
        print("  ese token (cobertura del feed), no es falta de liquidez del mercado.")


def main() -> int:
    track_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("track_record")
    if not track_dir.exists():
        print(f"ERROR: no existe la carpeta '{track_dir}'.")
        print("Descarga la copia de respaldo (repo privado / S3) y pasa la ruta, p.ej.:")
        print("  python3 ver_track_record.py ~/Downloads/track_record")
        return 2

    print(f"\nTrack record: {track_dir.resolve()}\n")
    manifest = _read_json(track_dir / "manifest.json", {}) or {}

    intact = check_integrity(track_dir, manifest)
    report_campaign(manifest)
    report_ranking(track_dir)
    orders = _load_orders(track_dir)
    report_orders(orders)
    report_rejections(track_dir, manifest)

    print()
    print("=" * 78)
    if not intact:
        print("! ALGUNOS ARCHIVOS NO CUADRAN CON EL MANIFEST: vuelve a descargar la copia.")
    if not orders:
        executed = (manifest.get("hybrid") or {}).get("orders_executed")
        if executed == 0:
            print("i  Aun no hay ordenes ejecutadas registradas: el Modo Hibrido solo guarda")
            print("   las señales que pasan todos los filtros (las rechazadas se cuentan")
            print("   aparte, ver seccion 6). Es normal al inicio de la campana.")
        else:
            print("i  No hay ledger de ordenes hibridas: activa BACKUP_TARGETS off-site")
            print("   (git/s3) o fuerza 'POST /api/backup/run' antes de apagar la VPS.")
    elif intact:
        print("OK Respaldo integro y legible. Este es el historico real de lo que hizo el bot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

