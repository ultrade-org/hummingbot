import json
import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.request import urlopen

from pydantic import Field, field_validator

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import MarketDict, OrderType, PriceType, TradeType
from hummingbot.core.data_type.limit_order import LimitOrder
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase


@dataclass
class OrderPlan:
    replacements: List[Tuple[LimitOrder, OrderCandidate]]
    creates: List[OrderCandidate]
    cancels: List[LimitOrder]
    kept: int

    @property
    def create_candidates(self) -> List[OrderCandidate]:
        return [candidate for _, candidate in self.replacements] + self.creates

    @property
    def cancel_orders(self) -> List[LimitOrder]:
        return [order for order, _ in self.replacements] + self.cancels


class UltradeBulkReplacePMMConfig(StrategyV2ConfigBase):
    script_file_name: str = os.path.basename(__file__)
    controllers_config: List[str] = []

    exchange: str = Field("ultrade_dev4", json_schema_extra={
        "prompt": "Connector to trade on", "prompt_on_new": True})
    trading_pair: str = Field("AVAX-USDC", json_schema_extra={
        "prompt": "Trading pair", "prompt_on_new": True})

    order_amount: Decimal = Field(Decimal("1"), json_schema_extra={
        "prompt": "Order amount per level in base asset", "prompt_on_new": True})
    buy_levels: int = Field(5, json_schema_extra={
        "prompt": "Number of buy levels", "prompt_on_new": True})
    sell_levels: int = Field(5, json_schema_extra={
        "prompt": "Number of sell levels", "prompt_on_new": True})
    bid_spread: Decimal = Field(Decimal("0.02"), json_schema_extra={
        "prompt": "First bid spread as a decimal (0.02 = 2%)", "prompt_on_new": True})
    ask_spread: Decimal = Field(Decimal("0.02"), json_schema_extra={
        "prompt": "First ask spread as a decimal (0.02 = 2%)", "prompt_on_new": True})
    order_level_spread: Decimal = Field(Decimal("0.01"), json_schema_extra={
        "prompt": "Additional spread per level as a decimal", "prompt_on_new": True})
    order_level_amount: Decimal = Field(Decimal("0"), json_schema_extra={
        "prompt": "Additional amount per level in base asset", "prompt_on_new": True})

    order_refresh_time: float = Field(5.0, json_schema_extra={
        "prompt": "Order refresh time in seconds", "prompt_on_new": True})
    replace_tolerance_pct: Decimal = Field(Decimal("0"), json_schema_extra={
        "prompt": "Price/amount tolerance before replacing (0.001 = 0.1%)", "prompt_on_new": True})
    order_type: Literal["LIMIT", "LIMIT_MAKER"] = Field("LIMIT", json_schema_extra={
        "prompt": "Order type (LIMIT/LIMIT_MAKER)", "prompt_on_new": True})

    price_source: Literal["mid", "last", "custom_api"] = Field("mid", json_schema_extra={
        "prompt": "Reference price source (mid/last/custom_api)", "prompt_on_new": True})
    price_source_custom_api: str = Field("", json_schema_extra={
        "prompt": "Custom price API URL, used only when price_source is custom_api", "prompt_on_new": False})
    custom_api_timeout: float = Field(2.0, json_schema_extra={
        "prompt": "Custom price API timeout in seconds", "prompt_on_new": False})

    def update_markets(self, markets: MarketDict) -> MarketDict:
        markets[self.exchange] = markets.get(self.exchange, set()) | {self.trading_pair}
        return markets

    @field_validator("buy_levels", "sell_levels", mode="before")
    @classmethod
    def validate_levels(cls, value: Any) -> int:
        value = int(value)
        if value < 0:
            raise ValueError("Levels must be greater than or equal to 0.")
        return value

    @field_validator("order_amount", "bid_spread", "ask_spread", "order_level_spread", "order_level_amount",
                     "replace_tolerance_pct", mode="before")
    @classmethod
    def validate_decimal(cls, value: Any) -> Decimal:
        return Decimal(str(value))


