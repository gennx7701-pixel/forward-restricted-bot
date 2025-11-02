import os

# Bot token @Botfather
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7285068108:AAE0J9EsQUwGQtygNbcYu78p-LVK_Yt3sdc")

# Your API ID from my.telegram.org
API_ID = int(os.environ.get("API_ID", "26605094"))

# Your API Hash from my.telegram.org
API_HASH = os.environ.get("API_HASH", "5d8bfdc71c2ae67fb636be3e0ef85936")

# Your Owner / Admin Id For Broadcast 
ADMINS = int(os.environ.get("ADMINS", "1791345486"))

# Your Mongodb Database Url
# Warning - Give Db uri in deploy server environment variable, don't give in repo.
DB_URI = os.environ.get("DB_URI", "mongodb+srv://rajrph54_db_user:pEN1GikquWKlDcGZ@cluster0.evnmi8x.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0") # Warning - Give Db uri in deploy server environment variable, don't give in repo.
DB_NAME = os.environ.get("DB_NAME", "idfinderpro")

# Force Subscription Channel
FORCE_SUB_CHANNEL = "idfinderpro"  # Channel username without @
FORCE_SUB_CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1002441460670"))

# If You Want Error Message In Your Personal Message Then Turn It True Else If You Don't Want Then Flase
ERROR_MESSAGE = bool(os.environ.get('ERROR_MESSAGE', True))
