import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hummingbot.connector.exchange.ultrade import ultrade_constants as CONSTANTS
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.logger import HummingbotLogger
from ultrade.sdk_client import Client as UltradeClient
from hummingbot.connector.exchange.ultrade import ultrade_utils

if TYPE_CHECKING:
    from hummingbot.connector.exchange.ultrade.ultrade_exchange import UltradeExchange


class UltradeAPIOrderBookDataSource(OrderBookTrackerDataSource):
    HEARTBEAT_TIME_INTERVAL = 30.0
    ONE_HOUR = 60 * 60
    ONE_DAY = 24 * ONE_HOUR

    _logger: Optional[HummingbotLogger] = None

    def __init__(self,
                 trading_pairs: List[str],
                 connector: 'UltradeExchange',
                 api_factory: WebAssistantsFactory,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN):
        super().__init__(trading_pairs)
        self._connector = connector
        self._snapshot_messages_queue_key = CONSTANTS.SNAPSHOT_EVENT_TYPE
        self._domain = domain
        self._api_factory = api_factory
        self._ultrade_client = self._ultrade_client = ultrade_utils.init_ultrade_client(self._connector._ultrade_credentials, self._connector._ultrade_options)
        self._connection_ids = set()

    async def get_last_traded_prices(self,
                                     trading_pairs: List[str],
                                     domain: Optional[str] = None) -> Dict[str, float]:
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def _request_order_book_snapshot(self, trading_pair: str) -> Dict[str, Any]:
        """
        Retrieves a copy of the full order book from the exchange, for a particular trading pair.

        :param trading_pair: the trading pair for which the order book will be retrieved

        :return: the response from the exchange (JSON dictionary)
        """

        symbol = await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

        data = await self._connector._ultrade_api.get_depth(symbol)  # default maximum depth of 100 levels
        order_book = self._connector.to_hb_order_book(data)

        return order_book

    async def listen_for_subscriptions(self):
        """
        Connects to the trade events and order diffs websocket endpoints and listens to the messages sent by the
        exchange. Each message is stored in its own queue.
        """
        while True:
            try:
                await self._process_socket_messages_ultrade_depth()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error occurred when listening to order book streams. Retrying in 5 seconds...",)
                await self._sleep(5.0)
            finally:
                continue

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        snapshot: Dict[str, Any] = await self._request_order_book_snapshot(trading_pair)

        timestamp: float = int(snapshot["ts"]) * 1e-3
        order_book_message_content = {
            "trading_pair": snapshot['trading_pair'],
            "update_id": snapshot['u'],
            "bids": snapshot['bids'],
            "asks": snapshot['asks'],
        }
        snapshot_message: OrderBookMessage = OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            order_book_message_content,
            timestamp)
        return snapshot_message

    async def _parse_order_book_snapshot_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        message = raw_message['message']

        timestamp: float = int(message["ts"]) * 1e-3
        order_book_message_content = {
            "trading_pair": message['trading_pair'],
            "update_id": message['u'],
            "bids": message['bids'],
            "asks": message['asks'],
        }

        snapshot_message: OrderBookMessage = OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            order_book_message_content,
            timestamp)

        message_queue.put_nowait(snapshot_message)

    async def _process_socket_messages_ultrade_depth(self):
        message_queue = self._connector.order_book_depth_queue_ultrade
        while True:
            try:
                snapshot_event = await message_queue.get()
                self._message_queue[self._snapshot_messages_queue_key].put_nowait(snapshot_event)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error when processing public order book snapshots from exchange")
                await self._sleep(1.0)
