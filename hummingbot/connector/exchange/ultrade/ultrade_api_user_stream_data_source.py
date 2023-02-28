import asyncio
import time
from typing import TYPE_CHECKING, List, Optional

from hummingbot.connector.exchange.ultrade import ultrade_constants as CONSTANTS, ultrade_web_utils as web_utils
from hummingbot.connector.exchange.ultrade.ultrade_auth import UltradeAuth
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger
from ultrade import socket_options as SOCKET_OPTIONS

if TYPE_CHECKING:
    from hummingbot.connector.exchange.ultrade.ultrade_exchange import UltradeExchange


class UltradeAPIUserStreamDataSource(UserStreamTrackerDataSource):

    LISTEN_KEY_KEEP_ALIVE_INTERVAL = 1800  # Recommended to Ping/Update listen key to keep connection alive
    HEARTBEAT_TIME_INTERVAL = 30.0

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

    @property
    def last_recv_time(self) -> float:
        """
        Returns the time of the last received message

        :return: the timestamp of the last received message in seconds
        """
        return self._last_recv_time

    async def listen_for_user_stream(self, output: asyncio.Queue):
        """
        Connects to the user private channel in the exchange using a websocket connection. With the established
        connection listens to all balance events and order updates provided by the exchange, and stores them in the
        output queue

        :param output: the queue to use to store the received messages
        """
        while True:
            try:
                await self._subscribe_channels_ultrade(output)
            except asyncio.CancelledError:
                raise
            except ConnectionError as connection_exception:
                self.logger().warning(f"The websocket connection was closed ({connection_exception})")
            except Exception:
                self.logger().exception("Unexpected error while listening to user stream. Retrying after 5 seconds...")
                await self._sleep(1.0)
            finally:
                pass

    async def _subscribe_channels_ultrade(self, output: asyncio.Queue):
        """
        Subscribes to the trade events and diff orders events through the provided websocket connection.

        Ultrade does not require any channel subscription.

        :param websocket_assistant: the websocket assistant used to connect to the exchange
        """
        try:
            trading_pair = self._trading_pairs[0]
            symbol = await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)

            def _process_websocket_messages_ultrade(event, *data):
                message = {}
                message['data'] = data
                if event in ['orders', 'trades']:
                    message['event'] = event
                    output.put_nowait(message)
                    self._last_recv_time = self._time()

            order_params = {
                'symbol': symbol,
                'streams': [SOCKET_OPTIONS.ORDER],
            }
            trade_params = {
                'symbol': symbol,
                'streams': [SOCKET_OPTIONS.TRADE],
            }
            await self._connector._ultrade_client.subscribe(order_params, _process_websocket_messages_ultrade)
            await self._connector._ultrade_client.subscribe(trade_params, _process_websocket_messages_ultrade)

            self.logger().info("Subscribed to public order book and trade channels...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().error(
                "Unexpected error occurred subscribing to order book trading and delta streams...",
                exc_info=True
            )
            raise
