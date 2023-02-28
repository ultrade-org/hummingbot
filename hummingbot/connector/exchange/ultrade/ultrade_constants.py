from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState
from hummingbot.core.data_type.common import OrderType, TradeType

DEFAULT_DOMAIN = "mainnet"
TESTNET_DOMAIN = "testnet"

HBOT_ORDER_ID_PREFIX = "ULTR-"
MAX_ORDER_ID_LEN = 32

# Base URL
REST_URL = "https://api.ultrade.{}/api/"
WSS_URL = "wss://stream.ultrade.{}:9443/ws"

PUBLIC_API_VERSION = "v3"
PRIVATE_API_VERSION = "v3"

# Public API endpoints or UltradeClient function
TICKER_PRICE_CHANGE_PATH_URL = "/ticker/24hr"
TICKER_BOOK_PATH_URL = "/ticker/bookTicker"
EXCHANGE_INFO_PATH_URL = "/exchangeInfo"
PING_PATH_URL = "/ping"
SNAPSHOT_PATH_URL = "/depth"
SERVER_TIME_PATH_URL = "/time"

# Private API endpoints or UltradeClient function
ACCOUNTS_PATH_URL = "/account"
MY_TRADES_PATH_URL = "/myTrades"
ORDER_PATH_URL = "/order"
BINANCE_USER_STREAM_PATH_URL = "/userDataStream"

WS_HEARTBEAT_TIME_INTERVAL = 30

# Order States
ORDER_STATE = {
    # "PENDING": OrderState.PENDING_CREATE,
    # "NEW": OrderState.OPEN,
    # "FILLED": OrderState.FILLED,
    # "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
    # "PENDING_CANCEL": OrderState.OPEN,
    # "CANCELED": OrderState.CANCELED,
    # "REJECTED": OrderState.FAILED,
    # "EXPIRED": OrderState.FAILED,
    1: OrderState.OPEN,
    2: OrderState.CANCELED,
    3: OrderState.FILLED
}

ORDER_TYPE = {
    OrderType.LIMIT: 0,  # LIMIT
    OrderType.MARKET: 3   # MARKET
}

ORDER_SIDE = {
    TradeType.BUY: 0,  # BUY
    TradeType.SELL: 1  # SELL
}

# Websocket event types
TRADE_EVENT_TYPE = "trades"
SNAPSHOT_EVENT_TYPE = "depth"

RATE_LIMITS = []
