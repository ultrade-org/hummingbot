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


async def ws_client(client, options):
    async def ws_loop(client, options):
        print(client.websocket_url)
        async with websockets.connect("wss://testnet-ws.ultradedev.net/wss") as ws:
            await ws.send(ujson.dumps(options))
            while True:
                print("++++++++++++ WS START ++++++++++++++")
                print("read:", await ws.recv())
                print("+++++++++++++ WS END +++++++++++++++")

    try:
        await ws_loop(client, options)
    except websockets.exceptions.ConnectionClosed as ex:
        print("connection closed", ex)
    except KeyboardInterrupt:
        pass


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

    # try:
    #     result = await client.get_wallet_transactions("algo_usdc")
    #     print(json.dumps(result, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    try:
        result = await client.get_balances("algo_usdc")
        print(json.dumps(result, indent=4))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

    try:
        result = await ultrade_api.get_pair_list()
        print(json.dumps(result, indent=4))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

    try:
        result = await ultrade_api.get_price("algo_usdc")
        print(json.dumps(result, indent=4))
        print(result['bid'])
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

    def ws_callback(event, *args):
        print("++++++++++++ WS MESSAGE ++++++++++++++")
        print(event)
        print(json.dumps(*args, indent=4))
        print("++++++++++++ WS MESSAGE ++++++++++++++")

    from ultrade import socket_options as OPTIONS
    # depth_params = {
    #     'symbol': "algo_usdc",
    #     'streams': [OPTIONS.DEPTH],
    # }
    # order_params = {
    #     'symbol': "algo_usdc",
    #     'streams': [OPTIONS.ORDERS],
    #     'options': {
    #         'address': address,
    #     }
    # }
    trades_params = {
        'symbol': "algo_usdc",
        'streams': [OPTIONS.TRADES],
        'options': {
            'address': address,
        }
    }
    order_book_params = {
        'symbol': "algo_usdc",
        'streams': [OPTIONS.ORDER_BOOK],
    }
    # await ws_client(client, options)
    # await client.subscribe(depth_params, ws_callback)
    # await client.subscribe(order_params, ws_callback)
    await client.subscribe(trades_params, ws_callback)
    await client.subscribe(order_book_params, ws_callback)


    # try:
    #     result = await ultrade_api.get_depth("algo_usdc")
    #     print(json.dumps(result, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # try:
    #     balances = await client._get_encoded_balance(address, partner_app_id)
    #     print(json.dumps(balances, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')


asyncio.run(main())
