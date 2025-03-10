from pybit.unified_trading import HTTP
import logging

logger = logging.getLogger(__name__)

class BybitAPI:
    def __init__(self, api_key, api_secret, testnet=False):
        self.session = HTTP(testnet=testnet, api_key=api_key, api_secret=api_secret)
    
    def get_available_symbols(self):
        try:
            response = self.session.get_instruments_info(category="spot")
            if response["retCode"] == 0:
                return [instrument["symbol"] for instrument in response["result"]["list"]]
            logger.error(f"Failed to fetch symbols: {response['retMsg']}")
            return []
        except Exception as e:
            logger.error(f"Exception in get_available_symbols: {str(e)}")
            return []
    
    def place_market_order(self, symbol, side, qty):
        try:
            response = self.session.place_order(
                category="spot", symbol=symbol, side=side.capitalize(),
                orderType="Market", qty=str(qty)
            )
            return f"Market {side} order placed: {response}" if response["retCode"] == 0 else f"Error: {response['retMsg']}"
        except Exception as e:
            logger.error(f"Exception in place_market_order: {str(e)}")
            return f"Exception: {e}"
    
    def place_limit_order(self, symbol, side, qty, price):
        try:
            response = self.session.place_order(
                category="spot", symbol=symbol, side=side.capitalize(),
                orderType="Limit", qty=str(qty), price=str(price)
            )
            return f"Limit {side} order placed: {response}" if response["retCode"] == 0 else f"Error: {response['retMsg']}"
        except Exception as e:
            logger.error(f"Exception in place_limit_order: {str(e)}")
            return f"Exception: {e}"
    
    def get_open_orders(self):
        try:
            response = self.session.get_open_orders(category="spot")
            if response["retCode"] == 0:
                return [
                    {"symbol": order["symbol"], "side": order["side"], "order_type": order["orderType"],
                     "qty": order["qty"], "price": order["price"], "order_status": order["orderStatus"]}
                    for order in response["result"]["list"]
                ]
            logger.error(f"Failed to fetch open orders: {response['retMsg']}")
            return []
        except Exception as e:
            logger.error(f"Exception in get_open_orders: {str(e)}")
            return []
    
    def get_positions(self):
        try:
            response = self.session.get_positions(category="linear")
            if response["retCode"] == 0:
                return [
                    {"symbol": pos["symbol"], "side": pos["side"], "size": pos["size"],
                     "entry_price": pos["entryPrice"], "unrealised_pnl": pos["unrealisedPnl"]}
                    for pos in response["result"]["list"] if float(pos["size"]) > 0
                ]
            logger.error(f"Failed to fetch positions: {response['retMsg']}")
            return []
        except Exception as e:
            logger.error(f"Exception in get_positions: {str(e)}")
            return []
    
    def cancel_all_orders(self):
        try:
            response = self.session.cancel_all_orders(category="spot")
            if response["retCode"] == 0:
                return "All open orders cancelled successfully."
            logger.error(f"Failed to cancel orders: {response['retMsg']}")
            return f"Error cancelling orders: {response['retMsg']}"
        except Exception as e:
            logger.error(f"Exception in cancel_all_orders: {str(e)}")
            return f"Exception: {e}"
    
    def get_wallet_balance(self):
        try:
            response = self.session.get_wallet_balance(accountType="SPOT")
            if response["retCode"] == 0:
                return response["result"]["list"][0]["coin"]
            logger.error(f"Failed to fetch wallet balance: {response['retMsg']}")
            return []
        except Exception as e:
            logger.error(f"Exception in get_wallet_balance: {str(e)}")
            return []
    
    def get_historical_data(self, symbol, interval="60", limit=200):
        """Fetch historical OHLCV data for a symbol."""
        try:
            response = self.session.get_kline(
                category="spot",
                symbol=symbol,
                interval=interval,  # 60 for 1-hour timeframe
                limit=limit
            )
            if response["retCode"] == 0:
                return [
                    {
                        "time": int(kline[0]) / 1000,  # Convert ms to seconds
                        "open": float(kline[1]),
                        "high": float(kline[2]),
                        "low": float(kline[3]),
                        "close": float(kline[4]),
                        "volume": float(kline[5])
                    }
                    for kline in response["result"]["list"]
                ]
            logger.error(f"Failed to fetch historical data: {response['retMsg']}")
            return []
        except Exception as e:
            logger.error(f"Exception in get_historical_data: {str(e)}")
            return []