from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, ChannelPrivate
from database.db import db
from config import ADMINS

# State to track user input
forcesub_state = {}

@Client.on_message(filters.private & filters.command(["forcesub"]) & filters.user(ADMINS))
async def forcesub_menu(client: Client, message: Message):
    """Force subscribe management menu (admin only)"""
    channels = await db.get_force_sub_channels()
    
    text = f"""**📢 Force Subscribe Management**

**Current Channels:** {len(channels)}/4

Manage force subscription channels that users must join before using the bot.

**Features:**
• Add up to 4 channels
• View all channels
• Remove channels
• Automatic subscription check"""
    
    buttons = [
        [InlineKeyboardButton("📋 View Channels", callback_data="fs_view")],
        [InlineKeyboardButton("➕ Add Channel", callback_data="fs_add")],
        [InlineKeyboardButton("➖ Remove Channel", callback_data="fs_remove")],
        [InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_panel")]
    ]
    
    await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^fs_"))
async def forcesub_callback_handler(client: Client, query):
    """Handle force subscribe callbacks"""
    data = query.data
    user_id = query.from_user.id
    
    if data == "fs_view":
        channels = await db.get_force_sub_channels()
        
        if not channels:
            text = "**📋 Force Subscribe Channels**\n\n❌ No channels configured.\n\nAdd channels to require users to join before using the bot."
            buttons = [[InlineKeyboardButton("🔙 Back", callback_data="fs_menu")]]
        else:
            text = f"**📋 Force Subscribe Channels ({len(channels)}/4)**\n\n"
            
            for idx, ch in enumerate(channels, 1):
                username = ch.get('username', 'Unknown')
                channel_id = ch['id']
                
                # Try to get channel info
                try:
                    chat = await client.get_chat(channel_id)
                    title = chat.title
                    if chat.username:
                        link = f"@{chat.username}"
                    else:
                        link = f"ID: `{channel_id}`"
                except:
                    title = "Unknown Channel"
                    link = f"ID: `{channel_id}`"
                
                text += f"**{idx}.** {title}\n{link}\n\n"
            
            buttons = [[InlineKeyboardButton("🔙 Back", callback_data="fs_menu")]]
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "fs_add":
        channels = await db.get_force_sub_channels()
        
        if len(channels) >= 4:
            await query.answer("❌ Maximum 4 channels allowed!", show_alert=True)
            return
        
        forcesub_state[user_id] = {'action': 'add'}
        
        text = f"""**➕ Add Force Subscribe Channel**

**Current:** {len(channels)}/4 channels

Please send the channel ID or username.

**Examples:**
• `-1001234567890` (Channel ID)
• `@yourchannel` (Username)

**Note:** The bot must be admin in the channel!

Send /cancel to cancel."""
        
        buttons = [[InlineKeyboardButton("🔙 Back", callback_data="fs_menu")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "fs_remove":
        channels = await db.get_force_sub_channels()
        
        if not channels:
            await query.answer("❌ No channels to remove!", show_alert=True)
            return
        
        text = "**➖ Remove Force Subscribe Channel**\n\nSelect channel to remove:"
        buttons = []
        
        for ch in channels:
            channel_id = ch['id']
            
            # Try to get channel info
            try:
                chat = await client.get_chat(channel_id)
                title = chat.title[:30]  # Limit length
            except:
                title = f"ID: {channel_id}"
            
            buttons.append([InlineKeyboardButton(
                f"❌ {title}",
                callback_data=f"fs_remove_{channel_id}"
            )])
        
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="fs_menu")])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "fs_menu":
        # Return to main force sub menu
        channels = await db.get_force_sub_channels()
        
        text = f"""**📢 Force Subscribe Management**

**Current Channels:** {len(channels)}/4

Manage force subscription channels that users must join before using the bot.

**Features:**
• Add up to 4 channels
• View all channels
• Remove channels
• Automatic subscription check"""
        
        buttons = [
            [InlineKeyboardButton("📋 View Channels", callback_data="fs_view")],
            [InlineKeyboardButton("➕ Add Channel", callback_data="fs_add")],
            [InlineKeyboardButton("➖ Remove Channel", callback_data="fs_remove")],
            [InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_panel")]
        ]
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data.startswith("fs_remove_"):
        channel_id = int(data.split("_")[-1])
        await db.remove_force_sub_channel(channel_id)
        
        await query.answer("✅ Channel removed!", show_alert=True)
        
        # Return to remove menu
        channels = await db.get_force_sub_channels()
        
        if not channels:
            text = "**➖ Remove Force Subscribe Channel**\n\n✅ All channels removed!"
            buttons = [[InlineKeyboardButton("🔙 Back", callback_data="fs_menu")]]
        else:
            text = "**➖ Remove Force Subscribe Channel**\n\nSelect channel to remove:"
            buttons = []
            
            for ch in channels:
                ch_id = ch['id']
                
                try:
                    chat = await client.get_chat(ch_id)
                    title = chat.title[:30]
                except:
                    title = f"ID: {ch_id}"
                
                buttons.append([InlineKeyboardButton(
                    f"❌ {title}",
                    callback_data=f"fs_remove_{ch_id}"
                )])
            
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="fs_menu")])
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    await query.answer()

# Handle channel input for adding
@Client.on_message(filters.private & filters.text & filters.user(ADMINS), group=20)
async def handle_forcesub_input(client: Client, message: Message):
    """Handle force subscribe channel input"""
    user_id = message.from_user.id
    
    if user_id not in forcesub_state:
        return  # Not in forcesub state
    
    if message.text == "/cancel":
        del forcesub_state[user_id]
        return await message.reply("❌ **Cancelled.**")
    
    state = forcesub_state[user_id]
    
    if state['action'] == 'add':
        channel_input = message.text.strip()
        
        # Try to parse channel ID or username
        if channel_input.startswith('@'):
            channel_identifier = channel_input
        elif channel_input.lstrip('-').isdigit():
            channel_identifier = int(channel_input)
        else:
            return await message.reply("❌ **Invalid input!**\n\nPlease send a valid channel ID or username.")
        
        # Try to get channel info
        try:
            chat = await client.get_chat(channel_identifier)
            
            # Check if bot is admin
            try:
                bot = await client.get_me()
                bot_member = await client.get_chat_member(chat.id, bot.id)
                # Convert enum to string for comparison
                status_str = str(bot_member.status).lower()
                if "administrator" not in status_str and "creator" not in status_str and "owner" not in status_str:
                    return await message.reply("❌ **Bot is not admin in this channel!**\n\nPlease make the bot admin first.")
            except:
                return await message.reply("❌ **Could not verify bot admin status!**\n\nMake sure bot is admin in the channel.")
            
            # Add channel
            channel_username = chat.username if hasattr(chat, 'username') else None
            success, msg = await db.add_force_sub_channel(chat.id, channel_username)
            
            if success:
                del forcesub_state[user_id]
                await message.reply(f"✅ **Channel Added!**\n\n**Title:** {chat.title}\n**ID:** `{chat.id}`")
            else:
                await message.reply(f"❌ **Error:** {msg}")
        
        except ChannelPrivate:
            await message.reply("❌ **Channel is private!**\n\nBot must be a member of the channel.")
        except Exception as e:
            await message.reply(f"❌ **Error:** `{e}`\n\nPlease check the channel ID/username and try again.")
