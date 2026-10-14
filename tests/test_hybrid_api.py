"""API del Modo Híbrido y dashboard (rutas nuevas del motor híbrido)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

c = TestClient(main.app)
r = c.get("/api/hybrid/status")
data = r.json()
assert r.status_code == 200, r.text
assert data["stats"]["engine"] == "hybrid", data
print("OK /api/hybrid/status ->", {"enabled": data["enabled"], **{
    k: data["stats"][k] for k in ("total_trades", "orders_logged", "avg_book_slippage_bps", "execution_stats")}})

r2 = c.get("/api/hybrid/orders?limit=5")
assert r2.status_code == 200, r2.text
print("OK /api/hybrid/orders ->", r2.json())

r3 = c.get("/api/track-record")
assert r3.status_code == 200, r3.text
print("OK /api/track-record -> equity =", r3.json().get("current_equity"))

r4 = c.get("/static/index.html")
assert r4.status_code == 200 and "hybrid-stats" in r4.text, r4.status_code
print("OK dashboard -> panel 'hybrid-stats' presente en el HTML")
print("\n[API DEL MODO HIBRIDO OK]")
