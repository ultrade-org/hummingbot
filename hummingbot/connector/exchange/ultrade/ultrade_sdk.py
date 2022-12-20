
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
            senderAddress = None
            if self.mnemonic:
                key = mnemonic.to_private_key(self.mnemonic)
                sender_address = account.address_from_private_key(key)
            else:
                senderAddress = order.sender

            params = self._get_transaction_params()

            contract_address
            account_info = self.get_balance_and_state()

            if self.is_asset_opted_in(account_info.balances, order.base_asset_index) is False:
                txnGroup
            if self.is_asset_opted_in(account_info.balances, order.base_asset_index) is False:
                txnGroup.append(self.asset_opt_in(sender_address, order.base_asset_index))

            signed_txn = unsigned_txn.sign(key)

            txid = algod_client.send_transaction(signed_txn)
            print("Signed transaction with txID: {}".format(txid))

            try:
                confirmed_txn = transaction.wait_for_confirmation(algod_client, txid, 4)
            except Exception as err:
                print(err)
                return

            print("Transaction information: {}".format(
                json.dumps(confirmed_txn, indent=4)))
            print("Decoded note: {}".format(base64.b64decode(
                confirmed_txn["txn"]["txn"]["note"]).decode()))

            print("Starting Account balance: {} microAlgos".format(account_info.get('amount')))
            print("Amount transferred: {} microAlgos".format(amount))
            print("Fee: {} microAlgos".format(params.fee))

            print("Final Account balance: {} microAlgos".format(account_info.get('amount')) + "\n")
        else:
            raise "You need to specify mnemonic or signer to execute method"

    def _prepare_app_call_transaction(self, suggested_params, asset_index, app_args, sender_address, app_id):
        suggested_params = algod_client.suggested_params()
        accounts = []
        foreign_apps = []
        foreign_assets = [asset_index]
        # params.flat_fee = True
        # params.fee = constants.MIN_TXN_FEE

        txn = transaction.ApplicationNoOpTxn(sender_address, suggested_params, app_id, app_args, accounts, foreign_apps, foreign_assets)

        return txn

    def _prepare_transfer_transaction(self, params, assetIndex, transferAmount, senderAddress, appAddress):
        txn_payment = None
        if transferAmount <= 0:
            return txn_payment

        if assetIndex == 0:
            txn_payment
        else:
            txn_payment

    def _encode_app_args(self, side, type, price, quantity, partnerAppId):
        return []

    def get_balance_and_state(self, account: str) -> Dict[int, int]:
        balances: Dict[int, int] = dict()

        account_info = self.client.account_info(account)

        # set key 0 to Algo balance
        balances[0] = account_info["amount"]

        assets: List[Dict[str, Any]] = account_info.get("assets", [])
        for asset in assets:
            asset_id = asset["asset-id"]
            amount = asset["amount"]
            balances[asset_id] = amount

        return {"balances": balances, "local_state": account_info.get('apps-local-state')}

    def is_asset_opted_in(self, balances: Dict[str, str], asset_id: int):
        for key in balances:
            if key == str(asset_id):
                return True
        return False

    def asset_opt_in(self, sender, asset_id):
        if asset_id:
            key = self._get_private_key()

            txn_group = [transaction.AssetTransferTxn(
                sender.get_address(),
                self._get_transaction_params(),
                sender.get_address(),
                0,
                asset_id)]

            return self.send_transaction("opt_in", [txn.sign(key) for txn in txn_group])
        else:
            # asa_id = 0 - which means ALGO
            pass

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
            "Transaction {} not confirmed after {} rounds".format(txID, timeout)
        )


creds = {"mnemonic": TEST_MNEMONIC_KEY}
opts = {"network": "testnet", "algo_sdk_client": algod_client, "api_url": None}

ultradeSdk = UltradeSDK(creds, opts)
ultradeSdk.transaction(address, key, account_info)
