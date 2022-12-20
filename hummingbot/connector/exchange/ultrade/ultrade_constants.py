from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

DEFAULT_DOMAIN = "ultrade"
ALGO_DOMAIN = "algo"
# DEV_DOMAIN
# BASE URL

HBOT_ORDER_ID_PREFIX = "ULTRADE-"
MAX_ORDER_ID_LEN = 32
HBOT_BROKER_ID = "Hummingbot"

TIME_IN_FORCE_GTC = 'GTC'         # Good till cancelled
TIME_IN_FORCE_IOC = 'IOC'         # Immediate or cancel
TIME_IN_FORCE_FOK = 'FOK'         # Fill or kill
TIME_IN_FORCE_MAK = 'MAKER_ONLY'  # Maker

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"

# REST_URL = "http://node3.testnet.ultradedev.net:8980/"
REST_URL = 'https://indexer.testnet.algoexplorerapi.io/'
'https://node.testnet.algoexplorerapi.io'
REST_URLS = {"acc": "https://indexer.testnet.algoexplorerapi.io",
             "ultrade": "https://dev-apigw.ultradedev.net"}

WSS_V1_PUBLIC_URL = {"ultrade": "wss://dev-ws.ultradedev.net/socket.io/?EIO=4&transport=websocket"}
WSS_PRIVATE_URL = {"ultrade": "wss://dev-ws.ultradedev.net/socket.io/?EIO=4&transport=websocket"}

WS_HEARTBEAT_TIME_INTERVAL = 25000

PUBLIC_API_VERSION = "/v2"
PRIVATE_API_VERSION = "v2"

# Websocket event types
START_EVENT_TYPE = 'START'
DIFF_EVENT_TYPE = "allStat"
TRADE_EVENT_TYPE = "trade"
SNAPSHOT_EVENT_TYPE = "currentPair"

# Rate Limit Type
REQUEST_WEIGHT = "REQUEST_WEIGHT"
ORDERS = "ORDERS"
ORDERS_24HR = "ORDERS_24HR"
RAW_REQUESTS = "RAW_REQUESTS"

# Rate Limit time intervals
ONE_MINUTE = 60
ONE_SECOND = 1
ONE_DAY = 86400

MAX_REQUEST = 5000


# Endpoints
ACCOUNTS_PATH_URL = "/accounts/"
PAIR_PATH_URL = "/trading/trade/pair-list"
SERVER_TIME_PATH_URL = '/system/time'
EXCHANGE_INFO_PATH_URL = "/trading/trade/pair-list"
SNAPSHOT_PATH_URL = "/market/depth"

GLOWL_DECIMAL = 4

# Order States
ORDER_STATE = {
    "PENDING": OrderState.PENDING_CREATE,
    "NEW": OrderState.OPEN,
    "FILLED": OrderState.FILLED,
    "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
    "PENDING_CANCEL": OrderState.OPEN,
    "CANCELED": OrderState.CANCELED,
    "REJECTED": OrderState.FAILED,
    "EXPIRED": OrderState.FAILED,
}

# DIFF_EVENT_TYPE = "depthUpdate"
# TRADE_EVENT_TYPE = "trade"

ACCOUNT_URL_ATTRIBUTE = '?include-all=true'


# Public API endpoints or BinanceClient function
# TICKER_PRICE_CHANGE_PATH_URL = "/ticker/24hr"
# TICKER_BOOK_PATH_URL = "/ticker/bookTicker"
# EXCHANGE_INFO_PATH_URL = "/exchangeInfo"
# PING_PATH_URL = "/ping"
# SNAPSHOT_PATH_URL = "/depth"
# SERVER_TIME_PATH_URL = "/time"
#
# MY_TRADES_PATH_URL = "/myTrades"
ORDER_PATH_URL = "/order"

RATE_LIMITS = [
    # Pools
    RateLimit(limit_id=REQUEST_WEIGHT, limit=1200, time_interval=ONE_MINUTE),
    RateLimit(limit_id=ORDERS, limit=50, time_interval=10 * ONE_SECOND),
    RateLimit(limit_id=ORDERS_24HR, limit=160000, time_interval=ONE_DAY),
    RateLimit(limit_id=RAW_REQUESTS, limit=6100, time_interval= 5 * ONE_MINUTE),
    # Weighted Limits
    RateLimit(limit_id=EXCHANGE_INFO_PATH_URL, limit=MAX_REQUEST, time_interval=ONE_MINUTE,
              linked_limits=[LinkedLimitWeightPair(REQUEST_WEIGHT, 10),
                             LinkedLimitWeightPair(RAW_REQUESTS, 1)]),
    RateLimit(limit_id=SNAPSHOT_PATH_URL, limit=MAX_REQUEST, time_interval=ONE_MINUTE,
              linked_limits=[LinkedLimitWeightPair(REQUEST_WEIGHT, 50),
                             LinkedLimitWeightPair(RAW_REQUESTS, 1)]),
    # RateLimit(limit_id=BINANCE_USER_STREAM_PATH_URL, limit=MAX_REQUEST, time_interval=ONE_MINUTE,
    #           linked_limits=[LinkedLimitWeightPair(REQUEST_WEIGHT, 1),
    #                          LinkedLimitWeightPair(RAW_REQUESTS, 1)]),
    RateLimit(limit_id=SERVER_TIME_PATH_URL, limit=MAX_REQUEST, time_interval=ONE_MINUTE,
              linked_limits=[LinkedLimitWeightPair(REQUEST_WEIGHT, 1),
                             LinkedLimitWeightPair(RAW_REQUESTS, 1)]),
    # RateLimit(limit_id=PING_PATH_URL, limit=MAX_REQUEST, time_interval=ONE_MINUTE,
    #           linked_limits=[LinkedLimitWeightPair(REQUEST_WEIGHT, 1),
    #                          LinkedLimitWeightPair(RAW_REQUESTS, 1)]),
    RateLimit(limit_id=ACCOUNTS_PATH_URL, limit=MAX_REQUEST, time_interval=ONE_MINUTE,
              linked_limits=[LinkedLimitWeightPair(REQUEST_WEIGHT, 10),
                             LinkedLimitWeightPair(RAW_REQUESTS, 1)]),
    RateLimit(limit_id=PAIR_PATH_URL, limit=MAX_REQUEST, time_interval=ONE_MINUTE,
              linked_limits=[LinkedLimitWeightPair(REQUEST_WEIGHT, 10),
                             LinkedLimitWeightPair(RAW_REQUESTS, 1)]),
    # RateLimit(limit_id=MY_TRADES_PATH_URL, limit=MAX_REQUEST, time_interval=ONE_MINUTE,
    #           linked_limits=[LinkedLimitWeightPair(REQUEST_WEIGHT, 10),
    #                          LinkedLimitWeightPair(RAW_REQUESTS, 1)]),
    # RateLimit(limit_id=ORDER_PATH_URL, limit=MAX_REQUEST, time_interval=ONE_MINUTE,
    #           linked_limits=[LinkedLimitWeightPair(REQUEST_WEIGHT, 2),
    #                          LinkedLimitWeightPair(ORDERS, 1),
    #                          LinkedLimitWeightPair(ORDERS_24HR, 1),
    #                          LinkedLimitWeightPair(RAW_REQUESTS, 1)])
]
