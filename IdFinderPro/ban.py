from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import PeerIdInvalid, UserNotParticipant
from database.db import db
from config import ADMINS


# /ban command - Admin only
@Client.on_message(filters.command("ban") & filters.private)
async def ban_command(client: Client, message: Message):
    """Ban a user from using the bot"""
    user_id = message.from_user.id
    
    # Check if user is admin
    if user_id != ADMINS:
        await message.reply_text("❌ **You are not authorized to use this command.**")
        return
    
    # Parse command: /ban user_id reason
    text = message.text.split(None, 2)
    
    if len(text) < 2:
        await message.reply_text(
            "**Usage:** `/ban user_id [reason]`\n\n"
            "**Example:** `/ban 123456789 Downloading adult content`\n\n"
            "You can get the user ID from the log channel.",
            quote=True
        )
        return
    
    try:
        target_user_id = int(text[1])
    except ValueError:
        await message.reply_text("❌ **Invalid user ID. Please provide a valid numeric ID.**")
        return
    
    # Get reason if provided
    reason = text[2] if len(text) > 2 else "No reason provided"
    
    # Check if already banned
    if await db.is_banned(target_user_id):
        await message.reply_text(f"⚠️ **User `{target_user_id}` is already banned.**")
        return
    
    # Ban the user
    await db.ban_user(target_user_id, reason)
    
    # Try to send notification to the banned user
    notification_sent = False
    try:
        await client.send_message(
            target_user_id,
            "🚫 **You have been banned from using this bot.**\n\n"
            f"**Reason:** {reason}\n\n"
            "⚠️ This may be due to violation of our terms or downloading inappropriate content.\n\n"
            "📩 **Contact admin for unban:** @tataa_sumo"
        )
        notification_sent = True
    except PeerIdInvalid:
        pass  # User never interacted with bot
    except Exception as e:
        pass  # Failed to send, user might have blocked the bot
    
    notification_status = "✅ User notified" if notification_sent else "⚠️ Could not notify user (user may have blocked bot or never started it)"
    
    await message.reply_text(
        f"✅ **User banned successfully!**\n\n"
        f"👤 **User ID:** `{target_user_id}`\n"
        f"📝 **Reason:** {reason}\n\n"
        f"{notification_status}"
    )


# /unban command - Admin only
@Client.on_message(filters.command("unban") & filters.private)
async def unban_command(client: Client, message: Message):
    """Unban a user"""
    user_id = message.from_user.id
    
    # Check if user is admin
    if user_id != ADMINS:
        await message.reply_text("❌ **You are not authorized to use this command.**")
        return
    
    # Parse command: /unban user_id
    text = message.text.split()
    
    if len(text) < 2:
        await message.reply_text(
            "**Usage:** `/unban user_id`\n\n"
            "**Example:** `/unban 123456789`",
            quote=True
        )
        return
    
    try:
        target_user_id = int(text[1])
    except ValueError:
        await message.reply_text("❌ **Invalid user ID. Please provide a valid numeric ID.**")
        return
    
    # Check if user is actually banned
    if not await db.is_banned(target_user_id):
        await message.reply_text(f"⚠️ **User `{target_user_id}` is not banned.**")
        return
    
    # Unban the user
    await db.unban_user(target_user_id)
    
    # Try to send notification to the unbanned user
    notification_sent = False
    try:
        await client.send_message(
            target_user_id,
            "✅ **You have been unbanned!**\n\n"
            "You can now use the bot again.\n\n"
            "⚠️ Please follow our terms of service to avoid future bans."
        )
        notification_sent = True
    except PeerIdInvalid:
        pass  # User never interacted with bot
    except Exception as e:
        pass  # Failed to send
    
    notification_status = "✅ User notified" if notification_sent else "⚠️ Could not notify user (user may have blocked bot or never started it)"
    
    await message.reply_text(
        f"✅ **User unbanned successfully!**\n\n"
        f"👤 **User ID:** `{target_user_id}`\n\n"
        f"{notification_status}"
    )


# /banlist command - Admin only
@Client.on_message(filters.command("banlist") & filters.private)
async def banlist_command(client: Client, message: Message):
    """Show list of all banned users"""
    user_id = message.from_user.id
    
    # Check if user is admin
    if user_id != ADMINS:
        await message.reply_text("❌ **You are not authorized to use this command.**")
        return
    
    # Get all banned users
    banned_users = await db.get_all_banned_users()
    
    if not banned_users:
        await message.reply_text("📋 **Ban List is empty.**\n\nNo users are currently banned.")
        return
    
    # Build the ban list message
    import datetime
    
    ban_text = "🚫 **Banned Users List**\n\n"
    
    for i, user in enumerate(banned_users, 1):
        user_id_banned = user.get('user_id', 'Unknown')
        reason = user.get('reason', 'No reason provided')
        banned_at = user.get('banned_at')
        
        # Format datetime
        if banned_at:
            ban_date = datetime.datetime.fromtimestamp(banned_at).strftime('%Y-%m-%d %H:%M')
        else:
            ban_date = 'Unknown'
        
        ban_text += f"**{i}.** `{user_id_banned}`\n"
        ban_text += f"   📝 Reason: {reason}\n"
        ban_text += f"   📅 Date: {ban_date}\n\n"
        
        # Split message if too long (Telegram limit)
        if len(ban_text) > 3800:
            ban_text += "... and more"
            break
    
    ban_text += f"\n📊 **Total Banned:** {len(banned_users)}"
    
    await message.reply_text(ban_text)
