from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, flash
from . import live_api, testnet_api, active_mode, logger
from .utils import get_summary_stats
import os
from functools import wraps

bp = Blueprint('main', __name__)

# Global symbol states
live_symbol = None
paper_symbol = None

# Webhook request counter
webhook_count = 0

# Bot configuration storage
class BotConfig:
    def __init__(self, name, dca_enabled=False):
        self.name = name
        self.dca_enabled = dca_enabled
        if not dca_enabled:  # Bot 1
            self.order_type = "market"  # "market" or "limit"
            self.stop_loss_percent = 10
            self.take_profit_targets = [{"percent": 5, "sell_percent": 100}]
            self.trades = {}  # {symbol: {"qty": qty, "entry_price": price, "status": "Running"}}
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

bots = {
    "Bot1": BotConfig("Bot1", dca_enabled=False),
    "Bot2": BotConfig("Bot2", dca_enabled=True)
}

# Helper to get the active API
def get_active_api():
    return testnet_api if active_mode == "testnet" else live_api

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('main.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == os.getenv("APP_USERNAME") and password == os.getenv("APP_PASSWORD"):
            session['logged_in'] = True
            next_page = request.args.get("next") or url_for('main.index')
            logger.info("Successful login for user: %s", username)
            return redirect(next_page)
        else:
            logger.warning("Failed login attempt for user: %s", username)
            flash("Invalid username or password")
    return render_template("login.html")

@bp.route("/logout")
def logout():
    logger.info("User logged out")
    session.pop('logged_in', None)
    return redirect(url_for('main.login'))

@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    global live_symbol
    api = get_active_api()
    if request.method == "POST":
        symbol = request.form.get("symbol").strip().upper()
        symbols = api.get_available_symbols()
        if symbol in symbols or not symbols:
            live_symbol = symbol
            logger.info("Symbol set to: %s", live_symbol)
    summary_stats = get_summary_stats(api)
    return render_template("index.html", symbol=live_symbol, summary_stats=summary_stats, mode=active_mode)

@bp.route("/place_order", methods=["POST"])
@login_required
def place_order():
    global live_symbol
    api = get_active_api()
    if not live_symbol:
        logger.warning("No symbol set for order placement")
        return redirect(url_for("main.index"))
    
    order_type = request.form.get("order_type")
    qty = float(request.form.get("qty"))
    price = request.form.get("price")
    
    if order_type == "market_buy":
        response = api.place_market_order(live_symbol, "Buy", qty)
    elif order_type == "market_sell":
        response = api.place_market_order(live_symbol, "Sell", qty)
    elif order_type == "limit_buy":
        response = api.place_limit_order(live_symbol, "Buy", qty, float(price))
    elif order_type == "limit_sell":
        response = api.place_limit_order(live_symbol, "Sell", qty, float(price))
    else:
        response = "Invalid order type"
        logger.warning("Invalid order type: %s", order_type)
    
    logger.info("Order placed: %s, %s, qty: %s, price: %s, response: %s", order_type, live_symbol, qty, price, response)
    summary_stats = get_summary_stats(api)
    return render_template("index.html", symbol=live_symbol, response=response, summary_stats=summary_stats, mode=active_mode)

@bp.route("/overview", methods=["GET", "POST"])
@login_required
def overview():
    global active_mode
    api = get_active_api()
    open_orders = api.get_open_orders() or []
    positions = api.get_positions() or []
    summary_stats = get_summary_stats(api)
    
    # Monitor Bot 1 trades
    bot1 = bots["Bot1"]
    for symbol, trade in list(bot1.trades.items()):
        if trade["status"] == "Running":
            try:
                current_price = float(api.get_ticker(symbol)["last_price"])
                entry_price = trade["entry_price"]
                qty = trade["qty"]
                # Take-profit
                for tp in bot1.take_profit_targets:
                    if current_price >= entry_price * (1 + tp["percent"] / 100):
                        api.place_market_order(symbol, "Sell", qty * (tp["sell_percent"] / 100))
                        logger.info("Bot1 TP hit for %s: sold %s at %s", symbol, qty, current_price)
                        del bot1.trades[symbol]  # Remove trade
                        break
                # Stop-loss
                if current_price <= entry_price * (1 - bot1.stop_loss_percent / 100):
                    api.place_market_order(symbol, "Sell", qty)
                    logger.info("Bot1 SL hit for %s: sold %s at %s", symbol, qty, current_price)
                    del bot1.trades[symbol]
            except Exception as e:
                logger.error("Error monitoring Bot1 trade for %s: %s", symbol, str(e))
    
    # Monitor Bot 2 DCA
    bot2 = bots["Bot2"]
    if bot2.status == "Activated" and bot2.symbol:
        symbol_orders = [o for o in open_orders if o.get("symbol") == bot2.symbol]
        symbol_positions = [p for p in positions if p.get("symbol") == bot2.symbol and float(p.get("size", 0)) > 0]
        if not symbol_orders and not symbol_positions:
            logger.info("No open orders or positions for %s, resetting Bot2", bot2.symbol)
            bot2.status = "Not Activated"
            bot2.total_qty = 0
            bot2.dca_orders_placed = 0
            bot2.symbol = None
            bot2.entry_price = None
        else:
            try:
                current_price = float(api.get_ticker(bot2.symbol)["last_price"])
                if current_price >= bot2.entry_price * (1 + bot2.take_profit_targets[0]["percent"] / 100):
                    api.cancel_all_orders(symbol=bot2.symbol)
                    api.place_market_order(bot2.symbol, "Sell", bot2.total_qty)
                    logger.info("Bot2 TP hit for %s: sold %s at %s", bot2.symbol, bot2.total_qty, current_price)
                    bot2.status = "Not Activated"
                    bot2.total_qty = 0
                    bot2.dca_orders_placed = 0
                    bot2.symbol = None
                    bot2.entry_price = None
                elif current_price <= bot2.entry_price * (1 - bot2.stop_loss_percent / 100):
                    api.cancel_all_orders(symbol=bot2.symbol)
                    api.place_market_order(bot2.symbol, "Sell", bot2.total_qty)
                    logger.info("Bot2 SL hit for %s: sold %s at %s", bot2.symbol, bot2.total_qty, current_price)
                    bot2.status = "Not Activated"
                    bot2.total_qty = 0
                    bot2.dca_orders_placed = 0
                    bot2.symbol = None
                    bot2.entry_price = None
            except Exception as e:
                logger.error("Error monitoring Bot2 for %s: %s", bot2.symbol, str(e))
    
    # Handle configuration updates
    if request.method == "POST":
        bot_name = request.form.get("bot_name")
        if bot_name in bots:
            bot = bots[bot_name]
            if bot_name == "Bot1":
                bot.order_type = request.form.get("order_type", "market")
                bot.stop_loss_percent = float(request.form.get("stop_loss_percent", 10))
                bot.take_profit_targets = [{"percent": float(request.form.get("tp_percent", 5)), "sell_percent": float(request.form.get("tp_sell_percent", 100))}]
            elif bot_name == "Bot2":
                bot.order_type = request.form.get("order_type", "market")
                bot.amount_per_trade = request.form.get("amount_per_trade", "10")
                bot.stop_loss_percent = float(request.form.get("stop_loss_percent", 20))
                bot.max_dca_orders = int(request.form.get("max_dca_orders", 5))
                bot.price_deviation = float(request.form.get("price_deviation", 1))
                bot.order_size_multiplier = float(request.form.get("order_size_multiplier", 2))
                bot.price_deviation_multiplier = float(request.form.get("price_deviation_multiplier", 2))
                bot.take_profit_targets = [{"percent": float(request.form.get("tp_percent", 1)), "sell_percent": float(request.form.get("tp_sell_percent", 100))}]
            logger.info("Bot %s configured: %s", bot_name, vars(bot))
    
    logger.info("Overview accessed: %d open orders, %d positions", len(open_orders), len(positions))
    return render_template("overview.html", open_orders=open_orders, positions=positions, summary_stats=summary_stats, bots=bots, mode=active_mode)

@bp.route("/switch_mode", methods=["POST"])
@login_required
def switch_mode():
    global active_mode
    if live_api is None:
        logger.warning("Cannot switch to live mode: Live API credentials not provided")
        return redirect(url_for("main.overview"))
    
    new_mode = request.form.get("mode")
    if new_mode in ["testnet", "live"]:
        active_mode = new_mode
        logger.info("Switched to %s mode", active_mode)
        # Reset bots
        bots["Bot1"].trades.clear()
        bots["Bot2"].status = "Not Activated"
        bots["Bot2"].total_qty = 0
        bots["Bot2"].dca_orders_placed = 0
        bots["Bot2"].symbol = None
        bots["Bot2"].entry_price = None
    return redirect(url_for("main.overview"))

@bp.route("/panic", methods=["POST"])
@login_required
def panic():
    logger.info("Panic action initiated")
    return render_template("panic_confirm.html")

@bp.route("/panic/confirm", methods=["POST"])
@login_required
def panic_confirm():
    api = get_active_api()
    pin = request.form.get("pin")
    expected_pin = os.getenv("PANIC_PIN")
    logger.info("Panic confirmation attempt with PIN: %s", pin)
    if request.form.get("confirm") == "yes" and pin == expected_pin:
        result = api.cancel_all_orders()
        logger.info("Panic executed successfully: %s", result)
        bots["Bot1"].trades.clear()
        bots["Bot2"].status = "Not Activated"
        bots["Bot2"].total_qty = 0
        bots["Bot2"].dca_orders_placed = 0
        bots["Bot2"].symbol = None
        bots["Bot2"].entry_price = None
        open_orders = api.get_open_orders() or []
        positions = api.get_positions() or []
        summary_stats = get_summary_stats(api)
        return render_template("overview.html", open_orders=open_orders, positions=positions, panic_result=result, summary_stats=summary_stats, bots=bots, mode=active_mode)
    elif pin != expected_pin:
        logger.warning("Invalid PIN attempt for panic: %s", pin)
        return render_template("panic_confirm.html", error="Invalid PIN")
    logger.info("Panic action canceled")
    return redirect(url_for("main.overview"))

@bp.route("/papertrading", methods=["GET", "POST"])
@login_required
def papertrading():
    global paper_symbol
    if request.method == "POST":
        symbol = request.form.get("symbol").strip().upper()
        symbols = testnet_api.get_available_symbols()
        if symbol in symbols or not symbols:
            paper_symbol = symbol
            logger.info("Paper trading symbol set to: %s", paper_symbol)
    summary_stats = get_summary_stats(testnet_api)
    return render_template("papertrading.html", symbol=paper_symbol, summary_stats=summary_stats, mode=active_mode)

@bp.route("/place_paper_order", methods=["POST"])
@login_required
def place_paper_order():
    global paper_symbol
    if not paper_symbol:
        logger.warning("No symbol set for paper order placement")
        return redirect(url_for("main.papertrading"))
    
    order_type = request.form.get("order_type")
    qty = float(request.form.get("qty"))
    price = request.form.get("price")
    
    if order_type == "market_buy":
        response = testnet_api.place_market_order(paper_symbol, "Buy", qty)
    elif order_type == "market_sell":
        response = testnet_api.place_market_order(paper_symbol, "Sell", qty)
    elif order_type == "limit_buy":
        response = testnet_api.place_limit_order(paper_symbol, "Buy", qty, float(price))
    elif order_type == "limit_sell":
        response = testnet_api.place_limit_order(paper_symbol, "Sell", qty, float(price))
    else:
        response = "Invalid order type"
        logger.warning("Invalid paper order type: %s", order_type)
    
    logger.info("Paper order placed: %s, %s, qty: %s, price: %s, response: %s", order_type, paper_symbol, qty, price, response)
    summary_stats = get_summary_stats(testnet_api)
    return render_template("papertrading.html", symbol=paper_symbol, response=response, summary_stats=summary_stats, mode=active_mode)

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

@bp.route("/webhook", methods=["POST"])
def webhook():
    global webhook_count
    api = get_active_api()
    data = request.get_json()
    
    webhook_count += 1
    log_data = {k: v if k != "secret" else "****" for k, v in (data or {}).items()}
    logger.info("Webhook request #%d received: %s", webhook_count, log_data)
    
    if not data:
        logger.warning("No JSON data received in webhook request #%d", webhook_count)
        return jsonify({"error": "No JSON data received"}), 400
    
    symbol = data.get("symbol")
    price = data.get("price")
    qty = data.get("quantity")
    action = data.get("action", "").lower()
    secret = data.get("secret")
    bot_name = data.get("bot", "Bot1")
    
    expected_secret = os.getenv("WEBHOOK_SECRET")
    if not secret or secret != expected_secret:
        logger.warning("Invalid or missing secret token in webhook request #%d", webhook_count)
        return jsonify({"error": "Invalid or missing secret token"}), 403
    
    if not all([symbol, price, qty]) or action not in ["buy", "sell"]:
        logger.warning("Missing or invalid parameters in webhook request #%d: %s", webhook_count, log_data)
        return jsonify({"error": "Missing or invalid parameters. Required: symbol, price, quantity, action='buy' or 'sell'"}), 400
    
    try:
        price = float(price)
        qty = float(qty)
    except (ValueError, TypeError):
        logger.warning("Price or quantity not numbers in webhook request #%d: %s", webhook_count, log_data)
        return jsonify({"error": "Price and quantity must be numbers"}), 400
    
    symbols = api.get_available_symbols()
    if symbol not in symbols and symbols:
        logger.warning("Invalid symbol in webhook request #%d: %s", webhook_count, symbol)
        return jsonify({"error": f"Invalid symbol: {symbol}"}), 400
    
    bot = bots.get(bot_name, bots["Bot1"])
    try:
        if bot_name == "Bot1":
            if action == "buy":
                if bot.order_type == "market":
                    response = api.place_market_order(symbol, "Buy", qty)
                else:
                    response = api.place_limit_order(symbol, "Buy", qty, price)
                bot.trades[symbol] = {"qty": qty, "entry_price": price, "status": "Running"}
                logger.info("Bot1 %s buy for %s: qty=%s at %s", bot.order_type, symbol, qty, price)
            elif action == "sell":
                if symbol in bot.trades:
                    trade = bot.trades[symbol]
                    if bot.order_type == "market":
                        response = api.place_market_order(symbol, "Sell", trade["qty"])
                    else:
                        response = api.place_limit_order(symbol, "Sell", trade["qty"], price)
                    del bot.trades[symbol]
                    logger.info("Bot1 %s sell for %s: qty=%s at %s", bot.order_type, symbol, trade["qty"], price)
                else:
                    return jsonify({"error": f"No active trade for {symbol} to sell"}), 400
            return jsonify({"status": "success", "message": f"{action.capitalize()} order placed for {qty} {symbol} at {price}", "response": response})
        else:  # Bot2
            if action == "buy":
                if bot.status == "Not Activated":
                    response = api.place_market_order(symbol, "Buy", qty)
                    bot.entry_price = price
                    bot.total_qty = qty
                    bot.dca_orders_placed = 0
                    bot.symbol = symbol
                    bot.status = "Activated"
                    logger.info("Bot2 initial buy for %s: qty=%s at %s", symbol, qty, price)
                    place_safety_orders(bot, symbol, price, qty)
                    return jsonify({"status": "success", "message": f"DCA started for {qty} {symbol} at {price} with {bot.max_dca_orders} safety orders", "response": response})
                else:
                    logger.warning("Bot2 already activated for %s", bot.symbol)
                    return jsonify({"error": "Bot2 is already activated for another trade"}), 400
            elif action == "sell":
                logger.warning("Sell action not supported for Bot2 DCA via webhook")
                return jsonify({"error": "Sell action not supported for Bot2 DCA"}), 400
    except Exception as e:
        logger.error("Failed to process webhook request #%d: %s", webhook_count, str(e))
        return jsonify({"error": f"Failed to process webhook: {str(e)}"}), 500