import traceback
from pyrogram.types import Message
from pyrogram import Client, filters
from asyncio.exceptions import TimeoutError
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import (
    ApiIdInvalid,
    PhoneNumberInvalid,
    PhoneCodeInvalid,
    PhoneCodeExpired,
    SessionPasswordNeeded,
    PasswordHashInvalid
)
from config import API_ID, API_HASH
from database.db import db

SESSION_STRING_SIZE = 351

@Client.on_message(filters.private & ~filters.forwarded & filters.command(["logout"]))
async def logout(client, message):
    user_data = await db.get_session(message.from_user.id)  
    if user_data is None:
        await message.reply("❌ **You are not logged in!**\n\nUse `/login` to authenticate first.")
        return 
    await db.set_session(message.from_user.id, session=None)  
    await message.reply("✅ **Logged out successfully!**\n\nYour session has been removed. Use `/login` anytime to login again.")

@Client.on_message(filters.private & ~filters.forwarded & filters.command(["login"]))
async def main(bot: Client, message: Message):
    user_data = await db.get_session(message.from_user.id)
    if user_data is not None:
        await message.reply("✅ **You are already logged in!**\n\nFirst use `/logout` to disconnect your current session, then login again.")
        return 
    user_id = int(message.from_user.id)
    phone_number_msg = await bot.ask(chat_id=user_id, text="**📱 Login to Your Account**\n\nPlease send your phone number with country code.\n\n**Example:** `+1234567890`\n\n**Tip:** Send `/cancel` to stop anytime.")
    if phone_number_msg.text=='/cancel':
        return await phone_number_msg.reply('❌ **Login cancelled!**')
    phone_number = phone_number_msg.text
    client = Client(name=":memory:", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await client.connect()
    await phone_number_msg.reply("📨 **Sending OTP...**")
    try:
        code = await client.send_code(phone_number)
        phone_code_msg = await bot.ask(user_id, "**🔐 Enter OTP**\n\nCheck your Telegram account for the OTP code.\n\n**Format:** If OTP is `12345`, send it as `1 2 3 4 5`\n\n**Tip:** Send `/cancel` to stop anytime", filters=filters.text, timeout=600)
    except PhoneNumberInvalid:
        await phone_number_msg.reply('❌ **Invalid phone number!**\n\nPlease check and try again with correct format.')
        return
    if phone_code_msg.text=='/cancel':
        return await phone_code_msg.reply('❌ **Login cancelled!**')
    try:
        phone_code = phone_code_msg.text.replace(" ", "")
        await client.sign_in(phone_number, code.phone_code_hash, phone_code)
    except PhoneCodeInvalid:
        await phone_code_msg.reply('❌ **Invalid OTP!**\n\nPlease try again with correct code.')
        return
    except PhoneCodeExpired:
        await phone_code_msg.reply('⏰ **OTP expired!**\n\nPlease use `/login` to get a new code.')
        return
    except SessionPasswordNeeded:
        two_step_msg = await bot.ask(user_id, '**🔒 Two-Step Verification Detected**\n\nYour account has 2FA enabled. Please enter your password.\n\n**Tip:** Send `/cancel` to stop anytime', filters=filters.text, timeout=300)
        if two_step_msg.text=='/cancel':
            return await two_step_msg.reply('❌ **Login cancelled!**')
        try:
            password = two_step_msg.text
            await client.check_password(password=password)
        except PasswordHashInvalid:
            await two_step_msg.reply('❌ **Invalid password!**\n\nPlease try again.')
            return
    string_session = await client.export_session_string()
    await client.disconnect()
    if len(string_session) < SESSION_STRING_SIZE:
        return await message.reply('❌ **Invalid session string!**\n\nPlease try again.')
    try:
        user_data = await db.get_session(message.from_user.id)
        if user_data is None:
            uclient = Client(name=":memory:", session_string=string_session, api_id=API_ID, api_hash=API_HASH, in_memory=True)
            await uclient.connect()
            await db.set_session(message.from_user.id, session=string_session)
            await uclient.disconnect()
    except Exception as e:
        return await message.reply_text(f"❌ **Login Error:**\n`{e}`\n\nPlease try again or contact support.")
    
    success_msg = """
✅ **Login Successful!**

Your account has been authenticated successfully.

**🎉 You can now:**
• Download restricted content
• Access private channels
• Use batch download feature

**💡 Tip:** If you get AUTH KEY errors, use `/logout` then `/login` again.

**Ready to start?** Just send me any Telegram post link!
"""
    await bot.send_message(message.from_user.id, success_msg)