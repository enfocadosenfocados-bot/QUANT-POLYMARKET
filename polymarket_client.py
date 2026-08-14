"""Cliente async para Polymarket - Gamma API, CLOB API, WebSocket Market Stream"""
import asyncio
import json
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Any
import httpx
import websockets

from config import GAMMA_API, CLOB_API, DATA_API, WS_MARKET, HEARTBEAT_INTERVAL, MAX_MARKETS_WS
from market_registry import registry


class PolymarketClient:
    """Cliente unificado para todas las APIs de Polymarket"""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=10.0, limits=httpx.Limits(max_connections=50))
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.ws_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.running = False
        self.subscribed_tokens: List[str] = []
        self._reconnect_delay = 1

    @staticmethod
    def _to_decimal(value: Any, default: str = "0") -> Decimal:
        if value in (None, ""):
            return Decimal(default)
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal(default)

    async def close(self):
        self.running = False
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.ws_task:
            self.ws_task.cancel()
        if self.ws:
            await self.ws.close()
        await self.http.aclose()

    # ========== GAMMA API ==========

    async def fetch_markets(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Obtener lista de mercados activos desde Gamma API"""
        url = f"{GAMMA_API}/markets"
        params = {
            "closed": "false",
            "active": "true",
            "limit": limit,
            "offset": offset,
        }
        start = time.time()
        try:
            resp = await self.http.get(url, params=params)
            latency = int((time.time() - start) * 1000)
            registry.system_stats["api_latency_ms"] = latency

            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else data.get("markets", [])
            else:
                print(f"[Gamma] Error {resp.status_code}: {resp.text[:200]}")
                return []
        except Exception as e:
            print(f"[Gamma] Exception: {e}")
            return []

    async def fetch_all_active_markets(self) -> List[Dict]:
        """Obtener todos los mercados activos con paginación"""
        all_markets = []
        offset = 0
        while True:
            markets = await self.fetch_markets(limit=100, offset=offset)
            if not markets:
                break
            all_markets.extend(markets)
            if len(markets) < 100:
                break
            offset += 100
            await asyncio.sleep(0.5)  # Rate limiting respetuoso
        print(f"[Gamma] Total mercados activos: {len(all_markets)}")
        return all_markets

    async def fetch_market_detail(self, market_id: str) -> Optional[Dict]:
        """Obtener detalle de un mercado"""
        url = f"{GAMMA_API}/markets/{market_id}"
        try:
            resp = await self.http.get(url)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[Gamma Detail] Error: {e}")
        return None

    # ========== CLOB API ==========

    async def fetch_orderbook(self, token_id: str) -> Optional[Dict]:
        """Obtener order book para un token"""
        url = f"{CLOB_API}/book"
        params = {"token_id": token_id}
        try:
            resp = await self.http.get(url, params=params)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[CLOB Book] Error: {e}")
        return None

    async def fetch_midpoint(self, token_id: str) -> Optional[Decimal]:
        """Obtener midpoint price"""
        url = f"{CLOB_API}/midpoint"
        params = {"token_id": token_id}
        try:
            resp = await self.http.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return self._to_decimal(data.get("mid", 0))
        except Exception as e:
            print(f"[CLOB Mid] Error: {e}")
        return None

    async def fetch_midpoints_batch(self, token_ids: List[str]) -> Dict[str, Decimal]:
        """Obtener múltiples midpoints en un solo request"""
        url = f"{CLOB_API}/midpoints"
        payload = [{"token_id": tid} for tid in token_ids]
        try:
            resp = await self.http.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return {k: self._to_decimal(v) for k, v in data.items()}
        except Exception as e:
            print(f"[CLOB Mids] Error: {e}")
        return {}

    async def fetch_price(self, token_id: str, side: str = "BUY") -> Optional[Decimal]:
        """Obtener precio top-of-book"""
        url = f"{CLOB_API}/price"
        params = {"token_id": token_id, "side": side}
        try:
            resp = await self.http.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return self._to_decimal(data.get("price", 0))
        except Exception as e:
            print(f"[CLOB Price] Error: {e}")
        return None

    # ========== DATA API pública ==========

    async def fetch_recent_trades(self, limit: int = 250) -> List[Dict]:
        """Obtener trades públicos recientes de Polymarket Data API."""
        url = f"{DATA_API}/trades"
        params = {"limit": limit, "takerOnly": "false"}
        try:
            resp = await self.http.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else data.get("trades", [])
            print(f"[Data Trades] Error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[Data Trades] Error: {e}")
        return []

    async def fetch_user_positions(self, wallet: str, limit: int = 100) -> List[Dict]:
        """Obtener posiciones públicas de una wallet/proxyWallet."""
        url = f"{DATA_API}/positions"
        params = {"user": wallet, "limit": limit, "sortBy": "CASHPNL", "sortDirection": "DESC"}
        try:
            resp = await self.http.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else data.get("positions", [])
        except Exception as e:
            print(f"[Data Positions] Error wallet={wallet[:10]}: {e}")
        return []

    async def fetch_market_holders(self, condition_id: str, limit: int = 10) -> List[Dict]:
        """Obtener top holders públicos por conditionId.

        Importante: el parámetro correcto de Data API es `market=<conditionId>`.
        `market=<id numérico de Gamma>` o `conditionId=...` devuelve 400.
        """
        url = f"{DATA_API}/holders"
        params = {"market": condition_id, "limit": min(limit, 20)}
        try:
            resp = await self.http.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else []
            print(f"[Data Holders] Error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[Data Holders] Error market={condition_id[:10]}: {e}")
        return []

    # ========== WEBSOCKET ==========

    async def start_websocket(self, token_ids: List[str]):
        """Iniciar conexión WebSocket a Polymarket"""
        self.subscribed_tokens = token_ids[:MAX_MARKETS_WS]
        if not self.subscribed_tokens:
            print("[WS] Sin tokens para suscribir; WebSocket externo en espera")
            return
        if self.running:
            return
        self.running = True
        self.ws_task = asyncio.create_task(self._ws_loop())
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        print(f"[WS] Iniciando conexión para {len(self.subscribed_tokens)} tokens")

    async def _ws_loop(self):
        """Loop principal de WebSocket con reconexión automática"""
        while self.running:
            if not self.subscribed_tokens:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                continue
            try:
                print(f"[WS] Conectando a {WS_MARKET}...")
                async with websockets.connect(WS_MARKET, ping_interval=None) as ws:
                    self.ws = ws
                    self._reconnect_delay = 1
                    registry.system_stats["ws_connected"] = True
                    print("[WS] Conectado!")

                    if self.subscribed_tokens:
                        subscribe_msg = {
                            "assets_ids": self.subscribed_tokens,
                            "type": "market"
                        }
                        await ws.send(json.dumps(subscribe_msg))
                    print(f"[WS] Suscrito a {len(self.subscribed_tokens)} tokens")

                    # Procesar mensajes
                    async for message in ws:
                        if not self.running:
                            break
                        await self._handle_ws_message(message)

            except websockets.exceptions.ConnectionClosed:
                print("[WS] Conexión cerrada, reconectando...")
            except Exception as e:
                print(f"[WS] Error: {e}")

            registry.system_stats["ws_connected"] = False
            self.ws = None

            if self.running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def _heartbeat_loop(self):
        """Enviar PING cada 10 segundos"""
        while self.running:
            try:
                if self.ws and not getattr(self.ws, "closed", False):
                    await self.ws.send("PING")
                await asyncio.sleep(HEARTBEAT_INTERVAL)
            except Exception:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _handle_ws_message(self, message: str):
        """Procesar mensaje WebSocket"""
        try:
            # PONG response
            if message == "PONG":
                return

            data = json.loads(message)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        await self._handle_ws_payload(item)
                return
            if isinstance(data, dict):
                await self._handle_ws_payload(data)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"[WS Handler] Error: {e}")

    async def _handle_ws_payload(self, data: Dict[str, Any]):
        """Procesar payload JSON individual del WebSocket."""
        try:

            # Determinar tipo de evento
            event_type = data.get("event_type") or data.get("type")

            if not event_type:
                return

            # Extraer token_id
            token_id = data.get("asset_id") or data.get("tokenId") or data.get("token_id")
            if not token_id:
                return

            # Actualizar registro
            await registry.update_from_ws(str(token_id), event_type, data)

            # Actualizar stats
            registry.system_stats["last_ws_message"] = time.time()

        except Exception as e:
            print(f"[WS Payload] Error: {e}")

    async def update_subscriptions(self, token_ids: List[str]):
        """Actualizar tokens suscritos en WebSocket"""
        self.subscribed_tokens = token_ids[:MAX_MARKETS_WS]
        if not self.subscribed_tokens:
            return
        if not self.running:
            await self.start_websocket(self.subscribed_tokens)
            return
        if self.ws and not getattr(self.ws, "closed", False):
            msg = {
                "assets_ids": self.subscribed_tokens,
                "type": "market"
            }
            await self.ws.send(json.dumps(msg))


# Instancia global
pm_client = PolymarketClient()
