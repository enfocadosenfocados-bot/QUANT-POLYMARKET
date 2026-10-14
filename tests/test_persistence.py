"""Test de persistencia off-site: ledger de ordenes hibridas + CSV + visor offline."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backup_manager as bm  # noqa: E402

FAKE_ORDERS = [
    {
        "order_id": "SIM-1", "recorded_at": "2026-10-14T10:00:00+00:00",
        "status": "FILLED", "reason": "libro suficiente",
        "market_id": "0xabc", "market_question": "Will X happen?",
        "strategy_code": "S25", "token": "Yes", "side": "BUY",
        "confidence": 0.71, "is_maker": False, "signal_entry_price": 0.46,
        "requested_size_usd": 100.0,
        "fill": {"exec_price": 0.4620, "fill_ratio": 1.0, "slippage_bps": 43.5,
                 "book_depth_usd": 5000.0, "levels_consumed": 3,
                 "fee_usd": 1.8, "rebate_usd": 0.0},
    },
    {
        "order_id": "SIM-2", "recorded_at": "2026-10-14T10:05:00+00:00",
        "status": "PARTIAL", "reason": "profundidad insuficiente",
        "market_id": "0xdef", "market_question": "Another market?",
        "strategy_code": "S25", "token": "No", "side": "BUY",
        "confidence": 0.55, "is_maker": True, "signal_entry_price": 0.30,
        "requested_size_usd": 200.0,
        "fill": {"exec_price": 0.3000, "fill_ratio": 0.62, "slippage_bps": 0.0,
                 "book_depth_usd": 124.0, "levels_consumed": 1,
                 "fee_usd": 0.0, "rebate_usd": 1.5},
    },
    {
        "order_id": "SIM-3", "recorded_at": "2026-10-14T10:09:00+00:00",
        "status": "REJECTED", "reason": "sin liquidez al limite",
        "market_id": "0xghi", "market_question": "Illiquid?",
        "strategy_code": "S12", "token": "Yes", "side": "BUY",
        "confidence": 0.9, "is_maker": False, "signal_entry_price": 0.12,
        "requested_size_usd": 50.0, "fill": {},
    },
]

failures = []


def check(name, cond, extra=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{(' :: ' + str(extra)) if extra else ''}")
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="trackrec-"))
try:
    # 1) Ledger append-only de ordenes + CSV
    mgr = bm.BackupManager()
    mgr.track_dir = tmp
    mgr.orders_ledger_path = tmp / "hybrid_orders.jsonl"
    mgr.orders_index_path = tmp / ".orders_ledger_index.json"
    mgr._read_hybrid_orders = staticmethod(lambda: FAKE_ORDERS)

    added = mgr._append_orders_ledger()
    check("append solo ejecutadas (rechazos fuera)", added == 2, added)
    check("ledger jsonl creado", mgr.orders_ledger_path.exists())

    added2 = mgr._append_orders_ledger()
    lines = mgr.orders_ledger_path.read_text().strip().splitlines()
    check("idempotente (no duplica)", added2 == 0 and len(lines) == 2, (added2, len(lines)))

    # Modo debug: incluir rechazos
    os.environ["HYBRID_ORDERS_LEDGER_ALL"] = "1"
    mgr.orders_ledger_path.unlink()
    mgr.orders_index_path.unlink()
    all_added = mgr._append_orders_ledger()
    check("HYBRID_ORDERS_LEDGER_ALL guarda rechazos", all_added == 3, all_added)
    os.environ.pop("HYBRID_ORDERS_LEDGER_ALL")
    mgr.orders_ledger_path.unlink()
    mgr.orders_index_path.unlink()
    mgr._append_orders_ledger()
    lines = mgr.orders_ledger_path.read_text().strip().splitlines()

    extra = dict(FAKE_ORDERS[0])
    extra["order_id"] = "SIM-4"
    mgr._read_hybrid_orders = staticmethod(lambda: [*FAKE_ORDERS, extra])
    added3 = mgr._append_orders_ledger()
    check("solo anade la nueva", added3 == 1)

    total = mgr._export_orders_csv()
    check("csv conserva TODAS (incl. rechazos)", total == 4 and (tmp / "hybrid_orders.csv").exists())

    first = json.loads(lines[0])
    check("campos aplanados", first["order_id"] == "SIM-1"
          and first["slippage_bps"] == 43.5 and first["status"] == "FILLED",
          first.get("slippage_bps"))

    # 2) Manifest + visor offline sobre la copia "descargada"
    manifest = {"campaign_name": "demo-15d", "campaign_start": "2026-10-01T00:00:00+00:00",
                "updated_at": "2026-10-14T10:10:00+00:00", "campaign_day": 13.4,
                "campaign_complete": False, "strategies": 3,
                "trade_counts": {"total": 149, "realistic": 14, "research": 135, "hybrid": 3},
                "files": {}}
    for p in sorted(tmp.glob("hybrid_orders.*")):
        manifest["files"][p.name] = {"bytes": p.stat().st_size, "sha256": bm._sha256(p)}
    (tmp / "manifest.json").write_text(json.dumps(manifest))

    out = subprocess.run([sys.executable, str(ROOT / "ver_track_record.py"), str(tmp)],
                         capture_output=True, text=True, cwd=str(ROOT))
    txt = out.stdout
    check("visor sale OK", out.returncode == 0, out.stderr[-300:])
    check("visor verifica integridad", "OK          hybrid_orders.jsonl" in txt)
    check("visor cuenta ordenes", "Ordenes totales      : 3" in txt)
    check("visor estados", "- FILLED           : 2" in txt and "- PARTIAL          : 1" in txt)
    check("visor fill ratio medio", "Fill ratio medio     : 0.8733" in txt,
          [l for l in txt.splitlines() if "Fill ratio" in l])
    check("visor marca liquidez justa", "liquidez justa" in txt)
    check("visor detalle con IDs", "SIM-1" in txt and "SIM-4" in txt)
    check("visor diagnostico de rechazos",
          "DIAGNOSTICO" in txt and "sin liquidez al limite" in txt and "REJECTED" in txt,
          [l for l in txt.splitlines() if "sin liquidez" in l])
    check("visor capital simulado", "Capital simulado     : $400.00" in txt,
          [l for l in txt.splitlines() if "Capital simulado" in l])
    check("visor OK final", "Respaldo integro y legible" in txt)

    # 2b) El diagnóstico puede venir del manifest (copia sin el log de órdenes)
    manifest["hybrid"] = {"orders_executed": 7, "rejections_total": 999,
                          "rejection_reasons": {"sin libro real disponible": 999}}
    (tmp / "manifest.json").write_text(json.dumps(manifest))
    out_m = subprocess.run([sys.executable, str(ROOT / "ver_track_record.py"), str(tmp)],
                           capture_output=True, text=True, cwd=str(ROOT))
    check("visor lee rechazos del manifest",
          "Ordenes ejecutadas : 7" in out_m.stdout and "999" in out_m.stdout
          and "sin libro real disponible" in out_m.stdout,
          [l for l in out_m.stdout.splitlines() if "rechazadas" in l])

    # 3) Integridad: archivo corrupto detectado
    (tmp / "hybrid_orders.csv").write_text("corrupted")
    out2 = subprocess.run([sys.executable, str(ROOT / "ver_track_record.py"), str(tmp)],
                          capture_output=True, text=True, cwd=str(ROOT))
    check("visor detecta corrupcion", "CORRUPTO" in out2.stdout and out2.returncode == 0)

    # 4) Carpeta inexistente
    out3 = subprocess.run([sys.executable, str(ROOT / "ver_track_record.py"), "/no/existe"],
                          capture_output=True, text=True, cwd=str(ROOT))
    check("visor avisa si falta la carpeta", out3.returncode == 2)

    # 4b) Falso negativo de git: el push SE HIZO pero git sale con codigo != 0
    #     ("waitpid for git-remote-https failed: No child processes").
    class _FakeCompleted:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    real_run = bm.subprocess.run

    def fake_run(args, **kw):
        if "push" in args:
            return _FakeCompleted(
                1,
                "To https://example.invalid/repo.git\n"
                "   abc1234..def5678  HEAD -> main\n"
                "error: waitpid for git-remote-https failed: No child processes\n")
        return _FakeCompleted(0)

    git_mgr = bm.BackupManager()
    git_mgr.track_dir = tmp
    git_mgr._resolve_git_token = staticmethod(lambda: "token-de-prueba")
    bm.subprocess.run = fake_run
    try:
        res_git = git_mgr._push_git([])
    finally:
        bm.subprocess.run = real_run
    check("push efectivo pese a exit!=0 (waitpid ECHILD)", res_git["ok"] is True, res_git)
    check("aviso de exit!=0 registrado", "aviso" in res_git["detail"], res_git["detail"])

    # 4c) Contrapartida: si NO hay linea de ref actualizada, es un fallo real.
    def fake_run_fail(args, **kw):
        if "push" in args:
            return _FakeCompleted(
                1, "error: waitpid for git-remote-https failed: No child processes\n")
        return _FakeCompleted(0)

    bm.subprocess.run = fake_run_fail
    try:
        res_fail = git_mgr._push_git([])
    finally:
        bm.subprocess.run = real_run
    check("fallo real sigue detectandose", res_fail["ok"] is False, res_fail)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# 5) run_once real sobre el track_record del proyecto (sin romper nada)
mgr = bm.BackupManager()
res = mgr.run_once()
check("run_once sin error", mgr.status.get("last_error") is None, mgr.status.get("last_error"))
check("run_once devuelve conteos", "orders_total" in res and "orders_events_added" in res,
      res.get("orders_total"))
check("status expone ordenes", "orders_events" in mgr.get_status()
      and "orders_logged" in mgr.get_status())
check("backend local ok", res["backends"].get("local", {}).get("ok") is True)

print()
print("RESULTADO:", "TODOS LOS TESTS PASAN" if not failures else f"FALLOS: {failures}")
sys.exit(1 if failures else 0)

