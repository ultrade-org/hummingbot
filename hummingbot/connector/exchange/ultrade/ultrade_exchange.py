import asyncio
from collections import defaultdict
from decimal import Decimal
from itertools import zip_longest
from typing import Any, Dict, List, Optional, Tuple

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
from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import DeductedFromReturnsTradeFee, TokenAmount, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from ultrade import Client as UltradeClient

PRICE_TOKEN = "18DEC"   # this is the default token for price conversion rule


class UltradeExchange(ExchangePyBase):
    web_utils = web_utils

    def __init__(self,
                 ultrade_trading_key: str,
                 ultrade_wallet_address: str,
                 ultrade_company_id: str,
                 ultrade_api_url: str,
                 ultrade_mnemonic_key: str,
                 use_bulk_order_endpoints: bool = True,
                 bulk_order_max_batch: int = 6,
                 balance_asset_limit: Optional[Dict[str, Dict[str, Decimal]]] = None,
                 rate_limits_share_pct: Decimal = Decimal("100"),
                 trading_pairs: Optional[List[str]] = None,
                 trading_required: bool = True,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 ):
        self.ultrade_trading_key = ultrade_trading_key
        self.ultrade_wallet_address = ultrade_wallet_address
        self.ultrade_mnemonic_key = ultrade_mnemonic_key
        self.ultrade_company_id = int(ultrade_company_id)
        self.ultrade_api_url = ultrade_api_url
        self._domain = domain
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        self._last_trades_poll_ultrade_timestamp = 1.0

        self.available_trading_pairs = None
        self.ultrade_client = self.create_ultrade_client()
        self._ultrade_conversion_rules: Optional[Dict[str, int]] = {
            "18DEC": 18,
        }
        self._ultrade_token_address_asset_map: Optional[Dict[str, str]] = {}
        self._ultrade_token_id_asset_map: Optional[Dict[int, str]] = {}
        self._ultrade_pair_symbol_to_pair_id_map: Optional[Dict[str, int]] = {}
        self._use_bulk_operations: bool = use_bulk_order_endpoints
        self._bulk_operations_supported: bool = use_bulk_order_endpoints
        self._bulk_max_batch: int = max(1, int(bulk_order_max_batch))
        self._orders_queued_to_create: List[InFlightOrder] = []
        self._orders_queued_to_cancel: List[InFlightOrder] = []
        self._orders_creating: Dict[str, InFlightOrder] = {}
        self._orders_cancel_after_create: Dict[str, InFlightOrder] = {}
        self._orders_queue_lock = asyncio.Lock()
        self._orders_processing_task: Optional[asyncio.Task] = None
        self._orders_processing_interval = 0.5
        self._pending_cancel_results: Dict[str, asyncio.Future] = {}
        super().__init__(balance_asset_limit, rate_limits_share_pct)

    def create_ultrade_client(self) -> UltradeClient:
        client = UltradeClient(
            network=self._domain,
            company_id=self.ultrade_company_id,
            api_url=self.ultrade_api_url
        )
        client.set_trading_key(
            trading_key=self.ultrade_trading_key,
            address=self.ultrade_wallet_address,
            trading_key_mnemonic=self.ultrade_mnemonic_key
        )
        return client

    async def start_network(self):
        await super().start_network()
        self._ensure_orders_processing_task()

    async def stop_network(self):
        await self._stop_orders_processing_task()
        await super().stop_network()

    def _should_use_bulk_processing(self) -> bool:
        return self._use_bulk_operations and self._bulk_operations_supported and self.is_trading_required

    def _ensure_orders_processing_task(self):
        if self._should_use_bulk_processing() and self._orders_processing_task is None:
            self._orders_processing_task = safe_ensure_future(self._process_queued_orders())

    async def _stop_orders_processing_task(self):
        if self._orders_processing_task is not None:
            task = self._orders_processing_task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._orders_processing_task = None

    def _get_cancel_future(self, client_order_id: str) -> asyncio.Future:
        future = self._pending_cancel_results.get(client_order_id)
        if future is None or future.done():
            future = asyncio.get_running_loop().create_future()
            self._pending_cancel_results[client_order_id] = future
        return future

    def _set_cancel_result(self, client_order_id: str, success: bool):
        future = self._pending_cancel_results.get(client_order_id)
        if future is not None and not future.done():
            future.set_result(success)
        self._pending_cancel_results.pop(client_order_id, None)

    def _pop_queued_create_order_locked(self, client_order_id: str) -> Optional[InFlightOrder]:
        for index, order in enumerate(self._orders_queued_to_create):
            if order.client_order_id == client_order_id:
                return self._orders_queued_to_create.pop(index)
        return None

    def _mark_orders_creating_locked(self, orders: List[InFlightOrder]):
        for order in orders:
            self._orders_creating[order.client_order_id] = order

    def _process_cancelled_before_create(self, order: InFlightOrder):
        order_update = OrderUpdate(
            client_order_id=order.client_order_id,
            trading_pair=order.trading_pair,
            update_timestamp=self._time_synchronizer.time(),
            new_state=OrderState.CANCELED,
        )
        self._order_tracker.process_order_update(order_update)
        self._set_cancel_result(order.client_order_id, True)

    async def _finalize_create_attempt(
            self,
            order: InFlightOrder,
            created: bool,
            cancel_result_if_not_created: bool = False):
        order_to_cancel = None
        async with self._orders_queue_lock:
            self._orders_creating.pop(order.client_order_id, None)
            order_to_cancel = self._orders_cancel_after_create.pop(order.client_order_id, None)
            if created and order_to_cancel is not None:
                self._orders_queued_to_cancel.append(order_to_cancel)

        if order_to_cancel is not None:
            if created:
                self._ensure_orders_processing_task()
            else:
                self._set_cancel_result(order.client_order_id, cancel_result_if_not_created)

    @staticmethod
    def ultrade_order_type(order_type: OrderType) -> str:
        return order_type.name.upper()

    @staticmethod
    def to_hb_order_type(ultrade_type: str) -> OrderType:
        return OrderType[ultrade_type]

    @property
    def authenticator(self):
        return UltradeAuth(
            trading_key=self.ultrade_trading_key,
            wallet_address=self.ultrade_wallet_address,
            mnemonic_key=self.ultrade_mnemonic_key,
            company_id=self.ultrade_company_id,
            api_url=self.ultrade_api_url,
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
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def trading_pairs_request_path(self):
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def check_network_request_path(self):
        return CONSTANTS.PING_PATH_URL

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
        return [OrderType.LIMIT, OrderType.LIMIT_MAKER, OrderType.MARKET]

    async def get_all_pairs_prices(self) -> List[Dict[str, str]]:
        pairs_prices = await self._api_get(path_url=CONSTANTS.TICKER_BOOK_PATH_URL)
        return pairs_prices

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        error_description = str(request_exception)
        is_time_synchronizer_related = ("-1021" in error_description
                                        and "Timestamp for this request" in error_description)
        return is_time_synchronizer_related

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        return any(msg in str(status_update_exception) for msg in CONSTANTS.ORDER_NOT_EXIST_MESSAGES)

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        return any(msg in str(cancelation_exception) for msg in CONSTANTS.UNKNOWN_ORDER_MESSAGES)

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

    async def _place_order_and_process_update(self, order: InFlightOrder, **kwargs) -> str:
        if not (self._use_bulk_operations and self._bulk_operations_supported):
            try:
                exchange_order_id, timestamp = await self._create_single_order(order)
            except Exception as exc:
                self._on_order_failure(
                    order_id=order.client_order_id,
                    trading_pair=order.trading_pair,
                    amount=order.amount,
                    trade_type=order.trade_type,
                    order_type=order.order_type,
                    price=order.price,
                    exception=exc,
                )
            else:
                order_update = OrderUpdate(
                    client_order_id=order.client_order_id,
                    exchange_order_id=str(exchange_order_id),
                    trading_pair=order.trading_pair,
                    update_timestamp=timestamp,
                    new_state=OrderState.OPEN,
                )
                self._order_tracker.process_order_update(order_update)
            return order.client_order_id

        async with self._orders_queue_lock:
            self._orders_queued_to_create.append(order)
        return order.client_order_id

    async def _execute_order_cancel(self, order: InFlightOrder) -> Optional[str]:
        if not (self._use_bulk_operations and self._bulk_operations_supported):
            success = await self._cancel_single_order(order)
            if success:
                update_timestamp = self._time_synchronizer.time()
                order_update = OrderUpdate(
                    client_order_id=order.client_order_id,
                    trading_pair=order.trading_pair,
                    update_timestamp=update_timestamp,
                    new_state=(OrderState.CANCELED
                               if self.is_cancel_request_in_exchange_synchronous
                               else OrderState.PENDING_CANCEL),
                )
                self._order_tracker.process_order_update(order_update)
                return order.client_order_id
            await self._order_tracker.process_order_not_found(order.client_order_id)
            return None

        cancel_future = self._get_cancel_future(order.client_order_id)
        cancelled_before_create = False
        async with self._orders_queue_lock:
            unsent_order = self._pop_queued_create_order_locked(order.client_order_id)
            if unsent_order is not None:
                order = unsent_order
                cancelled_before_create = True
            elif order.exchange_order_id is None and order.client_order_id in self._orders_creating:
                self._orders_cancel_after_create[order.client_order_id] = order
            else:
                self._orders_queued_to_cancel.append(order)

        if cancelled_before_create:
            self._process_cancelled_before_create(order)
        else:
            self._ensure_orders_processing_task()

        try:
            success = await cancel_future
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().warning(
                f"Unexpected error while waiting for bulk cancel of order {order.client_order_id}.", exc_info=True)
            success = False
        finally:
            self._pending_cancel_results.pop(order.client_order_id, None)

        return order.client_order_id if success else None

    async def _place_order(self,
                           order_id: str,
                           trading_pair: str,
                           amount: Decimal,
                           trade_type: TradeType,
                           order_type: OrderType,
                           price: Decimal,
                           **kwargs) -> Tuple[str, float]:
        raise NotImplementedError("Ultrade connector uses bulk order workflow.")

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        raise NotImplementedError("Ultrade connector uses bulk order workflow.")

    async def _process_queued_orders(self):
        try:
            while True:
                try:
                    await self._flush_queued_orders()
                    if not self._should_use_bulk_processing():
                        break
                    sleep_time = (self.clock.tick_size * 0.5
                                  if self.clock is not None
                                  else self._orders_processing_interval)
                    await asyncio.sleep(sleep_time)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.logger().exception("Unexpected error while processing queued Ultrade orders.", exc_info=True)
                    await asyncio.sleep(self._orders_processing_interval)
        finally:
            self._orders_processing_task = None

    async def _flush_queued_orders(self):
        orders_to_create: List[InFlightOrder] = []
        orders_to_cancel: List[InFlightOrder] = []
        use_bulk_processing = self._should_use_bulk_processing()

        async with self._orders_queue_lock:
            if self._orders_queued_to_cancel:
                orders_to_cancel = self._orders_queued_to_cancel
                self._orders_queued_to_cancel = []
            elif self._orders_queued_to_create:
                orders_to_create = self._orders_queued_to_create
                self._orders_queued_to_create = []
                if use_bulk_processing:
                    self._mark_orders_creating_locked(orders_to_create)

        if not use_bulk_processing:
            if orders_to_cancel:
                await self._execute_single_order_cancels(orders_to_cancel)
            if orders_to_create:
                await self._execute_single_order_creates(orders_to_create)
            return

        if orders_to_cancel:
            await self._execute_bulk_cancel(orders_to_cancel)
        if orders_to_create:
            await self._execute_bulk_create(orders_to_create)

    async def _execute_bulk_create(self, orders: List[InFlightOrder]):
        if not orders:
            return

        if not self._bulk_operations_supported:
            await self._execute_single_order_creates(orders)
            return
        async with self._orders_queue_lock:
            self._mark_orders_creating_locked(orders)
        try:
            await self.trading_pair_symbol_map()
        except Exception as exc:
            self.logger().exception("Failed to build trading pair symbol map before bulk order create.", exc_info=True)
            for order in orders:
                self._on_order_failure(
                    order_id=order.client_order_id,
                    trading_pair=order.trading_pair,
                    amount=order.amount,
                    trade_type=order.trade_type,
                    order_type=order.order_type,
                    price=order.price,
                    exception=exc,
                )
                await self._finalize_create_attempt(
                    order=order,
                    created=False,
                    cancel_result_if_not_created=True,
                )
            return

        payloads: List[Dict[str, Any]] = []
        valid_orders: List[InFlightOrder] = []

        for order in orders:
            try:
                payload = await self._build_bulk_create_payload(order)
            except Exception as exc:
                self._on_order_failure(
                    order_id=order.client_order_id,
                    trading_pair=order.trading_pair,
                    amount=order.amount,
                    trade_type=order.trade_type,
                    order_type=order.order_type,
                    price=order.price,
                    exception=exc,
                )
                await self._finalize_create_attempt(
                    order=order,
                    created=False,
                    cancel_result_if_not_created=True,
                )
                continue
            payloads.append(payload)
            valid_orders.append(order)

        if not valid_orders:
            return

        total_orders = len(valid_orders)

        for start in range(0, total_orders, self._bulk_max_batch):
            order_chunk = valid_orders[start:start + self._bulk_max_batch]
            payload_chunk = payloads[start:start + self._bulk_max_batch]

            self.logger().warning(f"Ultrade bulk create payloads: {payload_chunk}")
            try:
                response = await self.ultrade_client.create_bulk_orders(payload_chunk)
            except Exception as exc:
                self.logger().exception("Bulk order create request failed.", exc_info=True)
                for order in order_chunk:
                    self._on_order_failure(
                        order_id=order.client_order_id,
                        trading_pair=order.trading_pair,
                        amount=order.amount,
                        trade_type=order.trade_type,
                        order_type=order.order_type,
                        price=order.price,
                        exception=exc,
                    )
                    await self._finalize_create_attempt(
                        order=order,
                        created=False,
                        cancel_result_if_not_created=False,
                    )
                continue

            self.logger().warning(f"Ultrade bulk create raw response: {response}")
            if self._is_forbidden_response(response):
                self.logger().warning("Ultrade bulk create endpoint rejected the request. Falling back to sequential order placement.")
                self._bulk_operations_supported = False
                await self._execute_single_order_creates(valid_orders[start:])
                return

            normalized_results = self._normalize_bulk_create_response(response, payload_chunk)

            for order, result in zip_longest(order_chunk, normalized_results, fillvalue=None):
                if order is None:
                    continue

                explicit_error_message = self._bulk_create_error_message(result)
                error_message = explicit_error_message
                exchange_order_id = None if error_message else self._extract_order_id(result)

                if exchange_order_id is None and error_message is None:
                    error_message = f"Missing exchange order id in bulk order response entry: {result}"
                    self.logger().warning(error_message)

                if error_message:
                    self._on_order_failure(
                        order_id=order.client_order_id,
                        trading_pair=order.trading_pair,
                        amount=order.amount,
                        trade_type=order.trade_type,
                        order_type=order.order_type,
                        price=order.price,
                        exception=RuntimeError(error_message),
                    )
                    await self._finalize_create_attempt(
                        order=order,
                        created=False,
                        cancel_result_if_not_created=explicit_error_message is not None,
                    )
                    continue

                order.update_exchange_order_id(str(exchange_order_id))
                update_timestamp = self._time_synchronizer.time()
                order_update = OrderUpdate(
                    client_order_id=order.client_order_id,
                    exchange_order_id=str(exchange_order_id),
                    trading_pair=order.trading_pair,
                    update_timestamp=update_timestamp,
                    new_state=OrderState.OPEN,
                    misc_updates={"response": result} if isinstance(result, dict) else None,
                )
                self._order_tracker.process_order_update(order_update)
                await self._finalize_create_attempt(order=order, created=True)

    async def _execute_bulk_cancel(self, orders: List[InFlightOrder]):
        if not orders:
            return

        if not self._bulk_operations_supported:
            await self._execute_single_order_cancels(orders)
            return

        try:
            await self.trading_pair_symbol_map()
        except Exception:
            self.logger().exception("Failed to build trading pair symbol map before bulk order cancel.", exc_info=True)
            for order in orders:
                self._set_cancel_result(order.client_order_id, False)
            return

        orders_by_pair: Dict[int, List[InFlightOrder]] = defaultdict(list)
        order_id_by_client: Dict[str, int] = {}

        for order in orders:
            exchange_order_id = order.exchange_order_id
            if exchange_order_id is None and order.current_state == OrderState.FAILED:
                self.logger().warning(
                    f"Skipping cancellation for order {order.client_order_id}; order failed without exchange id.")
                await self._order_tracker.process_order_not_found(order.client_order_id)
                self._set_cancel_result(order.client_order_id, False)
                continue
            if exchange_order_id is None:
                async with self._orders_queue_lock:
                    create_in_flight = order.client_order_id in self._orders_creating
                    if create_in_flight:
                        self._orders_cancel_after_create[order.client_order_id] = order
                if create_in_flight:
                    self.logger().warning(
                        f"Deferring cancellation for order {order.client_order_id}; create response is still pending.")
                    continue
                try:
                    exchange_order_id = await order.get_exchange_order_id()
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError:
                    if order.current_state == OrderState.PENDING_CREATE:
                        self.logger().warning(
                            f"Timed out waiting for exchange order id for order {order.client_order_id}; "
                            "leaving the order tracked because its create request has not been resolved.")
                        self._set_cancel_result(order.client_order_id, False)
                        continue
                    self.logger().warning(
                        f"Timed out waiting for exchange order id for order {order.client_order_id}; skipping cancel.")
                    await self._order_tracker.process_order_not_found(order.client_order_id)
                    self._set_cancel_result(order.client_order_id, False)
                    continue
            if exchange_order_id is None:
                self.logger().warning(
                    f"Skipping cancellation for order {order.client_order_id}; exchange order id is not available.")
                await self._order_tracker.process_order_not_found(order.client_order_id)
                self._set_cancel_result(order.client_order_id, False)
                continue
            symbol = await self.exchange_symbol_associated_to_pair(trading_pair=order.trading_pair)
            pair_id = self._ultrade_pair_symbol_to_pair_id_map.get(symbol)
            try:
                order_id_int = int(exchange_order_id)
            except (TypeError, ValueError):
                self.logger().warning(
                    f"Invalid exchange order id for order {order.client_order_id}: {exchange_order_id}.")
                await self._order_tracker.process_order_not_found(order.client_order_id)
                self._set_cancel_result(order.client_order_id, False)
                continue
            if pair_id is None:
                self.logger().warning(f"Skipping cancellation for {order.client_order_id}; pair id not found.")
                self._set_cancel_result(order.client_order_id, False)
                continue
            order_id_by_client[order.client_order_id] = order_id_int
            orders_by_pair[pair_id].append(order)

        pair_items = list(orders_by_pair.items())

        for pair_index, (pair_id, grouped_orders) in enumerate(pair_items):
            order_ids: List[int] = []
            for order in grouped_orders:
                order_id = order_id_by_client.get(order.client_order_id)
                if order_id is not None:
                    order_ids.append(order_id)

            if not order_ids:
                continue

            for start in range(0, len(order_ids), self._bulk_max_batch):
                chunk_orders = grouped_orders[start:start + self._bulk_max_batch]
                chunk_ids = [order_id_by_client[order.client_order_id] for order in chunk_orders]

                self.logger().warning(f"Ultrade bulk cancel payload pair_id={pair_id}: {chunk_ids}")
                try:
                    response = await self.ultrade_client.cancel_bulk_orders(order_ids=chunk_ids, pair_id=pair_id)
                except Exception as exc:
                    self.logger().exception(
                        f"Bulk order cancel request failed for Ultrade pair id {pair_id}.", exc_info=True)
                    for order in chunk_orders:
                        self._set_cancel_result(order.client_order_id, False)
                    continue

                self.logger().warning(f"Ultrade bulk cancel raw response for pair {pair_id}: {response}")
                if self._is_forbidden_response(response):
                    self.logger().warning("Ultrade bulk cancel endpoint rejected the request. Falling back to sequential cancellations.")
                    self._bulk_operations_supported = False
                    remaining_orders = list(chunk_orders)
                    remaining_orders.extend(grouped_orders[start + len(chunk_orders):])
                    for _, future_orders in pair_items[pair_index + 1:]:
                        remaining_orders.extend(future_orders)
                    await self._execute_single_order_cancels(remaining_orders)
                    return

                normalized_results = self._normalize_bulk_response(response, len(chunk_orders))

                for order, result in zip_longest(chunk_orders, normalized_results, fillvalue=None):
                    if order is None:
                        continue
                    success, not_found, message = self._interpret_cancel_entry(result)
                    if success:
                        update_timestamp = self._time_synchronizer.time()
                        order_update = OrderUpdate(
                            client_order_id=order.client_order_id,
                            trading_pair=order.trading_pair,
                            update_timestamp=update_timestamp,
                            new_state=(OrderState.CANCELED
                                       if self.is_cancel_request_in_exchange_synchronous
                                       else OrderState.PENDING_CANCEL),
                            misc_updates={"response": result} if isinstance(result, dict) else None,
                        )
                        self._order_tracker.process_order_update(order_update)
                        self._set_cancel_result(order.client_order_id, True)
                    elif not_found:
                        await self._order_tracker.process_order_not_found(order.client_order_id)
                        self._set_cancel_result(order.client_order_id, False)
                    else:
                        self.logger().warning(
                            f"Failed to cancel order {order.client_order_id}: {message or 'Unknown error'}")
                        self._set_cancel_result(order.client_order_id, False)

    async def _build_bulk_create_payload(self, order: InFlightOrder) -> Dict[str, Any]:
        base, _ = order.trading_pair.split("-")
        amount_int = self.to_fixed_point(base, order.amount)
        price_value = self._sanitize_price(order.price)
        price_int = self.to_fixed_point(PRICE_TOKEN, price_value)

        if order.order_type == OrderType.LIMIT:
            type_str = "L"
        elif order.order_type == OrderType.LIMIT_MAKER:
            type_str = "P"
        elif order.order_type == OrderType.MARKET:
            type_str = "M"
        else:
            raise ValueError(f"Unsupported order type {order.order_type}")

        side_str = "B" if order.trade_type is TradeType.BUY else "S"
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=order.trading_pair)
        pair_id = self._ultrade_pair_symbol_to_pair_id_map[symbol]

        return {
            "pair_id": pair_id,
            "order_side": side_str,
            "order_type": type_str,
            "amount": amount_int,
            "price": price_int,
        }

    @staticmethod
    def _normalize_bulk_response(response: Any, expected_len: int) -> List[Any]:
        if response is None:
            results: List[Any] = []
        elif isinstance(response, list):
            results = list(response)
        elif isinstance(response, dict):
            aggregated: List[Any] = []
            for key in ("successfulOrders", "failedOrders", "results", "data", "orders", "arrayData"):
                value = response.get(key)
                if isinstance(value, list):
                    aggregated.extend(value)
            if aggregated:
                results = aggregated
            else:
                results = [response]
        else:
            results = [response]

        if expected_len <= 0:
            return results

        if not results:
            return [None] * expected_len

        if len(results) < expected_len:
            results = results + [None] * (expected_len - len(results))
        elif len(results) > expected_len:
            results = results[:expected_len]
        return results

    @classmethod
    def _normalize_bulk_create_response(cls, response: Any, payloads: List[Dict[str, Any]]) -> List[Any]:
        expected_len = len(payloads)
        if not isinstance(response, dict):
            return cls._normalize_bulk_response(response, expected_len)

        entries: List[Any] = []
        for key in ("successfulOrders", "failedOrders"):
            value = response.get(key)
            if isinstance(value, list):
                entries.extend(value)

        if not entries:
            return cls._normalize_bulk_response(response, expected_len)

        ordered_results: List[Any] = []
        used_entry_indexes = set()
        for payload in payloads:
            match_index = next(
                (
                    index for index, entry in enumerate(entries)
                    if index not in used_entry_indexes and cls._bulk_create_entry_matches_payload(entry, payload)
                ),
                None,
            )
            if match_index is None:
                ordered_results.append(None)
            else:
                used_entry_indexes.add(match_index)
                ordered_results.append(entries[match_index])

        unused_entries = [entry for index, entry in enumerate(entries) if index not in used_entry_indexes]
        for index, result in enumerate(ordered_results):
            if result is None and unused_entries:
                ordered_results[index] = unused_entries.pop(0)

        return cls._normalize_bulk_response(ordered_results, expected_len)

    @staticmethod
    def _bulk_create_entry_matches_payload(entry: Any, payload: Dict[str, Any]) -> bool:
        if not isinstance(entry, dict):
            return False

        order_data = entry.get("orderData")
        if not isinstance(order_data, dict):
            order_data = entry

        comparable_fields = [
            ("pair_id", entry.get("pairId") or order_data.get("pairId")),
            ("order_side", order_data.get("orderSide") or order_data.get("order_side")),
            ("order_type", order_data.get("orderType") or order_data.get("order_type")),
            ("amount", order_data.get("amount")),
            ("price", order_data.get("price")),
        ]

        matched_fields = 0
        for payload_key, entry_value in comparable_fields:
            if entry_value is None:
                continue
            matched_fields += 1
            if str(payload[payload_key]) != str(entry_value):
                return False

        return matched_fields > 0

    @staticmethod
    def _bulk_create_error_message(entry: Any) -> Optional[str]:
        if isinstance(entry, dict):
            for key in ("error", "reason", "failure_reason", "message"):
                value = entry.get(key)
                if value:
                    return str(value)
            if entry.get("success") is False:
                return "Bulk order create failed"
        elif isinstance(entry, str) and entry.lower().startswith("error"):
            return entry
        return None

    @classmethod
    def _extract_order_id(cls, entry: Any) -> Optional[str]:
        if isinstance(entry, dict):
            for key in ("id", "orderId", "order_id", "orderID"):
                value = entry.get(key)
                if value is not None:
                    return str(value)
            for key in ("order", "result", "data", "orderResult"):
                value = entry.get(key)
                if isinstance(value, (dict, list)):
                    candidate = cls._extract_order_id(value)
                    if candidate is not None:
                        return candidate
        elif isinstance(entry, list):
            for value in entry:
                candidate = cls._extract_order_id(value)
                if candidate is not None:
                    return candidate
        elif isinstance(entry, (int, str)):
            return str(entry)
        return None

    @classmethod
    def _interpret_cancel_entry(cls, entry: Any) -> Tuple[bool, bool, Optional[str]]:
        if entry is None:
            return True, False, None
        if isinstance(entry, dict):
            if entry.get("error") is not None:
                return False, False, str(entry.get("error"))
            failure_reason = entry.get("reason") or entry.get("failure_reason")
            if failure_reason is not None:
                status = str(entry.get("status", "")).lower()
                not_found = status in {"not_found", "unknown_cancel_order"}
                return False, not_found, str(failure_reason)
            if entry.get("success") is False:
                reason = entry.get("failure_reason") or entry.get("message")
                status = str(entry.get("status", "")).lower()
                not_found = status in {"not_found", "unknown_cancel_order"}
                return False, not_found, reason
            status = str(entry.get("status", "")).lower()
            if status in {"not_found", "unknown_cancel_order"}:
                return False, True, entry.get("message")
            for value in entry.values():
                success, not_found, reason = cls._interpret_cancel_entry(value)
                if not success or not_found:
                    return success, not_found, reason
            return True, False, None
        if isinstance(entry, list):
            for value in entry:
                success, not_found, reason = cls._interpret_cancel_entry(value)
                if not success or not_found:
                    return success, not_found, reason
            return True, False, None
        if isinstance(entry, str):
            lower = entry.lower()
            if lower.startswith("error"):
                return False, False, entry
            return True, False, None
        if isinstance(entry, bool):
            if entry:
                return True, False, None
            return False, False, "Cancellation failed"
        return True, False, None

    @staticmethod
    def _sanitize_price(price: Optional[Decimal]) -> Decimal:
        if price is None:
            return Decimal("0")
        if isinstance(price, Decimal) and price.is_nan():
            return Decimal("0")
        return price

    async def _execute_single_order_creates(self, orders: List[InFlightOrder]):
        for order in orders:
            try:
                exchange_order_id, timestamp = await self._create_single_order(order)
            except Exception as exc:
                self._on_order_failure(
                    order_id=order.client_order_id,
                    trading_pair=order.trading_pair,
                    amount=order.amount,
                    trade_type=order.trade_type,
                    order_type=order.order_type,
                    price=order.price,
                    exception=exc,
                )
                await self._finalize_create_attempt(
                    order=order,
                    created=False,
                    cancel_result_if_not_created=False,
                )
                continue

            order.update_exchange_order_id(str(exchange_order_id))
            order_update = OrderUpdate(
                client_order_id=order.client_order_id,
                exchange_order_id=str(exchange_order_id),
                trading_pair=order.trading_pair,
                update_timestamp=timestamp,
                new_state=OrderState.OPEN,
            )
            self._order_tracker.process_order_update(order_update)
            await self._finalize_create_attempt(order=order, created=True)

    async def _execute_single_order_cancels(self, orders: List[InFlightOrder]):
        for order in orders:
            try:
                success = await self._cancel_single_order(order)
            except Exception as exc:
                self.logger().warning(f"Failed to cancel order {order.client_order_id} via single cancel: {exc}")
                success = False

            if success:
                update_timestamp = self._time_synchronizer.time()
                order_update = OrderUpdate(
                    client_order_id=order.client_order_id,
                    trading_pair=order.trading_pair,
                    update_timestamp=update_timestamp,
                    new_state=(OrderState.CANCELED
                               if self.is_cancel_request_in_exchange_synchronous
                               else OrderState.PENDING_CANCEL),
                )
                self._order_tracker.process_order_update(order_update)
                self._set_cancel_result(order.client_order_id, True)
            else:
                await self._order_tracker.process_order_not_found(order.client_order_id)
                self._set_cancel_result(order.client_order_id, False)

    @staticmethod
    def _is_forbidden_response(response: Any) -> bool:
        if response is None:
            return False
        if isinstance(response, dict):
            message = str(response.get("message", "")).lower()
            status_code = str(response.get("statusCode", "")).lower()
            status = str(response.get("status", "")).lower()
            return "forbidden" in message or status_code == "403" or status == "403"
        if isinstance(response, str):
            return response.lower() == "forbidden"
        return False

    async def _create_single_order(self, order: InFlightOrder) -> Tuple[str, float]:
        await self.trading_pair_symbol_map()
        base, _ = order.trading_pair.split("-")
        amount_int = self.to_fixed_point(base, order.amount)
        price_value = self._sanitize_price(order.price)
        price_int = self.to_fixed_point(PRICE_TOKEN, price_value)

        if order.order_type == OrderType.LIMIT:
            type_str = "L"
        elif order.order_type == OrderType.LIMIT_MAKER:
            type_str = "P"
        elif order.order_type == OrderType.MARKET:
            type_str = "M"
        else:
            raise ValueError(f"Unsupported order type {order.order_type}")

        side_str = "B" if order.trade_type is TradeType.BUY else "S"
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=order.trading_pair)
        pair_id = self._ultrade_pair_symbol_to_pair_id_map[symbol]

        order_result = await self.ultrade_client.create_order(
            pair_id=pair_id,
            order_side=side_str,
            order_type=type_str,
            amount=amount_int,
            price=price_int
        )

        exchange_order_id = order_result.get("id") if isinstance(order_result, dict) else None
        if exchange_order_id is None:
            raise RuntimeError(f"Ultrade single order response missing id: {order_result}")

        return str(exchange_order_id), self._time_synchronizer.time()

    async def _cancel_single_order(self, order: InFlightOrder) -> bool:
        exchange_order_id = await order.get_exchange_order_id()
        if exchange_order_id is None:
            self.logger().warning(f"Cannot cancel order {order.client_order_id}; exchange order id is missing.")
            return False

        result = await self.ultrade_client.cancel_order(int(exchange_order_id))
        if result is None:
            return True
        if isinstance(result, dict) and result.get("error") is not None:
            self.logger().warning(f"Ultrade cancel order error for {order.client_order_id}: {result}")
            return False
        return True

    async def _format_trading_rules(self, exchange_info_dict: Dict[str, Any]) -> List[TradingRule]:
        """
        Example:
        [
            {
                "base_chain_id": 6,
                "base_currency": "amax",
                "base_decimal": 18,
                "base_id": "0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "base_token_id": 11,
                "created_at": "2024-05-17T12:21:31.997Z",
                "id": 55,
                "is_active": true,
                "min_order_size": "5000000000000000000",
                "min_price_increment": "1000000000000000",
                "min_size_increment": "1000000000000000000",
                "pair_key": "amax_usdc",
                "pair_name": "AMAX_USDC",
                "pairId": 55,
                "price_chain_id": 65537,
                "price_currency": "usdc",
                "price_decimal": 6,
                "price_id": "0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "price_token_id": 20,
                "updated_at": "2024-11-22T17:33:56.000Z",
                "inuseWithPartners":
                [
                    1,
                    63,
                    77
                ],
                "restrictedCountries": [],
                "pairSettings": {},
                "partner_id": 210179851,
                "delisting_date": null
            },
            ...
        ]
        """
        trading_pair_rules = exchange_info_dict.get("symbols", [])
        retval = []
        for rule in filter(ultrade_utils.is_exchange_information_valid, trading_pair_rules):
            try:
                trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol=rule.get("pair_key"))

                base_decimal = int(rule.get("base_decimal"))
                min_order_size = Decimal(rule.get("min_order_size")) / Decimal(10 ** base_decimal)
                min_base_amount_increment = Decimal(rule.get("min_size_increment")) / Decimal(10 ** base_decimal)
                # TODO: get clarification on this. for now, 18 is the default
                min_price_increment = Decimal(rule.get("min_price_increment")) / Decimal(10 ** 18)

                retval.append(
                    TradingRule(trading_pair,
                                min_order_size=min_order_size,
                                min_price_increment=min_price_increment,
                                min_base_amount_increment=min_base_amount_increment))

            except Exception:
                self.logger().exception(f"Error parsing the trading pair rule {rule}. Skipping.")
        return retval

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
                event_type = event_message.get("event")
                # Refer to https://github.com/ultrade-org/ultrade-python-sdk/blob/master/ultrade/socket_client.py
                if event_type == CONSTANTS.USER_ORDER_EVENT_TYPE:
                    update_type, order_data = event_message.get("data")
                    exchange_order_id = str(order_data[3])
                    tracked_order = next((order for order in self._order_tracker.all_updatable_orders.values() if order.exchange_order_id == exchange_order_id), None)

                    if tracked_order is None:
                        continue
                    if update_type == "add":
                        new_state = OrderState.OPEN
                    elif update_type == "update":
                        status_code = int(order_data[4])
                        if status_code == 1:
                            new_state = OrderState.OPEN
                        elif status_code == 2:
                            new_state = OrderState.CANCELED
                        elif status_code == 3 or status_code == 4:
                            new_state = OrderState.FILLED
                    elif update_type == "cancel":
                        new_state = OrderState.CANCELED
                    order_update = OrderUpdate(
                        trading_pair=tracked_order.trading_pair,
                        update_timestamp=self._time_synchronizer.time(),
                        new_state=new_state,
                        client_order_id=exchange_order_id,
                        exchange_order_id=exchange_order_id,
                    )
                    self._order_tracker.process_order_update(order_update=order_update)

                elif event_type == CONSTANTS.USER_TRADE_EVENT_TYPE:
                    trade_data = event_message.get("data")

                    if trade_data[11].upper() != "CONFIRMED" or Decimal(trade_data[7]) == 0:
                        continue
                    exchange_order_id = str(trade_data[3])
                    tracked_order = next((order for order in self._order_tracker.all_fillable_orders.values() if order.exchange_order_id == exchange_order_id), None)

                    if tracked_order is None:
                        continue
                    fee_token = self._ultrade_token_id_asset_map.get(int(trade_data[13]))
                    fee_amount = Decimal(str(int(trade_data[12]))) / Decimal(str(10 ** int(trade_data[14])))
                    trade_type = TradeType.BUY if trade_data[4] else TradeType.SELL
                    fee = TradeFeeBase.new_spot_fee(
                        fee_schema=self.trade_fee_schema(),
                        trade_type=trade_type,
                        percent_token=fee_token,
                        flat_fees=[TokenAmount(amount=fee_amount, token=fee_token)]
                    )
                    base, quote = tracked_order.trading_pair.split("-")
                    fill_price = self.from_fixed_point(PRICE_TOKEN, int(trade_data[7]))
                    fill_base_amount = self.from_fixed_point(base, int(trade_data[8]))
                    fill_quote_amount = fill_base_amount * fill_price
                    trade_update = TradeUpdate(
                        trade_id=str(trade_data[6]),
                        client_order_id=tracked_order.client_order_id,
                        exchange_order_id=exchange_order_id,
                        trading_pair=tracked_order.trading_pair,
                        fee=fee,
                        fill_base_amount=fill_base_amount,
                        fill_quote_amount=fill_quote_amount,
                        fill_price=fill_price,
                        fill_timestamp=self._time_synchronizer.time(),
                    )
                    self._order_tracker.process_trade_update(trade_update)

                elif event_type == CONSTANTS.USER_BALANCE_EVENT_TYPE:
                    balance_data = event_message.get("data", {}).get("data")
                    if balance_data is None:
                        continue
                    asset_name = self._ultrade_token_address_asset_map.get(balance_data.get("tokenAddress").upper())
                    total_balance = self.from_fixed_point(asset=asset_name, value=int(balance_data.get("amount")))
                    locked_balance = self.from_fixed_point(asset=asset_name, value=int(balance_data.get("lockedAmount")))
                    free_balance = total_balance - locked_balance
                    self._account_available_balances[asset_name] = free_balance
                    self._account_balances[asset_name] = total_balance

            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unexpected error in user stream listener loop.", exc_info=True)
                await self._sleep(5.0)

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        trade_updates = []

        if order.exchange_order_id is not None:
            exchange_order_id = int(order.exchange_order_id)
            trading_pair = order.trading_pair
            all_fills_response = await self.ultrade_client.get_order_by_id(exchange_order_id)

            base, quote = trading_pair.split("-")

            for trade in all_fills_response["trades"]:
                if Decimal(trade.get("price", "0")) == 0 or trade.get("status", "").upper() != "CONFIRMED":
                    continue    # Skip trades with zero price - they are canceled orders
                fee_token = base if trade["isBuyer"] else quote
                fee_amount = self.from_fixed_point(fee_token, int(trade["fee"]))
                fee = TradeFeeBase.new_spot_fee(
                    fee_schema=self.trade_fee_schema(),
                    trade_type=order.trade_type,
                    percent_token=fee_token,
                    flat_fees=[TokenAmount(amount=fee_amount, token=fee_token)]
                )
                fill_base_amount = self.from_fixed_point(base, int(trade["amount"]))
                fill_price = self.from_fixed_point(PRICE_TOKEN, int(trade["price"]))
                fill_quote_amount = fill_base_amount * fill_price
                trade_update = TradeUpdate(
                    trade_id=str(trade["tradeId"]),
                    client_order_id=order.client_order_id,
                    exchange_order_id=exchange_order_id,
                    trading_pair=trading_pair,
                    fee=fee,
                    fill_base_amount=fill_base_amount,
                    fill_quote_amount=fill_quote_amount,
                    fill_price=fill_price,
                    fill_timestamp=self._time_synchronizer.time(),
                )
                trade_updates.append(trade_update)

        return trade_updates

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        exchange_order_id = await tracked_order.get_exchange_order_id()
        updated_order_data = await self.ultrade_client.get_order_by_id(int(exchange_order_id))

        new_state = tracked_order.current_state
        order_status = updated_order_data["status"]
        if order_status == 1:
            if Decimal(updated_order_data.get("filledAmount", "0")) > 0:
                new_state = OrderState.PARTIALLY_FILLED
            else:
                new_state = OrderState.OPEN
        elif order_status == 2:
            new_state = OrderState.CANCELED
        elif order_status == 3 or order_status == 4:
            new_state = OrderState.FILLED

        order_update = OrderUpdate(
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=exchange_order_id,
            trading_pair=tracked_order.trading_pair,
            update_timestamp=self._time_synchronizer.time(),
            new_state=new_state,
        )

        return order_update

    async def _update_balances(self):
        local_asset_names = set(self._account_balances.keys())
        remote_asset_names = set()

        account_info = await self.ultrade_client.get_balances()
        await self.trading_pair_symbol_map()

        for balance_entry in account_info:
            asset_name = self._ultrade_token_address_asset_map.get(balance_entry["tokenAddress"].upper())
            total_balance = self.from_fixed_point(asset=asset_name, value=int(balance_entry["amount"]))
            locked_balance = self.from_fixed_point(asset=asset_name, value=int(balance_entry["lockedAmount"]))
            free_balance = total_balance - locked_balance
            self._account_available_balances[asset_name] = free_balance
            self._account_balances[asset_name] = total_balance
            remote_asset_names.add(asset_name)

        asset_names_to_remove = local_asset_names.difference(remote_asset_names)
        for asset_name in asset_names_to_remove:
            del self._account_available_balances[asset_name]
            del self._account_balances[asset_name]

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        trading_pair_mapping = bidict()
        token_address_asset_mapping = {}
        token_id_asset_mapping = {}
        conversion_rules = {}
        pair_symbol_to_pair_id_map = {}
        for symbol_data in filter(ultrade_utils.is_exchange_information_valid, exchange_info["symbols"]):
            trading_pair_mapping[symbol_data["pair_key"]] = combine_to_hb_trading_pair(base=symbol_data["base_currency"].upper(),
                                                                                       quote=symbol_data["price_currency"].upper())
            token_address_asset_mapping[str(symbol_data["base_id"]).upper()] = symbol_data["base_currency"].upper()
            token_address_asset_mapping[str(symbol_data["price_id"]).upper()] = symbol_data["price_currency"].upper()
            token_id_asset_mapping[int(symbol_data["base_token_id"])] = symbol_data["base_currency"].upper()
            token_id_asset_mapping[int(symbol_data["price_token_id"])] = symbol_data["price_currency"].upper()
            conversion_rules[str(symbol_data["base_currency"]).upper()] = int(symbol_data["base_decimal"])
            conversion_rules[str(symbol_data["price_currency"]).upper()] = int(symbol_data["price_decimal"])
            pair_symbol_to_pair_id_map[symbol_data["pair_key"]] = int(symbol_data["id"])
        self._set_trading_pair_symbol_map(trading_pair_mapping)
        self._ultrade_token_address_asset_map.update(token_address_asset_mapping)
        self._ultrade_token_id_asset_map.update(token_id_asset_mapping)
        self._ultrade_conversion_rules.update(conversion_rules)
        self._ultrade_pair_symbol_to_pair_id_map.update(pair_symbol_to_pair_id_map)

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

        # Ensure conversion rules are available before parsing price data
        await self.trading_pair_symbol_map()

        resp_json = await self.ultrade_client.get_price(symbol)
        raw_last_price = resp_json.get("lastPrice")
        if raw_last_price is None:
            return 0.0

        try:
            scaled_price = self.from_fixed_point(PRICE_TOKEN, int(Decimal(str(raw_last_price))))
        except (KeyError, ValueError, ArithmeticError):
            # Fallback to plain float if conversion info is missing or malformed
            return float(raw_last_price)

        return float(scaled_price)

    def from_fixed_point(self, asset: str, value: int) -> Decimal:
        if asset is None:
            return Decimal(0)
        value = Decimal(str(value)) / Decimal(str(10 ** self._ultrade_conversion_rules[asset]))

        return value

    def to_fixed_point(self, asset: str, value: Decimal) -> int:
        if asset is None:
            return 0
        value = int(Decimal(str(value)) * Decimal(str(10 ** self._ultrade_conversion_rules[asset])))

        return value

    async def _make_network_check_request(self):
        await self.ultrade_client.ping()

    async def _make_trading_rules_request(self) -> Any:
        exchange_info = await self.ultrade_client.get_pair_list()
        exchange_info = {
            "symbols": exchange_info
        }
        return exchange_info

    async def _make_trading_pairs_request(self) -> Any:
        exchange_info = await self.ultrade_client.get_pair_list()
        exchange_info = {
            "symbols": exchange_info
        }
        return exchange_info

    async def process_ultrade_order_book(self, order_book: Dict[str, Any]) -> Dict[str, Any]:
        trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol=order_book["pair"])

        base, quote = trading_pair.split("-")

        bids = order_book.get("buy", [])
        asks = order_book.get("sell", [])
        for bid in bids:
            bid[0] = float(self.from_fixed_point(PRICE_TOKEN, int(bid[0])))
            bid[1] = float(self.from_fixed_point(base, int(bid[1])))
        for ask in asks:
            ask[0] = float(self.from_fixed_point(PRICE_TOKEN, int(ask[0])))
            ask[1] = float(self.from_fixed_point(base, int(ask[1])))

        order_book["bids"] = bids
        order_book["asks"] = asks
        order_book["trading_pair"] = trading_pair

        return order_book
