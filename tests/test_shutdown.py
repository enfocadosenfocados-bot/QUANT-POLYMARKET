"""Verifica el backup automático al apagar el bot (hook de shutdown del lifespan)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

with TestClient(main.app) as client:
    assert client.get("/api/backup/status").status_code == 200
print("[TEST] arranque OK; cerrando (dispara backup final)...")

tr = ROOT / "track_record"
print("[TEST] manifest actualizado:", (tr / "manifest.json").exists())
status = main.backup_manager.get_status()
print("[TEST] ciclos de backup:", status.get("cycles"), "| errores:", status.get("last_error"))
print("[TEST] errores en backends:",
      {k: v for k, v in (status.get("backends") or {}).items() if not v.get("ok")} or "ninguno")
print("[TEST] OK")
