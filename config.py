"""Configuración global de QUANT POLYMARKET"""

# Endpoints de Polymarket
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
WS_MARKET = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Polling intervals (segundos)
GAMMA_POLL_INTERVAL = 30      # Mercados activos
CLOB_POLL_INTERVAL = 5       # Order books (fallback si WS falla)
HEARTBEAT_INTERVAL = 10      # WebSocket heartbeat

# Filtros de mercado
MIN_LIQUIDITY = 5000         # Mínimo liquidez para considerar
MIN_VOLUME_24H = 2000        # Mínimo volumen 24h
MAX_MARKETS_WS = 100

# ========== Paper Trading: realismo de ejecución y límite de capital ==========
PAPER_ENFORCE_CAPITAL = True    # Activar límite realista de capital (cuenta de $1,000)
PAPER_MAX_EXPOSURE_USD = 1000.0 # Capital máximo total en posiciones abiertas
PAPER_MAX_OPEN_POSITIONS = 12   # Nº máximo de posiciones abiertas simultáneas
PAPER_SLIPPAGE_BPS = 5          # Slippage de entrada en puntos básicos (0.05%)
PAPER_FEE_RATE = 0.0            # Comisión por trade (Polymarket típicamente 0)
PAPER_RESEARCH_BUDGET_PER_STRATEGY = 2000.0  # Presupuesto aislado por estrategia (Modo Research)
PAPER_RESEARCH_MAX_OPEN_PER_STRATEGY = 25    # Plazas por estrategia (Modo Research)
         # Máximo mercados en WebSocket

# Parámetros de estrategias
STRATEGY_PARAMS = {
    "market_making": {
        "min_spread_bps": 50,
        "min_depth_usd": 500,
        "min_volume_24h": 10000,
    },
    "bundle_arbitrage": {
        "min_inefficiency": 0.005,
    },
    "mean_reversion": {
        "min_liquidity": 100000,
        "min_volume_24h": 10000,
        "z_score_threshold": 2.0,
        "price_velocity_threshold": 0.05,
        # Fallback con cambios publicados por Gamma. Esto permite detectar
        # sobre-reacciones sin esperar a acumular 15m de historial local.
        "gamma_1d_change_threshold": 0.02,
        "gamma_1w_change_threshold": 0.04,
        "reversion_fraction": 0.50,
        "min_history_points": 5,
    },
    "favorite_longshot": {
        "favorite_threshold": 0.85,
        "longshot_threshold": 0.15,
        "min_volume_24h": 20000,
    },
    "external_data": {
        "max_lag_seconds": 120,
    },
    "whale_tracking": {
        "min_whale_position": 5000,
        "min_whale_winrate": 0.60,
        "min_recent_trade_size": 0,
        "recent_trade_window_seconds": 1800,
        "trades_poll_limit": 250,
        "positions_lookup_limit": 500,
        "holders_poll_limit": 10,
        "holders_market_scan_limit": 30,
        "holders_wallet_enrich_limit_per_cycle": 80,
    }
}

# Categorías
CATEGORIES = {
    "politics": "Politics",
    "sports": "Sports", 
    "weather": "Weather",
    "economics": "Economics",
    "crypto": "Crypto",
    "culture": "Culture",
    "science": "Science",
    "other": "Other",
}

# Clasificación local cuando Gamma no devuelve categoría explícita.
# Se aplica sobre question + slug + tags y permite filtrar visualmente mercados
# como Crypto, Clima, Política, Deportes, Economía, Cultura y Ciencia.
CATEGORY_KEYWORDS = {
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "doge",
        "dogecoin", "litecoin", "crypto", "cryptocurrency", "blockchain", "token",
        "stablecoin", "usdc", "usdt", "binance", "coinbase", "satoshi", "defi",
        "spot etf", "etf crypto",
    ],
    "weather": [
        "weather", "temperature", "rain", "snow", "hurricane", "storm", "tornado",
        "flood", "heat", "cold", "wind", "noaa", "climate", "temperatura", "lluvia",
        "huracán", "tormenta", "clima", "snowfall", "blizzard",
    ],
    "politics": [
        "trump", "biden", "president", "election", "senate", "congress", "governor",
        "mayor", "democrat", "democrats", "republican", "republicans", "nomination", "primary", "cabinet", "minister",
        "parliament", "vote", "poll", "politics", "putin", "zelensky", "israel", "gaza",
        "ukraine", "russia", "china", "tariff", "government", "supreme court",
        "nato", "donbas", "snowden", "presidential", "democratic", "republican",
        "governor race", "governor", "presidential election", "election",
    ],
    "sports": [
        "nba", "nfl", "mlb", "nhl", "ufc", "fifa", "soccer", "football", "tennis",
        "golf", "formula 1", "f1", "champions league", "world cup", "super bowl",
        "baseball", "basketball", "hockey", "olympics", "ballon d'or", "premier league",
        "laliga", "liga", "serie a", "wimbledon", "us open",
    ],
    "economics": [
        "fed", "federal reserve", "rate cut", "interest rate", "inflation", "cpi", "ppi",
        "jobs report", "unemployment", "gdp", "recession", "s&p", "sp500", "nasdaq",
        "dow", "oil", "gold", "silver", "treasury", "bond", "yield", "stock market",
        "economy", "tariff", "fomc", "macro",
    ],
    "culture": [
        "oscar", "oscars", "grammy", "emmy", "movie", "film", "box office", "album",
        "song", "music", "celebrity", "taylor swift", "netflix", "disney", "youtube",
        "tiktok", "x/twitter", "twitter", "met gala", "eurovision", "festival",
        "george r. r. martin", "winds of winter", "game of thrones", "book",
    ],
    "science": [
        "spacex", "nasa", "starship", "rocket", "launch", "moon", "mars", "space",
        "ai", "artificial intelligence", "openai", "anthropic", "google deepmind",
        "covid", "vaccine", "fda", "science", "research", "clinical trial",
    ],
}
