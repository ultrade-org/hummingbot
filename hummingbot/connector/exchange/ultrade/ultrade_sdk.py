
import base64
import json
from typing import Any, Dict, List, Optional, Tuple, Union

from algosdk import account, constants, mnemonic
from algosdk.future import transaction
from algosdk.v2client import algod
from algosdk.v2client.algod import AlgodClient
from test_credentials import TEST_ALGOD_ADDRESS, TEST_ALGOD_TOKEN, TEST_MNEMONIC_KEY

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
            txnGroup = []

            # sender_address = None
            if self.mnemonic:
                key = mnemonic.to_private_key(self.mnemonic)
                sender_address = account.address_from_private_key(key)
            else:
                sender_address = order.sender

            address = account.address_from_private_key(key)
            params = self._get_transaction_params()

            contract_address = self.client.application_info(order.get("app_id"))

            account_info = self.get_balance_and_state(address)
            #print("account_info", account_info)
            if self._is_asset_opted_in(account_info.get("balances"), order["base_asset_index"]) is False:
                print("asset is not oted in")
                self._opt_in_asset(sender_address, order["base_asset_index"])
            if self._is_asset_opted_in(account_info.get("balances"), order["price_asset_index"]) is False:
                print("price_asset_index is not opted in")
                self._opt_in_asset(sender_address, order["price_asset_index"])

            if self._is_app_opted_in(order.app_id, sender_address) is False:
                print("app is not opted in")
                self._opt_in_app(order.app_id, sender_address)

            # confirmed_txn = transaction.wait_for_confirmation(algod_client, txid, 4)
            asset_index = order.base_asset_index or order.price_asset_index  # todo replace
            self.make_transfer_transaction(asset_index, order.transfer_amount, sender_address, contract_address)
            self.call_app(asset_index, [], sender_address, order.app_id)

            if self.mnemonic:
                pass
            else:
                print("return")
                return
        else:
            raise "You need to specify mnemonic or signer to execute method"

    def call_app(self, asset_index, app_args, sender_address, app_id):
        suggested_params = self._get_transaction_params()
        accounts = []
        # foreign_apps = []
        # foreign_assets = [asset_index]
        # params.flat_fee = True
        # params.fee = constants.MIN_TXN_FEE
        # foreign_apps, foreign_assets
        txn = transaction.ApplicationNoOpTxn(sender_address, suggested_params, app_id, app_args, accounts)

        signed_txn = txn.sign(self.client_secret)
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

    def make_transfer_transaction(self, assetIndex, transferAmount, appAddress):
        txn_payment = None
        suggested_params = self._get_transaction_params()
        if transferAmount <= 0:
            return txn_payment

        print("Sending a transaction")
        txn = transaction.AssetTransferTxn(
            order.sender,
            self._get_transaction_params(),
            appAddress,
            order.transfer_amount,
            assetIndex
        )
        signed_txn = txn.sign(self.client_secret)
        self.client.send_transaction(signed_txn)

        if assetIndex == 0:
            txn_payment
        else:
            txn_payment

    def _encode_app_args(self, side, type, price, quantity, partnerAppId):
        return []

    def get_balance_and_state(self, address) -> Dict[str, int]:
        balances: Dict[str, int] = dict()

        account_info = self.client.account_info(address)

        # set key 0 to Algo balance
        balances[0] = account_info["amount"]

        assets: List[Dict[str, Any]] = account_info.get("assets", [])
        for asset in assets:
            asset_id = asset["asset-id"]
            amount = asset["amount"]
            balances[asset_id] = amount

        return {"balances": balances, "local_state": account_info.get('apps-local-state')}

    def _is_asset_opted_in(self, balances: Dict[str, str], asset_id: int):
        for key in balances:
            if key == str(asset_id):
                return True
        return False

    def _opt_in_asset(self, sender, asset_id):
        if asset_id:
            key = self._get_private_key()

            txn_group = [transaction.AssetTransferTxn(
                sender,
                self._get_transaction_params(),
                sender,
                0,
                asset_id)]

            return self.send_transaction("opt_in", [txn.sign(key) for txn in txn_group])
        else:
            # asa_id = 0 - which means ALGO
            pass

    def _is_app_opted_in(self, app_id: int, account_address):
        account_info = self.client.account_info(account_address)
        for a in account_info.get('apps-local-state', []):
            if a['id'] == app_id:
                return True
        return False

    def _opt_in_app(self, app_id: int, sender_address):
        txn = transaction.ApplicationOptInTxn(
            sender_address,
            self._get_transaction_params(),
            app_id
        )
        signed_txn = txn.sign(self.client_secret)
        tx_id = self.client.send_transaction(signed_txn)
        self.wait_for_transaction(tx_id)

    def _get_transaction_params(self):
        return self.client.suggested_params()

    def _get_private_key(self):
        mnemonic.to_private_key(self.mnemonic)

    def send_transaction(self, name, signed_group):
        print(f"Sending Transaction for {name}")
        txid = self.client.send_transactions(signed_group)
        response = self.wait_for_transaction(txid)
        print("LOGS:", response.logs)
        print("LOGINTS:", response.logints)
        return response

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


creds = {"mnemonic": TEST_MNEMONIC_KEY}
opts = {"network": "testnet", "algo_sdk_client": algod_client, "api_url": None}

ultradeSdk = UltradeSDK(creds, opts)
order = {
    "app_id": 92958457,  # algo-usdt
    "side": 'S',
    "type": "0",
    "quantity": 10,
    "price": 800,
    "transfer_amount": 10,
    "base_asset_index": 0,
    "price_asset_index": 81981957,
    "sender": address,
    "partner_app_id": "87654321"
}
ultradeSdk.create_order(order)
