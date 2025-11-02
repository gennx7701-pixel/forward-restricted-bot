from pyrogram import Client
from pyrogram.types import BotCommand
from config import API_ID, API_HASH, BOT_TOKEN

class Bot(Client):

    def __init__(self):
        super().__init__(
            "idfinderpro",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins=dict(root="IdFinderPro"),
            workers=50,
            sleep_threshold=10
        )

      
    async def start(self):
            
        await super().start()
        
        # Set bot commands menu
        await self.set_bot_commands([
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Get help guide"),
            BotCommand("login", "Login with Telegram"),
            BotCommand("logout", "Logout account"),
            BotCommand("settings", "Forward settings"),
            BotCommand("batch", "Batch download"),
            BotCommand("premium", "Premium membership info"),
            BotCommand("redeem", "Redeem premium code"),
            BotCommand("cancel", "Cancel download")
        ])
        
        print('='*50)
        print('RESTRICTED CONTENT DOWNLOAD BOT STARTED')
        print('Made by: Surya (@tataa_sumo)')
        print('Channel: @idfinderpro')
        print('='*50)

    async def stop(self, *args):

        await super().stop()
        print('Bot Stopped Bye')

Bot().run()
