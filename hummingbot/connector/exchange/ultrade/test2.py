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

    # try:
    #     result = await client.get_balances("algo_usdc")
    #     print(json.dumps(result, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # try:
    #     result = await ultrade_api.get_pair_list()
    #     print(json.dumps(result, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # try:
    #     result = await ultrade_api.get_price("moon_algo")
    #     print(json.dumps(result, indent=4))
    #     print(result['bid'])
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # try:
    #     order_params = {
    #         'symbol': 'algo_usdc',
    #         'side': 'B',
    #         'type': 'LIMIT',
    #         'quantity': 1000000,
    #         'price': 11000000
    #     }
    #     order_info = await client.new_order('algo_usdc', 'S', '0', 1000000, 11000000)
    #     print(order_info)
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # await asyncio.sleep(5.0)

    # try:
    #     result = await client.get_balances("algo_usdc")
    #     print(json.dumps(result, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # try:
    #     result = await client.get_orders("algo_usdc", 0)
    #     print(json.dumps(result, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # try:
    #     result = await client.get_order_by_id("algo_usdc", order_id)
    #     print(json.dumps(result, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # try:
    #     result = await client.cancel_order("algo_usdc", 12064, 60)
    #     print(result)
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # await asyncio.sleep(5.0)

    # try:
    #     result = await client.get_orders("algo_usdc", 0)
    #     print(json.dumps(result, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    # try:
    #     result = await client.get_balances("algo_usdc")
    #     print(json.dumps(result, indent=4))
    # except asyncio.CancelledError:
    #     raise
    # except asyncio.TimeoutError:
    #     print('timeout!')

    def ws_callback(event, *args):
        print("++++++++++++ WS MESSAGE ++++++++++++++")
        print(event)
        print(*args)
        print("++++++++++++ WS MESSAGE ++++++++++++++")

    from ultrade import socket_options as OPTIONS
    depth_params = {
        'symbol': "algo_usdc",
        'streams': [OPTIONS.DEPTH],
        # 'address': client.client.get_account_address()
    }
    await client.subscribe(depth_params, ws_callback)
    # await ws_client(client, options)


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
