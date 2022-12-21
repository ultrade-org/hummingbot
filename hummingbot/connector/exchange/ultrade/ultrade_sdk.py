from typing import Any, Dict, List, Optional, Tuple, Union
from random import random

from algosdk import account, constants, mnemonic
from algosdk.future import transaction
from algosdk.v2client import algod
from algosdk.v2client.algod import AlgodClient
from test_credentials import TEST_ALGOD_ADDRESS, TEST_ALGOD_TOKEN, TEST_MNEMONIC_KEY
from algosdk.logic import get_application_address

key = mnemonic.to_private_key(TEST_MNEMONIC_KEY)
address = account.address_from_private_key(key)

algod_client = algod.AlgodClient(TEST_ALGOD_TOKEN, TEST_ALGOD_ADDRESS)
account_info = algod_client.account_info(address)


class UltradeSDK ():

    def __init__(self,
                 auth_credentials: Dict[str, Any],
                 options: Dict[str, Any]
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

        self.client: AlgodClient = options.get("algo_sdk_client")
        self.websocket_url: Optional[str] = options.get("websocket_url")
        self.mnemonic: Optional[str] = auth_credentials.get("mnemonic")
        self.signer: Optional[Dict] = auth_credentials.get("signer")
        self.client_secret: Optional[str] = auth_credentials.get("client_secret")
        self.company: Optional[str] = auth_credentials.get("company")
        self.client_id: Optional[str] = auth_credentials.get("client_id")

    def subscribe(self):
        pass

    def unsubscribe(self):
        pass

    def create_order(self, order):
        if self.mnemonic or self.signer:
            if self.mnemonic:
                key = mnemonic.to_private_key(self.mnemonic)
                sender_address = account.address_from_private_key(key)
            else:
                sender_address = order["sender"]
                raise "Signer not implemented"

            account_info = self.get_balance_and_state(sender_address)

            if self._is_asset_opted_in(account_info.get("balances"), order["base_asset_index"]) is False:
                self._opt_in_asset(sender_address, order["base_asset_index"])

            if self._is_asset_opted_in(account_info.get("balances"), order["price_asset_index"]) is False:
                self._opt_in_asset(sender_address, order["price_asset_index"])

            if self._is_app_opted_in(order["app_id"], sender_address) is False:
                self._opt_in_app(order["app_id"], sender_address)

            app_args = self._construct_args_for_app_call(order["side"], order["type"], order["price"], order["quantity"], order["partner_app_id"])

            asset_index = order["base_asset_index"] if order["side"] == "S" else order["price_asset_index"]
            self.make_transfer_transaction(asset_index, order["transfer_amount"], order)
            self.call_app(asset_index, app_args, sender_address, order["app_id"])
        else:
            raise "You need to specify mnemonic or signer to execute this method"

    def call_app(self, asset_index, app_args, sender_address, app_id):
        print("Calling the application...")

        suggested_params = self._get_transaction_params()
        accounts = []
        foreign_apps = []
        foreign_assets = [asset_index]

        txn = transaction.ApplicationNoOpTxn(sender_address, suggested_params, 92958595, app_args, accounts, foreign_apps, foreign_assets, str(random()))
        key = self._get_private_key()

        signed_txn = txn.sign(key)
        tx_id = signed_txn.transaction.get_txid()
        self.client.send_transactions([signed_txn])

        try:
            transaction_response = transaction.wait_for_confirmation(self.client, tx_id, 5)
            print("TXID: ", tx_id)
            print("Result confirmed in round: {}".format(transaction_response['confirmed-round']))

        except Exception as err:
            print(err)
            return
        print("Application called")

    def make_transfer_transaction(self, asset_index, transfer_amount, order):
        if transfer_amount <= 0:
            return

        print("Sending a transfer transaction", asset_index)
        if asset_index == 0:
            # txn_args = [
            #     order["sender"],
            #     self._get_transaction_params(),
            #     get_application_address(int(order["app_id"])),
            # ]

            txn = transaction.AssetTransferTxn(
                order["sender"],
                self._get_transaction_params(),
                get_application_address(int(order["app_id"])),
                transfer_amount,
                asset_index
            )
        else:
            txn = transaction.AssetTransferTxn(
                order["sender"],
                self._get_transaction_params(),
                get_application_address(int(order["app_id"])),
                order["transfer_amount"],
                asset_index
            )

        key = self._get_private_key()
        signed_txn = txn.sign(key)
        self.client.send_transaction(signed_txn)

    def _construct_args_for_app_call(self, side, type, price, quantity, partnerAppId):
        args = ["new_order", side, price, quantity, type, partnerAppId]
        return args

    def get_balance_and_state(self, address) -> Dict[str, int]:
        balances: Dict[str, int] = dict()

        account_info = self.client.account_info(address)

        balances[0] = account_info["amount"]

        assets: List[Dict[str, Any]] = account_info.get("assets", [])
        for asset in assets:
            asset_id = asset["asset-id"]
            amount = asset["amount"]
            balances[asset_id] = amount

        return {"balances": balances, "local_state": account_info.get('apps-local-state')}

    def _is_asset_opted_in(self, balances: Dict[str, str], asset_id: int):
        for key in balances:
            if str(key) == str(asset_id):
                print(f"asset {asset_id} is opted in")
                return True
        print(f"asset {asset_id} is not opted in")
        return False

    def _opt_in_asset(self, sender, asset_id):
        if asset_id:
            key = self._get_private_key()

            txn = transaction.AssetTransferTxn(
                sender,
                self._get_transaction_params(),
                sender,
                0,
                asset_id)
            signed_txn = txn.sign(key)

            return self.client.send_transaction(signed_txn)
        else:
            # asa_id = 0 - which means ALGO
            pass

    def _is_app_opted_in(self, app_id: int, account_address):
        account_info = self.client.account_info(account_address)
        for a in account_info.get('apps-local-state', []):
            if str(a['id']) == str(app_id):
                print("app is opted in")
                return True
        print("app is not opted in")
        return False

    def _opt_in_app(self, app_id: int, sender_address):
        txn = transaction.ApplicationOptInTxn(
            sender_address,
            self._get_transaction_params(),
            app_id
        )
        key = self._get_private_key()
        signed_txn = txn.sign(key)

        tx_id = self.client.send_transaction(signed_txn)
        self.wait_for_transaction(tx_id)

    def _get_transaction_params(self):
        return self.client.suggested_params()

    def _get_private_key(self):
        return mnemonic.to_private_key(self.mnemonic)

    def wait_for_transaction(
        self, tx_id: str, timeout: int = 10
    ):
        last_status = self.client.status()
        last_round = last_status["last-round"]
        start_round = last_round

        while last_round < start_round + timeout:
            pending_txn = self.client.pending_transaction_info(tx_id)

            if pending_txn.get("confirmed-round", 0) > 0:
                return pending_txn

            if pending_txn["pool-error"]:
                raise Exception("Pool error: {}".format(pending_txn["pool-error"]))

            last_status = self.client.status_after_block(last_round + 1)

            last_round += 1

        raise Exception(
            "Transaction {} not confirmed after {} rounds".format(tx_id, timeout)
        )

    def cancel_order():
        pass


creds = {"mnemonic": TEST_MNEMONIC_KEY}
opts = {"network": "testnet", "algo_sdk_client": algod_client, "api_url": None}

ultradeSdk = UltradeSDK(creds, opts)
order = {
    "app_id": "92958457",  # algo-usdt
    "side": 'S',
    "type": "0",
    "quantity": 350000000,
    "price": 800,
    "transfer_amount": 350000000,
    "base_asset_index": 0,
    "price_asset_index": 81981957,
    "sender": address,
    "partner_app_id": "87654321"
}
ultradeSdk.create_order(order)
