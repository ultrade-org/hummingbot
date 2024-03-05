import os
from decimal import Decimal
from typing import Dict

from pydantic import Field

from hummingbot.client.config.config_data_types import BaseClientModel, ClientFieldData
from hummingbot.connector.connector_base import ConnectorBase, TradeType
from hummingbot.core.data_type.common import OrderType, PositionAction, PositionSide
from hummingbot.data_feed.candles_feed.candles_factory import CandlesConfig
from hummingbot.smart_components.controllers.trend_follower_v1 import TrendFollowerV1, TrendFollowerV1Config
from hummingbot.smart_components.strategy_frameworks.data_types import (
    ExecutorHandlerStatus,
    OrderLevel,
    TripleBarrierConf,
)
from hummingbot.smart_components.strategy_frameworks.directional_trading.directional_trading_executor_handler import (
    DirectionalTradingExecutorHandler,
)
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class DirectionalTradingTrendFollowerConfig(BaseClientModel):
    script_file_name: str = Field(default_factory=lambda: os.path.basename(__file__))

    # Trading pairs configuration
    exchange: str = Field("binance_perpetual", client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Enter the name of the exchange where the bot will operate (e.g., binance_perpetual):"))
    trading_pairs: str = Field("DOGE-USDT,INJ-USDT", client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "List the trading pairs for the bot to trade on, separated by commas (e.g., BTC-USDT,ETH-USDT):"))
    leverage: int = Field(20, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Set the leverage to use for trading (e.g., 20 for 20x leverage):"))

    # Triple barrier configuration
    stop_loss: Decimal = Field(0.01, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Set the stop loss percentage (e.g., 0.01 for 1% loss):"))
    take_profit: Decimal = Field(0.06, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Enter the take profit percentage (e.g., 0.03 for 3% gain):"))
    time_limit: int = Field(60 * 60 * 24, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Set the time limit in seconds for the triple barrier (e.g., 21600 for 6 hours):"))
    trailing_stop_activation_price_delta: Decimal = Field(0.01, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Enter the activation price delta for the trailing stop (e.g., 0.008 for 0.8%):"))
    trailing_stop_trailing_delta: Decimal = Field(0.004, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Set the trailing delta for the trailing stop (e.g., 0.004 for 0.4%):"))
    open_order_type: str = Field("MARKET", client_data=ClientFieldData(prompt_on_new=False, prompt=lambda mi: "Specify the type of order to open (e.g., MARKET or LIMIT):"))

    # Orders configuration
    order_amount_usd: Decimal = Field(15, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Enter the order amount in USD (e.g., 15):"))
    spread_factor: Decimal = Field(0, client_data=ClientFieldData(prompt_on_new=False, prompt=lambda mi: "Set the spread factor (e.g., 0.5):"))
    order_refresh_time: int = Field(60 * 5, client_data=ClientFieldData(prompt_on_new=False, prompt=lambda mi: "Enter the refresh time in seconds for orders (e.g., 300 for 5 minutes):"))
    cooldown_time: int = Field(15, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Specify the cooldown time in seconds between order placements (e.g., 15):"))

    # Candles configuration
    candles_exchange: str = Field("binance_perpetual", client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Enter the exchange name to fetch candle data from (e.g., binance_perpetual):"))
    candles_interval: str = Field("3m", client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Set the time interval for candles (e.g., 1m, 5m, 1h):"))

    # Controller specific configuration
    sma_fast: int = Field(20, ge=10, le=150, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Enter the SMA fast length (range 10-150, e.g., 20):"))
    sma_slow: int = Field(100, ge=50, le=400, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Set the SMA slow length (range 50-400, e.g., 100):"))
    bb_length: int = Field(100, ge=50, le=200, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Enter the Bollinger Bands length (range 100-200, e.g., 100):"))
    bb_std: float = Field(2.0, ge=2.0, le=3.0, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Set the standard deviation for the Bollinger Bands (range 2.0-3.0, e.g., 2.0):"))
    bb_threshold: float = Field(0.2, ge=0.1, le=0.5, client_data=ClientFieldData(prompt_on_new=True, prompt=lambda mi: "Specify the threshold for the Bollinger Bands as a safety mechanism to don't enter in the market (range 0.1-0.5, e.g., 0.2):"))


class DirectionalTradingTrendFollower(ScriptStrategyBase):

    @classmethod
    def init_markets(cls, config: DirectionalTradingTrendFollowerConfig):
        cls.markets = {config.exchange: set(config.trading_pairs.split(","))}

    def __init__(self, connectors: Dict[str, ConnectorBase], config: DirectionalTradingTrendFollowerConfig):
        super().__init__(connectors)
        self.config = config

        triple_barrier_conf = TripleBarrierConf(
            stop_loss=config.stop_loss,
            take_profit=config.take_profit,
            time_limit=config.time_limit,
            trailing_stop_activation_price_delta=config.trailing_stop_activation_price_delta,
            trailing_stop_trailing_delta=config.trailing_stop_trailing_delta,
            open_order_type=OrderType.MARKET if config.open_order_type == "MARKET" else OrderType.LIMIT,
        )

        order_levels = [
            OrderLevel(level=0, side=TradeType.BUY, order_amount_usd=config.order_amount_usd,
                       spread_factor=config.spread_factor, order_refresh_time=config.order_refresh_time,
                       cooldown_time=config.cooldown_time, triple_barrier_conf=triple_barrier_conf),
            OrderLevel(level=0, side=TradeType.SELL, order_amount_usd=config.order_amount_usd,
                       spread_factor=config.spread_factor, order_refresh_time=config.order_refresh_time,
                       cooldown_time=config.cooldown_time, triple_barrier_conf=triple_barrier_conf),
        ]

        self.controllers = {}
        self.executor_handlers = {}

        for trading_pair in config.trading_pairs.split(","):
            trend_follower_config = TrendFollowerV1Config(
                exchange=config.exchange,
                trading_pair=trading_pair,
                order_levels=order_levels,
                candles_config=[
                    CandlesConfig(connector=config.candles_exchange,
                                  trading_pair=trading_pair,
                                  interval=config.candles_interval,
                                  max_records=config.bb_length + 200),
                ],
                leverage=config.leverage,
                sma_fast=config.sma_fast, sma_slow=config.sma_slow,
                bb_length=config.bb_length, bb_std=config.bb_std, bb_threshold=config.bb_threshold,
            )
            controller = TrendFollowerV1(config=trend_follower_config)
            self.controllers[trading_pair] = controller
            self.executor_handlers[trading_pair] = DirectionalTradingExecutorHandler(strategy=self, controller=controller)

    @property
    def is_perpetual(self):
        """
        Checks if the exchange is a perpetual market.
        """
        return "perpetual" in self.config.exchange

    def on_stop(self):
        if self.is_perpetual:
            self.close_open_positions()

    def close_open_positions(self):
        # we are going to close all the open positions when the bot stops
        for connector_name, connector in self.connectors.items():
            for trading_pair, position in connector.account_positions.items():
                if trading_pair in connector.trading_pairs:
                    if position.position_side == PositionSide.LONG:
                        self.sell(connector_name=connector_name,
                                  trading_pair=position.trading_pair,
                                  amount=abs(position.amount),
                                  order_type=OrderType.MARKET,
                                  price=connector.get_mid_price(position.trading_pair),
                                  position_action=PositionAction.CLOSE)
                    elif position.position_side == PositionSide.SHORT:
                        self.buy(connector_name=connector_name,
                                 trading_pair=position.trading_pair,
                                 amount=abs(position.amount),
                                 order_type=OrderType.MARKET,
                                 price=connector.get_mid_price(position.trading_pair),
                                 position_action=PositionAction.CLOSE)

    def on_tick(self):
        """
        This shows you how you can start meta controllers. You can run more than one at the same time and based on the
        market conditions, you can orchestrate from this script when to stop or start them.
        """
        for executor_handler in self.executor_handlers.values():
            if executor_handler.status == ExecutorHandlerStatus.NOT_STARTED:
                executor_handler.start()

    def format_status(self) -> str:
        if not self.ready_to_trade:
            return "Market connectors are not ready."
        lines = []
        for trading_pair, executor_handler in self.executor_handlers.items():
            if executor_handler.controller.all_candles_ready:
                lines.extend(
                    [f"Strategy: {executor_handler.controller.config.strategy_name} | Trading Pair: {trading_pair}",
                     executor_handler.to_format_status()])
        return "\n".join(lines)
