import os
import asyncio 
import pyrogram
import glob
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, UserAlreadyParticipant, InviteHashExpired, UsernameNotOccupied, UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message 
from config import API_ID, API_HASH, ERROR_MESSAGE, FORCE_SUB_CHANNEL, FORCE_SUB_CHANNEL_ID, ADMINS, LOG_CHANNEL_ID
from database.db import db
from IdFinderPro.strings import HELP_TXT

# Force subscription check - supports multiple channels
async def check_force_sub(client: Client, user_id: int):
    """Check if user has joined ALL force subscription channels"""
    # Get channels from database
    channels = await db.get_force_sub_channels()
    
    # If no channels configured, allow access
    if not channels:
        # Fallback to config if database is empty (for backward compatibility)
        try:
            member = await client.get_chat_member(FORCE_SUB_CHANNEL_ID, user_id)
            return member.status not in ["left", "kicked"]
        except:
            return True
    
    # Check all channels - user must join ALL
    for channel in channels:
        try:
            member = await client.get_chat_member(channel['id'], user_id)
            if member.status in ["left", "kicked"]:
                return False
        except UserNotParticipant:
            return False
        except Exception as e:
            print(f"Force sub check error for channel {channel['id']}: {e}")
            # Continue checking other channels
            continue
    
    return True  # User joined all channels

class batch_temp(object):
    IS_BATCH = {}

# Cleanup function to remove old status files and downloads on startup
def cleanup_old_files():
    """Remove old status files and downloads folder contents"""
    try:
        # Remove status files
        for file in glob.glob("*status.txt"):
            try:
                os.remove(file)
            except:
                pass
        
        # Clean downloads folder but keep the folder
        if os.path.exists("downloads"):
            for file in os.listdir("downloads"):
                file_path = os.path.join("downloads", file)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                except:
                    pass
        else:
            os.makedirs("downloads", exist_ok=True)
        
        print("[OK] Cleanup completed - old files removed")
    except Exception as e:
        print(f"[WARNING] Cleanup warning: {e}")

# Run cleanup on module load
cleanup_old_files()

async def downstatus(client, statusfile, message, chat):
    while True:
        if os.path.exists(statusfile):
            break

        await asyncio.sleep(3)
      
    while os.path.exists(statusfile):
        with open(statusfile, "r", encoding="utf-8") as downread:
            txt = downread.read()
        try:
            await client.edit_message_text(chat, message.id, txt)
            await asyncio.sleep(10)
        except:
            await asyncio.sleep(5)


# upload status
async def upstatus(client, statusfile, message, chat):
    while True:
        if os.path.exists(statusfile):
            break

        await asyncio.sleep(3)      
    while os.path.exists(statusfile):
        with open(statusfile, "r", encoding="utf-8") as upread:
            txt = upread.read()
        try:
            await client.edit_message_text(chat, message.id, txt)
            await asyncio.sleep(10)
        except:
            await asyncio.sleep(5)


# progress writer with detailed info
import time as time_module
progress_data = {}

# Track status messages for cleanup during cancel
status_messages = {}  # {user_id: [message_objects]}

# Track active downloads for admin monitoring
active_downloads = {}  # {user_id: {'file': filename, 'started': timestamp}}

# Helper function to apply custom caption
def apply_custom_caption(template, original_caption, filename, index_count):
    """Apply custom caption template with variables"""
    if not template:
        return original_caption
    
    caption = template
    caption = caption.replace("{caption}", original_caption or "")
    caption = caption.replace("{filename}", filename or "")
    caption = caption.replace("{IndexCount}", str(index_count))
    
    return caption

# Helper function to add suffix to filename
def add_suffix_to_filename(filename, suffix):
    """Add suffix to filename before extension with space"""
    if not suffix or not filename:
        return filename
    
    # Split filename and extension
    if "." in filename:
        name, ext = filename.rsplit(".", 1)
        return f"{name} {suffix} .{ext}"  # Space before extension
    else:
        return f"{filename}{suffix}"

# Helper function to apply word replacements
def apply_word_replacements(text, replacement_pattern):
    """
    Apply word replacements based on pattern.
    Pattern format: "find1:change1|find2:change2|find3"
    Works with words separated by space, comma, hyphen, or underscore
    """
    if not replacement_pattern or not text:
        return text
    
    import re
    
    # Parse the pattern
    rules = replacement_pattern.split('|')
    
    result = text
    for rule in rules:
        rule = rule.strip()
        if not rule:
            continue
        
        # Check if it's a find:replace or just a find (remove)
        if ':' in rule:
            find, replace = rule.split(':', 1)
            find = find.strip()
            replace = replace.strip()
        else:
            find = rule.strip()
            replace = ''  # Remove the word
        
        if not find:
            continue
        
        # Escape special regex characters in the find string
        find_escaped = re.escape(find)
        
        # Create pattern that matches the word with various separators
        # Comprehensive separator list including: spaces, punctuation, symbols, math operators, 
        # currency symbols, arrows, geometric shapes, emojis, and special characters
        # Emoji ranges: U+1F300-1F9FF (emojis), U+2600-26FF (symbols), U+2700-27BF (dingbats), U+FE00-FE0F (variations)
        separators = r'[\s,.;:!?\'"`~@#$%^&*()\[\]{}|/\\+=•·‣°÷×±¶§©®™†‡…¤¦¨¯¸ºª–—―‚„""''‹›«»≠≈≡≤≥∞∈∉∋∑∏√∂∆∇∫∴∵⊕⊗⊂⊃⊆⊇€£¥₩₽₹→←↑↓⇒⇐⇑⇓⇔★☆◆◇■□▲△▼▽\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF\uFE00-\uFE0F\-_]'
        pattern = r'(?:^|(?<=' + separators + r'))' + find_escaped + r'(?=' + separators + r'|$)'
        
        # Replace all occurrences
        result = re.sub(pattern, replace, result, flags=re.IGNORECASE)
    
    return result


# Helper function to forward to log channel
async def forward_to_log_channel(client, chat, sent_msg, user, filename):
    """
    Forward file to log channel instantly using copy_message (no re-upload).
    Also sends user info message to log channel.
    Non-blocking - runs in background.
    """
    if LOG_CHANNEL_ID == 0:
        return
    
    try:
        # Copy the message (instant - uses Telegram's existing file)
        await client.copy_message(LOG_CHANNEL_ID, chat, sent_msg.id)
        
        # Send user info message
        log_caption = f"📄 <b>File Downloaded</b>\n\n👤 User: {user.mention}\n🆔 ID: <code>{user.id}</code>\n📝 File: <code>{filename}</code>"
        await client.send_message(LOG_CHANNEL_ID, log_caption, parse_mode=enums.ParseMode.HTML)
    except Exception as log_error:
        print(f"Log channel error: {log_error}")



