import asyncio
import json

from algosdk.v2client import algod

from ultrade.sdk_client import Client as UltradeClient

# constants
mnemonic = "desert credit remove robot rail violin notice wisdom fly divert kiss pioneer carbon return short chief resemble jealous response twice certain sight slow absorb more"
address = "CTVMMBXKBL772GCJ2DOHPDXKFNQVJ2GQ23PV7Q3FO6NNRR7NMIUPUAKSPM"
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

    # create a taker order
    try:
        order_info = await client.new_order('algo_usdc', 'S', 'L', 2000000, 10000000)
        print(order_info)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

    await asyncio.sleep(15.0)

    # cancel any open orders
    try:
        response = await client.cancel_all_orders('algo_usdc')
        print(json.dumps(response, indent=4))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        print('timeout!')

asyncio.run(main())
