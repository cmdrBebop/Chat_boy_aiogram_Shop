import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CRYPTO_PAY_TOKEN = os.environ.get('CRYPTO_PAY_TOKEN')

# Список Админов ID
ADMINS = []

FREE_DELIVERY_THRESHOLD = 2500
DELIVERY_COST = 300
MINIMAL_CART = 1000
