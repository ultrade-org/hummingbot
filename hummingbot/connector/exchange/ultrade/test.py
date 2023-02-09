import hashlib
import hmac
import time
import json
import ujson
import datetime
import aiohttp
import asyncio
import websockets
from base64 import b64decode, b64encode
from algosdk.v2client import algod
from ultrade.sdk_client import Client as UltradeClient
from ultrade import api as ultrade_api


# constants
mnemonic = "fix unfold end strike team detail route cheese end shine brave view wage main avocado enroll future notable hazard west remain soft order about globe"
address = "7MKAO5BJHJN5GBL4ZIEIIXYYUE7FYORUKCBIWEWLSPWPVXTXBYO525MWPQ"
partner_app_id = "92138200"
pair = "ALGO-USDC"





async def main():

    # should not leave algod_address empty!!
    algod_client = algod.AlgodClient("", "https://node.testnet.algoexplorerapi.io")
    options = {
        "network": "testnet",
        "algo_sdk_client": algod_client,
        "api_url": None,
        "websocket_url": "wss://testnet-ws.ultradedev.net/socket.io"
    }

    credentials = {"mnemonic": mnemonic}

    client = UltradeClient(credentials, options)

    print(json.dumps(client._get_balance_and_state(), indent=4))

    try:
        result = await client.get_wallet_transactions("algo_usdc")
        print(json.dumps(result, indent=4))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

    try:
        result = await client.get_balances("algo_usdc")
        print(json.dumps(result, indent=4))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

    try:
        result = await ultrade_api.get_pair_list(partner_app_id)
        print(json.dumps(result, indent=4))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

    try:
        result = await ultrade_api.get_exchange_info("algo_usdc")
        print(json.dumps(result, indent=4))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

    try:
        result = await ultrade_api.get_price("algo_usdc")
        print(json.dumps(result, indent=4))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

    try:
        result = await ultrade_api.get_depth("algo_usdc")
        print(json.dumps(result, indent=4))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

    # try:
    #     balances = await client._get_encoded_balance(address, partner_app_id)
    #     print(json.dumps(balances, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')


asyncio.run(main())
