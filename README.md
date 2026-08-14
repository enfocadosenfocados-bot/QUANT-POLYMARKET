# 🔮 QUANT POLYMARKET

Sistema de inteligencia de mercado en tiempo real para Polymarket con estrategias quant y dashboard por estrategia.

## 🚀 Características

- **Datos en tiempo real** vía WebSocket de Polymarket (latencia ~100-500ms)
- **6 estrategias quant** calculadas automáticamente:
  - A: Market Making intra-mercado
  - B: Bundle Arbitrage (YES + NO ≠ $1)
  - C: Mean Reversion (historial local + fallback Gamma 1d/1w)
  - D: Favorite-Longshot Bias
  - E: Latencia en datos externos (placeholder)
  - F: Whale Tracking (Data API pública: top holders + trades recientes + posiciones públicas)
- **Dashboard web** con actualizaciones en tiempo real
- **Reconexión automática** de WebSockets
- **Sin autenticación requerida** para lectura de datos

## 📋 Requisitos

- Python 3.11+ probado también con Python 3.14 en Windows
- pip

## ⚡ Instalación Rápida

```bash
# 1. Clonar o descargar el proyecto
cd QUANT-POLYMARKET

# 2. Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o: venv\Scripts\activate  # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Ejecutar
python main.py
```

## 🌐 Acceder al Dashboard

Abre tu navegador en: **http://localhost:8000/dashboard**

La API REST está disponible en: **http://localhost:8000**

## 🪟 Windows

También puedes ejecutar directamente:

```bat
start.bat
```

El script crea `venv`, instala/actualiza dependencias y arranca el backend.


## 🧭 Dashboard por estrategias

La pestaña **Señales en Tiempo Real** está dividida en 5 paneles independientes:

- **A: Market Making** (`MM`)
- **B: Bundle Arbitrage** (`BA`)
- **C: Mean Reversion** (`MR`)
- **D: Favorite-Longshot Bias** (`FLB`)
- **F: Whale Tracking** (`WT`)

Dentro de cada panel, las señales mantienen la prioridad operativa: primero las de **800 bps**, luego mayor profit esperado, mayor confianza y señal más reciente.

## 🗂️ Clasificación de mercados

La pestaña **Todos los Mercados** incluye filtros por categoría:

- Politics
- Sports
- Weather
- Economics
- Crypto
- Culture
- Science
- Other

Si Gamma API no devuelve categoría, QUANT POLYMARKET la infiere automáticamente desde `question`, `slug` y `tags` usando palabras clave. Esto permite separar mercados de criptomonedas, clima, política, deportes, economía, cultura y ciencia aunque el campo `category` venga vacío.

## 📡 Endpoints API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/markets?limit=1000&category=Crypto` | Lista de mercados activos con resumen y filtro opcional por categoría |
| `GET /api/market/{id}` | Detalle de un mercado |
| `GET /api/signals?limit=1000` | Señales activas ordenadas para el dashboard |
| `GET /api/arbitrage` | Oportunidades de bundle arbitrage |
| `GET /api/stats` | Estadísticas del sistema |
| `GET /api/strategies` | Diagnóstico por estrategia y razones de filtrado |
| `WS /ws` | WebSocket para actualizaciones en tiempo real |

## 🏗️ Arquitectura

```
Polymarket APIs
    ├── Gamma API (REST) ──→ Descubrimiento de mercados
    ├── CLOB API (REST) ───→ Order books y precios
    └── WebSocket ─────────→ Order book en tiempo real
              │
              ▼
    QUANT POLYMARKET
    ├── market_registry.py ──→ Cache en memoria
    ├── strategies.py ─────────→ Motor de estrategias
    ├── polymarket_client.py ─→ Cliente async
    └── main.py ─────────────→ FastAPI + WebSocket propio
              │
              ▼
    Dashboard (localhost:8000/dashboard)
```

## ⚙️ Configuración

Edita `config.py` para ajustar parámetros:

```python
# Intervalos de polling
GAMMA_POLL_INTERVAL = 30   # segundos
CLOB_POLL_INTERVAL = 5       # segundos

# Filtros de mercado
MIN_LIQUIDITY = 5000
MIN_VOLUME_24H = 2000

# Parámetros de estrategias
STRATEGY_PARAMS = {
    "market_making": {"min_spread_bps": 50, ...},
    "bundle_arbitrage": {"min_inefficiency": 0.005},
    "mean_reversion": {"z_score_threshold": 2.0, ...},
    ...
}
```

## 🖥️ Despliegue 24/7

### Opción 1: VPS (DigitalOcean, AWS, Hetzner)

```bash
# En el servidor
sudo apt update && sudo apt install python3-pip screen
screen -S quant-polymarket
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
# Ctrl+A, D para desconectar
```

### Opción 2: Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "main.py"]
```

### Opción 3: systemd (Linux)

Crear `/etc/systemd/system/quant-polymarket.service`:

```ini
[Unit]
Description=QUANT POLYMARKET
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/QUANT-POLYMARKET
ExecStart=/home/ubuntu/QUANT-POLYMARKET/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable quant-polymarket
sudo systemctl start quant-polymarket
sudo systemctl status quant-polymarket
```

## 📊 Sobre la Latencia

| Fuente | Latencia típica |
|--------|----------------|
| WebSocket Polymarket | 100-500ms |
| REST API (fallback) | 200-800ms |
| Cálculo de estrategias | <10ms |
| Dashboard (localhost) | <50ms |
| **Total end-to-end** | **<1 segundo** |

## 🔒 Notas de Seguridad

- Este scanner opera en **modo solo lectura** por defecto
- No requiere claves API para datos de mercado
- Para ejecutar órdenes automáticas, necesitarás:
  - Cuenta en Polymarket
  - API Key de CLOB (autenticada)
  - Wallet con fondos en Polygon
  - Implementar el módulo de ejecución en `strategies.py`

## 🛠️ Próximos Pasos

1. **Integrar fuentes de datos externos** (NOAA, ESPN, FRED) para Estrategia E
2. **Añadir watchlist manual de wallets** para Whale Tracking si quieres seguir direcciones concretas aunque no hayan operado recientemente.
3. **Implementar ejecución automática** de órdenes vía CLOB API
4. **Agregar backtesting** con datos históricos
5. **Alertas** vía Telegram/Discord

## 📄 Licencia

MIT - Uso bajo tu propio riesgo. El trading conlleva riesgo de pérdida.
