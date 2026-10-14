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
| `GET /api/hybrid/status` | Estado del **Modo Híbrido** (órdenes live simuladas contra el libro real) |
| `GET /api/hybrid/orders?limit=100` | Últimas órdenes simuladas (fill, slippage de libro, fills parciales) |
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

- Ejecuta **todas** las estrategias en tres trackers:
  - `paper_trades.json` → cuenta realista de $1,000 (solo señales Ultra ≥75%).
  - `paper_trades_research.json` → **presupuesto aislado por estrategia**, captura
    todas las señales (≥60%) para poder comparar estrategias entre sí.
  - `paper_trades_hybrid.json` → **Modo Híbrido**: mismo pipeline, pero cada entrada
    se ejecuta como una **orden live simulada contra el libro real** (ver más abajo).
- Cada `BACKUP_INTERVAL_SECONDS` (por defecto 15 min), `backup_manager.py`:
  1. Añade cada trade nuevo a `track_record/ledger.jsonl` (**append-only**: nunca
     se reescribe, así un borrado parcial no destruye el histórico).
  2. Exporta `track_record/trades_all.csv`, `strategy_ranking.json` y
     `manifest.json` (con hashes SHA-256 para detectar corrupción).
  3. Empuja la copia a los destinos off-site configurados.

### Configuración off-site

Copia `.env.example` a `.env` y elige el destino (puedes combinar varios).
El archivo se carga **automáticamente** al arrancar (lector propio, sin
dependencias); la unidad systemd ya incluye `EnvironmentFile=-.../.env`:

```
BACKUP_TARGETS=git,http      # local,git,s3,http (separados por comas)
```

- **git** (recomendado): crea un repo dedicado (privado o **público** si quieres
  publicar tu track record) y define `BACKUP_GIT_REMOTE`. No hace falta
  `BACKUP_GIT_TOKEN`: si está vacío, el token se resuelve en tiempo de ejecución
  con **`gh auth token`** (o `GITHUB_TOKEN`/`GH_TOKEN`), así no guardas secretos
  en `.env` y sobrevives a la rotación del PAT.
  También puedes reutilizar este mismo repo apuntando a otra rama
  (`BACKUP_GIT_BRANCH=trackrecord`), **nunca a `main`**: el backend git empuja
  su propio HEAD a esa rama y sobrescribiría el código.
  Para revisar la copia sin la VPS: `python3 ver_track_record.py /ruta/track_record`.
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

### 🆘 ¿Y si me quitan la VPS? (recuperar todo lo que hizo el bot)

Todo el histórico se materializa **fuera del proceso**, en `track_record/`:

| Archivo | Para qué sirve |
|---------|----------------|
| `ledger.jsonl` | Registro **append-only** de cada trade abierto/cerrado. Nunca se reescribe: sobrevive a reinicios y borrados parciales. |
| `hybrid_orders.jsonl` | Registro **append-only** de cada orden live simulada **ejecutada** (FILLED/PARTIAL/MAKER_FILLED). |
| `hybrid_orders.csv` | Las mismas órdenes en CSV/Excel para leerlas a mano. |
| `trades_all.csv` | Todos los trades de todos los motores, aplanados. |
| `strategy_ranking.json` | Ranking y veredicto por estrategia, con desglose por origen. |
| `CAMPAIGN_REPORT.md` | Informe final legible (lo genera `report_campaign.py`). |
| `manifest.json` | Día de campaña + **SHA-256** de cada archivo para detectar corrupción. |

**Paso 1 — sacarlos de la VPS.** En `.env` (copia de `.env.example`), activa al
menos un destino externo:

```
BACKUP_ENABLED=1
BACKUP_TARGETS=git,local      # o "git,s3" / "s3" / "http"
BACKUP_INTERVAL_SECONDS=900

# Repo dedicado a DATOS. NO reutilices el repo del código:
# el backend git hace push de su propio HEAD a BACKUP_GIT_BRANCH.
BACKUP_GIT_REMOTE=https://github.com/USUARIO/quant-polymarket-trackrecord.git
BACKUP_GIT_BRANCH=main
#BACKUP_GIT_TOKEN=            # vacío = se resuelve con `gh auth token`
```

