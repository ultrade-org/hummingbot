import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hummingbot.connector.exchange.ultrade import ultrade_constants as CONSTANTS

# from hummingbot.connector.exchange.ultrade.ultrade_order_book import UltradeOrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.logger import HummingbotLogger
from ultrade import socket_options as SOCKET_OPTIONS
from ultrade.sdk_client import Client as UltradeClient

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
        self._ultrade_client = UltradeClient(self._connector._ultrade_credentials, self._connector._ultrade_options)
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
        order_book = self._to_hb_order_book(data)

        return order_book

    async def _subscribe_channels_ultrade(self):
        """
        Subscribes to the trade events and diff orders events through the provided websocket connection.
        :param ws: the websocket assistant used to connect to the exchange
        """
        try:
            trading_pair = self._trading_pairs[0]
            symbol = await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
            depth_params = {
                'symbol': symbol,
                'streams': [SOCKET_OPTIONS.DEPTH],
            }

            def process_websocket_messages_ultrade(event, message):
                event_message = {}
                if event == self._snapshot_messages_queue_key and message is not None:
                    event_message['type'] = event
                    order_book = self._to_hb_order_book(message)
                    event_message['message'] = order_book
                    self._message_queue[event].put_nowait(event_message)

            connection_id = await self._ultrade_client.subscribe(depth_params, process_websocket_messages_ultrade)
            self._connection_ids.add(connection_id)

            self.logger().info("Subscribed to public order book and trade channels...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().error(
                "Unexpected error occurred while subscribing to order book trading and delta streams...",
                exc_info=True
            )
            raise

    async def _unsubscribe_channels_ultrade(self):
        try:
            for connection_id in self._connection_ids:
                await self._ultrade_client.unsubscribe(connection_id)
            self.logger().info("Unsubscribed to public order book and trade channels.")
        except Exception:
            pass
        finally:
            self._connection_ids.clear()

    async def listen_for_subscriptions(self):
        """
        Connects to the trade events and order diffs websocket endpoints and listens to the messages sent by the
        exchange. Each message is stored in its own queue.
        """
        while True:
            try:
                # await self._subscribe_channels_ultrade()
                # await self._sleep(self.ONE_DAY)
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

    def _to_hb_order_book(self, order_book: Dict[str, Any]) -> Dict[str, Any]:
        try:
            trading_pair = self._trading_pairs[0]
            base, quote = list(map(lambda x: x, trading_pair.split('-')))

            bids = [[self._connector.from_fixed_point(quote, bid[0]), self._connector.from_fixed_point(base, bid[1])] for bid in order_book['buy']]
            asks = [[self._connector.from_fixed_point(quote, ask[0]), self._connector.from_fixed_point(base, ask[1])] for ask in order_book['sell']]

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
