import re
from decimal import Decimal
from typing import Any, Dict, Literal

import base58
from algosdk.encoding import is_valid_address as is_valid_algorand_address
from bip_utils import AlgorandMnemonicValidator
from pydantic import ConfigDict, Field, SecretStr, field_validator, model_validator

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap, ClientFieldData
from hummingbot.core.data_type.trade_fee import TradeFeeSchema

CENTRALIZED = True
EXAMPLE_PAIR = "SOL-USDC"
DEV4_API_URL = "https://api.dev4.ultradedev.net/"

DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.001"),
    taker_percent_fee_decimal=Decimal("0.001"),
    buy_percent_fee_deducted_from_returns=True
)

UUID_V4_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

ORDER_MANAGEMENT_SINGLE = "single_order"
ORDER_MANAGEMENT_BULK = "bulk_order"
ORDER_MANAGEMENT_BULK_REPLACE = "bulk_replace"
ORDER_MANAGEMENT_MODES = (
    ORDER_MANAGEMENT_SINGLE,
    ORDER_MANAGEMENT_BULK,
    ORDER_MANAGEMENT_BULK_REPLACE,
)
OrderManagementMode = Literal["single_order", "bulk_order", "bulk_replace"]


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
    "Solana": is_valid_solana_address,
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
    :return: True if the trading pair is active, False otherwise
    """
    return exchange_info.get("is_active", False)


def is_spot_exchange_information_valid(exchange_info: Dict[str, Any]) -> bool:
    if not is_exchange_information_valid(exchange_info):
        return False
    if exchange_info.get("type", "spot") != "spot":
        return False
    required_fields = (
        "base_currency",
        "price_currency",
        "base_decimal",
        "price_decimal",
        "base_id",
        "price_id",
        "base_token_id",
        "price_token_id",
    )
    return all(exchange_info.get(field) is not None for field in required_fields)


def validate_order_management_mode(value: Any) -> str:
    aliases = {
        "single": ORDER_MANAGEMENT_SINGLE,
        "single_order": ORDER_MANAGEMENT_SINGLE,
        "single-order": ORDER_MANAGEMENT_SINGLE,
        "single order": ORDER_MANAGEMENT_SINGLE,
        "false": ORDER_MANAGEMENT_SINGLE,
        "no": ORDER_MANAGEMENT_SINGLE,
        "n": ORDER_MANAGEMENT_SINGLE,
        "0": ORDER_MANAGEMENT_SINGLE,
        "bulk": ORDER_MANAGEMENT_BULK,
        "bulk_order": ORDER_MANAGEMENT_BULK,
        "bulk-order": ORDER_MANAGEMENT_BULK,
        "bulk order": ORDER_MANAGEMENT_BULK,
        "true": ORDER_MANAGEMENT_BULK,
        "yes": ORDER_MANAGEMENT_BULK,
        "y": ORDER_MANAGEMENT_BULK,
        "1": ORDER_MANAGEMENT_BULK,
        "bulk_replace": ORDER_MANAGEMENT_BULK_REPLACE,
        "bulk-replace": ORDER_MANAGEMENT_BULK_REPLACE,
        "bulk replace": ORDER_MANAGEMENT_BULK_REPLACE,
        "replace": ORDER_MANAGEMENT_BULK_REPLACE,
    }
    if isinstance(value, bool):
        return ORDER_MANAGEMENT_BULK if value else ORDER_MANAGEMENT_SINGLE
    if value is None:
        return ORDER_MANAGEMENT_BULK
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in aliases:
            return aliases[normalized]
    raise ValueError(
        f"Invalid Ultrade order management mode. Choose one of: {', '.join(ORDER_MANAGEMENT_MODES)}"
    )


def migrate_order_management_mode(values: Any) -> Any:
    if not isinstance(values, dict) or "order_management_mode" in values:
        return values

    legacy_bulk_flag = values.get("use_bulk_order_endpoints")
    if legacy_bulk_flag is None:
        return values

    migrated_values = dict(values)
    migrated_values["order_management_mode"] = validate_order_management_mode(legacy_bulk_flag)
    return migrated_values


class UltradeConfigMap(BaseConnectorConfigMap):
    connector: str = "ultrade"
    ultrade_trading_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade trading key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_wallet_address: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade login wallet address",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_mnemonic_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade Algorand mnemonic or EVM private key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_company_id: SecretStr = Field(
        # default="27",
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade CompanyID",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_api_url: SecretStr = Field(
        # default="https://api.ultrade.org",
        # default="https://secure-api.ultrade.org",
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade connecting API URL",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    use_bulk_order_endpoints: bool = Field(
        default=True,
        json_schema_extra={
            "prompt": "Enable Ultrade bulk order endpoints? (true/false)",
            "is_secure": False,
            "is_connect_key": False,
            "prompt_on_new": False,
        }
    )
    order_management_mode: OrderManagementMode = Field(
        default=ORDER_MANAGEMENT_BULK,
        json_schema_extra={
            "prompt": "Ultrade order management mode (single_order/bulk_order/bulk_replace)",
            "is_secure": False,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    bulk_order_max_batch: int = Field(
        default=6,
        json_schema_extra={
            "prompt": "Maximum orders per Ultrade bulk request (default 6)",
            "is_secure": False,
            "is_connect_key": True,
            "prompt_on_new": False,
        }
    )
    model_config = ConfigDict(title="ultrade")

    @model_validator(mode="before")
    @classmethod
    def migrate_order_management_mode(cls, values: Any) -> Any:
        return migrate_order_management_mode(values)

    @field_validator("order_management_mode", mode="before")
    @classmethod
    def validate_order_management_mode(cls, value: Any) -> str:
        return validate_order_management_mode(value)

    #@field_validator("ultrade_trading_key", mode="before")
    #@classmethod
    def check_trading_key(cls, v: str):
        is_trading_key_valid = is_valid_algorand_address(v)
        if not is_trading_key_valid and len(v) > 0:
            raise ValueError("Invalid Ultrade Trading Key provided.")
        return v

    #@field_validator("ultrade_wallet_address", mode="before")
    #@classmethod
    def check_wallet_address(cls, v: str, values):
        wallet_address = v
        is_valid = check_is_wallet_address_valid(wallet_address)
        if not is_valid:
            raise ValueError(
                f"Invalid Ultrade Wallet Address provided. "
                f"Please provide a valid {'/'.join(WALLET_VALIDATORS.keys())} Wallet Address"
            )
        return v

    #@field_validator("ultrade_mnemonic_key", mode="before")
    #@classmethod
    def check_mnemonic(cls, v: str, values):
        mnemonic_or_key = v

        algorand_ok = AlgorandMnemonicValidator().IsValid(mnemonic_or_key)

        evm_ok = False
        mk = mnemonic_or_key.strip().lower()
        if mk.startswith("0x"):
            mk = mk[2:]
        if re.match(r"^[0-9a-f]{64}$", mk):
            evm_ok = True

        if not (algorand_ok or evm_ok):
            raise ValueError(
                "Invalid Ultrade Algorand Mnemonic or EVM Private Key provided."
            )
        return v
    

KEYS = UltradeConfigMap.construct()

OTHER_DOMAINS = ["ultrade_testnet", "ultrade_dev4"]
OTHER_DOMAINS_PARAMETER = {"ultrade_testnet": "testnet", "ultrade_dev4": "dev4"}
OTHER_DOMAINS_EXAMPLE_PAIR = {"ultrade_testnet": "SOL-USDC", "ultrade_dev4": "AMAX-USDC"}
OTHER_DOMAINS_DEFAULT_FEES = {"ultrade_testnet": DEFAULT_FEES, "ultrade_dev4": DEFAULT_FEES}


class UltradeTestnetConfigMap(BaseConnectorConfigMap):
    connector: str = "ultrade_testnet"
    ultrade_trading_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade TestNet trading key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_wallet_address: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade TestNet login wallet address",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_mnemonic_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade TestNet Algorand mnemonic or EVM private key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_company_id: SecretStr = Field(
        # default="27",
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade TextNet CompanyID",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_api_url: SecretStr = Field(
        # default="https://api.testnet.ultrade.org",
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade TestNet connecting API URL",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    use_bulk_order_endpoints: bool = Field(
        default=True,
        json_schema_extra={
            "prompt": "Enable Ultrade bulk order endpoints? (true/false)",
            "is_secure": False,
            "is_connect_key": False,
            "prompt_on_new": False,
        }
    )
    order_management_mode: OrderManagementMode = Field(
        default=ORDER_MANAGEMENT_BULK,
        json_schema_extra={
            "prompt": "Ultrade order management mode (single_order/bulk_order/bulk_replace)",
            "is_secure": False,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    bulk_order_max_batch: int = Field(
        default=6,
        json_schema_extra={
            "prompt": "Maximum orders per Ultrade bulk request (default 6)",
            "is_secure": False,
            "is_connect_key": True,
            "prompt_on_new": False,
        }
    )
    model_config = ConfigDict(title="ultrade_testnet")

    @model_validator(mode="before")
    @classmethod
    def migrate_order_management_mode(cls, values: Any) -> Any:
        return migrate_order_management_mode(values)

    @field_validator("order_management_mode", mode="before")
    @classmethod
    def validate_order_management_mode(cls, value: Any) -> str:
        return validate_order_management_mode(value)

    #@field_validator("ultrade_trading_key", mode="before")
    #@classmethod
    def check_trading_key(cls, v: str):
        is_trading_key_valid = is_valid_algorand_address(v)
        if not is_trading_key_valid and len(v) > 0:
            raise ValueError("Invalid Ultrade Testnet Trading Key provided.")
        return v

    #@field_validator("ultrade_wallet_address", mode="before")
    #@classmethod
    def check_wallet_address(cls, v: str, values):
        wallet_address = v
        is_valid = check_is_wallet_address_valid(wallet_address)
        if not is_valid:
            raise ValueError(
                f"Invalid Ultrade Testnet Wallet Address provided. "
                f"Please provide a valid {'/'.join(WALLET_VALIDATORS.keys())} Wallet Address"
            )
        return v

    #@field_validator("ultrade_mnemonic_key", mode="before")
    #@classmethod
    def check_mnemonic(cls, v: str, values):
        mnemonic_or_key = v

        algorand_ok = AlgorandMnemonicValidator().IsValid(mnemonic_or_key)

        evm_ok = False
        mk = mnemonic_or_key.strip().lower()
        if mk.startswith("0x"):
            mk = mk[2:]
        if re.match(r"^[0-9a-f]{64}$", mk):
            evm_ok = True

        if not (algorand_ok or evm_ok):
            raise ValueError(
                "Invalid Ultrade Testnet Algorand Mnemonic or EVM Private Key provided."
            )
        return v


class UltradeDev4ConfigMap(BaseConnectorConfigMap):
    connector: str = "ultrade_dev4"
    ultrade_trading_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade Dev4 trading key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_wallet_address: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade Dev4 login wallet address",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_mnemonic_key: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Ultrade Dev4 Algorand mnemonic or EVM private key",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_company_id: SecretStr = Field(
        default="1",
        json_schema_extra={
            "prompt": "Enter your Ultrade Dev4 CompanyID",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    ultrade_api_url: SecretStr = Field(
        default=DEV4_API_URL,
        json_schema_extra={
            "prompt": "Enter your Ultrade Dev4 connecting API URL",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    use_bulk_order_endpoints: bool = Field(
        default=True,
        json_schema_extra={
            "prompt": "Enable Ultrade bulk order endpoints? (true/false)",
            "is_secure": False,
            "is_connect_key": False,
            "prompt_on_new": False,
        }
    )
    order_management_mode: OrderManagementMode = Field(
        default=ORDER_MANAGEMENT_BULK,
        json_schema_extra={
            "prompt": "Ultrade order management mode (single_order/bulk_order/bulk_replace)",
            "is_secure": False,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )
    bulk_order_max_batch: int = Field(
        default=6,
        json_schema_extra={
            "prompt": "Maximum orders per Ultrade bulk request (default 6)",
            "is_secure": False,
            "is_connect_key": True,
            "prompt_on_new": False,
        }
    )
    model_config = ConfigDict(title="ultrade_dev4")

    @model_validator(mode="before")
    @classmethod
    def migrate_order_management_mode(cls, values: Any) -> Any:
        return migrate_order_management_mode(values)

    @field_validator("order_management_mode", mode="before")
    @classmethod
    def validate_order_management_mode(cls, value: Any) -> str:
        return validate_order_management_mode(value)


OTHER_DOMAINS_KEYS = {
    "ultrade_testnet": UltradeTestnetConfigMap.construct(),
    "ultrade_dev4": UltradeDev4ConfigMap.construct(),
}
