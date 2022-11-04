import hashlib
import hmac
import time
from collections import OrderedDict
from typing import Any, Dict, Optional
from urllib.parse import urlencode

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

    def add_auth_to_params(self,
                           params: Optional[Dict[str, Any]]):
        timestamp = int(self.time_provider.time() * 1e3)
        request_params = params or {}
        request_params["timestamp"] = timestamp
        request_params = self.keysort(request_params)
        return request_params

    def _generate_signature(self, params: Dict[str, Any]) -> str:
        encoded_params_str = urlencode(params)
        digest = hmac.new(self.wallet_address.encode("utf8"), encoded_params_str.encode("utf8"), hashlib.sha256).hexdigest()
        return digest

    def generate_ws_authentication_message(self):
        """
        Generates the authentication message to start receiving messages from
        the 3 private ws channels
        """
        expires = int((self.time_provider.time() + 10) * 1e3)
        _val = f'GET/realtime{expires}'
        signature = hmac.new(self.wallet_address.encode("utf8"),
                             _val.encode("utf8"), hashlib.sha256).hexdigest()
        auth_message = {
            "op": "auth",
            "args": [self.wallet_address, expires, signature]
        }
        return auth_message

    def _time(self):
        return time.time()