class UltradeBulkReplacePMM(StrategyV2Base):
    """
    Ultrade-focused PMM script that deliberately emits order updates as a
    proposal diff. When the Ultrade connector is configured with
    order_management_mode=bulk_replace, matched cancel/create pairs are sent
    through the connector's SDK-backed replace endpoint.
    """

    def __init__(self, connectors: Dict[str, ConnectorBase], config: UltradeBulkReplacePMMConfig):
        super().__init__(connectors, config)
        self.config = config
        self._next_refresh_timestamp = 0.0
        self._last_reference_price: Optional[Decimal] = None
        self._last_plan: Optional[OrderPlan] = None
        self._last_action_timestamp = 0.0
        if getattr(self.connector, "_order_management_mode", None) != "bulk_replace":
            self.logger().warning(
                "UltradeBulkReplacePMM is running without connector order_management_mode=bulk_replace; "
                "orders will still be diffed, but the connector may execute them as cancel/create instead of replace.")

    @property
    def connector(self) -> ConnectorBase:
        return self.connectors[self.config.exchange]

    def on_tick(self):
        if self.current_timestamp < self._next_refresh_timestamp:
            return

        reference_price = self.get_reference_price()
        if reference_price is None or reference_price <= 0:
            self.logger().warning(
                f"Skipping Ultrade bulk-replace PMM refresh; invalid reference price: {reference_price}")
            self._next_refresh_timestamp = self.current_timestamp + self.config.order_refresh_time
            return

        proposal = self.create_proposal(reference_price)
        active_orders = self.active_orders_for_pair()
        plan = self.build_order_plan(active_orders, proposal)
        self.execute_order_plan(plan)

        self._last_reference_price = reference_price
        self._last_plan = plan
        self._last_action_timestamp = self.current_timestamp
        self._next_refresh_timestamp = self.current_timestamp + self.config.order_refresh_time

    def get_reference_price(self) -> Optional[Decimal]:
        if self.config.price_source == "custom_api":
            return self.get_custom_api_price()

        price_type = PriceType.LastTrade if self.config.price_source == "last" else PriceType.MidPrice
        price = self.connector.get_price_by_type(self.config.trading_pair, price_type)
        if price is None or price.is_nan():
            return None
        return Decimal(str(price))

    def get_custom_api_price(self) -> Optional[Decimal]:
        if not self.config.price_source_custom_api:
            return None
        try:
            with urlopen(self.config.price_source_custom_api, timeout=self.config.custom_api_timeout) as response:
                body = response.read().decode("utf-8").strip()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = body
            price = self.extract_price_from_payload(payload)
            return Decimal(str(price)) if price is not None else None
        except Exception:
            self.logger().warning("Failed to fetch Ultrade PMM custom reference price.", exc_info=True)
            return None

    @staticmethod
    def extract_price_from_payload(payload: Any) -> Optional[Any]:
        if isinstance(payload, (int, float, str)):
            return payload
        if isinstance(payload, dict):
            for key in ("price", "last", "mid", "value", "result"):
                value = payload.get(key)
                if isinstance(value, dict):
                    nested_value = UltradeBulkReplacePMM.extract_price_from_payload(value)
                    if nested_value is not None:
                        return nested_value
                elif value is not None:
                    return value
        return None

    def create_proposal(self, reference_price: Decimal) -> List[OrderCandidate]:
        candidates: List[OrderCandidate] = []
        order_type = OrderType[self.config.order_type]

        for side, levels, first_spread in (
                (TradeType.BUY, self.config.buy_levels, self.config.bid_spread),
                (TradeType.SELL, self.config.sell_levels, self.config.ask_spread)):
            for level in range(levels):
                spread = first_spread + (self.config.order_level_spread * Decimal(level))
                amount = self.config.order_amount + (self.config.order_level_amount * Decimal(level))
                if side is TradeType.BUY:
                    price = reference_price * (Decimal("1") - spread)
                else:
                    price = reference_price * (Decimal("1") + spread)

                quantized_price = self.connector.quantize_order_price(self.config.trading_pair, price)
                quantized_amount = self.connector.quantize_order_amount(self.config.trading_pair, amount)
                if quantized_price <= 0 or quantized_amount <= 0:
                    continue

                candidates.append(OrderCandidate(
                    trading_pair=self.config.trading_pair,
                    is_maker=True,
                    order_type=order_type,
                    order_side=side,
                    amount=quantized_amount,
                    price=quantized_price,
                ))

        return candidates

    def active_orders_for_pair(self) -> List[LimitOrder]:
        return [
            order for order in self.get_active_orders(connector_name=self.config.exchange)
            if order.trading_pair == self.config.trading_pair
        ]

    def build_order_plan(self, active_orders: List[LimitOrder], proposal: List[OrderCandidate]) -> OrderPlan:
        replacements: List[Tuple[LimitOrder, OrderCandidate]] = []
        creates: List[OrderCandidate] = []
        cancels: List[LimitOrder] = []
        kept = 0

        for is_buy, side in ((True, TradeType.BUY), (False, TradeType.SELL)):
            active_side = sorted(
                [order for order in active_orders if order.is_buy == is_buy],
                key=lambda order: order.price,
                reverse=is_buy,
            )
            proposal_side = sorted(
                [candidate for candidate in proposal if candidate.order_side is side],
                key=lambda candidate: candidate.price,
                reverse=is_buy,
            )

            matched_count = min(len(active_side), len(proposal_side))
            for index in range(matched_count):
                active_order = active_side[index]
                target_order = proposal_side[index]
                if self.orders_equivalent(active_order, target_order):
                    kept += 1
                else:
                    replacements.append((active_order, target_order))

            cancels.extend(active_side[matched_count:])
            creates.extend(proposal_side[matched_count:])

        return OrderPlan(replacements=replacements, creates=creates, cancels=cancels, kept=kept)

    def orders_equivalent(self, active_order: LimitOrder, target_order: OrderCandidate) -> bool:
        price_tolerance = self.relative_difference(active_order.price, target_order.price)
        amount_tolerance = self.relative_difference(active_order.quantity, target_order.amount)
        return (
            price_tolerance <= self.config.replace_tolerance_pct
            and amount_tolerance <= self.config.replace_tolerance_pct
        )

    @staticmethod
    def relative_difference(current: Decimal, target: Decimal) -> Decimal:
        if current == 0:
            return Decimal("Infinity") if target != 0 else Decimal("0")
        return abs(target - current) / abs(current)

    def execute_order_plan(self, plan: OrderPlan):
        if not plan.cancel_orders and not plan.create_candidates:
            return

        if plan.replacements:
            self.logger().info(
                f"({self.config.trading_pair}) Replacing {len(plan.replacements)} levels, "
                f"creating {len(plan.creates)}, canceling {len(plan.cancels)}, keeping {plan.kept}.")

        for order in plan.cancel_orders:
            self.cancel(self.config.exchange, order.trading_pair, order.client_order_id)

        for candidate in plan.create_candidates:
            self.place_order(candidate)

    def place_order(self, order: OrderCandidate) -> Optional[str]:
        if order.order_side is TradeType.BUY:
            return self.buy(
                connector_name=self.config.exchange,
                trading_pair=order.trading_pair,
                amount=order.amount,
                order_type=order.order_type,
                price=order.price,
            )
        if order.order_side is TradeType.SELL:
            return self.sell(
                connector_name=self.config.exchange,
                trading_pair=order.trading_pair,
                amount=order.amount,
                order_type=order.order_type,
                price=order.price,
            )
        return None

    def format_status(self) -> str:
        lines = [super().format_status()]
        if self._last_reference_price is not None:
            lines.extend([
                "",
                "  Ultrade Bulk Replace PMM:",
                f"    Reference price: {self._last_reference_price}",
                f"    Last refresh: {self._last_action_timestamp}",
            ])
        if self._last_plan is not None:
            lines.extend([
                f"    Replacements: {len(self._last_plan.replacements)}",
                f"    Creates: {len(self._last_plan.creates)}",
                f"    Cancels: {len(self._last_plan.cancels)}",
                f"    Kept: {self._last_plan.kept}",
            ])
        return "\n".join(lines)

    def did_fill_order(self, event: OrderFilledEvent):
        msg = (
            f"{event.trade_type.name} {event.amount.normalize()} {event.trading_pair} "
            f"{self.config.exchange} at {event.price.normalize()}"
        )
        self.log_with_clock(logging.INFO, msg)
        self.notify_hb_app_with_timestamp(msg)
