import asyncio
from typing import TYPE_CHECKING, List, Optional

from hummingbot.connector.exchange.ultrade import ultrade_constants as CONSTANTS
from hummingbot.connector.exchange.ultrade.ultrade_auth import UltradeAuth
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.logger import HummingbotLogger
from hummingbot.connector.exchange.ultrade import ultrade_utils

if TYPE_CHECKING:
    from hummingbot.connector.exchange.ultrade.ultrade_exchange import UltradeExchange


class UltradeAPIUserStreamDataSource(UserStreamTrackerDataSource):

    LISTEN_KEY_KEEP_ALIVE_INTERVAL = 1800  # Recommended to Ping/Update listen key to keep connection alive
    HEARTBEAT_TIME_INTERVAL = 30.0
    ONE_HOUR = 60 * 60
    ONE_DAY = 24 * ONE_HOUR

    _logger: Optional[HummingbotLogger] = None

    def __init__(self,
                 auth: UltradeAuth,
                 trading_pairs: List[str],
                 connector: 'UltradeExchange',
                 api_factory: WebAssistantsFactory,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN):
        super().__init__()
        self._auth: UltradeAuth = auth
        self._trading_pairs = trading_pairs
        self._connector = connector
        self._domain = domain
        self._api_factory = api_factory
        self._last_recv_time = 0
        self._connection_ids = set()

    @property
    def last_recv_time(self) -> float:
        """
        Returns the time of the last received message

        :return: the timestamp of the last received message in seconds
        """
        return self._last_recv_time

    async def _process_socket_messages_ultrade_orders(self, output: asyncio.Queue):
        message_queue = self._connector.user_stream_order_queue_ultrade
        while True:
            try:
                snapshot_event = await message_queue.get()
                self._last_recv_time = self._time()
                output.put_nowait(snapshot_event)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error when processing public order book snapshots from exchange")

    async def listen_for_user_stream(self, output: asyncio.Queue):
        """
        Connects to the user private channel in the exchange using a websocket connection. With the established
        connection listens to all balance events and order updates provided by the exchange, and stores them in the
        output queue

        :param output: the queue to use to store the received messages
        """
        while True:
            try:
                await self._process_socket_messages_ultrade_orders(output)
                await self._sleep(self.ONE_DAY)
            except asyncio.CancelledError:
                raise
            except GeneratorExit:
                break
            except Exception:
                self.logger().exception("Unexpected error while listening to user stream. Retrying after 5 seconds...")
                await self._sleep(5.0)