> Si el repo de datos es **público**, cualquiera podrá leer tus mercados,
> estrategias, PnL simulado y motivos de rechazo. El respaldo **no** contiene
> credenciales (verificado), pero decide tú si eso se puede publicar.
>
> Si prefieres reutilizar tu repo actual, usa **otra rama**
> (`BACKUP_GIT_BRANCH=trackrecord`), nunca `main`, o sobrescribirás el código.
>
> Alternativa sin GitHub: `BACKUP_TARGETS=s3` con Cloudflare R2 / Backblaze B2
> (`pip install boto3`), o `BACKUP_TARGETS=http` con un webhook
> (Apps Script, n8n, Make, Supabase…).

Cada 15 min (y **al apagar el bot** de forma ordenada) se empuja el paquete.
También puedes forzarlo antes de que te retiren la VPS:

```
curl -X POST http://localhost:8010/api/backup/run      # o GET /api/backup/status
```
> El puerto debe ser el del servicio systemd (`--port 8010`, ver `quant-polymarket.service`).
> Si arrancas a mano con `python main.py`, es el `8000`.

**Paso 2 — revisarlo sin VPS.** Descarga la carpeta respaldada en tu PC y:

```
python3 ver_track_record.py /ruta/descargada/track_record
```

Verifica los SHA-256 contra el manifest y resume campaña, ranking, órdenes
simuladas, fill ratio, slippage real y motivos de rechazo. Para el informe de
decisión final:

```
python3 report_campaign.py /ruta/descargada/track_record
```

### Ruido de rechazos (importante)

La mayoría de las señales evaluadas **no** llegan a ejecutarse: se registran
miles de rechazos por hora (`sin libro real disponible` = en ese instante no
había order book para ese token). Por eso:

- El historial de órdenes guarda **solo las ejecutadas** (con su precio de libro,
  `fill_ratio` y slippage real).
- Los rechazos se conservan como **contadores agregados** en
  `hybrid_orders.json` → `rejection_reasons` y en `manifest.json` → `hybrid`,
  así que no se pierde el diagnóstico y el respaldo no se infla.
- Para auditar cada rechazo: `HYBRID_ORDERS_LEDGER_ALL=1` en `.env` (+ reinicio)
  guarda también las rechazadas en el ledger.
- Mantenimiento del ledger (conserva todas las ejecutadas, quita rechazos):

```
python3 backup_manager.py compact-orders     # compacta el ledger append-only
python3 backup_manager.py rebuild-orders     # lo reconstruye desde el log actual
python3 backup_manager.py run                # fuerza un ciclo de respaldo
```

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

> La unidad arranca uvicorn en el **puerto 8010** y carga la config con
> `EnvironmentFile=-.../.env`. Cambia `--port` en el `.service` si lo necesitas
> (en esta VPS el 8000 ya estaba ocupado por otra aplicación) y recuerda
> `daemon-reload` + `restart` tras cualquier edición.
>
> El **apagado ordenado** (`systemctl stop`) dispara un último ciclo de respaldo:
> verás `[SHUTDOWN] Backup final OK: {...}` en el journal.

#### Respaldo independiente del bot (por si el bot se cuelga)

El bot ya respalda cada `BACKUP_INTERVAL_SECONDS`, pero si el proceso queda vivo
y atascado, su ciclo interno puede no ejecutarse. `quant-backup.timer` empuja el
track record **desde fuera**, con su propio proceso:

```bash
sudo cp quant-backup.service quant-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quant-backup.timer
systemctl list-timers quant-backup.timer      # proxima ejecucion
sudo systemctl start quant-backup.service     # forzarlo ahora y ver el JSON
journalctl -u quant-backup.service -n 30      # resultado del ultimo ciclo
```

- Lanza `python backup_manager.py run` cada 15 min (`OnCalendar=*:07,22,37,52`,
  desfasado del ciclo interno del bot a propósito).
- `run_once()` toma un **lock** (`track_record/.backup.lock`): si el bot ya está
  respaldando en ese instante, el timer se salta el ciclo en vez de corromper el
  repo git temporal.
- El resultado del ciclo se registra como JSON en el journal (`git.ok`, `local.ok`).

## ✅ Tests

Batería de verificación (no requiere pytest; usa solo la librería estándar y el venv):

```bash
bash tests/run_all.sh
```

