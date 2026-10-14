# 🔮 QUANT POLYMARKET

Sistema de inteligencia de mercado en tiempo real para Polymarket con estrategias quant y dashboard por estrategia.

## 🚀 Características

- **Datos en tiempo real** vía WebSocket de Polymarket (latencia ~100-500ms)
- **11 estrategias quant** calculadas automáticamente:
  - A: Market Making intra-mercado
  - B: Bundle Arbitrage (YES + NO ≠ $1)
  - C: Mean Reversion (historial local + fallback Gamma 1d/1w)
  - D: Favorite-Longshot Bias
  - E: Latencia en datos externos (placeholder)
  - F: Whale Tracking (Data API pública: top holders + trades recientes + posiciones públicas)
  - S02: Weather NOAA
  - S03: Nothing Ever Happens
  - S05: NegRisk Rebalancing
  - S10: Yes Bias
  - S12: High Probability Harvesting
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

La pestaña **Señales en Tiempo Real** está dividida en paneles independientes por estrategia:

- **A: Market Making** (`MM`)
- **B: Bundle Arbitrage** (`BA`)
- **C: Mean Reversion** (`MR`)
- **D: Favorite-Longshot Bias** (`FLB`)
- **F: Whale Tracking** (`WT`)
- **S02: Weather NOAA** (`S02`)
- **S03: Nothing Ever Happens** (`S03`)
- **S05: NegRisk Rebalancing** (`S05`)
- **S10: Yes Bias** (`S10`)
- **S12: High Probability Harvesting** (`S12`)

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
    ├── strategies.py ─────────→ Motor de estrategias + adaptador modular Sxx
    ├── core_models.py ────────→ Modelos base para estrategias modulares
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

## 🧪 Campaña Demo >15d y Respaldo Off-Site del Track Record

El objetivo es **experimentar en demo (paper) con TODAS las estrategias durante
más de 15 días** y decidir con datos cuáles pasan a operar en real, sin depender
de una única VPS: si se cae o se reinicia, el track record no se pierde.

### Qué hace el bot automáticamente

- Ejecuta **todas** las estrategias en dos trackers:
  - `paper_trades.json` → cuenta realista de $1,000 (solo señales Ultra ≥75%).
  - `paper_trades_research.json` → **presupuesto aislado por estrategia**, captura
    todas las señales (≥60%) para poder comparar estrategias entre sí.
- Cada `BACKUP_INTERVAL_SECONDS` (por defecto 15 min), `backup_manager.py`:
  1. Añade cada trade nuevo a `track_record/ledger.jsonl` (**append-only**: nunca
     se reescribe, así un borrado parcial no destruye el histórico).
  2. Exporta `track_record/trades_all.csv`, `strategy_ranking.json` y
     `manifest.json` (con hashes SHA-256 para detectar corrupción).
  3. Empuja la copia a los destinos off-site configurados.

### Configuración off-site

Copia `.env.example` a `.env` y elige el destino (puedes combinar varios):

```
BACKUP_TARGETS=git,http      # local,git,s3,http (separados por comas)
```

- **git** (recomendado): crea un repo **privado** vacío y define
  `BACKUP_GIT_REMOTE` + `BACKUP_GIT_TOKEN` (PAT con permiso de escritura).
  También puedes reutilizar este mismo repo apuntando a otra rama
  (`BACKUP_GIT_BRANCH=trackrecord`).
- **s3**: AWS S3 / Cloudflare R2 / Backblaze B2 / MinIO (requiere `pip install boto3`).
- **http**: webhook (Google Apps Script, n8n, Make, Supabase...).
- **local**: copia a otra carpeta (p. ej. disco montado) vía `BACKUP_LOCAL_DIR`.

Un backend caído **nunca** rompe el bot: el fallo se registra y se consulta en
`GET /api/backup/status`.

### API

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/backup/status` | Estado, día de campaña, ciclos y resultado por backend |
| `POST /api/backup/run` | Forzar un ciclo de respaldo inmediato |
| `GET /api/campaign/report` | Ranking por estrategia + manifest de la campaña |

### Reporte y decisión (pasar a real / descartar)

```
python report_campaign.py                 # usa ./track_record
python report_campaign.py /ruta/track_record
```

Genera `track_record/CAMPAIGN_REPORT.md` con el veredicto por estrategia:

- ✅ `CANDIDATA_REAL` — ≥10 cierres, win rate ≥55% y PnL neto > 0.
- 🟡 `PROMETEDORA` — PnL neto > 0, pero aún sin la muestra/win rate exigidos.
- ⏳ `MUESTRA_INSUFICIENTE` — menos de 10 trades cerrados.
- ❌ `DESCARTAR` — PnL neto ≤ 0.

### Operación 24/7 (garantizar los >15 días)

El bot debe sobrevivir a reinicios y caídas. Unidad systemd incluida
(`quant-polymarket.service`):

```bash
sudo cp quant-polymarket.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quant-polymarket
sudo systemctl status quant-polymarket
journalctl -u quant-polymarket -f      # ver "[Backup] ciclo #N ..."
```

## 📄 Licencia

MIT - Uso bajo tu propio riesgo. El trading conlleva riesgo de pérdida.
