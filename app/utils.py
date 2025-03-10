import logging

logger = logging.getLogger(__name__)

def get_summary_stats(bybit_api):
    try:
        open_orders_list = bybit_api.get_open_orders()
        open_orders = len(open_orders_list) if open_orders_list is not None else "Error fetching orders"
        
        positions_list = bybit_api.get_positions()
        wallet_balances = bybit_api.get_wallet_balance()
        spot_balances = len([coin for coin in wallet_balances if float(coin["walletBalance"]) > 0]) if wallet_balances else 0
        open_positions = len(positions_list) if positions_list else spot_balances
        
        unrealized_pnl = sum(float(pos["unrealised_pnl"]) for pos in positions_list) if positions_list else 0
        unrealized_pnl = round(unrealized_pnl, 2) if unrealized_pnl else "N/A"
        
        return {
            "open_orders": open_orders,
            "open_positions": open_positions,
            "unrealized_pnl": unrealized_pnl
        }
    except Exception as e:
        logger.error(f"Exception in get_summary_stats: {str(e)}")
        return {"open_orders": f"Error: {str(e)}", "open_positions": "Error", "unrealized_pnl": "Error"}