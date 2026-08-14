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
MAX_MARKETS_WS = 100         # Máximo mercados en WebSocket

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
}
