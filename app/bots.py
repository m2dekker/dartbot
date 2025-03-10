# bots.py
from . import live_api, testnet_api, active_mode, logger

class BotConfig:
    def __init__(self, name, dca_enabled=False):
        self.name = name
        self.dca_enabled = dca_enabled
        if not dca_enabled:  # Bot 1
            self.order_type = "market"
            self.stop_loss_percent = 10
            self.take_profit_targets = [{"percent": 5, "sell_percent": 100}]
            self.trades = {}
        else:  # Bot 2
            self.order_type = "market"
            self.amount_per_trade = 10
            self.take_profit_targets = [{"percent": 1, "sell_percent": 100}]
            self.stop_loss_percent = 20
            self.max_dca_orders = 5
            self.price_deviation = 1
            self.order_size_multiplier = 2
            self.price_deviation_multiplier = 2
            self.total_qty = 0
            self.dca_orders_placed = 0
            self.symbol = None
            self.entry_price = None
            self.status = "Not Activated"

def get_active_api():
    return testnet_api if active_mode == "testnet" else live_api

bots = {
    "Bot1": BotConfig("Bot1", dca_enabled=False),
    "Bot2": BotConfig("Bot2", dca_enabled=True)
}

def monitor_bot1(bot, api):
    for symbol, trade in list(bot.trades.items()):
        if trade["status"] == "Running":
            try:
                current_price = float(api.get_ticker(symbol)["last_price"])
                entry_price = trade["entry_price"]
                qty = trade["qty"]
                for tp in bot.take_profit_targets:
                    if current_price >= entry_price * (1 + tp["percent"] / 100):
                        api.place_market_order(symbol, "Sell", qty * (tp["sell_percent"] / 100))
                        logger.info("Bot1 TP hit for %s: sold %s at %s", symbol, qty, current_price)
                        del bot.trades[symbol]
                        break
                if current_price <= entry_price * (1 - bot.stop_loss_percent / 100):
                    api.place_market_order(symbol, "Sell", qty)
                    logger.info("Bot1 SL hit for %s: sold %s at %s", symbol, qty, current_price)
                    del bot.trades[symbol]
            except Exception as e:
                logger.error("Error monitoring Bot1 trade for %s: %s", symbol, str(e))

def monitor_bot2(bot, api, open_orders, positions):
    if bot.status == "Activated" and bot.symbol:
        symbol_orders = [o for o in open_orders if o.get("symbol") == bot.symbol]
        symbol_positions = [p for p in positions if p.get("symbol") == bot.symbol and float(p.get("size", 0)) > 0]
        if not symbol_orders and not symbol_positions:
            logger.info("No open orders or positions for %s, resetting Bot2", bot.symbol)
            bot.status = "Not Activated"
            bot.total_qty = 0
            bot.dca_orders_placed = 0
            bot.symbol = None
            bot.entry_price = None
        else:
            try:
                current_price = float(api.get_ticker(bot.symbol)["last_price"])
                if current_price >= bot.entry_price * (1 + bot.take_profit_targets[0]["percent"] / 100):
                    api.cancel_all_orders(symbol=bot.symbol)
                    api.place_market_order(bot.symbol, "Sell", bot.total_qty)
                    logger.info("Bot2 TP hit for %s: sold %s at %s", bot.symbol, bot.total_qty, current_price)
                    bot.status = "Not Activated"
                    bot.total_qty = 0
                    bot.dca_orders_placed = 0
                    bot.symbol = None
                    bot.entry_price = None
                elif current_price <= bot.entry_price * (1 - bot.stop_loss_percent / 100):
                    api.cancel_all_orders(symbol=bot.symbol)
                    api.place_market_order(bot.symbol, "Sell", bot.total_qty)
                    logger.info("Bot2 SL hit for %s: sold %s at %s", bot.symbol, bot.total_qty, current_price)
                    bot.status = "Not Activated"
                    bot.total_qty = 0
                    bot.dca_orders_placed = 0
                    bot.symbol = None
                    bot.entry_price = None
            except Exception as e:
                logger.error("Error monitoring Bot2 for %s: %s", bot.symbol, str(e))

def place_safety_orders(bot, symbol, initial_price, initial_qty):
    api = get_active_api()
    amount = bot.amount_per_trade if isinstance(bot.amount_per_trade, (int, float)) else float(bot.amount_per_trade.strip("%")) / 100 * initial_price
    current_deviation = bot.price_deviation
    
    for i in range(bot.max_dca_orders):
        qty = amount / initial_price * (bot.order_size_multiplier ** i)
        dca_price = initial_price * (1 - current_deviation / 100)
        try:
            response = api.place_limit_order(symbol, "Buy", qty, dca_price)
            bot.total_qty += qty
            bot.dca_orders_placed += 1
            logger.info("Safety order #%d placed for %s: qty=%s at %s, response=%s", i+1, symbol, qty, dca_price, response)
        except Exception as e:
            logger.error("Failed to place safety order #%d for %s: %s", i+1, symbol, str(e))
        current_deviation *= bot.price_deviation_multiplier