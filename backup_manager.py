"""QUANT POLYMARKET - Persistencia Off-Site del Track Record.

Este módulo garantiza que el track-record de la campaña demo NO viva únicamente
en esta VPS. Cada ciclo:

  1. Materializa un snapshot local en ``track_record/`` (CSV + ranking + manifest).
  2. Añade un **ledger append-only** (``track_record/ledger.jsonl``) con cada
     trade abierto/cerrado. Al ser append-only, un reinicio o un borrado parcial
     nunca pierde los eventos ya emitidos.
  3. Empuja la copia a uno o varios destinos off-site configurables por entorno:
     ``git`` (repo GitHub/GitLab), ``s3`` (AWS S3 / Cloudflare R2 / B2 / MinIO)
     y ``http`` (webhook: Apps Script, n8n, Make, Supabase...).

Todos los fallos se capturan y se registran: un backend caído jamás rompe el bot.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

import config


def utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# Columnas que se exportan al ledger / CSV combinado.
_LEDGER_KEYS = [
    "trade_id", "status", "close_reason", "strategy_code", "strategy",
    "market_id", "market_question", "category", "token", "side",
    "confidence", "edge_pct", "horizon", "entry_price", "current_price",
    "target_price", "stop_loss", "shares", "position_size_usd",
    "realized_pnl_usd", "realized_pnl_pct", "unrealized_pnl_usd",
    "unrealized_pnl_pct", "opened_at", "closed_at",
    # Ejecución (Modo Híbrido: órdenes live simuladas contra el libro real)
    "engine", "order_id", "order_status", "is_partial_fill",
    "fill_ratio", "book_slippage_bps", "book_depth_usd", "book_levels_consumed",
]

# Columnas del ledger/CSV de órdenes live simuladas (Modo Híbrido).
_ORDERS_LEDGER_KEYS = [
    "order_id", "recorded_at", "status", "reason", "market_id", "market_question",
    "strategy_code", "token", "side", "confidence", "is_maker",
    "signal_entry_price", "requested_size_usd",
]

# Campos del dict "fill" de cada orden simulada que se aplanan al ledger/CSV.
_ORDERS_FILL_KEYS = [
    "exec_price", "fill_ratio", "slippage_bps", "book_depth_usd",
    "levels_consumed", "fee_usd", "rebate_usd",
]

# Solo estas órdenes se guardan en el ledger append-only por defecto: son las
# que realmente se ejecutaron. Los rechazos "sin libro real disponible" se
# producen a miles por hora y harían el respaldo inservible (el CSV sí los
# conserva mientras estén dentro de HYBRID_KEEP_ORDERS).
_ORDERS_LEDGER_STATUSES = {"FILLED", "PARTIAL", "MAKER_FILLED"}


class BackupManager:
    """Motor de respaldo y reporting del track record (campaña demo >15d)."""

    def __init__(self) -> None:
        self.project_dir = Path(__file__).resolve().parent
        self.track_dir = Path(getattr(config, "TRACK_RECORD_DIR",
                                       self.project_dir / "track_record"))
        self.files = list(getattr(config, "TRACK_RECORD_FILES", [
            "paper_trades.json", "paper_trades_research.json",
            "trade_memory.json", "quant_ml_state.json",
        ]))
        self.targets = list(getattr(config, "BACKUP_TARGETS", ["local"]))
        self.enabled = bool(getattr(config, "BACKUP_ENABLED", True))
        self.interval = int(getattr(config, "BACKUP_INTERVAL_SECONDS", 900))
        self.campaign_name = getattr(config, "CAMPAIGN_NAME", "demo-15d")
        self.campaign_min_days = int(getattr(config, "CAMPAIGN_MIN_DAYS", 15))

        self.ledger_path = self.track_dir / "ledger.jsonl"
        self.index_path = self.track_dir / ".ledger_index.json"
        self.orders_ledger_path = self.track_dir / "hybrid_orders.jsonl"
        self.orders_index_path = self.track_dir / ".orders_ledger_index.json"
        self.manifest_path = self.track_dir / "manifest.json"

        self.status: Dict[str, Any] = {
            "enabled": self.enabled,
            "targets": self.targets,
            "interval_seconds": self.interval,
            "campaign_name": self.campaign_name,
            "campaign_min_days": self.campaign_min_days,
            "cycles": 0,
            "last_run_at": None,
            "last_duration_ms": None,
            "ledger_events": 0,
            "backends": {},
            "last_error": None,
            "campaign_start": None,
            "campaign_day": 0.0,
            "campaign_complete": False,
        }

    # ------------------------------------------------------------------ #
    #  Snapshot + ledger append-only
    # ------------------------------------------------------------------ #
    @staticmethod
    def _source_for(name: str) -> str:
        """Etiqueta de origen de cada archivo de track record."""
        if name == "paper_trades.json":
            return "realistic"
        if name == "paper_trades_hybrid.json":
            return "hybrid"
        return "research"

    def _snapshot_files(self) -> Dict[str, str]:
        snap: Dict[str, str] = {}
        for name in self.files:
            p = self.project_dir / name
            if p.exists():
                try:
                    snap[name] = p.read_text(encoding="utf-8")
                except Exception:
                    pass
        return snap

    def _load_index(self) -> set:
        data = _read_json(self.index_path, {})
        return set(data.get("keys", []))

    def _save_index(self, keys: set) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"keys": sorted(keys)}), encoding="utf-8")
        tmp.replace(self.index_path)

    def _append_ledger(self) -> int:
        """Añade al ledger append-only los eventos (trade+estado) nuevos."""
        index = self._load_index()
        lines: List[str] = []
        now_iso = utc_now().isoformat()

        for name in self.files:
            if not name.startswith("paper_trades"):
                continue
            raw = _read_json(self.project_dir / name, {})
            trades = raw.get("trades", {}) if isinstance(raw, dict) else {}
            source = self._source_for(name)
            for trade_id, t in trades.items():
                if not isinstance(t, dict):
                    continue
                key = f"{source}:{trade_id}:{t.get('status', '?')}"
                if key in index:
                    continue
                event = {"_source": source, "_ingested_at": now_iso}
                for k in _LEDGER_KEYS:
                    event[k] = t.get(k)
                lines.append(json.dumps(event, ensure_ascii=False))
                index.add(key)

        if lines:
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            self._save_index(index)
        return len(lines)

    # ------------------------------------------------------------------ #
    #  Órdenes live simuladas (Modo Híbrido) -> ledger + CSV
    # ------------------------------------------------------------------ #
    def _load_orders_index(self) -> set:
        data = _read_json(self.orders_index_path, {})
        return set(data.get("keys", []))

    def _save_orders_index(self, keys: set) -> None:
        tmp = self.orders_index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"keys": sorted(keys)}), encoding="utf-8")
        tmp.replace(self.orders_index_path)

    @staticmethod
    def _read_hybrid_orders() -> List[Dict[str, Any]]:
        raw = _read_json(
            Path(__file__).resolve().parent / "hybrid_orders.json", {}
        )
        if isinstance(raw, dict):
            orders = raw.get("orders", [])
        else:
            orders = raw or []
        return [o for o in orders if isinstance(o, dict)]

    @staticmethod
    def _flatten_order(order: Dict[str, Any]) -> Dict[str, Any]:
        row: Dict[str, Any] = {}
        for k in _ORDERS_LEDGER_KEYS:
            row[k] = order.get(k)
        fill = order.get("fill") or {}
        for k in _ORDERS_FILL_KEYS:
            row[k] = fill.get(k)
        return row

    @staticmethod
    def _ledger_includes_rejected() -> bool:
        """``HYBRID_ORDERS_LEDGER_ALL=1`` guarda también los rechazos (modo debug)."""
        return str(os.getenv("HYBRID_ORDERS_LEDGER_ALL", "0")).lower() in ("1", "true", "yes")

    def _append_orders_ledger(self) -> int:
        """Añade al ledger append-only las órdenes simuladas nuevas (nunca reescribe)."""
        index = self._load_orders_index()
        lines: List[str] = []
        now_iso = utc_now().isoformat()
        keep_rejected = self._ledger_includes_rejected()

        for order in self._read_hybrid_orders():
            oid = order.get("order_id")
            if not oid or oid in index:
                continue
            status = str(order.get("status") or "").upper()
            if not keep_rejected and status not in _ORDERS_LEDGER_STATUSES:
                continue
            event = {"_source": "hybrid", "_ingested_at": now_iso}
            event.update(self._flatten_order(order))
            lines.append(json.dumps(event, ensure_ascii=False))
            index.add(oid)

        if lines:
            with open(self.orders_ledger_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            self._save_orders_index(index)
        return len(lines)

    @staticmethod
    def _hybrid_diagnostics() -> Dict[str, Any]:
        """Resumen de ejecución del Modo Híbrido para el manifest (offline-friendly)."""
        raw = _read_json(Path(__file__).resolve().parent / "hybrid_orders.json", {})
        if not isinstance(raw, dict):
            return {}
        reasons = raw.get("rejection_reasons") or {}
        orders = raw.get("orders") or []
        return {
            "orders_executed": len(orders),
            "rejection_reasons": {str(k): int(v) for k, v in reasons.items()},
            "rejections_total": sum(int(v) for v in reasons.values()),
            "log_updated_at": raw.get("updated_at"),
        }

    def rebuild_orders_ledger(self) -> int:
        """Reconstruye el ledger de órdenes desde el log actual (compacta ruido)."""
        self.orders_ledger_path.unlink(missing_ok=True)
        self.orders_index_path.unlink(missing_ok=True)
        return self._append_orders_ledger()

    def compact_orders_ledger(self) -> Dict[str, int]:
        """Compacta el ledger existente conservando TODAS las ejecutadas.

        Quita las líneas de rechazo (ruido masivo) y deduplica por ``order_id``,
        pero nunca elimina una orden ejecutada: la historia real se respeta.
        """
        seen: Dict[str, Dict[str, Any]] = {}
        dropped = 0
        if self.orders_ledger_path.exists():
            for line in self.orders_ledger_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    dropped += 1
                    continue
                oid = event.get("order_id")
                status = str(event.get("status") or "").upper()
                if not oid or status not in _ORDERS_LEDGER_STATUSES:
                    dropped += 1
                    continue
                seen.setdefault(oid, event)

        tmp = self.orders_ledger_path.with_suffix(".jsonl.tmp")
        if seen:
            with open(tmp, "w", encoding="utf-8") as f:
                for event in seen.values():
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            tmp.replace(self.orders_ledger_path)
        else:
            self.orders_ledger_path.unlink(missing_ok=True)
        self._save_orders_index(set(seen))
        return {"kept": len(seen), "dropped": dropped}

    def _export_orders_csv(self) -> int:
        """Exporta las órdenes simuladas a un CSV legible (Excel / Google Sheets)."""
        orders = self._read_hybrid_orders()
        cols = [*_ORDERS_LEDGER_KEYS, *_ORDERS_FILL_KEYS]
        with open(self.track_dir / "hybrid_orders.csv", "w",
                  encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for order in orders:
                w.writerow(self._flatten_order(order))
        return len(orders)

    # ------------------------------------------------------------------ #
    #  Export CSV + ranking por estrategia
    # ------------------------------------------------------------------ #
    def _collect_trades(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for name in self.files:
            if not name.startswith("paper_trades"):
                continue
            raw = _read_json(self.project_dir / name, {})
            trades = raw.get("trades", {}) if isinstance(raw, dict) else {}
            source = self._source_for(name)
            for t in trades.values():
                if isinstance(t, dict):
                    r: Dict[str, Any] = {"source": source}
                    r.update(t)
                    rows.append(r)
        return rows

    def _export_csv(self, rows: List[Dict[str, Any]]) -> None:
        cols: List[str] = ["source"]
        seen = {"source"}
        for r in rows:
            for k, v in r.items():
                if k not in seen and not isinstance(v, (dict, list)):
                    seen.add(k)
                    cols.append(k)
        csv_path = self.track_dir / "trades_all.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    def _build_ranking(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_strat: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            code = r.get("strategy_code") or "GEN"
            s = by_strat.setdefault(code, {
                "strategy_code": code,
                "strategy_name": r.get("strategy") or code,
                "total": 0, "open": 0, "won": 0, "lost": 0,
                "realized_pnl_usd": 0.0, "unrealized_pnl_usd": 0.0,
                "partial_fills": 0, "by_source": {},
            })
            s["total"] += 1
            st = r.get("status")
            if st == "OPEN":
                s["open"] += 1
            elif st == "WON":
                s["won"] += 1
            elif st == "LOST":
                s["lost"] += 1
            s["realized_pnl_usd"] += float(r.get("realized_pnl_usd") or 0.0)
            s["unrealized_pnl_usd"] += float(r.get("unrealized_pnl_usd") or 0.0)

            # Comparativa por motor (realistic / research / hybrid) y calidad de
            # ejecución del Modo Híbrido (slippage real de libro y fills parciales).
            src = r.get("source") or "unknown"
            bucket = s["by_source"].setdefault(
                src, {"total": 0, "won": 0, "lost": 0, "net_pnl_usd": 0.0}
            )
            bucket["total"] += 1
            if st == "WON":
                bucket["won"] += 1
            elif st == "LOST":
                bucket["lost"] += 1
            bucket["net_pnl_usd"] += float(r.get("realized_pnl_usd") or 0.0) + float(
                r.get("unrealized_pnl_usd") or 0.0
            )
            if r.get("is_partial_fill"):
                s["partial_fills"] += 1
            slip = r.get("book_slippage_bps")
            if slip is not None:
                s["_slip_sum"] = s.get("_slip_sum", 0.0) + float(slip)
                s["_slip_n"] = s.get("_slip_n", 0) + 1

        ranking: List[Dict[str, Any]] = []
        for s in by_strat.values():
            closed = s["won"] + s["lost"]
            s["closed"] = closed
            s["win_rate_pct"] = round(s["won"] / closed * 100.0, 1) if closed else 0.0
            s["realized_pnl_usd"] = round(s["realized_pnl_usd"], 2)
            s["unrealized_pnl_usd"] = round(s["unrealized_pnl_usd"], 2)
            s["net_pnl_usd"] = round(s["realized_pnl_usd"] + s["unrealized_pnl_usd"], 2)
            slip_n = s.pop("_slip_n", 0)
            slip_sum = s.pop("_slip_sum", 0.0)
            s["avg_book_slippage_bps"] = round(slip_sum / slip_n, 2) if slip_n else None
            for bucket in s["by_source"].values():
                bucket["net_pnl_usd"] = round(bucket["net_pnl_usd"], 2)
            if closed < 10:
                s["verdict"] = "MUESTRA_INSUFICIENTE"
            elif s["win_rate_pct"] >= 55 and s["net_pnl_usd"] > 0:
                s["verdict"] = "CANDIDATA_REAL"
            elif s["net_pnl_usd"] > 0:
                s["verdict"] = "PROMETEDORA"
            else:
                s["verdict"] = "DESCARTAR"
            ranking.append(s)
        ranking.sort(key=lambda x: (x["net_pnl_usd"], x["closed"]), reverse=True)
        return ranking

    def _export_ranking(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        ranking = self._build_ranking(rows)
        out = {
            "generated_at": utc_now().isoformat(),
            "campaign": self.campaign_name,
            "strategies": ranking,
        }
        (self.track_dir / "strategy_ranking.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    # ------------------------------------------------------------------ #
    #  Backends off-site
    # ------------------------------------------------------------------ #
    def _push_local(self, files: List[Path]) -> Dict[str, Any]:
        mirror = os.getenv("BACKUP_LOCAL_DIR", "").strip()
        if not mirror:
            return {"ok": True, "detail": f"export local en {self.track_dir}"}
        dest = Path(mirror)
        dest.mkdir(parents=True, exist_ok=True)
        for p in files:
            try:
                shutil.copy2(p, dest / p.name)
            except Exception as e:
                return {"ok": False, "detail": str(e)}
        return {"ok": True, "detail": f"copiado a {dest}"}

    @staticmethod
    def _resolve_git_token() -> str:
        """Token para el push, en orden de prioridad:

        1. ``BACKUP_GIT_TOKEN`` (explícito en ``.env``),
        2. ``GITHUB_TOKEN`` / ``GH_TOKEN`` del entorno,
        3. ``gh auth token`` (CLI de GitHub ya autenticada).

        Resolverlo en tiempo de ejecución evita guardar secretos en ``.env`` y
        sobrevive a la rotación del token OAuth de ``gh``.
        """
        token = getattr(config, "BACKUP_GIT_TOKEN", "").strip()
        if token:
            return token
        token = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GH_TOKEN", "").strip()
        if token:
            return token
        try:
            r = subprocess.run(["gh", "auth", "token"], capture_output=True,
                               text=True, timeout=15)
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception:
            pass
        return ""

    def _git_auth_url(self) -> str:
        url = getattr(config, "BACKUP_GIT_REMOTE", "").strip()
        token = self._resolve_git_token()
        if not url or not token:
            return url
        tail = url.split("//", 1)[-1]
        if "@" in tail:
            return url  # ya lleva credenciales embebidas
        if url.startswith("https://"):
            return "https://" + token + "@" + url[len("https://"):]
        return url

    def _git_ident(self) -> List[str]:
        return [
            "-c", f"user.name={getattr(config, 'BACKUP_GIT_USER', 'quant-bot')}",
            "-c", f"user.email={getattr(config, 'BACKUP_GIT_EMAIL', 'quant-bot@users.noreply.github.com')}",
        ]

    # git puede devolver un codigo != 0 *despues* de haber actualizado la
    # referencia remota: si el hijo 'git-remote-https' ya fue recolectado, git
    # falla al hacer su waitpid ("No child processes") aunque el push SI llego.
    # Sin este filtro el respaldo se reportaba como caido estando a salvo.
    _GIT_ECHILD = "waitpid for git-remote-https failed"

    @classmethod
    def _git_push_effective(cls, output: str, branch: str) -> bool:
        if cls._GIT_ECHILD not in (output or ""):
            return False
        return any("->" in line and branch in line for line in output.splitlines())

    def _push_git(self, files: List[Path]) -> Dict[str, Any]:
        url = getattr(config, "BACKUP_GIT_REMOTE", "").strip()
        if not url:
            return {"ok": False, "detail": "BACKUP_GIT_REMOTE no configurado"}
        if not self._resolve_git_token():
            return {"ok": False,
                    "detail": "sin token: define BACKUP_GIT_TOKEN o ejecuta 'gh auth login'"}
        branch = getattr(config, "BACKUP_GIT_BRANCH", "main")
        repo = self.track_dir / ".git_push_repo"
        repo.mkdir(parents=True, exist_ok=True)
        auth_url = self._git_auth_url()

        def run(args, check=True):
            return subprocess.run(["git", "-C", str(repo), *args],
                                  capture_output=True, text=True, timeout=180, check=check)

        try:
            if not (repo / ".git").exists():
                run(["init", "-q", "-b", branch])
            if run(["remote", "get-url", "origin"], check=False).returncode == 0:
                run(["remote", "set-url", "origin", auth_url])
            else:
                run(["remote", "add", "origin", auth_url])
            for p in files:
                shutil.copy2(p, repo / p.name)
            run([*self._git_ident(), "add", "-A"])
            run([*self._git_ident(), "commit", "-m",
                 f"track-record backup {utc_now().isoformat()}", "--allow-empty"], check=False)
            r = run(["push", "-u", "origin", f"HEAD:{branch}"], check=False)
            out = f"{r.stdout or ''}{r.stderr or ''}"
            detail = out.strip().replace(auth_url, "<remote>")
            if r.returncode == 0:
                return {"ok": True, "detail": detail[-300:]}
            if self._git_push_effective(out, branch):
                return {"ok": True,
                        "detail": (f"[aviso: git exit {r.returncode} tras actualizar "
                                   f"la ref; push efectivo] {detail[-220:]}")}
            return {"ok": False, "detail": (detail[-300:] or f"git exit {r.returncode}")}
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or str(e)).replace(auth_url, "<remote>")
            return {"ok": False, "detail": msg.strip()[-300:]}
        except Exception as e:
            return {"ok": False, "detail": str(e)}

    def _push_s3(self, files: List[Path]) -> Dict[str, Any]:
        bucket = getattr(config, "BACKUP_S3_BUCKET", "").strip()
        if not bucket:
            return {"ok": False, "detail": "BACKUP_S3_BUCKET no configurado"}
        try:
            import boto3
        except ImportError:
            return {"ok": False, "detail": "boto3 no instalado (pip install boto3)"}
        try:
            kwargs: Dict[str, Any] = {}
            endpoint = getattr(config, "BACKUP_S3_ENDPOINT", "").strip()
            if endpoint:
                kwargs["endpoint_url"] = endpoint
            ak = getattr(config, "BACKUP_S3_ACCESS_KEY", "").strip()
            sk = getattr(config, "BACKUP_S3_SECRET_KEY", "").strip()
            if ak and sk:
                kwargs["aws_access_key_id"] = ak
                kwargs["aws_secret_access_key"] = sk
            kwargs["region_name"] = getattr(config, "BACKUP_S3_REGION", "auto") or "auto"
            s3 = boto3.client("s3", **kwargs)
            prefix = getattr(config, "BACKUP_S3_PREFIX", "quant-polymarket").strip("/")
            for p in files:
                s3.upload_file(str(p), bucket, f"{prefix}/{p.name}")
            return {"ok": True, "detail": f"{len(files)} archivos -> s3://{bucket}/{prefix}/"}
        except Exception as e:
            return {"ok": False, "detail": str(e)}

    def _push_http(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = getattr(config, "BACKUP_HTTP_URL", "").strip()
        if not url:
            return {"ok": False, "detail": "BACKUP_HTTP_URL no configurado"}
        try:
            import httpx
            headers = {}
            token = getattr(config, "BACKUP_HTTP_TOKEN", "").strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            r = httpx.post(url, json=payload, headers=headers, timeout=30)
            return {"ok": r.status_code < 300, "detail": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "detail": str(e)}

    # ------------------------------------------------------------------ #
    #  Ciclo completo
    # ------------------------------------------------------------------ #
    def _acquire_cycle_lock(self):
        """Serializa los ciclos de respaldo (hilo del bot vs. timer de systemd).

        Devuelve el descriptor del lock, ``False`` si ya hay otro ciclo en curso
        o ``None`` si la plataforma no soporta ``fcntl`` (se sigue sin lock).
        """
        try:
            import fcntl
        except ImportError:  # pragma: no cover - plataformas sin fcntl
            return None
        try:
            self.track_dir.mkdir(parents=True, exist_ok=True)
            fh = open(self.track_dir / ".backup.lock", "w")
        except OSError:
            return None
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            fh.close()
            return False

    def run_once(self) -> Dict[str, Any]:
        lock = self._acquire_cycle_lock()
        if lock is False:
            print("[Backup] Ya hay otro ciclo en curso; se omite este.")
            return {"skipped": True, "reason": "otro ciclo de respaldo en curso"}
        started = utc_now()
        result: Dict[str, Any] = {"ran_at": started.isoformat(), "backends": {}}
        try:
            self.track_dir.mkdir(parents=True, exist_ok=True)
            manifest = _read_json(self.manifest_path, {})
            if not manifest.get("campaign_start"):
                manifest["campaign_start"] = started.isoformat()
            manifest["campaign_name"] = self.campaign_name
            manifest["updated_at"] = started.isoformat()

            # 1) Ledger append-only
            result["ledger_events_added"] = self._append_ledger()

            # 2) CSV combinado + ranking por estrategia
            rows = self._collect_trades()
            self._export_csv(rows)
            ranking = self._export_ranking(rows)

            # 2b) Órdenes live simuladas del Modo Híbrido (ledger append-only + CSV)
            result["orders_events_added"] = self._append_orders_ledger()
            result["orders_total"] = self._export_orders_csv()

            # 2c) Diagnóstico de la ejecución híbrida (motivos de rechazo agregados)
            manifest["hybrid"] = self._hybrid_diagnostics()

            # 3) Manifest de integridad (hashes para detectar corrupción)
            manifest["files"] = {
                p.name: {"bytes": p.stat().st_size, "sha256": _sha256(p)}
                for p in sorted(self.track_dir.glob("*"))
                if p.is_file() and p.name != "manifest.json" and not p.name.startswith(".")
            }
            manifest["trade_counts"] = {
                "total": len(rows),
                "realistic": sum(1 for r in rows if r["source"] == "realistic"),
                "research": sum(1 for r in rows if r["source"] == "research"),
                "hybrid": sum(1 for r in rows if r["source"] == "hybrid"),
            }
            manifest["strategies"] = len(ranking["strategies"])
            try:
                cstart = datetime.fromisoformat(manifest["campaign_start"])
                manifest["campaign_day"] = round((started - cstart).total_seconds() / 86400.0, 2)
                manifest["campaign_complete"] = manifest["campaign_day"] >= self.campaign_min_days
            except Exception:
                manifest["campaign_day"] = 0.0
                manifest["campaign_complete"] = False
            self.manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

            # 4) Lista de archivos a empujar off-site
            files_to_push = [
                self.track_dir / n
                for n in ("ledger.jsonl", "trades_all.csv", "strategy_ranking.json",
                          "manifest.json", "hybrid_orders.jsonl", "hybrid_orders.csv",
                          "CAMPAIGN_REPORT.md")
                if (self.track_dir / n).exists()
            ]
            for name in self.files:
                p = self.project_dir / name
                if p.exists():
                    files_to_push.append(p)

            payload = {
                "campaign": self.campaign_name,
                "campaign_day": manifest.get("campaign_day"),
                "trade_counts": manifest.get("trade_counts"),
                "strategies": ranking["strategies"],
                "hybrid_orders": result.get("orders_total", 0),
                "generated_at": manifest["updated_at"],
            }

            # 5) Push a cada backend habilitado (nunca rompe el bot)
            for target in self.targets:
                if target == "local":
                    res = self._push_local(files_to_push)
                elif target == "git":
                    res = self._push_git(files_to_push)
                elif target == "s3":
                    res = self._push_s3(files_to_push)
                elif target == "http":
                    res = self._push_http(payload)
                else:
                    res = {"ok": False, "detail": f"target desconocido: {target}"}
                result["backends"][target] = res
                if not res.get("ok"):
                    print(f"[Backup] backend '{target}' FALLO: {res.get('detail')}")

            self.status.update({
                "cycles": self.status["cycles"] + 1,
                "last_run_at": started.isoformat(),
                "last_duration_ms": round((utc_now() - started).total_seconds() * 1000, 1),
                "ledger_events": len(self._load_index()),
                "orders_events": len(self._load_orders_index()),
                "orders_logged": result.get("orders_total", 0),
                "backends": result["backends"],
                "last_error": None,
                "campaign_start": manifest.get("campaign_start"),
                "campaign_day": manifest.get("campaign_day"),
                "campaign_complete": manifest.get("campaign_complete", False),
                "trade_counts": manifest.get("trade_counts"),
            })
        except Exception as e:
            self.status["last_error"] = str(e)
            print(f"[Backup] Error en ciclo: {e}")
        finally:
            if lock is not None:
                try:
                    lock.close()
                except Exception:
                    pass
        return result

    def get_status(self) -> Dict[str, Any]:
        return dict(self.status)


# Instancia global usada por main.py
backup_manager = BackupManager()


# --------------------------------------------------------------------------- #
#  Mantenimiento por línea de comandos
# --------------------------------------------------------------------------- #
def _main(argv: List[str]) -> int:
    """Utilidades de mantenimiento del track record.

    Uso:
        python3 backup_manager.py run                 # fuerza un ciclo completo
        python3 backup_manager.py rebuild-orders      # compacta el ledger de órdenes
        python3 backup_manager.py compact-orders      # quita rechazos del ledger (conserva ejecutadas)
    """
    cmd = argv[1] if len(argv) > 1 else "run"
    if cmd == "run":
        res = backup_manager.run_once()
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        return 0
    if cmd == "compact-orders":
        res = backup_manager.compact_orders_ledger()
        path = backup_manager.orders_ledger_path
        size = path.stat().st_size if path.exists() else 0
        print(f"Ledger compactado: {res['kept']} ejecutadas conservadas, "
              f"{res['dropped']} descartadas ({size:,} bytes) en {path}")
        return 0
    if cmd == "rebuild-orders":
        total = backup_manager.rebuild_orders_ledger()
        path = backup_manager.orders_ledger_path
        size = path.stat().st_size if path.exists() else 0
        print(f"Ledger de órdenes reconstruido: {total} eventos ({size:,} bytes) en {path}")
        if not backup_manager._ledger_includes_rejected():
            print("Solo órdenes ejecutadas (FILLED/PARTIAL/MAKER_FILLED). "
                  "Usa HYBRID_ORDERS_LEDGER_ALL=1 para incluir rechazos.")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
