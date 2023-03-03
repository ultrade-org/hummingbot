from algosdk.v2client import algod
import asyncio
from decimal import Decimal
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from async_timeout import timeout
from bidict import bidict

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.exchange.ultrade import (
    ultrade_constants as CONSTANTS,
    ultrade_utils,
    ultrade_web_utils as web_utils,
)
from hummingbot.connector.exchange.ultrade.ultrade_api_order_book_data_source import UltradeAPIOrderBookDataSource
from hummingbot.connector.exchange.ultrade.ultrade_api_user_stream_data_source import UltradeAPIUserStreamDataSource
from hummingbot.connector.exchange.ultrade.ultrade_auth import UltradeAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import TradeFillOrderDetails, combine_to_hb_trading_pair
from hummingbot.core.data_type.cancellation_result import CancellationResult
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import DeductedFromReturnsTradeFee, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.event.events import MarketEvent, OrderFilledEvent
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.core.utils.async_utils import safe_gather
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

from ultrade.sdk_client import Client as UltradeClient
from ultrade import api as ultrade_api

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter

s_logger = None


class UltradeExchange(ExchangePyBase):
    SHORT_POLL_INTERVAL = 1.0
    LONG_POLL_INTERVAL = 1.0

    web_utils = web_utils

    def __init__(self,
                 client_config_map: "ClientConfigAdapter",
                 ultrade_mnemonic: str,
                 ultrade_wallet_address: str,
                 trading_pairs: Optional[List[str]] = None,
                 trading_required: bool = True,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 ):
        self.mnemonic = ultrade_mnemonic
        self.wallet_address = ultrade_wallet_address
        self._domain = domain
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        self._last_trades_poll_ultrade_timestamp = 1.0

        algod_address = "https://node.testnet.algoexplorerapi.io" if self._domain == "testnet" \
            else "https://node.algoexplorerapi.io"
        algod_client = algod.AlgodClient("", algod_address)

        options = {
            "network": f"{self._domain}",
            "algo_sdk_client": algod_client,
            "api_url": None,
            "websocket_url": f"wss://{self._domain}-ws.ultradedev.net/socket.io"
        }

        credentials = {"mnemonic": ultrade_mnemonic}

        self._ultrade_client = UltradeClient(credentials, options)
        self._ultrade_api = ultrade_api
        
        self._conversion_rules = {}

        super().__init__(client_config_map)
        self.real_time_balance_update = False

    @staticmethod
    def ultrade_order_type(order_type: OrderType) -> int:
        return CONSTANTS.FROM_HB_ORDER_TYPE[order_type]

    @staticmethod
    def to_hb_order_type(ultrade_type: int) -> OrderType:
        return CONSTANTS.TO_HB_ORDER_TYPE[ultrade_type]

    @property
    def authenticator(self):
        return UltradeAuth(
            mnemonic=self.mnemonic,
            wallet_address=self.wallet_address,
            time_provider=self._time_synchronizer)

    @property
    def name(self) -> str:
        if self._domain == "mainnet":
            return "ultrade"
        else:
            return f"ultrade_{self._domain}"

    @property
    def rate_limits_rules(self):
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self):
        return self._domain

    @property
    def client_order_id_max_length(self):
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self):
        return CONSTANTS.HBOT_ORDER_ID_PREFIX

    @property
    def trading_rules_request_path(self):
        return

    @property
    def trading_pairs_request_path(self):
        return

    @property
    def check_network_request_path(self):
        return

    @property
    def trading_pairs(self):
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return False

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    def supported_order_types(self):
        return [OrderType.LIMIT, OrderType.MARKET]

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        return False

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            domain=self._domain,
            auth=self._auth)

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return UltradeAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            domain=self.domain,
            api_factory=self._web_assistants_factory)

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        return UltradeAPIUserStreamDataSource(
            auth=self._auth,
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _get_fee(self,
                 base_currency: str,
                 quote_currency: str,
                 order_type: OrderType,
                 order_side: TradeType,
                 amount: Decimal,
                 price: Decimal = s_decimal_NaN,
                 is_maker: Optional[bool] = None) -> TradeFeeBase:
        is_maker = order_type is OrderType.LIMIT_MAKER
        return DeductedFromReturnsTradeFee(percent=self.estimate_fee_pct(is_maker))

    async def _update_trading_rules(self):
        exchange_info = await self._get_ultrade_trading_pairs ()
        trading_rules_list = await self._format_trading_rules(exchange_info)
        self._trading_rules.clear()
        for trading_rule in trading_rules_list:
            self._trading_rules[trading_rule.trading_pair] = trading_rule
        self._initialize_trading_pair_symbols_from_exchange_info(exchange_info=exchange_info)

    async def _place_order(self,
                           order_id: str,
                           trading_pair: str,
                           amount: Decimal,
                           trade_type: TradeType,
                           order_type: OrderType,
                           price: Decimal,
                           **kwargs) -> Tuple[str, float]:
        # order_result = None
        base, quote = list(map(lambda x: x, trading_pair.split("-")))
        quantity_int = self.to_fixed_point(base, amount)
        price_int = self.to_fixed_point(quote, price)
        type_str = '0' if order_type is OrderType.LIMIT else 'M'
        side_str = 'B' if trade_type is TradeType.BUY else 'S'
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

        order_info = await self._ultrade_client.new_order(symbol, side_str, type_str, quantity_int, price_int)
        order_id_slot = f"{order_info['order_id']}-{order_info['slot']}"
        transact_time = time.time()
        return (order_id_slot, transact_time)
    
    async def cancel_all(self, timeout_seconds: float) -> List[CancellationResult]:
        """
        Cancels all currently active orders. The cancellations are performed in parallel tasks.

        :param timeout_seconds: the maximum time (in seconds) the cancel logic should run

        :return: a list of CancellationResult instances, one for each of the orders to be cancelled
        """
        incomplete_orders = [o for o in self.in_flight_orders.values() if not o.is_done]
        tasks = [self._execute_cancel(o.trading_pair, o.client_order_id) for o in incomplete_orders]
        order_id_set = set([o.client_order_id for o in incomplete_orders])
        failed_cancellations = []

        try:
            async with timeout(timeout_seconds):
                await safe_gather(*tasks, return_exceptions=True)

                await asyncio.sleep(5.0)
                open_orders = await self._get_open_orders()

                for client_order_id in open_orders:
                    order_id_set.remove(client_order_id)
                    failed_cancellations.append(CancellationResult(client_order_id, False))
        except Exception:
            self.logger().network(
                "Unexpected error cancelling orders.",
                exc_info=True,
                app_warning_msg="Failed to cancel order. Check API key and network connection."
            )
        successful_cancellations = [CancellationResult(oid, True) for oid in order_id_set]
        return successful_cancellations + failed_cancellations

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=tracked_order.trading_pair)

        exchange_order_id, slot = list(map(lambda x: int(x), tracked_order.exchange_order_id.split(('-'))))

        cancel_result = await self._ultrade_client.cancel_order(symbol, exchange_order_id, slot)
        if not isinstance(cancel_result, Exception):
            return True
        return False
    
    async def check_network(self) -> NetworkStatus:
        """
        Checks connectivity with the exchange using the API
        """
        try:
            await self._ultrade_api.ping()
        except asyncio.CancelledError:
            raise
        except Exception:
            return NetworkStatus.NOT_CONNECTED
        return NetworkStatus.CONNECTED

    async def _format_trading_rules(self, exchange_info_list: List[Dict[str, Any]]) -> List[TradingRule]:
        """
        Example:
        [
            {
                "id": 1,
                "pairId": 1,
                "pair_key": "algo_usdc",
                "is_verified": 1,
                "application_id": 92138200,
                "base_currency": "algo",
                "price_currency": "usdc",
                "trade_fee_buy": 1000000,
                "trade_fee_sell": 1000000,
                "base_id": 0,
                "price_id": 81981957,
                "price_decimal": 4,
                "base_decimal": 6,
                "is_active": true,
                "pair_name": "ALGO_USDC",
                "min_price_increment": 5,
                "min_order_size": 1000000,
                "min_size_increment": 1000000,
                "created_at": "2022-04-19T07:40:42.000Z",
                "updated_at": "2022-04-19T07:40:42.000Z",
                "inuseWithPartners": [
                    12345678
                ],
                "restrictedCountries": []
            },
        ]
        """
        retval = []
        for rule in filter(ultrade_utils.is_exchange_information_valid, exchange_info_list):
            try:
                trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol=rule.get("pair_key"))
                base, quote = list(map(lambda x: x, trading_pair.split("-")))
                
                min_order_size = self.from_fixed_point(base, int(rule['min_order_size']))
                min_price_increment = self.from_fixed_point(quote, int(rule['min_price_increment']))
                min_base_amount_increment = self.from_fixed_point(base, int(rule['min_size_increment']))

                retval.append(
                    TradingRule(trading_pair,
                                min_order_size=min_order_size,
                                min_price_increment=min_price_increment,
                                min_base_amount_increment=min_base_amount_increment))

            except Exception:
                self.logger().exception(f"Error parsing the trading pair rule {rule}. Skipping.")
        return retval

    async def _status_polling_loop_fetch_updates(self):
        await self._update_order_fills_from_trades()
        await super()._status_polling_loop_fetch_updates()

    async def _update_trading_fees(self):
        """
        Update fees information from the exchange
        """
        pass

    async def _user_stream_event_listener(self):
        """
        This functions runs in background continuously processing the events received from the exchange by the user
        stream data source. It keeps reading events from the queue until the task is interrupted.
        The events received are balance updates, order updates and trade events.
        """
        async for event_message in self._iter_user_event_queue():
            try:
                event_type = event_message.get('type')
                if event_type == 'order':
                    action, message = event_message.get('message')
                    if action == 'cancel':
                        o_id = message['orderId']
                        tracked_order = next((order for order in self._order_tracker.all_orders.values() if str(o_id) == order.exchange_order_id.split('-')[0]), None)
                        if tracked_order is not None:
                            order_update = OrderUpdate(
                                trading_pair=tracked_order.trading_pair,
                                update_timestamp=time.time(),
                                new_state=OrderState.CANCELED,
                                client_order_id=tracked_order.client_order_id,
                                exchange_order_id=tracked_order.exchange_order_id,
                            )
                            self._order_tracker.process_order_update(order_update=order_update)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unexpected error in user stream listener loop.", exc_info=True)
                await self._sleep(5.0)

    async def _update_order_fills_from_trades(self):
        """
        This is intended to be a backup measure to get filled events with trade ID for orders,
        in case Ultrade's user stream events are not working.
        NOTE: It is not required to copy this functionality in other connectors.
        This is separated from _update_order_status which only updates the order status without producing filled
        events, since Ultrade's get order endpoint does not return trade IDs.
        The minimum poll interval for order status is 10 seconds.
        """
        if self.in_flight_orders:
            query_time = int(self._last_trades_poll_ultrade_timestamp * 1e3)
            self._last_trades_poll_ultrade_timestamp = self._time_synchronizer.time()
            order_by_exchange_id_map = {}
            for order in self._order_tracker.all_fillable_orders.values():
                order_by_exchange_id_map[order.exchange_order_id] = order

            tasks = []
            trading_pairs = self.trading_pairs
            for trading_pair in trading_pairs:
                symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
                if self._last_poll_timestamp > 0:
                   tasks.append(self._ultrade_client.get_orders(
                       symbol=symbol,
                       status=1))      # all orders except open orders
                   tasks.append(self._ultrade_client.get_orders(
                       symbol=symbol,
                       status=-1))
                tasks.append(self._ultrade_client.get_orders(
                    symbol=symbol,
                    status=1,
                    start_time=query_time))
                tasks.append(self._ultrade_client.get_orders(
                    symbol=symbol,
                    status=-1,
                    start_time=query_time))

            self.logger().debug(f"Polling for order fills of {len(tasks)} trading pairs.")
            results = await safe_gather(*tasks, return_exceptions=True)
            results = [results[2*i:2*i+2] for i in range(int(len(results)/2))]

            for trade_chunks, trading_pair in zip(results, trading_pairs):
                base, quote = list(map(lambda x: x, trading_pair.split("-")))
                open_order_trades, other_order_trades = trade_chunks

                if isinstance(open_order_trades, Exception):
                    self.logger().network(
                        f"Error fetching trades update for the order {trading_pair}: {open_order_trades}.",
                        app_warning_msg=f"Failed to fetch trade update for {trading_pair}."
                    )
                    open_order_trades = []
                if isinstance(other_order_trades, Exception):
                    self.logger().network(
                        f"Error fetching trades update for the order {trading_pair}: {other_order_trades}.",
                        app_warning_msg=f"Failed to fetch trade update for {trading_pair}."
                    )
                    other_order_trades = []
                for trade in open_order_trades + other_order_trades:
                    exchange_order_id = f"{trade.get('orders_id', None)}-{trade.get('slot', None)}"
                    status = CONSTANTS.ORDER_STATE[int(trade['order_status'])]
                    trade_price = int(trade['trade_price']) if trade['trade_price'] else 0
                    if exchange_order_id in order_by_exchange_id_map and status != OrderState.CANCELED and trade_price:
                        # This is a fill for a tracked order
                        tracked_order = order_by_exchange_id_map[exchange_order_id]
                        fee = TradeFeeBase.new_spot_fee(
                            fee_schema=self.trade_fee_schema(),
                            trade_type=tracked_order.trade_type,
                            percent_token=trading_pair.split('-')[0]
                        )

                        fill_base_amount = self.from_fixed_point(int(trade['trade_amount']), base)
                        fill_price = self.from_fixed_point(int(trade['trade_price']), quote)
                        fill_quote_amount = fill_base_amount * fill_price

                        trade_update = TradeUpdate(
                            trade_id=str(trade["trades_id"]),
                            client_order_id=tracked_order.client_order_id,
                            exchange_order_id=exchange_order_id,
                            trading_pair=trading_pair,
                            fee=fee,
                            fill_base_amount=fill_base_amount,
                            fill_quote_amount=fill_quote_amount,
                            fill_price=fill_price,
                            fill_timestamp=time.time(),
                        )
                        self._order_tracker.process_trade_update(trade_update)
                    elif self.is_confirmed_new_order_filled_event(str(trade["id"]), exchange_order_id, trading_pair):
                        # This is a fill of an order registered in the DB but not tracked any more
                        self._current_trade_fills.add(TradeFillOrderDetails(
                            market=self.display_name,
                            exchange_trade_id=str(trade["trades_id"]),
                            symbol=trading_pair))
                        fill_base_amount = self.from_fixed_point(int(trade['trade_amount']), base)
                        fill_price = self.from_fixed_point(int(trade['trade_price']), quote)
                        self.trigger_event(
                            MarketEvent.OrderFilled,
                            OrderFilledEvent(
                                timestamp=time.time(),
                                order_id=self._exchange_order_ids.get(exchange_order_id, None),
                                trading_pair=trading_pair,
                                trade_type=CONSTANTS.ORDER_SIDE[int(trade['order_side'])],
                                order_type=CONSTANTS.TO_HB_ORDER_TYPE[int(trade['order_type'])],
                                price=fill_price,
                                amount=fill_base_amount,
                                trade_fee=DeductedFromReturnsTradeFee(),
                                exchange_trade_id=str(trade["trades_id"])
                            ))
                        self.logger().info(f"Recreating missing trade in TradeFill: {trade}")

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        trade_updates = []

        return trade_updates

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=tracked_order.trading_pair)
        o_id = int(tracked_order.exchange_order_id.split('-'))
        updated_order_data = await self._ultrade_client.get_order_by_id(symbol, o_id)

        new_state = CONSTANTS.ORDER_STATE[updated_order_data["status"]]

        order_update = OrderUpdate(
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=str(updated_order_data["orders_id"]),
            trading_pair=tracked_order.trading_pair,
            update_timestamp=time.time(),
            new_state=new_state,
        )

        return order_update

    async def _update_balances(self):
        local_asset_names = set(self._account_balances.keys())
        remote_asset_names = set()

        exchange_info_list = await self._get_ultrade_trading_pairs()
        pairs = [pair_info.get("pair_key") for pair_info in filter(ultrade_utils.is_exchange_information_valid, exchange_info_list)]

        tasks = []
        for pair in pairs:
            tasks.append(self._ultrade_client.get_balances(pair))

        balances = await safe_gather(*tasks, return_exceptions=True)

        for pair, balance in zip(pairs, balances):
            base, quote = list(map(lambda x: x.upper(), pair.split("_")))

            if isinstance(balance, Exception):
                continue

            base_wallet = self.from_fixed_point(base, int(balance.get("baseCoin", 0)))
            base_available = self.from_fixed_point(base, int(balance.get("baseCoin_available", 0)))
            base_locked = self.from_fixed_point(base, int(balance.get("baseCoin_locked", 0)))
            quote_wallet = self.from_fixed_point(base, int(balance.get("priceCoin", 0)))
            quote_available = self.from_fixed_point(base, int(balance.get("priceCoin_available", 0)))
            quote_locked = self.from_fixed_point(base, int(balance.get("priceCoin_locked", 0)))

            self._account_available_balances[base] = base_available + base_wallet
            self._account_balances[base] = base_available + base_wallet + base_locked
            self._account_available_balances[quote] = quote_available + quote_wallet
            self._account_balances[quote] = quote_available + quote_wallet + quote_locked
            remote_asset_names.add(base)
            remote_asset_names.add(quote)

        asset_names_to_remove = local_asset_names.difference(remote_asset_names)
        for asset_name in asset_names_to_remove:
            del self._account_available_balances[asset_name]
            del self._account_balances[asset_name]

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: List[Dict[str, Any]]):
        mapping = bidict()
        self._conversion_rules.clear()
        for symbol_data in filter(ultrade_utils.is_exchange_information_valid, exchange_info):

            # initialize conversion rules here.
            base = symbol_data["base_currency"].upper()
            quote = symbol_data["price_currency"].upper()
            self._conversion_rules[base] = 10 ** int(symbol_data["base_decimal"])
            self._conversion_rules[quote] = 10 ** int(symbol_data["price_decimal"])

            mapping[symbol_data["pair_key"]] = combine_to_hb_trading_pair(base=base,
                                                                        quote=quote)
        self._set_trading_pair_symbol_map(mapping)

    async def _initialize_trading_pair_symbol_map(self):
        try:
            exchange_info = await self._get_ultrade_trading_pairs()
            self._initialize_trading_pair_symbols_from_exchange_info(exchange_info=exchange_info)
        except Exception:
            self.logger().exception("There was an error requesting exchange info.")

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        price_asset = trading_pair.split("-")[1]

        resp_json = await self._ultrade_api.get_price(symbol)
        last_price = int(resp_json["last"]) if resp_json["last"] else 0
        last_price = self.from_fixed_point(price_asset, last_price)

        return float(last_price)

    async def _get_ultrade_trading_pairs(self):
        response = await self._ultrade_api.get_pair_list()

        return response
    
    async def _get_open_orders(self) -> List[str]:
        if self._trading_pairs is None:
            self.logger().error(f"Trading Pairs needed for fetching Open orders in Ultrade Exchange.")
        incomplete_orders = [o for o in self.in_flight_orders.values() if not o.is_done]

        tasks = []
        for trading_pair in self._trading_pairs:
            symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
            tasks.append(self._ultrade_client.get_orders(symbol=symbol, status=1))
        resusls = await safe_gather(*tasks, return_exceptions=True)

        ret_val = set()
        for result in resusls:
            if isinstance(result, Exception):
                continue

            for order in result:
                exchange_order_id = f"{order.get('orders_id', None)}-{order.get('slot', None)}"
                open_order = next((order for order in incomplete_orders if order.exchange_order_id == exchange_order_id), None)
                
                if open_order is not None:
                    ret_val.add(open_order.client_order_id)
                
        return list(ret_val)


    def from_fixed_point(self, asset: str, value: int) -> Decimal:
        asset: str = asset.upper()
        value = Decimal(str(value)) / Decimal(str(self._conversion_rules[asset]))

        return value

    def to_fixed_point(self, asset: str, value: Decimal) -> int:
        asset: str = asset.upper()
        value = int(Decimal(str(value)) * Decimal(str(self._conversion_rules[asset])))

        return value
