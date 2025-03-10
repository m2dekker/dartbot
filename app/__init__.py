from flask import Flask
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Global API clients and mode
live_api = None
testnet_api = None
active_mode = "testnet"  # Default to testnet

def create_app():
    global live_api, testnet_api
    app = Flask(__name__)
    
    # Set the secret key for session management
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "a_default_secret_key_please_change_me")
    
    # Bybit API credentials
    testnet_api_key = os.getenv("BYBIT_TESTNET_API_KEY")
    testnet_api_secret = os.getenv("BYBIT_TESTNET_API_SECRET")
    live_api_key = os.getenv("BYBIT_LIVE_API_KEY")
    live_api_secret = os.getenv("BYBIT_LIVE_API_SECRET")
    
    if not testnet_api_key or not testnet_api_secret:
        logger.error("Testnet API_KEY or API_SECRET not set in environment variables.")
        raise ValueError("Please set BYBIT_TESTNET_API_KEY and BYBIT_TESTNET_API_SECRET in .env")
    
    # Initialize API clients
    from .bybit_api import BybitAPI
    testnet_api = BybitAPI(api_key=testnet_api_key, api_secret=testnet_api_secret, testnet=True)
    live_api = BybitAPI(api_key=live_api_key, api_secret=live_api_secret, testnet=False) if live_api_key and live_api_secret else None
    
    if not live_api:
        logger.warning("Live API credentials not provided; only testnet mode available.")
    
    # Register blueprints
    from .routes import bp
    app.register_blueprint(bp)
    
    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)