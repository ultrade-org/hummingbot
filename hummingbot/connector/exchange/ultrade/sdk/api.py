import requests
from constants import get_domain
import time


def get_exchange_info(symbol=None):  # should be replaced when dedicated endpoint is ready
    data = requests.get(f"{get_domain()}/market/markets").json()
    if symbol is None:
        return data

    for dict in data:
        if dict["pair_key"].lower() == symbol.lower():
            return dict

    raise "Can't find exchange info for the specified symbol"


def ping():
    response = requests.get(f"{get_domain()}/system/time")
    code = response.status_code
    if code != 200:
        raise "Ping request failed"
    sever_time = response.json()['currentTime']

    return round(time.time() * 1000) - sever_time


def get_order_by_id(symbol, order_id):
    url = f"{get_domain()}/market/getOrderById?orderId={order_id}"  # there should be symbol query support
    data = requests.get(url).json()
    if not len(data["order"]):
        raise "Order not found"
    return data["order"]


def get_open_orders(symbol):
    data = requests.get(f"{get_domain()}/market/open-orders?symbol={symbol}").json()
    return data["openOrders"]


def get_orders(symbol, start_time, end_time, limit=500, page=0):
    # waiting for back-end side implementation
    pass


def get_price(symbol):
    data = requests.get(f"{get_domain()}/market/price?symbol={symbol}").json()
    return data


def get_depth(symbol, depth):  # server error, need to test later
    data = requests.get(f"{get_domain()}/market/depth?symbol={symbol}&depth={depth}").json()
    return data


def get_last_trades(symbol):  # server error, need to test later
    data = requests.get(f"{get_domain()}/market/last-trades?symbol={symbol}").json()
    return data


def get_symbols(mask):  # endpoint is not working
    data = requests.get(f"{get_domain()}/market/symbols?mask={mask}").json()
    return data


def get_history(symbol, interval, start_time, end_time, limit=500):
    data = requests.get(f"{get_domain()}/market/history?symbol={symbol}&interval={interval}&startTime={start_time}&endTime={end_time}&limit={limit}").json()
    return data


def get_order_with_trades(address, status, symbol=None):  # is not documented
    symbol_query = f"&symbol={symbol}" if symbol else ""
    data = requests.get(f"{get_domain()}/market/orders-with-trades?address={address}&status={status}{symbol_query}").json()
    return data


def get_wallet_transactions(address, symbol=None):  # is not documented
    symbol_query = f"&symbol={symbol}" if symbol else ""
    data = requests.get(f"{get_domain()}/market/wallet-transactions?address={address}{symbol_query}").json()
    return data


# result = get_exchange_info("algo_usdt")
# print("result!", result)
