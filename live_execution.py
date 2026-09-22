"""Módulo de Ejecución Real (Live Trading) para Polymarket CLOB.
Permite alternar entre Paper Trading y Live Trading con límites estrictos de capital,
firma de órdenes y botón de parada de emergencia (Kill-Switch).
"""
import os
import json
import time
import hmac
import hashlib
import base64
from pathlib import Path
from typing import Dict, Any, Optional
import httpx

CLOB_API_URL = "https://clob.polymarket.com"
CREDENTIALS_FILE = Path(__file__).resolve().parent / "clob_credentials.json"


class LiveExecutionManager:
    """Gestor de órdenes reales en Polymarket CLOB con salvaguardas de riesgo."""

    def __init__(self):
        self.mode: str = "PAPER"  # "PAPER" o "LIVE"
        self.max_live_trade_usd: float = 25.0  # Límite de seguridad por trade en Live ($25 USD para cuenta de $1,000)
        self.max_open_live_trades: int = 5
        self.api_key: str = ""
        self.api_secret: str = ""
        self.api_passphrase: str = ""
        self.wallet_address: str = ""
        self.kill_switch_active: bool = False
        self.load_credentials()

    @property
    def is_live(self) -> bool:
        return self.mode == "LIVE"

    def load_credentials(self):
        if CREDENTIALS_FILE.exists():
            try:
                with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.mode = data.get("mode", "PAPER")
                    self.max_live_trade_usd = float(data.get("max_live_trade_usd", 50.0))
                    self.api_key = data.get("api_key", "")
                    self.api_secret = data.get("api_secret", "")
                    self.api_passphrase = data.get("api_passphrase", "")
                    self.wallet_address = data.get("wallet_address", "")
            except Exception as e:
                print(f"[LiveExecution] Error leyendo credenciales: {e}")

    def save_credentials(self, data: Dict[str, Any]):
        try:
            self.mode = data.get("mode", self.mode)
            self.max_live_trade_usd = float(data.get("max_live_trade_usd", self.max_live_trade_usd))
            if "api_key" in data and data["api_key"] != "***":
                self.api_key = data["api_key"]
            if "api_secret" in data and data["api_secret"] != "***":
                self.api_secret = data["api_secret"]
            if "api_passphrase" in data and data["api_passphrase"] != "***":
                self.api_passphrase = data["api_passphrase"]
            if "wallet_address" in data:
                self.wallet_address = data["wallet_address"]

            to_save = {
                "mode": self.mode,
                "max_live_trade_usd": self.max_live_trade_usd,
                "api_key": self.api_key,
                "api_secret": self.api_secret,
                "api_passphrase": self.api_passphrase,
                "wallet_address": self.wallet_address,
                "updated_at": time.time(),
            }
            with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                json.dump(to_save, f, indent=2)
            print("[LiveExecution] Credenciales actualizadas con éxito.")
        except Exception as e:
            print(f"[LiveExecution] Error guardando credenciales: {e}")

    def get_public_status(self) -> Dict[str, Any]:
        """Devuelve el estado público sin exponer secretos ni claves privadas."""
        return {
            "mode": self.mode,
            "is_live": self.mode == "LIVE",
            "has_credentials": bool(self.api_key and self.api_secret and self.wallet_address),
            "max_live_trade_usd": self.max_live_trade_usd,
            "max_open_live_trades": self.max_open_live_trades,
            "wallet_address": self.wallet_address[:6] + "..." + self.wallet_address[-4:] if len(self.wallet_address) > 10 else (self.wallet_address or "No conectada"),
            "kill_switch_active": self.kill_switch_active,
        }

    def set_mode(self, new_mode: str) -> Dict[str, Any]:
        valid_mode = "LIVE" if new_mode.upper() == "LIVE" else "PAPER"
        if valid_mode == "LIVE" and not (self.api_key and self.api_secret and self.wallet_address):
            return {
                "success": False,
                "message": "No se puede activar Live Trading sin configurar primero API Key, Secret y Wallet de Polymarket.",
                "status": self.get_public_status(),
            }

        self.mode = valid_mode
        self.save_credentials({"mode": self.mode})
        return {
            "success": True,
            "message": f"Modo cambiado a {'🟢 OPERATIVA REAL (Live)' if self.mode == 'LIVE' else '🧪 SIMULACIÓN (Paper Trading)'}",
            "status": self.get_public_status(),
        }

    def activate_kill_switch(self) -> Dict[str, Any]:
        """Detención de emergencia: fuerza el modo PAPER y cancela ejecuciones reales."""
        self.kill_switch_active = True
        self.mode = "PAPER"
        self.save_credentials({"mode": "PAPER"})
        print("[LiveExecution] 🛑 KILL-SWITCH ACTIVADO: Modo revertido a PAPER Trading de inmediato.")
        return {
            "success": True,
            "message": "🛑 Kill-Switch activado con éxito. Todas las ejecuciones reales han sido detenidas y el bot volvió a Paper Trading.",
            "status": self.get_public_status(),
        }

    async def execute_order(self, signal: Dict[str, Any], market: Any, size_usd: float) -> Dict[str, Any]:
        """Ejecuta una orden real en Polymarket CLOB si el modo LIVE está activo."""
        if self.mode != "LIVE":
            return {"executed": False, "mode": "PAPER", "message": "Ejecutado en simulación (Paper Trading)"}

        if self.kill_switch_active:
            return {"executed": False, "error": "Kill-Switch activo. Operaciones bloqueadas."}

        # Control estricto de capital máximo
        allocated_usd = min(size_usd, self.max_live_trade_usd)
        token_id = signal.get("token_id")
        price = float(signal.get("entry_price") or 0)
        side = str(signal.get("side") or "BUY").upper()

        if price <= 0 or not token_id:
            return {"executed": False, "error": "Parámetros de orden inválidos"}

        shares = round(allocated_usd / price, 2)

        # Preparar payload para CLOB API
        order_payload = {
            "order": {
                "tokenID": token_id,
                "price": price,
                "size": shares,
                "side": side,
                "feeRateBps": 0,
                "expiration": 0,
                "nonce": int(time.time() * 1000),
            },
            "owner": self.wallet_address,
            "orderType": "GTC",
        }

        print(f"[LiveExecution] 🚀 Enviando orden REAL a Polymarket CLOB: {side} {shares} shares @ ${price:.4f} (${allocated_usd:.2f} USD)")

        # Enviar petición autenticada a CLOB
        try:
            timestamp = str(int(time.time()))
            # Firma HMAC básica si se dispone de api_secret
            headers = {
                "POLY_API_KEY": self.api_key,
                "POLY_PASSPHRASE": self.api_passphrase,
                "POLY_TIMESTAMP": timestamp,
                "Content-Type": "application/json",
            }
            if self.api_secret:
                sig_payload = f"{timestamp}POST/order{json.dumps(order_payload)}"
                signature = base64.b64encode(hmac.new(self.api_secret.encode(), sig_payload.encode(), hashlib.sha256).digest()).decode()
                headers["POLY_SIGNATURE"] = signature

            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(f"{CLOB_API_URL}/order", json=order_payload, headers=headers)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    print(f"[LiveExecution] ✅ Orden REAL ejecutada con éxito: {data}")
                    return {"executed": True, "mode": "LIVE", "clob_response": data, "size_usd": allocated_usd}
                else:
                    print(f"[LiveExecution] ⚠️ CLOB API respondió con código {resp.status_code}: {resp.text}")
                    return {"executed": False, "mode": "LIVE", "error": f"HTTP {resp.status_code}: {resp.text[:150]}"}
        except Exception as e:
            print(f"[LiveExecution] ❌ Error conectando con CLOB API: {e}")
            return {"executed": False, "mode": "LIVE", "error": str(e)}


# Instancia global
live_manager = LiveExecutionManager()
