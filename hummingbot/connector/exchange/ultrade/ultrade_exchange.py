import asyncio
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from algosdk.v2client import algod
from bidict import bidict
from ultrade import api as ultrade_api, socket_options as SOCKET_OPTIONS
from ultrade.sdk_client import Client as UltradeClient

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
from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.data_type.cancellation_result import CancellationResult
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import DeductedFromReturnsTradeFee, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.core.utils.async_utils import safe_ensure_future, safe_gather
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter

s_logger = None


class UltradeExchange(ExchangePyBase):
    SHORT_POLL_INTERVAL = 2.0
    LONG_POLL_INTERVAL = 2.0

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

        algod_address = "https://testnet-api.algonode.cloud" if self._domain == "testnet" \
            else "https://mainnet-api.algonode.cloud"
        algod_client = algod.AlgodClient("", algod_address)

        self._ultrade_options = {
            "network": f"{self._domain}",
            "algo_sdk_client": algod_client,
            "api_url": None,
            "websocket_url": f"wss://{self._domain}-ws.ultradedev.net/socket.io"
        }

        self._ultrade_credentials = {"mnemonic": ultrade_mnemonic}

        self._ultrade_client = UltradeClient(self._ultrade_credentials, self._ultrade_options)
        self._ultrade_api = ultrade_api

        self._conversion_rules_ultrade = {}
        self.order_book_depth_queue_ultrade: asyncio.Queue = asyncio.Queue()
        self.user_stream_order_queue_ultrade: asyncio.Queue = asyncio.Queue()
        self._stop_event_set: asyncio.Event = asyncio.Event()
        self._connection_ids_ultrade = set()
        self._requested_for_cancel_ultrade = set()
        self._conversion_rules_ultrade_set_event_task: asyncio.Event() = asyncio.Event()
        safe_ensure_future(self._initialize_conversion_rules_ultrade())

        # safe_ensure_future(self._subscribe_channles_ultrade())

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
        return True

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    def supported_order_types(self):
        return [OrderType.LIMIT]

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

    async def start_network(self):
        """
        Start all required tasks to update the status of the connector. Those tasks include:
        - The order book tracker
        - The polling loops to update the trading rules and trading fees
        - The polling loop to update order status and balance status using REST API (backup for main update process)
        - The background task to process the events received through the user stream tracker (websocket connection)
        """
        self._stop_network()
        safe_ensure_future(self._subscribe_channles_ultrade())
        self.order_book_tracker.start()
        self._trading_rules_polling_task = safe_ensure_future(self._trading_rules_polling_loop())
        self._trading_fees_polling_task = safe_ensure_future(self._trading_fees_polling_loop())
        if self.is_trading_required:
            self._status_polling_task = safe_ensure_future(self._status_polling_loop())
            self._user_stream_tracker_task = self._create_user_stream_tracker_task()
            self._user_stream_event_listener_task = safe_ensure_future(self._user_stream_event_listener())
            self._lost_orders_update_task = safe_ensure_future(self._lost_orders_update_polling_loop())

    async def stop_network(self):
        """
        This function is executed when the connector is stopped. It perform a general cleanup and stops all background
        tasks that require the connection with the exchange to work.
        """

        self._stop_event_set.set()
        self._stop_network()
        safe_ensure_future(self._unsubscribe_channels_ultrade())

    async def _update_trading_rules(self):
        exchange_info = await self._get_ultrade_trading_pairs()

        # update conversion rules every trading rules cycle
        await self._initialize_conversion_rules_ultrade(exchange_info)

        trading_rules_list = await self._format_trading_rules(exchange_info)

        self._trading_rules.clear()
        for trading_rule in trading_rules_list:
            self._trading_rules[trading_rule.trading_pair] = trading_rule
        self._initialize_trading_pair_symbols_from_exchange_info(exchange_info=exchange_info)

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        error_description = str(request_exception)
        is_time_synchronizer_related = ("-1021" in error_description
                                        and "Timestamp for this request" in error_description)
        return is_time_synchronizer_related

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        return str(CONSTANTS.ORDER_NOT_EXIST_ERROR_CODE) in str(
            status_update_exception
        ) and CONSTANTS.ORDER_NOT_EXIST_MESSAGE in str(status_update_exception)

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        return str(CONSTANTS.UNKNOWN_ORDER_ERROR_CODE) in str(
            cancelation_exception
        ) and CONSTANTS.UNKNOWN_ORDER_MESSAGE in str(cancelation_exception)

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
        type_str = 'L' if order_type is OrderType.LIMIT else 'M'
        side_str = 'B' if trade_type is TradeType.BUY else 'S'
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

        place_order_task = asyncio.create_task(self._ultrade_client.new_order(symbol, side_str, type_str, quantity_int, price_int, 0, "Y"))
        order_info = await place_order_task
        order_id_slot = f"{order_info['order_id']}-{order_info['slot']}"
        transact_time = time.time()
        return (order_id_slot, transact_time)

    async def cancel_all(self, timeout_seconds: float) -> List[CancellationResult]:
        """
        Cancels all currently active orders. The cancellations are performed in parallel tasks.

        :param timeout_seconds: the maximum time (in seconds) the cancel logic should run

        :return: a list of CancellationResult instances, one for each of the orders to be cancelled
        """
        if self._trading_pairs is None:
            self.logger().error("Trading Pairs needed for fetching Open orders in Ultrade Exchange.")
            return []

        try:
            incomplete_orders = [o for o in self.in_flight_orders.values() if not o.is_done]
            tasks = [self._ultrade_client.cancel_all_orders(await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)) for trading_pair in self._trading_pairs]
            order_id_set = set([o.client_order_id for o in incomplete_orders])
            failed_cancellations = []

            # wait for all in-progress order creations to be complete.
            self.logger().info("Waiting for all order creations to be complete...")
            await asyncio.sleep(10.0)
            await safe_gather(*tasks, return_exceptions=True)

            # wait for all in-progress order cancellations to be complete.
            self.logger().info("Waiting for all order cancellations to be complete...")
            await asyncio.sleep(10.0)
            open_orders = await self._get_open_orders()

            for client_order_id in open_orders:
                order_id_set.discard(client_order_id)
                failed_cancellations.append(CancellationResult(client_order_id, False))
        except Exception:
            self.logger().network(
                "Unexpected error cancelling orders.",
                exc_info=True,
                app_warning_msg="Failed to cancel order. Check API key and network connection."
            )
        successful_cancellations = [CancellationResult(oid, True) for oid in order_id_set]
        return successful_cancellations + failed_cancellations

    async def _execute_order_cancel_and_process_update(self, order: InFlightOrder) -> bool:
        cancelled = await self._place_cancel(order.client_order_id, order)
        # cancellation will be processed in the next status polling cycle
        return cancelled

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=tracked_order.trading_pair)
        exchange_order_id = await tracked_order.get_exchange_order_id()

        cancelled = False

        if exchange_order_id not in self._requested_for_cancel_ultrade:
            o_id, slot = list(map(lambda x: int(x), exchange_order_id.split(('-'))))
            try:
                self._requested_for_cancel_ultrade.add(exchange_order_id)
                await self._ultrade_client.cancel_order(symbol, o_id, slot)

                cancelled = True
            except Exception:
                self.logger().info(f"Exception from Ultrade SDK on cancelling order {exchange_order_id}. "
                                   f"Order may have already been cancelled or filled.")
                cancelled = False
                self._requested_for_cancel_ultrade.discard(exchange_order_id)
        return cancelled

    async def check_network(self) -> NetworkStatus:
        """
        Checks connectivity with the exchange using the API
        """
        try:
            # await self._ultrade_api.ping()
            pass
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
        await self._conversion_rules_ultrade_set_event_task.wait()
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
        await self._update_order_fills_and_status()
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
                        tracked_order = next((order for order in self._order_tracker.all_orders.values() if order.exchange_order_id is not None and str(o_id) == order.exchange_order_id.split('-')[0]), None)
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

    async def _update_order_fills_and_status(self):
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
                        status=2))
                tasks.append(self._ultrade_client.get_orders(
                    symbol=symbol,
                    status=1,
                    start_time=query_time))
                tasks.append(self._ultrade_client.get_orders(
                    symbol=symbol,
                    status=2,
                    start_time=query_time))

            self.logger().debug(f"Polling for order fills of {len(tasks)} trading pairs.")
            results = await safe_gather(*tasks, return_exceptions=True)
            results = [results[2 * i:(2 * i) + 2] for i in range(int(len(results) / 2))]

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

                    fill_base_amount = int(trade['trade_amount']) if trade['trade_amount'] else 0
                    fill_base_amount = self.from_fixed_point(base, fill_base_amount)
                    fill_price = int(trade['trade_price']) if trade['trade_price'] else 0
                    fill_price = self.from_fixed_point(quote, fill_price)
                    fill_quote_amount = fill_base_amount * fill_price

                    tracked_order = order_by_exchange_id_map.get(exchange_order_id, None)
                    if exchange_order_id in order_by_exchange_id_map and fill_price and trade['trades_id']:
                        # This is a fill for a tracked order
                        fee = TradeFeeBase.new_spot_fee(
                            fee_schema=self.trade_fee_schema(),
                            trade_type=tracked_order.trade_type,
                            percent_token=trading_pair.split('-')[0]
                        )
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

                        if status == OrderState.FILLED:
                            # This is a filled status update for a tracked order
                            order_update = OrderUpdate(
                                trading_pair=tracked_order.trading_pair,
                                update_timestamp=time.time(),
                                new_state=OrderState.FILLED,
                                client_order_id=tracked_order.client_order_id,
                                exchange_order_id=tracked_order.exchange_order_id,
                            )
                            self._order_tracker.process_order_update(order_update)

                    if tracked_order and status == OrderState.CANCELED:
                        # This is a cancelled status update for a tracked order
                        order_update = OrderUpdate(
                            trading_pair=tracked_order.trading_pair,
                            update_timestamp=time.time(),
                            new_state=OrderState.CANCELED,
                            client_order_id=tracked_order.client_order_id,
                            exchange_order_id=tracked_order.exchange_order_id,
                        )
                        self._order_tracker.process_order_update(order_update)

    async def _update_orders_fills(self, orders: List[InFlightOrder]):
        pass

    async def _update_orders(self):
        pass

    async def _update_lost_orders(self):
        pass

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        trade_updates = []

        return trade_updates

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        pass

    async def _update_balances(self):
        local_asset_names = set(self._account_balances.keys())
        remote_asset_names = set()

        balances = await self._ultrade_client.get_account_balances()
        for key in balances:
            asset_name = balances[key].get("asset", None)
            if asset_name is None:
                continue

            free_balance = self.from_fixed_point(asset_name, int(balances[key].get("free", 0)))
            total_balance = self.from_fixed_point(asset_name, int(balances[key].get("total", 0)))

            self._account_available_balances[asset_name] = free_balance
            self._account_balances[asset_name] = total_balance
            remote_asset_names.add(asset_name)

        asset_names_to_remove = local_asset_names.difference(remote_asset_names)

        for asset_name in asset_names_to_remove:
            del self._account_available_balances[asset_name]
            del self._account_balances[asset_name]

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: List[Dict[str, Any]]):
        mapping = bidict()
        for symbol_data in filter(ultrade_utils.is_exchange_information_valid, exchange_info):
            base = symbol_data["base_currency"].upper()
            quote = symbol_data["price_currency"].upper()
            mapping[symbol_data["pair_key"]] = combine_to_hb_trading_pair(base=base,
                                                                          quote=quote)
        self._set_trading_pair_symbol_map(mapping)

    async def _initialize_trading_pair_symbol_map(self):
        try:
            exchange_info = await self._get_ultrade_trading_pairs()
            self._initialize_trading_pair_symbols_from_exchange_info(exchange_info=exchange_info)
        except Exception:
            self.logger().exception("There was an error requesting exchange info.")

    async def _subscribe_channles_ultrade(self):
        try:
            trading_pair = self._trading_pairs[0]
            symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
            params = {
                'symbol': symbol,
                'streams': [SOCKET_OPTIONS.DEPTH, SOCKET_OPTIONS.ORDERS],
                'options': {
                    'address': self.wallet_address,
                }
            }
            self.user_stream_order_queue_ultrade.put_nowait({'type': 'init'})

            def process_socket_messages_ultrade(event, message):
                event_message = {}
                if event == 'depth' and message is not None:
                    event_message['type'] = event
                    order_book = self.to_hb_order_book(message)
                    event_message['message'] = order_book
                    self.order_book_depth_queue_ultrade.put_nowait(event_message)
                elif event == 'order' and message is not None:
                    event_message['type'] = event
                    event_message['message'] = message
                    self.user_stream_order_queue_ultrade.put_nowait(event_message)

            connection_id = await self._ultrade_client.subscribe(params, process_socket_messages_ultrade)
            self._connection_ids_ultrade.add(connection_id)

            self.logger().info("Subscribed to order book and user order...")
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._stop_event_set.is_set:
                self.logger().error(
                    "Unexpected error occurred while subscribing to order book stream & user stream...",
                    exc_info=True
                )
                self.logger().info("Attempting to subscribe to channels again.")
                await asyncio.sleep(1.0)
                await self._subscribe_channles_ultrade()

    async def _unsubscribe_channels_ultrade(self):
        try:
            for connection_id in self._connection_ids_ultrade:
                await self._ultrade_client.unsubscribe(connection_id)
            self.logger().info("Unsubscribed to public order book and trade channels.")
        except Exception:
            pass
        finally:
            self._connection_ids_ultrade.clear()

    async def _initialize_conversion_rules_ultrade(self, exchange_info=None):
        try:
            self._conversion_rules_ultrade.clear()
            if exchange_info is None:
                exchange_info = await self._get_ultrade_trading_pairs()
            for symbol_data in filter(ultrade_utils.is_exchange_information_valid, exchange_info):
                # initialize conversion rules here.
                base = symbol_data["base_currency"].upper()
                quote = symbol_data["price_currency"].upper()
                self._conversion_rules_ultrade[base] = 10 ** int(symbol_data["base_decimal"])
                self._conversion_rules_ultrade[quote] = 10 ** int(symbol_data["price_decimal"])

                self._conversion_rules_ultrade_set_event_task.set()
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
        # self.logger().info("GET_TP:: START")
        response = await self._ultrade_api.get_pair_list()
        # self.logger().info(f"GET_TP:: {response}")

        return response

    async def _get_open_orders(self) -> List[str]:
        if self._trading_pairs is None:
            self.logger().error("Trading Pairs needed for fetching Open orders in Ultrade Exchange.")
            return []

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
        if asset is None:
            return Decimal(0)
        asset: str = asset.upper()
        value = Decimal(str(value)) / Decimal(str(self._conversion_rules_ultrade[asset]))

        return value

    def to_fixed_point(self, asset: str, value: Decimal) -> int:
        asset: str = asset.upper()
        value = int(Decimal(str(value)) * Decimal(str(self._conversion_rules_ultrade[asset])))

        return value

    def to_hb_order_book(self, order_book: Dict[str, Any]) -> Dict[str, Any]:
        try:
            trading_pair = self._trading_pairs[0]
            base, quote = list(map(lambda x: x, trading_pair.split('-')))

            bids = [[self.from_fixed_point(quote, bid[0]), self.from_fixed_point(base, bid[1])] for bid in order_book['buy']]
            asks = [[self.from_fixed_point(quote, ask[0]), self.from_fixed_point(base, ask[1])] for ask in order_book['sell']]

            order_book['bids'] = bids
            order_book['asks'] = asks

            del order_book['buy']
            del order_book['sell']

            order_book['trading_pair'] = trading_pair

            return order_book
        except Exception:
            self.logger().error(
                "Unexpected error occurred transalting order book stream...",
                exc_info=True
            )