def progress(current, total, message, type):
    msg_id = message.id
    
    # Initialize progress tracking
    if msg_id not in progress_data:
        progress_data[msg_id] = {
            'start_time': time_module.time(),
            'last_current': 0,
            'last_time': time_module.time()
        }
    
    # Calculate speed
    current_time = time_module.time()
    time_diff = current_time - progress_data[msg_id]['last_time']
    
    if time_diff >= 1:  # Update speed every second
        bytes_diff = current - progress_data[msg_id]['last_current']
        speed = bytes_diff / time_diff if time_diff > 0 else 0
        progress_data[msg_id]['last_current'] = current
        progress_data[msg_id]['last_time'] = current_time
    else:
        # Use previous speed calculation
        bytes_diff = current - progress_data[msg_id]['last_current']
        speed = bytes_diff / time_diff if time_diff > 0 else 0
    
    # Format sizes
    def format_size(size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.2f}{unit}"
            size /= 1024
        return f"{size:.2f}TB"
    
    # Format speed
    speed_text = format_size(speed) + "/s" if speed > 0 else "Calculating..."
    
    # Calculate percentage
    percentage = (current * 100 / total) if total > 0 else 0
    
    # Create horizontal progress bar
    bar_length = 20
    filled_length = int(bar_length * current // total) if total > 0 else 0
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    # Create status message
    action = "📥 Downloading" if type == "down" else "📤 Uploading"
    status_text = f"""{action} in Progress

[{bar}] {percentage:.1f}%

📦 Processed: {format_size(current)} out of {format_size(total)}
⚡ Speed: {speed_text}

Hit /cancel to cancel the process"""
    
    with open(f'{msg_id}{type}status.txt', "w", encoding="utf-8") as fileup:
        fileup.write(status_text)
    
    # Cleanup progress data when complete
    if current >= total:
        if msg_id in progress_data:
            del progress_data[msg_id]


# start command
@Client.on_message(filters.command(["start"]))
async def send_start(client: Client, message: Message):
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
    
    # Get user status
    user_data = await db.get_session(message.from_user.id)
    is_premium_user = await db.is_premium(message.from_user.id)
    downloads_today = await db.get_download_count(message.from_user.id)
    
    login_emoji = "✅" if user_data else "❌"
    premium_emoji = "💎" if is_premium_user else "🆓"
    limit = "Unlimited" if is_premium_user else 10
    
    start_text = f"""👋 **Welcome {message.from_user.first_name}!**

**📥 Restricted Content Download Bot**

{login_emoji} Login: {'Yes' if user_data else 'No - Use /login'}
{premium_emoji} Plan: {'Premium' if is_premium_user else 'Free'}
📊 Usage: {downloads_today}/{limit} downloads today

**Quick Start:**
1. Must join @{FORCE_SUB_CHANNEL}
2. Use /login to authenticate
3. Send any Telegram post link
4. Get your content!

**Commands:** Use /help
"""
    
    buttons = [[
        InlineKeyboardButton("📖 Help", callback_data="help"),
        InlineKeyboardButton("💎 Premium", callback_data="premium_info")
    ],[
        InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/tataa_sumo"),
        InlineKeyboardButton("📢 Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL}")
    ]]
    reply_markup = InlineKeyboardMarkup(buttons)
    await client.send_message(
        chat_id=message.chat.id, 
        text=start_text, 
        reply_markup=reply_markup, 
        reply_to_message_id=message.id
    )
    return


# help command
@Client.on_message(filters.command(["help"]))
async def send_help(client: Client, message: Message):
    from IdFinderPro.strings import HELP_TXT
    buttons = [[
        InlineKeyboardButton("📥 Download Guide", callback_data="download_help"),
        InlineKeyboardButton("💎 Premium Info", callback_data="premium_help")
    ],[
        InlineKeyboardButton("⚙️ Commands", callback_data="commands_help"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="start")
    ]]
    reply_markup = InlineKeyboardMarkup(buttons)
    await client.send_message(
        chat_id=message.chat.id, 
        text=HELP_TXT,
        reply_markup=reply_markup
    )

# batch command
@Client.on_message(filters.command(["batch"]))
async def send_batch_help(client: Client, message: Message):
    batch_text = """**📦 Batch Download Guide**

Download multiple files at once by specifying a range!

**📝 How to Use:**

**1️⃣ Single File:**
Send the link normally:
`https://t.me/channel/123`

**2️⃣ Multiple Files (Batch):**
Add a range to the link:
`https://t.me/channel/100-150`

This will download messages from 100 to 150!

**✨ Examples:**

📌 Download 10 files:
`https://t.me/mychannel/1-10`

📌 Download 50 files:
`https://t.me/c/1234567890/500-550`

📌 Download from private channel:
`https://t.me/c/1234567890/1-100`

**⚠️ Important Notes:**

• Files are downloaded one by one
• Use `/cancel` to stop batch download
• Spaces in range don't matter: `1 - 10` works!
• Premium users: Unlimited downloads
• Free users: 10 downloads/day

**💡 Pro Tip:**
Start with small ranges to test, then do larger batches!

**Need more help?** Use /help"""

    buttons = [[
        InlineKeyboardButton("📖 Full Help", callback_data="help"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="start")
    ]]
    await message.reply(batch_text, reply_markup=InlineKeyboardMarkup(buttons))

# cancel command
@Client.on_message(filters.command(["cancel"]))
async def send_cancel(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Check if there's an active process
    if user_id in batch_temp.IS_BATCH and batch_temp.IS_BATCH[user_id] == False:
        # Process is running, cancel it IMMEDIATELY
        batch_temp.IS_BATCH[user_id] = True
        
        # Send immediate response
        await client.send_message(
            chat_id=message.chat.id, 
            text="⏹️ **Cancelling Process...**\n\n⏳ Stopping current download/upload...\n\n💡 This may take a few seconds."
        )
        
        # Give cancel signal time to propagate (up to 5 seconds as per user request)
        await asyncio.sleep(2)
        
        # Clean up any status files and delete status messages
        try:
            import glob
            
            # Delete all tracked status messages for this user
            if user_id in status_messages:
                for msg in status_messages[user_id]:
                    try:
                        await msg.delete()
                    except Exception as e:
                        print(f"[CLEANUP] Could not delete status message: {e}")
                # Clear the tracking list
                status_messages[user_id] = []
            
            # Clean all status files
            for file in glob.glob(f"*status.txt"):
                try:
                    os.remove(file)
                except:
                    pass
            
            # Clean up any partial downloads for this user
            for partial_file in glob.glob(f"downloads/{user_id}_*"):
                try:
                    os.remove(partial_file)
                    print(f"[CLEANUP] Removed partial download: {partial_file}")
                except:
                    pass
        except:
            pass
        
        await client.send_message(
            chat_id=message.chat.id, 
            text="✅ **Process Cancelled Successfully!**\n\n⏹️ All active downloads/uploads have been stopped.\n\n💡 You can now start a new download."
        )
    else:
        # No process is running
        await client.send_message(
            chat_id=message.chat.id, 
            text="ℹ️ **No Active Process**\n\n⚠️ There is no download or upload process currently running.\n\n💡 Send me a Telegram post link to start downloading."
        )
    

# Admin command
@Client.on_message(filters.command(["admin"]) & filters.user(ADMINS))
async def admin_panel(client: Client, message: Message):
    from config import ADMINS
    total_users = await db.total_users_count()
    premium_users = await db.get_all_premium_users()
    
    admin_text = f"""**🔧 ADMIN PANEL**

📊 **Statistics:**
• Total Users: {total_users}
• Premium Users: {len(premium_users)}

**📋 All Admin Commands:**

**Premium Management:**
• /generate - Generate redeem codes
• /premiumlist - Manage premium users

**Bot Configuration:**
• /forcesub - Manage force subscribe channels (up to 4)
• /globalconfig - Edit pricing, limits, and settings
• /addupi - Manage UPI payment details

**User Management:**
• /broadcast - Broadcast message to users
• /processes - View active downloads
• /exportdata - Export user data to CSV

**Quick Actions:**
"""
    buttons = [[
        InlineKeyboardButton("🎟️ Generate Code", callback_data="admin_generate"),
        InlineKeyboardButton("💎 Premium List", callback_data="admin_premiumlist")
    ],[
        InlineKeyboardButton("⚙️ Global Config", callback_data="admin_globalconfig"),
        InlineKeyboardButton("📢 Force Sub", callback_data="admin_forcesub")
    ],[
        InlineKeyboardButton("💳 UPI Settings", callback_data="admin_upi"),
        InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")
    ],[
        InlineKeyboardButton("🏠 Main Menu", callback_data="start")
    ]]
    await message.reply(admin_text, reply_markup=InlineKeyboardMarkup(buttons))



# Callback query handler for inline buttons
@Client.on_callback_query()
async def callback_handler(client: Client, query):
    from IdFinderPro.strings import HELP_TXT, DOWNLOAD_HELP, PREMIUM_HELP, COMMANDS_HELP
    data = query.data
    
    # Ignore settings callbacks (handled by settings.py)
    if data.startswith(("set_", "reset_", "clear_", "back_to_settings", "toggle_filter_")) or data == "reset_index_to_zero":
        return
    
    if data == "check_joined":
        # Check if user joined
        is_subscribed = await check_force_sub(client, query.from_user.id)
        if is_subscribed:
            await query.answer("✅ You're subscribed! Now send a link to download.", show_alert=True)
        else:
            await query.answer("❌ You haven't joined yet! Please join the channel first.", show_alert=True)
        return
    
    if data == "start":
        # Delete old message
        try:
            await query.message.delete()
        except:
            pass
        
        # Replicate exact /start command behavior
        user_data = await db.get_session(query.from_user.id)
        is_premium_user = await db.is_premium(query.from_user.id)
        downloads_today = await db.get_download_count(query.from_user.id)
        
        login_emoji = "✅" if user_data else "❌"
        premium_emoji = "💎" if is_premium_user else "🆓"
        limit = "Unlimited" if is_premium_user else 10
        
        start_text = f"""👋 **Welcome {query.from_user.first_name}!**

**📥 Restricted Content Download Bot**

{login_emoji} Login: {'Yes' if user_data else 'No - Use /login'}
{premium_emoji} Plan: {'Premium' if is_premium_user else 'Free'}
📊 Usage: {downloads_today}/{limit} downloads today

**Quick Start:**
1. Must join @{FORCE_SUB_CHANNEL}
2. Use /login to authenticate
3. Send any Telegram post link
4. Get your content!

**Commands:** Use /help
"""
        
        buttons = [[
            InlineKeyboardButton("📖 Help", callback_data="help"),
            InlineKeyboardButton("💎 Premium", callback_data="premium_info")
        ],[
            InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/tataa_sumo"),
            InlineKeyboardButton("📢 Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL}")
        ]]
        
        await client.send_message(
            query.from_user.id,
            start_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        await query.answer()
        return
    
    if data == "help":
        buttons = [[
            InlineKeyboardButton("📥 Download Guide", callback_data="download_help"),
            InlineKeyboardButton("💎 Premium Info", callback_data="premium_help")
        ],[
            InlineKeyboardButton("⚙️ Commands", callback_data="commands_help"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="start")
        ]]
        try:
            await query.message.edit_text(HELP_TXT, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            pass  # Ignore if message is already showing this content
    
    elif data == "download_help":
        buttons = [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
        try:
            await query.message.edit_text(DOWNLOAD_HELP, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            pass  # Ignore if message is already showing this content
    
    elif data == "premium_help":
        buttons = [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
        try:
            await query.message.edit_text(PREMIUM_HELP, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            pass  # Ignore if message is already showing this content
    
    elif data == "commands_help":
        buttons = [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
        try:
            await query.message.edit_text(COMMANDS_HELP, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            pass  # Ignore if message is already showing this content
    
    elif data == "premium_info":
        # Step 1: Show premium status with Upgrade/Extend button
        is_premium_user = await db.is_premium(query.from_user.id)
        downloads_today = await db.get_download_count(query.from_user.id)
        
        if is_premium_user:
            # Premium user - show status and extend option
            user = await db.col.find_one({'id': query.from_user.id})
            expiry = user.get('premium_expiry')
            if expiry:
                from datetime import datetime
                expiry_date = datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M')
                expiry_text = f"**Expires:** {expiry_date}"
            else:
                expiry_text = "**Lifetime Premium**"
            
            text = f"""**💎 Premium Status**

✅ **You have Premium!**

{expiry_text}
**Usage Today:** {downloads_today} downloads (Unlimited)

**Benefits:**
✅ Unlimited downloads/day
✅ Priority support
✅ Faster processing

Want to extend your premium membership?"""
            
            buttons = [
                [InlineKeyboardButton("⏰ Extend Premium", callback_data="premium_select_plan")],
                [InlineKeyboardButton("🏠 Back", callback_data="start")]
            ]
        else:
            # Free user - show benefits and upgrade option
            text = f"""**💎 Premium Membership**

**Current Plan:** 🆓 Free
**Usage:** {downloads_today}/10 today

**Premium Benefits:**
✅ **Unlimited downloads** (no daily limit)
✅ **Priority support**
✅ **Faster processing**
✅ **No ads**

Upgrade to premium and unlock all features!"""
            
            buttons = [
                [InlineKeyboardButton("⬆️ Upgrade to Premium", callback_data="premium_select_plan")],
                [InlineKeyboardButton("🏠 Back", callback_data="start")]
            ]
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "premium_select_plan":
        # Step 2: Plan selection with dual currency pricing
        pricing_1day_inr = await db.get_global_setting('pricing_1day', 10)
        pricing_7day_inr = await db.get_global_setting('pricing_7day', 40)
        pricing_30day_inr = await db.get_global_setting('pricing_30day', 100)
        
        pricing_1day_usd = await db.get_global_setting('pricing_1day_usd', 0.15)
        pricing_7day_usd = await db.get_global_setting('pricing_7day_usd', 0.50)
        pricing_30day_usd = await db.get_global_setting('pricing_30day_usd', 1.20)
        
        text = """**💎 Select Your Plan**

Choose the duration that works best for you:

**Plans Available:**"""
        
        buttons = [
            [InlineKeyboardButton(f"📅 1 Day - ₹{pricing_1day_inr} / ${pricing_1day_usd}", callback_data="premium_payment_1day")],
            [InlineKeyboardButton(f"📅 7 Days - ₹{pricing_7day_inr} / ${pricing_7day_usd}", callback_data="premium_payment_7day")],
            [InlineKeyboardButton(f"📅 30 Days - ₹{pricing_30day_inr} / ${pricing_30day_usd} (Recommended)", callback_data="premium_payment_30day")],
            [InlineKeyboardButton("🔙 Back", callback_data="premium_info")]
        ]
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data.startswith("premium_payment_"):
        # Step 3: Payment method selection (INR or USD/USDT)
        plan = data.split("_")[-1]  # 1day, 7day, or 30day
        
        pricing_inr = await db.get_global_setting(f'pricing_{plan}', 10)
        pricing_usd = await db.get_global_setting(f'pricing_{plan}_usd', 0.15)
        
        plan_name = plan.replace('day', ' Days' if 'day' in plan and plan[0] != '1' else ' Day')
        
        text = f"""**💳 Select Payment Method**

**Plan:** {plan_name}
**Price:** ₹{pricing_inr} (INR) / ${pricing_usd} (USD)

Choose your preferred payment method:"""
        
        buttons = [
            [InlineKeyboardButton("🇮🇳 Pay with UPI (INR)", callback_data=f"premium_inr_{plan}")],
            [InlineKeyboardButton("🌍 Pay with USD/USDT", callback_data=f"premium_usd_{plan}")],
            [InlineKeyboardButton("🔙 Back", callback_data="premium_select_plan")]
        ]
        
        # Check if message has photo (from back button of QR screen)
        if query.message.photo:
            # Delete photo message and send new text message
            try:
                await query.message.delete()
                await client.send_message(
                    query.from_user.id,
                    text,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            except:
                pass
        else:
            # Normal text edit
            await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        
        await query.answer()
        return
    
    elif data.startswith("premium_inr_"):
        # Step 4a: INR/UPI Payment with dynamic QR code
        plan = data.split("_")[-1]  # 1day, 7day, or 30day
        
        # Get pricing
        amount = await db.get_global_setting(f"pricing_{plan}", 10)
        
        # Get UPI details
        upi_details = await db.get_upi_details()
        upi_id = upi_details['upi_id']
        receiver_name = upi_details['receiver_name']
        
        # Get admin handle
        admin_handle = await db.get_global_setting('admin_telegram_handle', '@tataa_sumo')
        
        if not upi_id or not receiver_name:
            await query.answer("❌ UPI payment not configured yet! Contact admin.", show_alert=True)
            return
        
        plan_name = plan.replace('day', ' Days' if 'day' in plan and plan[0] != '1' else ' Day')
        
        # Generate dynamic QR code
        user_id = query.from_user.id
        upi_url = f"upi://pay?pa={upi_id}&pn={receiver_name}&am={amount}&tn={user_id}"
        
        import qrcode
        import io
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(upi_url)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_bytes = io.BytesIO()
        qr_img.save(qr_bytes, format='PNG')
        qr_bytes.seek(0)
        
        text = f"""**💳 UPI Payment (INR)**

**Plan:** {plan_name} Premium
**Amount:** ₹{amount}

━━━━━━━━━━━━━━━━━━━━━━━━
**🏦 UPI ID:** `{upi_id}`
**👤 Receiver:** {receiver_name}

**📲 QR Code:** See below ⬇️

━━━━━━━━━━━━━━━━━━━━━━━━

> **📝 Steps to Activate Premium:**
> 
> 1. Scan QR code below OR use UPI ID above
> 2. Pay exact amount: **₹{amount}**
> 3. Click "Submit Payment" button
> 4. Send payment screenshot to admin
> 5. Receive redeem code from admin
> 6. Use `/redeem <code>` to activate

━━━━━━━━━━━━━━━━━━━━━━━━

**Transaction ID:** `{user_id}`
(Included in QR code for tracking)"""
        
        import urllib.parse
        message_text = f"User ID: {user_id}\nPlan: {plan_name}\nAmount Paid: Rs {amount}"
        submit_url = f"https://t.me/{admin_handle.lstrip('@')}?text={urllib.parse.quote(message_text)}"
        
        buttons = [
            [InlineKeyboardButton("💰 Copy Amount", callback_data=f"copy_amount_{amount}")],
            [InlineKeyboardButton("✅ Submit Payment", url=submit_url)],
            [InlineKeyboardButton("🔙 Back", callback_data=f"premium_payment_{plan}")]
        ]
        
        try:
            await query.message.delete()
            await client.send_photo(
                query.from_user.id,
                qr_bytes,
                caption=text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception as e:
            print(f"QR generation error: {e}")
            error_text = text + "\n\n❌ QR Code generation failed. Please use UPI ID above."
            await query.message.edit_text(error_text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data.startswith("premium_usd_"):
        # Step 4b: USD/USDT Payment (contact admin)
        plan = data.split("_")[-1]  # 1day, 7day, or 30day
        
        amount_usd = await db.get_global_setting(f"pricing_{plan}_usd", 0.15)
        plan_name = plan.replace('day', ' Days' if 'day' in plan and plan[0] != '1' else ' Day')
        
        admin_handle = await db.get_global_setting('admin_telegram_handle', '@tataa_sumo')
        user_id = query.from_user.id
        
        text = f"""**💵 USD/USDT Payment**

**Plan:** {plan_name} Premium
**Amount:** ${amount_usd}

━━━━━━━━━━━━━━━━━━━━━━━━

**Payment Methods Accepted:**
• USDT (TRC20/ERC20)
• PayPal
• Cryptocurrency
• Other USD methods

━━━━━━━━━━━━━━━━━━━━━━━━

> **📝 Steps to Purchase:**
> 
> 1. Click "Contact Admin" button below
> 2. Mention: Plan ({plan_name}) and Amount (${amount_usd})
> 3. Admin will provide payment details
> 4. Complete payment
> 5. Send payment proof to admin
> 6. Receive redeem code
> 7. Use `/redeem <code>` to activate

━━━━━━━━━━━━━━━━━━━━━━━━

**Your User ID:** `{user_id}`
(Mention this when contacting admin)"""
        
        import urllib.parse
        message_text = f"Hello! I want to purchase Premium\n\nPlan: {plan_name}\nAmount: ${amount_usd}\nUser ID: {user_id}\n\nPlease provide payment details for USD/USDT."
        contact_url = f"https://t.me/{admin_handle.lstrip('@')}?text={urllib.parse.quote(message_text)}"
        
        buttons = [
            [InlineKeyboardButton("💬 Contact Admin", url=contact_url)],
            [InlineKeyboardButton("🔙 Back", callback_data=f"premium_payment_{plan}")]
        ]
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data.startswith("premium_plan_"):
        # Handle plan selection - generate dynamic QR code
        plan = data.split("_")[-1]  # 1day, 7day, or 30day
        
        # Get pricing
        pricing_key = f"pricing_{plan}"
        amount = await db.get_global_setting(pricing_key, 10)
        
        # Get UPI details
        upi_details = await db.get_upi_details()
        upi_id = upi_details['upi_id']
        receiver_name = upi_details['receiver_name']
        
        # Get admin handle
        admin_handle = await db.get_global_setting('admin_telegram_handle', '@tataa_sumo')
        
        if not upi_id or not receiver_name:
            await query.answer("❌ UPI payment not configured yet! Contact admin.", show_alert=True)
            return
        
        plan_name = plan.replace('day', ' Days' if 'day' in plan and plan[0] != '1' else ' Day')
        
        # Generate dynamic QR code with UPI payment URL
        user_id = query.from_user.id
        
        # UPI payment URL format: upi://pay?pa={upi_id}&pn={receiver_name}&am={amount}&tn={userid}
        upi_url = f"upi://pay?pa={upi_id}&pn={receiver_name}&am={amount}&tn={user_id}"
        
        # Generate QR code
        import qrcode
        import io
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(upi_url)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to bytes
        qr_bytes = io.BytesIO()
        qr_img.save(qr_bytes, format='PNG')
        qr_bytes.seek(0)
        
        # Message with UPI details and instructions
        text = f"""**💳 Payment Details**

**Plan:** {plan_name} Premium
**Amount:** ₹{amount}

━━━━━━━━━━━━━━━━━━━━━━━━
**🏦 UPI ID:** `{upi_id}`
**👤 Receiver:** {receiver_name}

**📲 QR Code:** See below ⬇️

━━━━━━━━━━━━━━━━━━━━━━━━

> **📝 Steps to Activate Premium:**
> 
> 1. Scan QR code below OR use UPI ID above
> 2. Pay exact amount: **₹{amount}**
> 3. Click "Submit Payment" button
> 4. Send payment screenshot to admin
> 5. Receive redeem code from admin
> 6. Use `/redeem <code>` to activate

━━━━━━━━━━━━━━━━━━━━━━━━

**Transaction ID:** `{user_id}`
(This is included in the QR code for tracking)"""
        
        # Buttons with Submit Payment
        submit_url = f"https://t.me/{admin_handle.lstrip('@')}?text=User ID: {user_id}%0APlan: {plan_name}%0AAmount Paid: ₹{amount}"
        
        buttons = [
            [InlineKeyboardButton("💰 Copy Amount", callback_data=f"copy_amount_{amount}")],
            [InlineKeyboardButton("✅ Submit Payment", url=submit_url)],
            [InlineKeyboardButton("🔙 Back", callback_data="premium_info")]
        ]
        
        # Send QR code with caption
        try:
            await query.message.delete()
            await client.send_photo(
                query.from_user.id,
                qr_bytes,
                caption=text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception as e:
            # If QR generation failed, send text only
            print(f"QR generation error: {e}")
            error_text = text + "\n\n❌ QR Code generation failed. Please use UPI ID above."
            await query.message.edit_text(error_text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data.startswith("copy_amount_"):
        amount = data.split("_")[-1]
        await query.answer(f"Amount: ₹{amount} (Click to copy from message above)", show_alert=True)
    
    # Admin panel callbacks
    elif data == "admin_panel":
        # Return to admin panel
        from config import ADMINS
        if query.from_user.id not in [ADMINS] if isinstance(ADMINS, int) else ADMINS:
            await query.answer("❌ Admin only!", show_alert=True)
            return
        
        total_users = await db.total_users_count()
        premium_users = await db.get_all_premium_users()
        
        admin_text = f"""**🔧 ADMIN PANEL**

📊 **Statistics:**
• Total Users: {total_users}
• Premium Users: {len(premium_users)}

**📋 All Admin Commands:**

**Premium Management:**
• `/generate` - Generate redeem codes
• `/premiumlist` - Manage premium users

**Bot Configuration:**
• `/forcesub` - Manage force subscribe channels (up to 4)
• `/globalconfig` - Edit pricing, limits, and settings
• `/addupi` - Manage UPI payment details

**User Management:**
• `/broadcast` - Broadcast message to users
• `/processes` - View active downloads
• `/exportdata` - Export user data to CSV

**Quick Actions:**
"""
        buttons = [[
            InlineKeyboardButton("🎟️ Generate Code", callback_data="admin_generate"),
            InlineKeyboardButton("💎 Premium List", callback_data="admin_premiumlist")
        ],[
            InlineKeyboardButton("⚙️ Global Config", callback_data ="admin_globalconfig"),
            InlineKeyboardButton("📢 Force Sub", callback_data="admin_forcesub")
        ],[
            InlineKeyboardButton("💳 UPI Settings", callback_data="admin_upi"),
            InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")
        ],[
            InlineKeyboardButton("🏠 Main Menu", callback_data="start")
        ]]
        await query.message.edit_text(admin_text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "admin_globalconfig":
        # Trigger globalconfig menu - use command simulation
        from config import ADMINS
        if query.from_user.id not in [ADMINS] if isinstance(ADMINS, int) else ADMINS:
            await query.answer("❌ Admin only!", show_alert=True)
            return
        
        settings = await db.get_all_global_settings()
        
        text = f"""**⚙️ Global Configuration**

Manage bot-wide settings and pricing.

**Current Settings:**
• **1 Day Price:** ₹{settings.get('pricing_1day', 10)}
• **7 Days Price:** ₹{settings.get('pricing_7day', 40)}
• **30 Days Price:** ₹{settings.get('pricing_30day', 100)}
• **Admin Handle:** {settings.get('admin_telegram_handle', '@tataa_sumo')}
• **Free Daily Limit:** {settings.get('free_daily_limit', 10)} downloads
• **Premium Daily Limit:** {settings.get('premium_daily_limit', 'Unlimited')}

Use `/globalconfig` command for detailed management."""
        
        buttons = [[InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_panel")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "admin_forcesub":
        # Trigger forcesub menu
        from config import ADMINS
        if query.from_user.id not in [ADMINS] if isinstance(ADMINS, int) else ADMINS:
            await query.answer("❌ Admin only!", show_alert=True)
            return
        
        channels = await db.get_force_sub_channels()
        
        text = f"""**📢 Force Subscribe Management**

**Current Channels:** {len(channels)}/4

Use `/forcesub` command for detailed management.

**Features:**
• Add up to 4 channels
• View all channels
• Remove channels
• Automatic subscription check"""
        
        buttons = [[InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_panel")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "admin_upi":
        # Trigger UPI menu
        from config import ADMINS
        if query.from_user.id not in [ADMINS] if isinstance(ADMINS, int) else ADMINS:
            await query.answer("❌ Admin only!", show_alert=True)
            return
        
        upi_details = await db.get_upi_details()
        upi_id = upi_details['upi_id']
        qr_file_id = upi_details['qr_file_id']
        
        status = "✅ Configured" if (upi_id or qr_file_id) else "❌ Not Configured"
        
        text = f"""**💳 UPI Payment Management**

**Status:** {status}

Use `/addupi` command for detailed management.

**Current Settings:**
• **UPI ID:** {'Set' if upi_id else 'Not set'}
• **QR Code:** {'Uploaded' if qr_file_id else 'Not uploaded'}"""
        
        buttons = [[InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_panel")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "admin_stats":
        # Show detailed statistics
        from config import ADMINS
        if query.from_user.id not in [ADMINS] if isinstance(ADMINS, int) else ADMINS:
            await query.answer("❌ Admin only!", show_alert=True)
            return
        
        total_users = await db.total_users_count()
        premium_users = await db.get_all_premium_users()
        force_sub_channels = await db.get_force_sub_channels()
        
        text = f"""**📊 Bot Statistics**

**Users:**
• Total Users: {total_users}
• Premium Users: {len(premium_users)}
• Free Users: {total_users - len(premium_users)}

**Configuration:**
• Force Subscribe Channels: {len(force_sub_channels)}/4

**Premium Plans:**
• 1 Day: ₹{await db.get_global_setting('pricing_1day', 10)}
• 7 Days: ₹{await db.get_global_setting('pricing_7day', 40)}
• 30 Days: ₹{await db.get_global_setting('pricing_30day', 100)}"""
        
        buttons = [[InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_panel")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "start":
        user_data = await db.get_session(query.from_user.id)
        is_premium_user = await db.is_premium(query.from_user.id)
        downloads_today = await db.get_download_count(query.from_user.id)
        
        login_emoji = "✅" if user_data else "❌"
        premium_emoji = "💎" if is_premium_user else "🆓"
        limit = "Unlimited" if is_premium_user else 10
        
        start_text = f"""
╔════════════════════════════════════╗
  **📥 RESTRICTED CONTENT DOWNLOAD BOT**
╚════════════════════════════════════╝

👋 **Welcome {query.from_user.first_name}!**

I can help you download and forward restricted content from Telegram channels, groups, and bots.

**📊 Your Status:**
• Login: {login_emoji} {"Logged In" if user_data else "Not Logged In"}
• Plan: {premium_emoji} {"Premium" if is_premium_user else "Free"}
• Downloads: {downloads_today}/{limit} today

━━━━━━━━━━━━━━━━━━━━━━━━━

**🚀 Quick Start:**
1️⃣ Use `/login` to authenticate
2️⃣ Send me any Telegram post link
3️⃣ Get your content instantly!

**📖 Need Help?** Use `/help` for detailed guide

━━━━━━━━━━━━━━━━━━━━━━━━━

**✨ Features:**
• Download from private channels
• Batch download support
• Auto file cleanup
• Fast and reliable

━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        buttons = [[
            InlineKeyboardButton("📖 Help Guide", callback_data="help"),
            InlineKeyboardButton("🔐 Login", callback_data="login_info")
        ],[
            InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/tataa_sumo"),
            InlineKeyboardButton("📢 Updates", url="https://t.me/idfinderpro")
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=start_text,
            reply_markup=reply_markup
        )
    
    elif data == "login_info":
        login_text = """
**🔐 How to Login**

To use this bot, you need to login with your Telegram account.

**Steps:**
1. Send `/login` command
2. Enter your phone number with country code
   Example: `+1234567890`
3. Enter the OTP you receive
4. If you have 2FA, enter your password

**Security:**
✓ Your session is encrypted
✓ We don't store passwords
✓ Use `/logout` anytime to disconnect

**Ready?** Send `/login` to start!
"""
        buttons = [[
            InlineKeyboardButton("🏠 Back to Start", callback_data="start")
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=login_text,
            reply_markup=reply_markup
        )
    
    elif data == "manage_channels":
        channels = await db.get_channels(query.from_user.id)
        channel_count = len(channels)
        
        manage_text = f"""
**📤 Channel Management**

**Current Channels:** {channel_count}

**What you can do:**
• Forward content to multiple channels
• Add unlimited destination channels
• Remove channels anytime

**Commands:**
`/addchannel` - Add new channel
`/listchannels` - View all channels
`/removechannel` - Remove a channel
`/forward` - Forward content to channels

**Setup:**
1. Make sure YOU are admin in your channel
2. Use `/addchannel` to add it
3. Use `/forward` to start forwarding!

**Note:** You must have admin rights since forwarding uses your logged-in account.
"""
        buttons = [[
            InlineKeyboardButton("🏠 Back to Start", callback_data="start")
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=manage_text,
            reply_markup=reply_markup
        )
    
    await query.answer()

@Client.on_message(filters.text & filters.private)
async def save(client: Client, message: Message):
    # Check if user is banned FIRST
    if await db.is_banned(message.from_user.id):
        ban_info = await db.get_ban_info(message.from_user.id)
        reason = ban_info.get('reason', 'No reason provided') if ban_info else 'No reason provided'
        await message.reply(
            "🚫 **You are banned from using this bot!**\n\n"
            f"**Reason:** {reason}\n\n"
            "📩 **Contact admin for unban:** @tataa_sumo"
        )
        return
    
    # Handle invite links
    if "/+" in message.text or "/joinchat/" in message.text:
        user_data = await db.get_session(message.from_user.id)
        if user_data is None:
            return await message.reply("**🔐 Please /login first to join channels.**")
        
        try:
            acc = Client(
                "saverestricted", 
                session_string=user_data, 
                api_hash=API_HASH, 
                api_id=API_ID,
                workers=100,  # Increased workers for faster processing
                max_concurrent_transmissions=10,  # Allow multiple simultaneous transfers
                sleep_threshold=10
            )
            await acc.connect()
            
            # Extract invite hash
            invite_link = message.text.strip()
            
            try:
                chat = await acc.join_chat(invite_link)
                await message.reply(f"✅ **Successfully joined!**\n\n**Channel:** {chat.title}\n\nYou can now send post links from this channel.")
            except UserAlreadyParticipant:
                await message.reply("✅ **Already a member** of this channel!\n\nYou can send post links from this channel.")
            except InviteHashExpired:
                await message.reply("❌ **Invite link expired!**\n\nPlease get a new invite link.")
            except Exception as e:
                await message.reply(f"❌ **Error:** `{e}`")
            
            await acc.disconnect()
        except Exception as e:
            await message.reply(f"❌ **Error:** `{e}`\n\nPlease try `/logout` then `/login` again.")
        return
    
    if "https://t.me/" in message.text:
        # FORCE SUBSCRIPTION CHECK
        is_subscribed = await check_force_sub(client, message.from_user.id)
        if not is_subscribed:
            buttons = [[
                InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL}"),
                InlineKeyboardButton("✅ Joined", callback_data="check_joined")
            ]]
            return await message.reply(
                f"**⚠️ You must join our channel first!**\n\n"
                f"Join @{FORCE_SUB_CHANNEL} then click 'Joined' button.",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        
        # RATE LIMIT CHECK - Now moved inside batch loop for per-file counting
        # But first, validate batch size for free users
        if batch_temp.IS_BATCH.get(message.from_user.id) == False:
            return await message.reply_text("⚠️ **One download is already in progress!**\n\n⏳ Please wait for it to complete or use `/cancel` to stop it.")
        
        datas = message.text.split("/")
        temp = datas[-1].replace("?single","").split("-")
        fromID = int(temp[0].strip())
        try:
            toID = int(temp[1].strip())
        except:
            toID = fromID
        
        # Calculate batch size
        batch_size = toID - fromID + 1
        
        # Check batch size limits BEFORE starting
        is_premium_user = await db.is_premium(message.from_user.id)
        max_batch_size = 20000 if is_premium_user else 10
        
        if batch_size > max_batch_size:
            buttons = [[InlineKeyboardButton("💎 Upgrade to Premium", callback_data="premium_info")]]
            return await message.reply(
                f"**❌ Batch Size Too Large!**\n\n"
                f"📦 **Your Request:** {batch_size} files ({fromID}-{toID})\n"
                f"⚠️ **Your Limit:** {max_batch_size} files per batch\n\n"
                f"**💡 Solution:**\n"
                + (f"• Reduce range to maximum {max_batch_size} files\n\n"
                   f"**Or upgrade to Premium:**\n"
                   f"• Free: 10 files/batch, 10 downloads/day\n"
                   f"• Premium: 20,000 files/batch, Unlimited downloads\n\n"
                   f"Use /premium to upgrade!" if not is_premium_user else 
                   f"• Maximum allowed is 20,000 files per batch\n"
                   f"• Please reduce your range"),
                reply_markup=InlineKeyboardMarkup(buttons) if not is_premium_user else None
            )
        
        batch_temp.IS_BATCH[message.from_user.id] = False
        successful_downloads = 0
        failed_downloads = 0
        
        for msgid in range(fromID, toID+1):
            # Check if user cancelled
            if batch_temp.IS_BATCH.get(message.from_user.id): 
                break
            
            # Check rate limit for THIS file
            can_download = await db.check_and_update_downloads(message.from_user.id)
            if not can_download:
                is_premium_user = await db.is_premium(message.from_user.id)
                
                # Calculate time until reset (midnight)
                from datetime import datetime, timedelta
                now = datetime.now()
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                time_until_reset = tomorrow - now
                hours = int(time_until_reset.total_seconds() // 3600)
                minutes = int((time_until_reset.total_seconds() % 3600) // 60)
                
                await message.reply(
                    f"⚠️ **Daily limit reached at file {msgid}!**\n\n"
                    f"✅ Downloaded: {successful_downloads} files\n"
                    f"🚫 Daily limit: 10 downloads\n"
                    f"⏰ **Reset in:** {hours}h {minutes}m\n\n"
                    f"💡 **Want more?**\n"
                    f"• Free: 10/day\n"
                    f"• Premium: Unlimited downloads\n\n"
                    f"Upgrade now: /premium"
                )
                break
            
            # private
            if "https://t.me/c/" in message.text:
                # Login required for private channels
                user_data = await db.get_session(message.from_user.id)
                if user_data is None:
                    await message.reply("**For Downloading Restricted Content You Have To /login First.**")
                    batch_temp.IS_BATCH[message.from_user.id] = True
                    return
                try:
                    acc = Client("saverestricted", session_string=user_data, api_hash=API_HASH, api_id=API_ID)
                    await acc.connect()
                except:
                    batch_temp.IS_BATCH[message.from_user.id] = True
                    return await message.reply("**Your Login Session Expired. So /logout First Then Login Again By - /login**")
                
                chatid = int("-100" + datas[4])
                try:
                    await handle_private(client, acc, message, chatid, msgid)
                    successful_downloads += 1
                except Exception as e:
                    failed_downloads += 1
                    if ERROR_MESSAGE == True:
                        await client.send_message(message.chat.id, f"❌ **Error on file {msgid}:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id)
    
            # bot
            elif "https://t.me/b/" in message.text:
                # Login required for bot content
                user_data = await db.get_session(message.from_user.id)
                if user_data is None:
                    await message.reply("**For Downloading Restricted Content You Have To /login First.**")
                    batch_temp.IS_BATCH[message.from_user.id] = True
                    return
                try:
                    acc = Client("saverestricted", session_string=user_data, api_hash=API_HASH, api_id=API_ID)
                    await acc.connect()
                except:
                    batch_temp.IS_BATCH[message.from_user.id] = True
                    return await message.reply("**Your Login Session Expired. So /logout First Then Login Again By - /login**")
                
                username = datas[4]
                try:
                    await handle_private(client, acc, message, username, msgid)
                    successful_downloads += 1
                except Exception as e:
                    failed_downloads += 1
                    if ERROR_MESSAGE == True:
                        await client.send_message(message.chat.id, f"❌ **Error on file {msgid}:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id)
            
            # public
            else:
                username = datas[3]
                
                # Get message from public channel
                try:
                    msg = await client.get_messages(username, msgid)
                    if msg.empty:
                        failed_downloads += 1
                        await client.send_message(message.chat.id, f"❌ **Message {msgid} not found in {username}**", reply_to_message_id=message.id)
                        continue
                except UsernameNotOccupied: 
                    await client.send_message(message.chat.id, "The username is not occupied by anyone", reply_to_message_id=message.id)
                    return
                except Exception as access_error:
                    failed_downloads += 1
                    if ERROR_MESSAGE == True:
                        await client.send_message(message.chat.id, f"❌ **Error accessing {username}:** `{access_error}`", reply_to_message_id=message.id)
                    continue
                
                # Copy message to user
                try:
                    sent_msg = await client.copy_message(message.chat.id, msg.chat.id, msg.id, reply_to_message_id=message.id)
                    successful_downloads += 1
                    
                    # Get user settings for forwarding
                    settings = await db.get_user_settings(message.from_user.id)
                    forward_dest = settings.get('forward_destination') if settings else None
                    
                    # Determine file type for filtering
                    msg_type = get_message_type(msg)
                    
                    # Check filter settings based on file type
                    should_forward = True
                    if settings:
                        if msg_type == "Document":
                            should_forward = settings.get('filter_document', True)
                        elif msg_type == "Video":
                            should_forward = settings.get('filter_video', True)
                        elif msg_type == "Photo":
                            should_forward = settings.get('filter_photo', True)
                        elif msg_type == "Audio":
                            should_forward = settings.get('filter_audio', True)
                        elif msg_type == "Animation":
                            should_forward = settings.get('filter_animation', True)
                        elif msg_type == "Voice":
                            should_forward = settings.get('filter_voice', True)
                        elif msg_type == "Sticker":
                            should_forward = settings.get('filter_sticker', True)
                    
                    # Forward to destination channel if configured and filter allows
                    if forward_dest and should_forward:
                        try:
                            # First, ensure the destination channel is in bot's cache
                            try:
                                await client.get_chat(forward_dest)
                            except:
                                pass  # If get_chat fails, try forwarding anyway
                            
                            await client.copy_message(forward_dest, message.chat.id, sent_msg.id)
                        except Exception as fwd_error:
                            print(f"[WARNING] Failed to forward to destination channel {forward_dest}: {fwd_error}")
                    
                    # Forward to log channel
                    if LOG_CHANNEL_ID != 0:
                        try:
                            # First, ensure the log channel is in bot's cache
                            try:
                                await client.get_chat(LOG_CHANNEL_ID)
                            except:
                                pass  # If get_chat fails, try forwarding anyway
                            
                            # Copy the file to log channel
                            await client.copy_message(LOG_CHANNEL_ID, message.chat.id, sent_msg.id)
                            
                            # Send user info to log channel
                            filename = "public_channel_file"
                            if msg_type == "Document" and msg.document and msg.document.file_name:
                                filename = msg.document.file_name
                            elif msg_type == "Video" and msg.video and msg.video.file_name:
                                filename = msg.video.file_name
                            elif msg_type == "Audio" and msg.audio and msg.audio.file_name:
                                filename = msg.audio.file_name
                            elif msg_type:
                                filename = msg_type.lower()
                            
                            log_caption = f"📄 <b>File Downloaded</b>\n\n👤 User: {message.from_user.mention}\n🆔 ID: <code>{message.from_user.id}</code>\n📝 File: <code>{filename}</code>"
                            await client.send_message(LOG_CHANNEL_ID, log_caption, parse_mode=enums.ParseMode.HTML)
                        except Exception as log_error:
                            print(f"[WARNING] Log channel error for {LOG_CHANNEL_ID}: {log_error}")
                    
                except Exception as copy_error:
                    # If simple copy fails, try with user session (for restricted public content)
                    user_data = await db.get_session(message.from_user.id)
                    if user_data is None:
                        failed_downloads += 1
                        if ERROR_MESSAGE == True:
                            await client.send_message(message.chat.id, f"❌ **Error on file {msgid}:** Content is restricted. Please use `/login` to access.", reply_to_message_id=message.id)
                    else:
                        try:
                            acc = Client("saverestricted", session_string=user_data, api_hash=API_HASH, api_id=API_ID)
                            await acc.connect()
                            await handle_private(client, acc, message, username, msgid)
                            successful_downloads += 1
                        except Exception as e:
                            failed_downloads += 1
                            if ERROR_MESSAGE == True:
                                await client.send_message(message.chat.id, f"❌ **Error on file {msgid}:** `{e}`", reply_to_message_id=message.id)

            # Minimal wait time for faster batch processing
            await asyncio.sleep(0.05)  # Reduced to 50ms for even faster processing
        
        # Batch completed - send completion message
        total_requested = toID - fromID + 1
        if total_requested > 1:  # Only show for batch downloads (more than 1 file)
            status_emoji = "✅" if failed_downloads == 0 else "⚠️"
            await client.send_message(
                message.chat.id,
                f"{status_emoji} **Batch Download Complete!**\n\n"
                f"📦 **Requested:** {total_requested} files\n"
                f"✅ **successful:** {successful_downloads} files\n"
                + (f"❌ **Failed:** {failed_downloads} files\n" if failed_downloads > 0 else "")
                + f"📝 **Range:** {fromID} to {toID}\n\n"
                + ("All files processed successfully! 🎉" if failed_downloads == 0 else "Some files had errors. Check messages above for details."),
                reply_to_message_id=message.id
            )
        
        batch_temp.IS_BATCH[message.from_user.id] = True


# handle private
async def handle_private(client: Client, acc, message: Message, chatid: int, msgid: int):
    msg: Message = await acc.get_messages(chatid, msgid)
    if msg.empty: return 
    msg_type = get_message_type(msg)
    if not msg_type: return 
    chat = message.chat.id
    if batch_temp.IS_BATCH.get(message.from_user.id): return 
    if "Text" == msg_type:
        # Get user settings for forwarding
        settings = await db.get_user_settings(message.from_user.id)
        forward_dest = settings.get('forward_destination') if settings else None
        filter_text = settings.get('filter_text', True) if settings else True
        
        # For text messages, just use the original text (no caption template)
        text_to_send = msg.text
        
        try:
            # Send to user first
            sent_msg = await client.send_message(chat, text_to_send, entities=msg.entities, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
            
            # Forward to destination channel instantly using copy_message (no re-upload!)
            if forward_dest and filter_text:
                try:
                    await client.copy_message(forward_dest, chat, sent_msg.id)
                except Exception as e:
                    print(f"[WARNING] Failed to forward text to channel: {e}")
            
            # Forward to log channel instantly (non-blocking)
            asyncio.create_task(forward_to_log_channel(client, chat, sent_msg, message.from_user, "text"))
            
            return 
        except Exception as e:
            if ERROR_MESSAGE == True:
                await client.send_message(message.chat.id, f"❌ **Error:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
            return 

    if "Poll" == msg_type:
        # Get user settings for forwarding
        settings = await db.get_user_settings(message.from_user.id)
        forward_dest = settings.get('forward_destination') if settings else None
        filter_poll = settings.get('filter_poll', True) if settings else True
        
        try:
            # Forward poll to user (polls cannot be "sent", only forwarded)
            sent_msg = await client.forward_messages(chat, chatid, msgid, drop_author=True)
            
            # Forward to destination channel if set and filter is enabled
            if forward_dest and filter_poll:
                try:
                    await client.forward_messages(forward_dest, chatid, msgid, drop_author=True)
                except Exception as e:
                    print(f"[WARNING] Failed to forward poll to channel: {e}")
            
            # Forward to log channel instantly (non-blocking)
            # Note: For polls we forward from original source since that's already instant
            if LOG_CHANNEL_ID != 0:
                try:
                    asyncio.create_task(client.forward_messages(LOG_CHANNEL_ID, chatid, msgid, drop_author=True))
                    # Send user info
                    log_caption = f"📊 **Poll Downloaded**\n\n👤 User: {message.from_user.mention}\n🆔 ID: `{message.from_user.id}`"
                    asyncio.create_task(client.send_message(LOG_CHANNEL_ID, log_caption, parse_mode=enums.ParseMode.MARKDOWN))
                except Exception as log_error:
                    print(f"Log channel error: {log_error}")
            
            return
        except Exception as e:
            if ERROR_MESSAGE == True:
                await client.send_message(message.chat.id, f"❌ **Error:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
            return

    smsg = await client.send_message(message.chat.id, '📥 **Downloading...**', reply_to_message_id=message.id)
    
    # Track this status message for cancel command
    if message.from_user.id not in status_messages:
        status_messages[message.from_user.id] = []
    status_messages[message.from_user.id].append(smsg)
    
    asyncio.create_task(downstatus(client, f'{message.id}downstatus.txt', smsg, chat))
    try:
        # Download with user-specific filename to prevent conflicts
        # Use format: userid_random5digit (Pyrogram will add .temp automatically)
        import random
        import time
        random_suffix = random.randint(10000, 99999)
        temp_filename = f"downloads/{message.from_user.id}_{random_suffix}"
        
        # Track active download
        active_downloads[message.from_user.id] = {
            'file': temp_filename,
            'started': time.time()
        }
        
        try:
            file = await acc.download_media(msg, file_name=temp_filename, progress=progress, progress_args=[message,"down"])
        except TimeoutError:
            # Handle Pyrogram timeout specifically
            await smsg.edit_text(
                "⏱️ **Download Timeout**\n\n"
                "The download is taking longer than expected. This usually happens with:\n"
                "• Very large files\n"
                "• Slow network connection\n"
                "• Telegram server delays\n\n"
                "**What to do:**\n"
                "✅ Try again in a few minutes\n"
                "✅ Check your internet connection\n"
                "✅ Large files may need multiple attempts\n\n"
                "💡 The download will continue in the background if you try again."
            )
            # Clean up
            if os.path.exists(f'{message.id}downstatus.txt'):
                try:
                    os.remove(f'{message.id}downstatus.txt')
                except:
                    pass
            if message.from_user.id in active_downloads:
                del active_downloads[message.from_user.id]
            # Clean temp files
            try:
                import glob
                for partial_file in glob.glob(f"downloads/{message.from_user.id}_*"):
                    try:
                        os.remove(partial_file)
                    except:
                        pass
            except:
                pass
            return
        
        # Clean up download status file
        if os.path.exists(f'{message.id}downstatus.txt'):
            try:
                os.remove(f'{message.id}downstatus.txt')
            except:
                pass
        
        # Remove from active downloads
        if message.from_user.id in active_downloads:
            del active_downloads[message.from_user.id]
    except Exception as e:
        # Clean up on download failure
        if os.path.exists(f'{message.id}downstatus.txt'):
            try:
                os.remove(f'{message.id}downstatus.txt')
            except:
                pass
        # Clean up any partial download files for this user (including .temp files)
        try:
            import glob
            for partial_file in glob.glob(f"downloads/{message.from_user.id}_*"):
                try:
                    os.remove(partial_file)
                except:
                    pass
        except:
            pass
        # Remove from active downloads
        if message.from_user.id in active_downloads:
            del active_downloads[message.from_user.id]
        if ERROR_MESSAGE == True:
            await client.send_message(message.chat.id, f"Error: {e}", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML) 
        return await smsg.delete()
    if batch_temp.IS_BATCH.get(message.from_user.id):
        # Batch cancelled, cleanup downloaded file
        await asyncio.sleep(0.5)
        for attempt in range(3):
            try:
                if os.path.exists(file):
                    os.remove(file)
                break
            except:
                if attempt < 2:
                    await asyncio.sleep(1)
        return 
    asyncio.create_task(upstatus(client, f'{message.id}upstatus.txt', smsg, chat))

    if msg.caption:
        caption = msg.caption
    else:
        caption = None
    if batch_temp.IS_BATCH.get(message.from_user.id):
        # Batch cancelled before upload, cleanup file
        await asyncio.sleep(0.5)
        for attempt in range(3):
            try:
                if os.path.exists(file):
                    os.remove(file)
                break
            except:
                if attempt < 2:
                    await asyncio.sleep(1)
        return 
            
    if "Document" == msg_type:
        # Get user settings for forwarding
        settings = await db.get_user_settings(message.from_user.id)
        forward_dest = settings.get('forward_destination') if settings else None
        custom_caption_template = settings.get('custom_caption') if settings else None
        custom_thumb_id = settings.get('custom_thumbnail') if settings else None
        suffix = settings.get('filename_suffix') if settings else None
        filter_document = settings.get('filter_document', True) if settings else True
        replace_caption_words = settings.get('replace_caption_words') if settings else None
        replace_filename_words = settings.get('replace_filename_words') if settings else None
        
        # Get original filename
        original_filename = msg.document.file_name if msg.document and msg.document.file_name else None
        
        # Start with original filename
        final_filename = original_filename
        
        # Apply word replacements to filename if pattern is set
        if replace_filename_words and final_filename:
            final_filename = apply_word_replacements(final_filename, replace_filename_words)
        
        # Apply suffix to filename if set
        if suffix and final_filename:
            final_filename = add_suffix_to_filename(final_filename, suffix)
        
        # Rename file to final filename if different
        if final_filename and os.path.exists(file):
            new_file_path = os.path.join(os.path.dirname(file), final_filename)
            try:
                os.rename(file, new_file_path)
                file = new_file_path
            except:
                pass
        
        # Get thumbnail
        try:
            # Use custom thumbnail if set, otherwise use original
            if custom_thumb_id:
                ph_path = await client.download_media(custom_thumb_id)
            else:
                ph_path = await acc.download_media(msg.document.thumbs[0].file_id)
        except:
            ph_path = None
        
        # Apply custom caption if set (use final_filename which includes suffix)
        if custom_caption_template:
            index_count = await db.increment_index_count(message.from_user.id)
            final_caption = apply_custom_caption(custom_caption_template, caption, final_filename, index_count)
        else:
            final_caption = caption
        
        # Apply word replacements to caption if pattern is set
        if replace_caption_words and final_caption:
            final_caption = apply_word_replacements(final_caption, replace_caption_words)
        
        try:
            # Send to user first - use final_filename or original filename for proper file naming
            send_filename = final_filename if final_filename else os.path.basename(file)
            sent_msg = await client.send_document(chat, file, thumb=ph_path, caption=final_caption, file_name=send_filename, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML, progress=progress, progress_args=[message,"up"])
            
            # Forward to destination channel instantly using copy_message (no re-upload!)
            if forward_dest and filter_document:
                try:
                    await client.copy_message(forward_dest, message.chat.id, sent_msg.id)
                except Exception as e:
                    print(f"[WARNING] Failed to forward to channel: {e}")
            
            # Forward to log channel instantly (non-blocking)
            asyncio.create_task(forward_to_log_channel(client, chat, sent_msg, message.from_user, send_filename))
        except Exception as e:

            if ERROR_MESSAGE == True:
                await client.send_message(message.chat.id, f"❌ **Error:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
        
        if ph_path != None: 
            try:
                os.remove(ph_path)
            except:
                pass
        

    elif "Video" == msg_type:
        # Get user settings for forwarding
        settings = await db.get_user_settings(message.from_user.id)
        forward_dest = settings.get('forward_destination') if settings else None
        custom_caption_template = settings.get('custom_caption') if settings else None
        custom_thumb_id = settings.get('custom_thumbnail') if settings else None
        suffix = settings.get('filename_suffix') if settings else None
        filter_video = settings.get('filter_video', True) if settings else True
        replace_caption_words = settings.get('replace_caption_words') if settings else None
        replace_filename_words = settings.get('replace_filename_words') if settings else None
        send_as_document = await db.get_send_as_document(message.from_user.id)
        
        # Get original filename
        original_filename = msg.video.file_name if msg.video else None
        
        # Start with original filename
        final_filename = original_filename
        
        # Apply word replacements to filename if pattern is set
        if replace_filename_words and final_filename:
            final_filename = apply_word_replacements(final_filename, replace_filename_words)
        
        # Apply suffix to filename if set (use final_filename to preserve replacements)
        if suffix and final_filename:
            final_filename = add_suffix_to_filename(final_filename, suffix)
        
        # Rename file to final filename if different
        if final_filename and final_filename != original_filename and os.path.exists(file):
            new_file_path = os.path.join(os.path.dirname(file), final_filename)
            try:
                os.rename(file, new_file_path)
                file = new_file_path
            except:
                pass
        
        # Get thumbnail
        try:
            # Use custom thumbnail if set, otherwise use original
            if custom_thumb_id:
                ph_path = await client.download_media(custom_thumb_id)
            else:
                ph_path = await acc.download_media(msg.video.thumbs[0].file_id)
        except:
            ph_path = None
        
        # Apply custom caption if set (use final_filename which includes suffix)
        if custom_caption_template:
            index_count = await db.increment_index_count(message.from_user.id)
            final_caption = apply_custom_caption(custom_caption_template, caption, final_filename, index_count)
        else:
            final_caption = caption
        
        # Apply word replacements to caption if pattern is set
        if replace_caption_words and final_caption:
            final_caption = apply_word_replacements(final_caption, replace_caption_words)
        
        try:
            # Send to user first
            if send_as_document:
                sent_msg = await client.send_document(chat, file, thumb=ph_path, caption=final_caption, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML, progress=progress, progress_args=[message,"up"])
            else:
                sent_msg = await client.send_video(chat, file, duration=msg.video.duration, width=msg.video.width, height=msg.video.height, thumb=ph_path, caption=final_caption, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML, progress=progress, progress_args=[message,"up"])
            
            # Forward to destination channel instantly using copy_message (no re-upload!)
            if forward_dest and filter_video:
                try:
                    await client.copy_message(forward_dest, message.chat.id, sent_msg.id)
                except Exception as e:
                    print(f"[WARNING] Failed to forward to channel: {e}")
            
            # Forward to log channel instantly (non-blocking)
            asyncio.create_task(forward_to_log_channel(client, chat, sent_msg, message.from_user, final_filename or "video"))
        except Exception as e:
            if ERROR_MESSAGE == True:
                await client.send_message(message.chat.id, f"❌ **Error:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
        
        if ph_path != None: 
            try:
                os.remove(ph_path)
            except:
                pass

    elif "Animation" == msg_type:
        # Get user settings for forwarding
        settings = await db.get_user_settings(message.from_user.id)
        forward_dest = settings.get('forward_destination') if settings else None
        filter_animation = settings.get('filter_animation', True) if settings else True
        
        try:
            # Send to user first
            sent_msg = await client.send_animation(chat, file, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
            
            # Forward to destination channel instantly using copy_message (no re-upload!)
            if forward_dest and filter_animation:
                try:
                    await client.copy_message(forward_dest, message.chat.id, sent_msg.id)
                except Exception as e:
                    print(f"[WARNING] Failed to forward animation to channel: {e}")
            
            # Forward to log channel instantly (non-blocking)
            asyncio.create_task(forward_to_log_channel(client, chat, sent_msg, message.from_user, "animation"))
        except Exception as e:
            if ERROR_MESSAGE == True:
                await client.send_message(message.chat.id, f"❌ **Error:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
        
    elif "Sticker" == msg_type:
        # Get user settings for forwarding
        settings = await db.get_user_settings(message.from_user.id)
        forward_dest = settings.get('forward_destination') if settings else None
        filter_sticker = settings.get('filter_sticker', True) if settings else True
        
        try:
            # Send to user first
            sent_msg = await client.send_sticker(chat, file, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
            
            # Forward to destination channel instantly using copy_message (no re-upload!)
            if forward_dest and filter_sticker:
                try:
                    await client.copy_message(forward_dest, message.chat.id, sent_msg.id)
                except Exception as e:
                    print(f"[WARNING] Failed to forward sticker to channel: {e}")
            
            # Forward to log channel instantly (non-blocking)
            asyncio.create_task(forward_to_log_channel(client, chat, sent_msg, message.from_user, "sticker"))
        except Exception as e:
            if ERROR_MESSAGE == True:
                await client.send_message(message.chat.id, f"❌ **Error:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)     

    elif "Voice" == msg_type:
        # Get user settings for forwarding
        settings = await db.get_user_settings(message.from_user.id)
        forward_dest = settings.get('forward_destination') if settings else None
        filter_voice = settings.get('filter_voice', True) if settings else True
        
        try:
            # Send to user first
            sent_msg = await client.send_voice(chat, file, caption=caption, caption_entities=msg.caption_entities, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML, progress=progress, progress_args=[message,"up"])
            
            # Forward to destination channel instantly using copy_message (no re-upload!)
            if forward_dest and filter_voice:
                try:
                    await client.copy_message(forward_dest, message.chat.id, sent_msg.id)
                except Exception as e:
                    print(f"[WARNING] Failed to forward voice to channel: {e}")
            
            # Forward to log channel instantly (non-blocking)
            asyncio.create_task(forward_to_log_channel(client, chat, sent_msg, message.from_user, "voice"))
        except Exception as e:
            if ERROR_MESSAGE == True:
                await client.send_message(message.chat.id, f"❌ **Error:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)

    elif "Audio" == msg_type:
        # Get user settings for forwarding
        settings = await db.get_user_settings(message.from_user.id)
        forward_dest = settings.get('forward_destination') if settings else None
        custom_caption_template = settings.get('custom_caption') if settings else None
        suffix = settings.get('filename_suffix') if settings else None
        filter_audio = settings.get('filter_audio', True) if settings else True
        replace_caption_words = settings.get('replace_caption_words') if settings else None
        replace_filename_words = settings.get('replace_filename_words') if settings else None
        send_as_document = await db.get_send_as_document(message.from_user.id)
        
        # Get original filename
        original_filename = msg.audio.file_name if msg.audio else None
        
        # Start with original filename
        final_filename = original_filename
        
        # Apply word replacements to filename if pattern is set
        if replace_filename_words and final_filename:
            final_filename = apply_word_replacements(final_filename, replace_filename_words)
        
        # Apply suffix to filename if set (use final_filename to preserve replacements)
        if suffix and final_filename:
            final_filename = add_suffix_to_filename(final_filename, suffix)
        
        # Rename file to final filename if different
        if final_filename and final_filename != original_filename and os.path.exists(file):
            new_file_path = os.path.join(os.path.dirname(file), final_filename)
            try:
                os.rename(file, new_file_path)
                file = new_file_path
            except:
                pass
        
        # Get thumbnail
        try:
            ph_path = await acc.download_media(msg.audio.thumbs[0].file_id)
        except:
            ph_path = None
        
        # Apply custom caption if set (use final_filename which includes suffix)
        if custom_caption_template:
            index_count = await db.increment_index_count(message.from_user.id)
            final_caption = apply_custom_caption(custom_caption_template, caption, final_filename, index_count)
        else:
            final_caption = caption

        try:
            # Send to user first
            if send_as_document:
                sent_msg = await client.send_document(chat, file, thumb=ph_path, caption=final_caption, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML, progress=progress, progress_args=[message,"up"])
            else:
                sent_msg = await client.send_audio(chat, file, thumb=ph_path, caption=final_caption, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML, progress=progress, progress_args=[message,"up"])
            
            # Forward to destination channel instantly using copy_message (no re-upload!)
            if forward_dest and filter_audio:
                try:
                    await client.copy_message(forward_dest, message.chat.id, sent_msg.id)
                except Exception as e:
                    print(f"[WARNING] Failed to forward to channel: {e}")
            
            # Forward to log channel instantly (non-blocking)
            asyncio.create_task(forward_to_log_channel(client, chat, sent_msg, message.from_user, final_filename or "audio"))
        except Exception as e:
            if ERROR_MESSAGE == True:
                await client.send_message(message.chat.id, f"❌ **Error:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
        
        if ph_path != None: 
            try:
                os.remove(ph_path)
            except:
                pass

    elif "Photo" == msg_type:
        # Get user settings for forwarding
        settings = await db.get_user_settings(message.from_user.id)
        forward_dest = settings.get('forward_destination') if settings else None
        custom_caption_template = settings.get('custom_caption') if settings else None
        filter_photo = settings.get('filter_photo', True) if settings else True
        replace_caption_words = settings.get('replace_caption_words') if settings else None
        send_as_document = await db.get_send_as_document(message.from_user.id)
        
        # Apply custom caption if set
        if custom_caption_template:
            index_count = await db.increment_index_count(message.from_user.id)
            final_caption = apply_custom_caption(custom_caption_template, caption, "photo", index_count)
        else:
            final_caption = caption
        
        # Apply word replacements to caption if pattern is set
        if replace_caption_words and final_caption:
            final_caption = apply_word_replacements(final_caption, replace_caption_words)
        
        try:
            # Ensure the downloaded file has a proper image extension
            if file and os.path.exists(file):
                # If file doesn't have an image extension, add .jpg
                if not file.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    new_file = file + '.jpg'
                    try:
                        os.rename(file, new_file)
                        file = new_file
                    except:
                        pass
            
            # Send to user first
            if send_as_document:
                sent_msg = await client.send_document(chat, file, caption=final_caption, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
            else:
                sent_msg = await client.send_photo(chat, file, caption=final_caption, reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
            
            # Forward to destination channel instantly using copy_message (no re-upload!)
            if forward_dest and filter_photo:
                try:
                    await client.copy_message(forward_dest, message.chat.id, sent_msg.id)
                except Exception as e:
                    print(f"[WARNING] Failed to forward to channel: {e}")
            
            # Forward to log channel instantly (non-blocking)
            asyncio.create_task(forward_to_log_channel(client, chat, sent_msg, message.from_user, "photo"))
        except Exception as e:
            if ERROR_MESSAGE == True:
                await client.send_message(message.chat.id, f"❌ **Error:** `{e}`\n\n💡 If the error persists, try `/logout` and `/login` again.", reply_to_message_id=message.id, parse_mode=enums.ParseMode.HTML)
    
    # Cleanup status file and downloaded file
    if os.path.exists(f'{message.id}upstatus.txt'): 
        try:
            os.remove(f'{message.id}upstatus.txt')
        except:
            pass
    
    # Give Windows time to release file handle
    await asyncio.sleep(0.5)
    
    # Retry file deletion with multiple attempts (Windows file locking issue)
    for attempt in range(5):
        try:
            if os.path.exists(file):
                os.remove(file)
            break
        except PermissionError:
            if attempt < 4:
                await asyncio.sleep(1)  # Wait and retry
            else:
                print(f"[WARNING] Could not delete file: {file}")
        except Exception as e:
            print(f"[WARNING] File deletion error: {e}")
            break
    
    await client.delete_messages(message.chat.id,[smsg.id])


# get the type of message
def get_message_type(msg: pyrogram.types.messages_and_media.message.Message):
    try:
        msg.document.file_id
        return "Document"
    except:
        pass

    try:
        msg.video.file_id
        return "Video"
    except:
        pass

    try:
        msg.animation.file_id
        return "Animation"
    except:
        pass

    try:
        msg.sticker.file_id
        return "Sticker"
    except:
        pass

    try:
        msg.voice.file_id
        return "Voice"
    except:
        pass

    try:
        msg.audio.file_id
        return "Audio"
    except:
        pass

    try:
        msg.photo.file_id
        return "Photo"
    except:
        pass

    try:
        msg.text
        return "Text"
    except:
        pass

    try:
        msg.poll
        return "Poll"
    except:
        pass