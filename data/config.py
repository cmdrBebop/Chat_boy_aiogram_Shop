import os

from dotenv import load_dotenv


load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CRYPTO_PAY_TOKEN = os.environ.get('CRYPTO_PAY_TOKEN')

#Список Админов ID
ADMINS = []