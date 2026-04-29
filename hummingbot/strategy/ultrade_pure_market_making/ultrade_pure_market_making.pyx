import logging
from decimal import Decimal

from libc.stdint cimport int64_t

from hummingbot.core.data_type.common import TradeType
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.strategy.pure_market_making.pure_market_making cimport PureMarketMakingStrategy
from hummingbot.strategy.strategy_base cimport StrategyBase
from hummingbot.strategy.utils import order_age


ultrade_pmm_logger = None


cdef class UltradePureMarketMakingStrategy(PureMarketMakingStrategy):
    """
    Full Pure Market Making strategy with an Ultrade-specific refresh path.

    The proposal generation and modifiers are inherited from PMM. When the
    connector is configured with order_management_mode=bulk_replace, refreshes
    emit cancel/create intents in the same tick so the Ultrade connector can
    collapse matched levels into SDK replace_orders calls.
    """

    @classmethod
    def logger(cls):
        global ultrade_pmm_logger
        if ultrade_pmm_logger is None:
            ultrade_pmm_logger = logging.getLogger(__name__)
        return ultrade_pmm_logger

    cdef c_tick(self, double timestamp):
        StrategyBase.c_tick(self, timestamp)

        cdef:
            int64_t current_tick = <int64_t>(timestamp // self._status_report_interval)
            int64_t last_tick = <int64_t>(self._last_timestamp // self._status_report_interval)
            bint should_report_warnings = ((current_tick > last_tick) and
                                           (self._logging_options & self.OPTION_LOG_STATUS_REPORT))
            object proposal
            bint handled_by_replace
        try:
            if not self._all_markets_ready:
                self._all_markets_ready = all([market.ready for market in self._sb_markets])
                if self._asset_price_delegate is not None and self._all_markets_ready:
                    self._all_markets_ready = self._asset_price_delegate.ready
                if not self._all_markets_ready:
                    if should_report_warnings:
                        self.logger().warning("Markets are not ready. No market making trades are permitted.")
                    return

            if should_report_warnings:
                if not all([market.network_status is NetworkStatus.CONNECTED for market in self._sb_markets]):
                    self.logger().warning("WARNING: Some markets are not connected or are down at the moment. Market "
                                          "making may be dangerous when markets or networks are unstable.")

            proposal = None
            if self._create_timestamp <= self._current_timestamp:
                proposal = self.c_create_base_proposal()
                self.c_apply_order_levels_modifiers(proposal)
                self.c_apply_order_price_modifiers(proposal)
                self.c_apply_order_size_modifiers(proposal)
                self.c_apply_budget_constraint(proposal)

                if not self._take_if_crossed:
                    self.c_filter_out_takers(proposal)

            self._hanging_orders_tracker.process_tick()

            handled_by_replace = self.c_try_execute_replace_refresh(proposal)
            if not handled_by_replace:
                self.c_cancel_active_orders_on_max_age_limit()
                self.c_cancel_active_orders(proposal)
                self.c_cancel_orders_below_min_spread()
                if self.c_to_create_orders(proposal):
                    self.c_execute_orders_proposal(proposal)
        finally:
            self._last_timestamp = timestamp

    cdef bint c_try_execute_replace_refresh(self, object proposal):
        cdef:
            list active_orders
            list active_buy_prices
            list active_sell_prices
            list proposal_buys
            list proposal_sells
            int active_buys
            int active_sells
            int replacement_count

        if proposal is None:
            return False
        if not self.c_connector_uses_bulk_replace():
            return False
        if len(self._sb_order_tracker.in_flight_pending_created) > 0 or len(self._sb_order_tracker.in_flight_cancels) > 0:
            return True
        if self._cancel_timestamp > self._current_timestamp:
            return False

        active_orders = [
            order for order in self.active_non_hanging_orders
            if not self._hanging_orders_tracker.is_potential_hanging_order(order)
        ]
        if len(active_orders) == 0:
            return False

        if not self.c_replace_refresh_is_forced(active_orders):
            if self._order_refresh_tolerance_pct >= 0:
                active_buy_prices = [Decimal(str(o.price)) for o in active_orders if o.is_buy]
                active_sell_prices = [Decimal(str(o.price)) for o in active_orders if not o.is_buy]
                proposal_buys = [buy.price for buy in proposal.buys]
                proposal_sells = [sell.price for sell in proposal.sells]
                if self.c_is_within_tolerance(active_buy_prices, proposal_buys) and \
                        self.c_is_within_tolerance(active_sell_prices, proposal_sells):
                    return False

        active_buys = len([order for order in active_orders if order.is_buy])
        active_sells = len(active_orders) - active_buys
        replacement_count = min(active_buys, len(proposal.buys)) + min(active_sells, len(proposal.sells))
        self.logger().info(
            f"({self.trading_pair}) Replacing {replacement_count} PMM levels via Ultrade bulk replace "
            f"from {len(active_orders)} active non-hanging orders.")

        self._hanging_orders_tracker.update_strategy_orders_with_equivalent_orders()
        for order in active_orders:
            self.c_cancel_order(self._market_info, order.client_order_id)

        self.c_execute_orders_proposal(proposal)
        return True

    cdef bint c_connector_uses_bulk_replace(self):
        return getattr(self._market_info.market, "_order_management_mode", None) == "bulk_replace"

    cdef bint c_replace_refresh_is_forced(self, list active_orders):
        return self.c_has_orders_over_max_age(active_orders) or self.c_has_orders_below_min_spread(active_orders)

    cdef bint c_has_orders_over_max_age(self, list active_orders):
        if len(active_orders) == 0:
            return False
        return any(order_age(order, self._current_timestamp) > self._max_order_age for order in active_orders)

    cdef bint c_has_orders_below_min_spread(self, list active_orders):
        cdef:
            object price = self.get_price()
            object spread
            int negation

        if price == 0:
            return False

        for order in active_orders:
            negation = -1 if order.is_buy else 1
            spread = (negation * (order.price - price) / price)
            if spread < self._minimum_spread:
                return True
        return False
