DEFAULT_DOMAIN = "mainnet"

HBOT_ORDER_ID_PREFIX = "ultr-"
MAX_ORDER_ID_LEN = 32

# Base URL
REST_URL = "https://api.ultrade.{}/api/"
WSS_URL = "wss://stream.ultrade.{}:9443/ws"

PUBLIC_API_VERSION = "v3"
PRIVATE_API_VERSION = "v3"

# Public API endpoints or UltradeClient function
TICKER_PRICE_CHANGE_PATH_URL = "/ticker/24hr"
TICKER_BOOK_PATH_URL = "/ticker/bookTicker"
PRICES_PATH_URL = "/ticker/price"
EXCHANGE_INFO_PATH_URL = "/exchangeInfo"
PING_PATH_URL = "/ping"
SNAPSHOT_PATH_URL = "/depth"
SERVER_TIME_PATH_URL = "/time"

# Private API endpoints or UltradeClient function
ACCOUNTS_PATH_URL = "/account"
MY_TRADES_PATH_URL = "/myTrades"
ORDER_PATH_URL = "/order"
ULTRADE_USER_STREAM_PATH_URL = "/userDataStream"

WS_HEARTBEAT_TIME_INTERVAL = 30

# Ultrade params

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

TIME_IN_FORCE_GTC = "GTC"  # Good till cancelled
TIME_IN_FORCE_IOC = "IOC"  # Immediate or cancel
TIME_IN_FORCE_FOK = "FOK"  # Fill or kill

# Websocket event types
ORDERBOOK_SNAPSHOT_EVENT_TYPE = "depth"
TRADE_EVENT_TYPE = "lastTrade"
USER_ORDER_EVENT_TYPE = "order"
USER_TRADE_EVENT_TYPE = "userTrade"
USER_BALANCE_EVENT_TYPE = "codexBalances"

RATE_LIMITS = []

ORDER_NOT_EXIST_MESSAGES = ["Order not found"]
UNKNOWN_ORDER_MESSAGES = ["Sorry this order id not found", "Order has already been cancelled"]
