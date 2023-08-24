from decimal import Decimal
from typing import Any, Dict

from pydantic import Field, SecretStr

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap, ClientFieldData
from hummingbot.core.data_type.trade_fee import TradeFeeSchema
from ultrade.sdk_client import Client as UltradeClient

CENTRALIZED = True
EXAMPLE_PAIR = "ALGO-USDC"

DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.001"),
    taker_percent_fee_decimal=Decimal("0.001"),
    buy_percent_fee_deducted_from_returns=True
)


def is_exchange_information_valid(exchange_info: Dict[str, Any]) -> bool:
    """
    Verifies if a trading pair is enabled to operate with based on its exchange information
    :param exchange_info: the exchange information for a trading pair
    :return: True if the trading pair is enabled, False otherwise
    """
    return exchange_info.get("is_active", False)


def init_ultrade_client(creds, options):
    try:
        client = UltradeClient(creds, options)
        return client
    except Exception as e:
        return str(e)


class UltradeConfigMap(BaseConnectorConfigMap):
    connector: str = Field(default="ultrade", const=True, client_data=None)
    ultrade_mnemonic: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Ultrade Mnemonic",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        )
    )
    ultrade_wallet_address: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Ultrade Wallet Address",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        )
    )

    class Config:
        title = "ultrade"


KEYS = UltradeConfigMap.construct()

OTHER_DOMAINS = ["ultrade_testnet"]
OTHER_DOMAINS_PARAMETER = {"ultrade_testnet": "testnet"}
OTHER_DOMAINS_EXAMPLE_PAIR = {"ultrade_testnet": EXAMPLE_PAIR}
OTHER_DOMAINS_DEFAULT_FEES = {"ultrade_testnet": DEFAULT_FEES}


class UltradeTestnetConfigMap(BaseConnectorConfigMap):
    connector: str = Field(default="ultrade_testnet", const=True, client_data=None)
    ultrade_mnemonic: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Ultrade Testnet Mnemonic",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        )
    )
    ultrade_wallet_address: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Ultrade Testnet Wallet Address",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        )
    )

    class Config:
        title = "ultrade_testnet"


OTHER_DOMAINS_KEYS = {"ultrade_testnet": UltradeTestnetConfigMap.construct()}
