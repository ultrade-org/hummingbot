from typing import Any, Dict, List, Optional, Tuple, Union


def is_asset_opted_in(balances: Dict[str, str], asset_id: int):
    for key in balances:
        if str(key) == str(asset_id):
            print(f"asset {asset_id} is opted in")
            return True
    print(f"asset {asset_id} is not opted in")
    return False


def is_app_opted_in(app_id: int, app_local_state):
    for a in app_local_state:
        if str(a['id']) == str(app_id):
            print("app is opted in")
            return True
    print("app is not opted in")
    return False


def construct_args_for_app_call(side, type, price, quantity, partnerAppId):
    args = ["new_order", side, price, quantity, type, partnerAppId]
    return args