| Test | Qué comprueba |
|------|----------------|
| `tests/test_dotenv.py` | Carga de `.env` sin dependencias, prioridad del entorno y que el token de push sea resoluble (`gh auth token`) |
| `tests/test_hybrid.py` | `walk_book`, fills taker/parcial/maker, orden simulada y no-regresión del paper |
| `tests/test_hybrid_api.py` | `/api/hybrid/status`, `/api/hybrid/orders`, `/api/track-record` y panel del dashboard |
| `tests/test_persistence.py` | Ledger append-only de órdenes, CSV, idempotencia, `HYBRID_ORDERS_LEDGER_ALL` y `ver_track_record.py` (integridad, ranking, rechazos) |
| `tests/test_shutdown.py` | Arranque/cierre de la app y respaldo final del shutdown |

## 🧪 Modo Híbrido (validar sin arriesgar capital)

Un modo intermedio entre *paper* y *live*: **todas las estrategias pasan por el
mismo motor que el paper** (mismos filtros, Kelly sizing, gobernador, gestión de
TP/SL/trailing y filtro conformal), pero cada entrada se registra como una
**orden live simulada** construida igual que la que enviaría el ejecutor real y
con su fill calculado contra **el libro de órdenes real**.

**Qué diferencia hay con el paper clásico**

| Aspecto | Paper clásico | Modo Híbrido |
|---------|---------------|--------------|
| Precio de entrada | `señal + PAPER_SLIPPAGE_BPS` (fijo) | **VWAP real** recorriendo la profundidad |
| Profundidad | Ignorada | Recorrida nivel a nivel (hasta el precio límite) |
| Fills parciales | No existen | Sí: `filled_shares`, `fill_ratio` |
| Fee taker | Estimada por categoría | Igual, pero sobre el VWAP pagado |
| Rebates maker | Estimados | Calculados sobre el fill real del libro |
| Capital en riesgo | Ninguno | **Ninguno** (la orden nunca se envía) |

**Cómo se simula el fill** (`hybrid_execution.py`)

1. Se limpia el libro real (`market_registry.order_book`) del token y lado.
2. Se recorre la profundidad (`walk_book`) acumulando niveles hasta agotar la
   orden o superar el precio límite de la señal.
3. Con el VWAP obtenido se calculan slippage, fee taker y rebate maker, y se
   decide el estado:
   - `FILLED` — se cubrió todo el tamaño dentro del límite.
   - `PARTIAL` — se cubrió parcialmente (menos liquidez que tamaño pedido).
   - `MAKER_FILLED` — la señal es maker: fill al límite, sin fee y con rebate.
   - `REJECTED` — sin libro disponible, spread excesivo o precio límite fuera de rango.
   - Los fills por debajo de `HYBRID_MIN_FILL_RATIO` se descartan (si `HYBRID_ALLOW_PARTIAL=0`, cualquier parcial se descarta).

**Trazabilidad**

- `paper_trades_hybrid.json` → posiciones (con `engine: "hybrid"`, `order_id`,
  `order_status`, `fill_ratio`, `book_avg_price`, `book_slippage_bps`).
- `hybrid_orders.json` → log de **órdenes live simuladas** (payload de la orden,
  fill, estado y motivo de rechazo). Acotado a `HYBRID_KEEP_ORDERS`.
- `track_record/strategy_ranking.json` incluye por estrategia `by_source`
  (`realistic` / `research` / `hybrid`), `partial_fills` y
  `avg_book_slippage_bps`, para comparar **mismo pipeline con fill teórico vs.
  fill real** y ver si el edge sobrevive a los costes de ejecución.
- `python report_campaign.py` añade una sección con el **Δ de ejecución**
  (PnL híbrido − PnL research) por estrategia.

**Configuración** (`.env`, ver `.env.example`)

```bash
HYBRID_ENABLED=1          # 0 desactiva el modo (no se registra nada)
HYBRID_MIN_FILL_RATIO=0.5 # descarta fills por debajo de este ratio del tamaño
HYBRID_ALLOW_PARTIAL=1    # 0 = descartar cualquier fill parcial
#HYBRID_STORAGE_FILE=paper_trades_hybrid.json
#HYBRID_ORDERS_FILE=hybrid_orders.json
```

**API**: `GET /api/hybrid/status` (stats + resumen) y
`GET /api/hybrid/orders?limit=100` (últimas órdenes simuladas). El dashboard los
muestra en la pestaña *📈 Track Record en Vivo*.

> Ruta recomendada: **paper → híbrido (>15 días) → live**. Si en híbrido el PnL
> se mantiene positivo y el `avg_book_slippage_bps` es asumible, la estrategia
> tiene una probabilidad mucho mayor de sobrevivir en real.

## 📄 Licencia

MIT - Uso bajo tu propio riesgo. El trading conlleva riesgo de pérdida.
