
import base64
import json

from algosdk import account, constants, mnemonic
from algosdk.future import transaction
from algosdk.v2client import algod

mnemonic_key = ""

key = mnemonic.to_private_key(mnemonic_key)
address = account.address_from_private_key(key)
algod_token = ""
algod_adress = "https://node.testnet.algoexplorerapi.io"
algod_client = algod.AlgodClient(algod_token, algod_adress)
account_info = algod_client.account_info(address)


class UltradeSDK ():

    def __init__(self,
                 auth_credentials,
                 options
                 ):
        if options["network"] == "mainnet":
            self.server = ''
            self.api_url = ""
        elif options["network"] == "testnet":
            self.api_url = "https://testnet-apigw.ultradedev.net"
            self.server = 'https://node.testnet.algoexplorerapi.io'
        else:
            self.api_url = "http://localhost:5001"
            self.server = 'http://localhost:4001'

        if options["api_url"] is not None:
            self.api_url = options["api_url"]

        self.websocketUrl = options["websocket_url"] if "websocket_url" in options else ""
        self.client = options
        self.auth_credentials = auth_credentials

    def send_transaction():
        pass

    def transaction(self, my_address, key, account_info):
        pass


creds = {"mnemonic": mnemonic_key}
opts = {"network": "testnet", "algo_sdk_client": algod_client, "api_url": None}

ultradeSdk = UltradeSDK(creds, opts)
ultradeSdk.transaction(address, key, account_info)
