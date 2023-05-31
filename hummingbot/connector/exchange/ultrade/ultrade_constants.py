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
    1: OrderState.OPEN,
    2: OrderState.CANCELED,
    3: OrderState.FILLED,
    4: OrderState.FILLED
}

TO_HB_ORDER_TYPE = {
    0: OrderType.LIMIT, # LIMIT
    3: OrderType.MARKET # MARKET
}

FROM_HB_ORDER_TYPE = {
    OrderType.LIMIT: 0, # LIMIT
    OrderType.MARKET: 3 # MARKET
}

ORDER_SIDE = {
    0: TradeType.BUY,  # BUY
    1: TradeType.SELL  # SELL
}

# Websocket event types
TRADE_EVENT_TYPE = "trades"
SNAPSHOT_EVENT_TYPE = "depth"

RATE_LIMITS = []
