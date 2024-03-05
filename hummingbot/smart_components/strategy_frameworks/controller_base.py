from abc import ABC
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel

from hummingbot.data_feed.candles_feed.candles_factory import CandlesConfig, CandlesFactory
from hummingbot.smart_components.strategy_frameworks.data_types import OrderLevel


class ControllerConfigBase(BaseModel):
    exchange: str
    trading_pair: str
    strategy_name: str
    candles_config: List[CandlesConfig]
    order_levels: List[OrderLevel]
    close_price_trading_pair: Optional[str]


class ControllerBase(ABC):
    """
    Abstract base class for controllers.
    """

    def get_balance_required_by_order_levels(self):
        """
        Get the balance required by the order levels.
        """
        pass

    def __init__(self,
                 config: ControllerConfigBase,
                 excluded_parameters: Optional[List[str]] = None):
        """
        Initialize the ControllerBase.

        :param config: Configuration for the controller.
        :param mode: Mode of the controller (LIVE or other modes).
        :param excluded_parameters: List of parameters to exclude from status formatting.
        """
        self.config = config
        self._excluded_parameters = excluded_parameters or ["order_levels", "candles_config"]
        self.candles = self.initialize_candles(config.candles_config)
        self.close_price_trading_pair = config.close_price_trading_pair or config.trading_pair

    def get_processed_data(self):
        """
        Get the processed data.
        """
        pass

    def filter_executors_df(self, df):
        """
        In case that you are running the multiple controllers in the same script, you should implement this method
        to recognize the executors that belongs to this controller.
        """
        return df

    def initialize_candles(self, candles_config: List[CandlesConfig]):
        return [CandlesFactory.get_candle(candles_config) for candles_config in candles_config]

    def get_close_price(self, trading_pair: str):
        """
        Gets the close price of the last candlestick.
        """
        candles = self.get_candles_by_trading_pair(trading_pair)
        first_candle = list(candles.values())[0]
        return Decimal(first_candle.candles_df["close"].iloc[-1])

    def get_candles_by_trading_pair(self, trading_pair: str):
        """
        Gets all the candlesticks with the given trading pair.
        """
        candles = {}
        for candle in self.candles:
            if candle._trading_pair == trading_pair:
                candles[candle.interval] = candle
        return candles

    def get_candles_by_connector_trading_pair(self, connector: str, trading_pair: str):
        """
        Gets all the candlesticks with the given connector and trading pair.
        """
        candle_name = f"{connector}_{trading_pair}"
        return self.get_candles_dict()[candle_name]

    def get_candle(self, connector: str, trading_pair: str, interval: str):
        """
        Gets the candlestick with the given connector, trading pair and interval.
        """
        return self.get_candles_by_connector_trading_pair(connector, trading_pair)[interval]

    def get_candles_dict(self) -> dict:
        candles = {candle.name: {} for candle in self.candles}
        for candle in self.candles:
            candles[candle.name][candle.interval] = candle
        return candles

    @property
    def all_candles_ready(self):
        """
        Checks if the candlesticks are full.
        """
        return all([candle.is_ready for candle in self.candles])

    def start(self) -> None:
        """
        Start the controller.
        """
        for candle in self.candles:
            candle.start()

    def load_historical_data(self, data_path: str):
        for candle in self.candles:
            candle.load_candles_from_csv(data_path)

    def stop(self) -> None:
        """
        Stop the controller.
        """
        for candle in self.candles:
            candle.stop()

    def get_csv_prefix(self) -> str:
        """
        Get the CSV prefix based on the strategy name.

        :return: CSV prefix string.
        """
        return f"{self.config.strategy_name}"

    def to_format_status(self) -> list:
        """
        Format and return the status of the controller.

        :return: Formatted status string.
        """
        lines = []
        lines.extend(["\n################################ Controller Config ################################"])
        for parameter, value in self.config.dict().items():
            if parameter not in self._excluded_parameters:
                lines.extend([f"     {parameter}: {value}"])
        return lines
