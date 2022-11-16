import time
from collections import OrderedDict
from typing import Dict

from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest


class UltradeAuth(AuthBase):

    def __init__(self, wallet_address: str, time_provider: TimeSynchronizer):
        self.wallet_address = wallet_address
        self.time_provider = time_provider

    @staticmethod
    def keysort(dictionary: Dict[str, str]) -> Dict[str, str]:
        return OrderedDict(sorted(dictionary.items(), key=lambda t: t[0]))

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """
        Adds the server time and the signature to the request, required for authenticated interactions. It also adds
        the required parameter in the request header.
        :param request: the request to be configured for authenticated interaction
        """
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """
        This method is intended to configure a websocket request to be authenticated. Bybit does not use this
        functionality
        """
        return request  # pass-through

    def _time(self):
        return time.time()
