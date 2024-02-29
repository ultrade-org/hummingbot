from decimal import Decimal
from typing import Any, Dict
from algosdk.encoding import is_valid_address as is_valid_algorand_address
import base58
import re

from pydantic import Field, SecretStr, validator

from hummingbot.connector.exchange.ultrade.ultrade_constants import ULTRADE_NETORKS, ULTRADE_DEV_API_URL, ULTRADE_DEV_SOCKET_URL
from hummingbot.client.config.config_data_types import BaseConnectorConfigMap, ClientFieldData
from hummingbot.core.data_type.trade_fee import TradeFeeSchema
from ultrade import Client as UltradeClient, Signer

CENTRALIZED = True
EXAMPLE_PAIR = "ALGO-USDC"

DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.001"),
    taker_percent_fee_decimal=Decimal("0.001"),
    buy_percent_fee_deducted_from_returns=True
)
        
def is_valid_evm_address(address: str) -> bool:
        return re.match(r"^0x[a-fA-F0-9]{40}$", address) is not None

def is_valid_solana_address(address: str) -> bool:
        try:
            decoded = base58.b58decode(address)
            return len(decoded) == 32
        except Exception:
            return False

WALLET_VALIDATORS = {
    "Algorand": is_valid_algorand_address,
    "EVM": is_valid_evm_address,
    "Solana": is_valid_solana_address
}

def check_is_wallet_address_valid(wallet_address: str) -> bool:
    """
    Verifies if a wallet address is valid
    :param wallet_address: the wallet address to verify
    :return: True if the wallet address is valid, False otherwise
    """
    return any(WALLET_VALIDATORS[wallet_type](wallet_address) for wallet_type in WALLET_VALIDATORS)


def is_exchange_information_valid(exchange_info: Dict[str, Any]) -> bool:
    """
    Verifies if a trading pair is enabled to operate with based on its exchange information
    :param exchange_info: the exchange information for a trading pair
    :return: True if the trading pair is enabled, False otherwise
    """
    return exchange_info.get("is_active", False)


def init_ultrade_client(network: str, mnemonic: str, wallet_address: str, trading_key: str) -> UltradeClient:
    try:
        client = UltradeClient(network)
        if network == "dev":
            client = UltradeClient(network="testnet", api_url=ULTRADE_DEV_API_URL, websocket_url=ULTRADE_DEV_SOCKET_URL)
        if len(trading_key) > 0 and len(wallet_address) > 0:
            #set trading key
            return client
        else:
            signer = Signer.from_mnemonic(mnemonic)
            client.set_login_user(signer)
        return client
    except Exception as e:
        return str(e)


class UltradeConfigMap(BaseConnectorConfigMap):    
    connector: str = Field(default="ultrade", const=True, client_data=None)
    ultrade_network: str = Field(
        default="mainnet",
        client_data=ClientFieldData(
            prompt=lambda cm: f"Enter your Ultrade Network ({'/'.join(ULTRADE_NETORKS)})",
            is_secure=False,
            is_connect_key=True,
            prompt_on_new=True,
        )
    )
    ultrade_trading_key: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Ultrade Trading Key (skip if you want to use a mnemonic or private key)",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        )
    )
    ultrade_wallet_address: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Ultrade Wallet Address (skip if you want to use a mnemonic or private key)",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        )   
    )
    ultrade_mnemonic: SecretStr = Field(
        default=...,
        client_data=ClientFieldData(
            prompt=lambda cm: "Enter your Wallet Mnemonic/Private key (skip if you have already entered your trading key)",
            is_secure=True,
            is_connect_key=True,
            prompt_on_new=True,
        )
    )

    @validator('ultrade_trading_key')
    def check_trading_key(cls, v):
        is_trading_key_valid = is_valid_algorand_address(v.get_secret_value())
        if not is_trading_key_valid and len(v.get_secret_value()) > 0:
            raise ValueError('Invalid Ultrade Trading Key provided.')

    @validator('ultrade_network', always=True)
    def check_network(cls, v):
        if v not in ULTRADE_NETORKS:
            raise ValueError(f"Invalid Ultrade Network provided. Please provide a valid network ({'/'.join(ULTRADE_NETORKS)})")
        return v

    @validator('ultrade_wallet_address', always=True)
    def check_wallet_address(cls, v, values):
        ultrade_trading_key = values.get('ultrade_trading_key', SecretStr('')).get_secret_value()
        wallet_address = v.get_secret_value() if v else ''
        is_valid = check_is_wallet_address_valid(wallet_address)
        if not is_valid and wallet_address:
            raise ValueError(f'Invalid Wallet Address provided. Please provide a valid {"/".join(WALLET_VALIDATORS.keys())} Wallet Address')
        if ultrade_trading_key and not wallet_address:
            raise ValueError('Wallet Address must be provided if Trading Key is provided')
        return v
    
    @validator('ultrade_mnemonic', always=True)
    def check_mnemonic(cls, v, values):
        ultrade_trading_key = values.get('ultrade_trading_key', SecretStr('')).get_secret_value()
        mnemonic = v.get_secret_value() if v else ''
        if not ultrade_trading_key and not mnemonic:
            raise ValueError('Either Wallet mnemonic/Private key or Trading Key must be provided')
        if ultrade_trading_key and mnemonic:
            raise ValueError('Only one of Wallet mnemonic/Private key or Trading Key must be provided')
        return v

    class Config:
        title = "ultrade"


KEYS = UltradeConfigMap.construct()