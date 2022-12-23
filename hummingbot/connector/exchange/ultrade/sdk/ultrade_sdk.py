from random import random
from typing import Any, Dict, List, Optional, Tuple, Union
import requests

from algosdk import account, constants, mnemonic
from algosdk.future import transaction
from algosdk.logic import get_application_address
from algosdk.v2client import algod
from algosdk.v2client.algod import AlgodClient
from test_credentials import TEST_ALGOD_ADDRESS, TEST_ALGOD_TOKEN, TEST_MNEMONIC_KEY

from algod_service import AlgodService
import utils


class Client ():

    def __init__(self,
                 auth_credentials: Dict[str, Any],
                 options: Dict[str, Any]
                 ):
        if options["network"] == "mainnet":
            self.server = ''
            self.api_url = ""
        elif options["network"] == "testnet":
            self.api_url = "https://dev-apigw.ultradedev.net"
            self.server = 'https://node.testnet.algoexplorerapi.io'
        else:
            self.api_url = "http://localhost:5001"
            self.server = 'http://localhost:4001'

        if options["api_url"] is not None:
            self.api_url = options["api_url"]

        self.client = AlgodService(options.get("algo_sdk_client"), auth_credentials.get("mnemonic"))
        self.websocket_url: Optional[str] = options.get("websocket_url")
        self.mnemonic: Optional[str] = auth_credentials.get("mnemonic")
        self.signer: Optional[Dict] = auth_credentials.get("signer")
        self.client_secret: Optional[str] = auth_credentials.get("client_secret")
        self.company: Optional[str] = auth_credentials.get("company")
        self.client_id: Optional[str] = auth_credentials.get("client_id")

    def connect():
        pass

    def subscribe(self):
        pass

    def unsubscribe(self):
        pass

    def new_order(self, order, on_complete=None):
        if not self.mnemonic:
            raise "You need to specify mnemonic or signer to execute this method"

        key = self.client.get_private_key()
        sender_address = account.address_from_private_key(key)

        unsigned_txns = []
        account_info = self.client.get_balance_and_state(sender_address)

        if utils.is_asset_opted_in(account_info.get("balances"), order["base_asset_index"]) is False:
            unsigned_txns.append(self.client.opt_in_asset(sender_address, order["base_asset_index"]))

        if utils.is_asset_opted_in(account_info.get("balances"), order["price_asset_index"]) is False:
            unsigned_txns.append(self.client.opt_in_asset(sender_address, order["price_asset_index"]))

        if utils.is_app_opted_in(order["app_id"], account_info.get("local_state")) is False:
            unsigned_txns.append(self.client.opt_in_app(order["app_id"], sender_address))

        app_args = utils.construct_args_for_app_call(order["side"], order["type"], order["price"], order["quantity"], order["partner_app_id"])
        asset_index = order["base_asset_index"] if order["side"] == "S" else order["price_asset_index"]

        if asset_index == 0:
            unsigned_txns.append(self.client.make_payment_txn(order))
        else:
            unsigned_txns.append(self.client.make_transfer_txn(asset_index, order))

        unsigned_txns.append(self.client.make_app_call_txn(asset_index, app_args, sender_address, order["app_id"]))

        txn_group = transaction.assign_group_id(unsigned_txns)
        signed_txns = self.client.sign_transaction_grp(txn_group)
        tx_id = self.client.send_transaction_grp(signed_txns)

        print(f"Order created successfully, order_id: {tx_id}")

    def cancel_order(self, order_id, on_complete=None):
        if not self.mnemonic:
            raise "You need to specify mnemonic or signer to execute this method"

        key = self.client.get_private_key()
        sender_address = account.address_from_private_key(key)

        data = self.get_order_by_id(order_id)

        order = data[0]
        params = self.client.get_transaction_params()

        app_args = ["cancel_order", order["orders_id"], order["slot"]]
        accounts = [sender_address]
        foreign_apps = []
        foreign_assets = [order["price_id"]]

        txn = transaction.ApplicationNoOpTxn(sender_address,
                                             params,
                                             order["application_id"],
                                             app_args,
                                             accounts,
                                             foreign_apps,
                                             foreign_assets)

        signed_txn = self.client.sign_transaction_grp(txn)
        tx_id = self.client.send_transaction_grp(signed_txn)

        if not on_complete:
            return

        # response = [wait_for_transaction(client, tx_id) for tx_id in ids]
        # print(f" >> second txn log >> {response[1].logs}")

    def cancel_all_orders():
        pass

    def get_order_by_id(self, order_id):
        url = f"{self.api_url}/market/getOrderById?orderId={order_id}"
        res = requests.get(url).json()
        if not len(res["order"]):
            raise "Order not found"
        return res["order"]

    def get_open_orders():
        pass

    def get_orders():
        pass
