from test_credentials import TEST_MNEMONIC_KEY, TEST_ALGOD_TOKEN, TEST_ALGOD_ADDRESS
from ultrade_sdk import Client

from algosdk.v2client import algod
from algosdk import account, mnemonic

key = mnemonic.to_private_key(TEST_MNEMONIC_KEY)
address = account.address_from_private_key(key)

algod_client = algod.AlgodClient(TEST_ALGOD_TOKEN, TEST_ALGOD_ADDRESS)

creds = {"mnemonic": TEST_MNEMONIC_KEY}
opts = {"network": "testnet", "algo_sdk_client": algod_client, "api_url": None}

ultrade_sdk = Client(creds, opts)

order_1 = {  # algo-usdt
    "side": 'S',
    "type": "0",
    "quantity": 2000000,
    "price": 800,
    "transfer_amount": 2000000,
    "sender": address,
    "partner_app_id": "87654321"
}

order_2 = {
    # YLDY_STBL
    "side": 'S',
    "type": "0",
    "quantity": 350000000,
    "price": 800,
    "transfer_amount": 350000000,
    "sender": address,
    "partner_app_id": "87654321"
}

order_3 = {
    # algo_usdt
    "side": 'S',
    "type": "0",
    "quantity": 2000000,
    "price": 80000,
    "partner_app_id": "87654321",
    "symbol": 1,
    "dry_run": True,
    "time_in_force": "GTC",
}
# "sender": address,
# "transfer_amount": 2000000,

example_order_id = "SDODRM6GMMPVVWJNYCAIXV7W3EGGOJ3V5PL7XJUKHLDDTQIYG6SA"
symbol = "YLDY_STBL"


ultrade_sdk.new_order(symbol, order_2)
# ultrade_sdk.cancel_order(76660)
