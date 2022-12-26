
from random import random
from typing import Any, Dict, List, Optional, Tuple, Union

from algosdk import account, constants, mnemonic
from algosdk.future import transaction
from algosdk.logic import get_application_address
from algosdk.v2client.algod import AlgodClient


class AlgodService:
    def __init__(self, client, mnemonic=None):
        self.client: AlgodClient = client
        self.mnemonic: str = mnemonic

    def make_app_call_txn(self, asset_index, app_args, sender_address, app_id):
        print("Preparing application call txn...")

        suggested_params = self.get_transaction_params()
        accounts = []
        foreign_apps = []
        foreign_assets = [asset_index]

        txn = transaction.ApplicationNoOpTxn(sender_address,
                                             suggested_params,
                                             app_id,
                                             app_args,
                                             accounts,
                                             foreign_apps,
                                             foreign_assets,
                                             str(random()))

        return txn

    def make_transfer_txn(self, asset_index, app_id, sender, transfer_amount):

        if transfer_amount <= 0:
            return

        print(f"Sending a transfer transaction #{asset_index}...")

        txn = transaction.AssetTransferTxn(
            sender,
            self.get_transaction_params(),
            get_application_address(int(app_id)),
            transfer_amount,
            asset_index
        )

        return txn

    def make_payment_txn(self, app_id, sender, transfer_amount):
        print("Sending a payment transaction...")

        rcv = get_application_address(int(app_id))
        receiver = rcv[0] if isinstance(rcv, list) else rcv

        txn = transaction.PaymentTxn(
            sender=sender,
            sp=self.get_transaction_params(),
            note=str(random()),
            receiver=receiver,
            amt=transfer_amount)

        return txn

    def opt_in_asset(self, sender, asset_id):
        if asset_id:
            txn = transaction.AssetTransferTxn(
                sender,
                self.get_transaction_params(),
                sender,
                0,
                asset_id)

            return txn
        else:
            # asa_id = 0 - which means ALGO
            pass

    def opt_in_app(self, app_id: int, sender_address):
        txn = transaction.ApplicationOptInTxn(
            sender_address,
            self.get_transaction_params(),
            app_id
        )

        return txn

    def get_transaction_params(self):
        return self.client.suggested_params()

    def get_private_key(self):
        if not self._check_is_mnemonic_valid():
            raise "An error occurred when trying to get private key from mnemonic"

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

    def sign_transaction_grp(self, txn_group) -> List:
        txn_group = txn_group if isinstance(txn_group, list) else [txn_group]
        txn_group = transaction.assign_group_id(txn_group)

        key = self.get_private_key()
        signed_txns = [txn.sign(key) for txn in txn_group]

        return signed_txns

    def send_transaction_grp(self, signed_group):
        print("Sending Transaction grp...")
        txid = self.client.send_transactions(signed_group)
        response = self.wait_for_transaction(txid)
        print("LOGS:", response.get("logs", ""))
        print("login's:", response.get("logints", ""))

        return txid

    def get_account_address(self):
        key = self.get_private_key()
        address = account.address_from_private_key(key)
        return address

    def _check_is_mnemonic_valid(self):
        return True  # todo

    def validate_transaction_order(self):
        pass  # todo
