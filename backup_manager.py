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
]


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
            source = "realistic" if name == "paper_trades.json" else "research"
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
    #  Export CSV + ranking por estrategia
    # ------------------------------------------------------------------ #
    def _collect_trades(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for name in self.files:
            if not name.startswith("paper_trades"):
                continue
            raw = _read_json(self.project_dir / name, {})
            trades = raw.get("trades", {}) if isinstance(raw, dict) else {}
            source = "realistic" if name == "paper_trades.json" else "research"
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

        ranking: List[Dict[str, Any]] = []
        for s in by_strat.values():
            closed = s["won"] + s["lost"]
            s["closed"] = closed
            s["win_rate_pct"] = round(s["won"] / closed * 100.0, 1) if closed else 0.0
            s["realized_pnl_usd"] = round(s["realized_pnl_usd"], 2)
            s["unrealized_pnl_usd"] = round(s["unrealized_pnl_usd"], 2)
            s["net_pnl_usd"] = round(s["realized_pnl_usd"] + s["unrealized_pnl_usd"], 2)
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

    def _git_auth_url(self) -> str:
        url = getattr(config, "BACKUP_GIT_REMOTE", "").strip()
        token = getattr(config, "BACKUP_GIT_TOKEN", "").strip()
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

    def _push_git(self, files: List[Path]) -> Dict[str, Any]:
        url = getattr(config, "BACKUP_GIT_REMOTE", "").strip()
        if not url:
            return {"ok": False, "detail": "BACKUP_GIT_REMOTE no configurado"}
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
            r = run(["push", "-u", "origin", f"HEAD:{branch}"])
            detail = (r.stderr or r.stdout).strip().replace(auth_url, "<remote>")
            return {"ok": True, "detail": detail[-300:]}
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
    def run_once(self) -> Dict[str, Any]:
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
                for n in ("ledger.jsonl", "trades_all.csv", "strategy_ranking.json", "manifest.json")
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
        return result

    def get_status(self) -> Dict[str, Any]:
        return dict(self.status)


# Instancia global usada por main.py
backup_manager = BackupManager()
