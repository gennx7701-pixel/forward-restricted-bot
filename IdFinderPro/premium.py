import time
import random
import string
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
from database.db import db
from config import ADMINS

# Store active redeem codes (in production, use database)
redeem_codes = {}

# Generate redeem code
@Client.on_message(filters.private & filters.command(["generate"]) & filters.user(ADMINS))
async def generate_redeem_code(client: Client, message: Message):
    """Admin command to generate redeem codes"""
    buttons = [[
        InlineKeyboardButton("1 Day", callback_data="gen_1"),
        InlineKeyboardButton("7 Days", callback_data="gen_7"),
        InlineKeyboardButton("30 Days", callback_data="gen_30")
    ]]
    await message.reply(
        "**🎟️ Generate Redeem Code**\n\nSelect duration:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# Premium membership menu
@Client.on_message(filters.private & filters.command(["premium"]))
async def premium_menu(client: Client, message: Message):
    is_premium_user = await db.is_premium(message.from_user.id)
    downloads_today = await db.get_download_count(message.from_user.id)
    
    if is_premium_user:
        user = await db.col.find_one({'id': message.from_user.id})
        expiry = user.get('premium_expiry')
        
        if expiry:
            from datetime import datetime
            expiry_date = datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M')
            expiry_text = f"**Expires:** {expiry_date}"
        else:
            expiry_text = "**Lifetime Premium**"
        
        text = f"""**💎 Premium Member**

✅ You have Premium!

{expiry_text}
**Usage Today:** {downloads_today}/100

**Benefits:**
✅ 100 downloads/day
✅ Priority support
✅ Faster processing

Use `/redeem` to extend membership."""
        buttons = [[InlineKeyboardButton("🏠 Main Menu", callback_data="start")]]
    else:
        text = f"""**💎 Premium Membership**

**Current Plan:** Free
**Usage Today:** {downloads_today}/10

**Premium Benefits:**
✅ 100 downloads/day (vs 10)
✅ Priority support  
✅ Faster processing

**💰 Pricing:**
• **₹20** (≈ 0.24 USDT) - 1 Day
• **₹50** (≈ 0.60 USDT) - 7 Days
• **₹100** (≈ 1.20 USDT) - 30 Days

**How to Purchase:**
1. Contact @tataa_sumo
2. Choose your plan
3. Get payment details
4. Receive redeem code
5. Use `/redeem <code>`

**Note:** Payment via UPI/Bank Transfer/Crypto"""
        buttons = [[
            InlineKeyboardButton("💬 Contact Admin", url="https://t.me/tataa_sumo")
        ],[
            InlineKeyboardButton("🏠 Main Menu", callback_data="start")
        ]]
    
    await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))

# Redeem code
@Client.on_message(filters.private & filters.command(["redeem"]))
async def redeem_code(client: Client, message: Message):
    try:
        code = message.text.split()[1].upper()
    except:
        return await message.reply("**Usage:** `/redeem <code>`\n\nExample: `/redeem ABC123`")
    
    if code not in redeem_codes:
        return await message.reply("❌ **Invalid or expired code!**")
    
    # Get code info
    code_info = redeem_codes[code]
    days = code_info['days']
    
    # Calculate expiry
    duration = days * 24 * 60 * 60  # Convert to seconds
    expiry_time = time.time() + duration
    
    # Set premium
    await db.set_premium(message.from_user.id, True, expiry_time)
    
    # Remove used code
    del redeem_codes[code]
    
    from datetime import datetime
    expiry_date = datetime.fromtimestamp(expiry_time).strftime('%Y-%m-%d %H:%M:%S')
    
    await message.reply(f"""
✅ **Premium Activated!**

**Duration:** {days} day(s)
**Expires:** {expiry_date}

**Benefits:**
• 100 downloads per day
• Priority support
• Faster downloads

Thank you for upgrading! 🎉
""")

# View all premium members (Admin only)
@Client.on_message(filters.private & filters.command(["premiumlist"]) & filters.user(ADMINS))
async def list_premium_users(client: Client, message: Message):
    premium_users = await db.get_all_premium_users()
    
    if not premium_users:
        return await message.reply("📭 **No premium users found.**")
    
    buttons = []
    for user in premium_users[:20]:  # Show first 20
        user_id = user['id']
        user_name = user['name']
        buttons.append([
            InlineKeyboardButton(
                f"❌ {user_name} ({user_id})",
                callback_data=f"removepremium_{user_id}"
            )
        ])
    
    await message.reply(
        f"**💎 Premium Members ({len(premium_users)})**\n\nClick to remove:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# Payment with Telegram Stars
@Client.on_callback_query(filters.regex(r"^pay_stars_"))
async def handle_stars_payment(client: Client, query):
    stars_amount = int(query.data.split("_")[-1])
    
    # Create invoice
    await query.message.reply_invoice(
        title="Premium Membership",
        description=f"Get {stars_amount} hour(s) of premium access",
        payload=f"premium_{stars_amount}h",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label="Premium", amount=stars_amount)]
    )
    
    await query.answer()

# Handle successful payment
@Client.on_pre_checkout_query()
async def on_pre_checkout_query(client: Client, query: PreCheckoutQuery):
    await query.answer(ok=True)

@Client.on_message(filters.successful_payment)
async def on_successful_payment(client: Client, message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    
    # Extract hours from payload
    hours = int(payload.split("_")[1].replace("h", ""))
    
    # Calculate expiry
    duration = hours * 60 * 60  # Convert to seconds
    expiry_time = time.time() + duration
    
    # Set premium
    await db.set_premium(message.from_user.id, True, expiry_time)
    
    from datetime import datetime
    expiry_date = datetime.fromtimestamp(expiry_time).strftime('%Y-%m-%d %H:%M:%S')
    
    await message.reply(f"""
✅ **Payment Successful!**

**Premium Activated:** {hours} hour(s)
**Expires:** {expiry_date}

**Benefits:**
• 100 downloads per day
• Priority support  
• Faster downloads

Thank you for your support! 🎉
""")

# Callback handlers
@Client.on_callback_query(filters.regex(r"^(gen_|removepremium_)"))
async def premium_callback_handler(client: Client, query):
    data = query.data
    
    if data.startswith("gen_"):
        days = int(data.split("_")[1])
        
        # Generate random code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        # Store code
        redeem_codes[code] = {
            'days': days,
            'generated_by': query.from_user.id,
            'generated_at': time.time()
        }
        
        await query.message.edit_text(f"""
✅ **Redeem Code Generated!**

**Code:** `{code}`
**Duration:** {days} day(s)

Share this code with users. They can redeem it using:
`/redeem {code}`

**Note:** Code is single-use and will be deleted after redemption.
""")
    
    elif data.startswith("removepremium_"):
        user_id = int(data.split("_")[1])
        
        # Remove premium
        await db.set_premium(user_id, False, None)
        
        await query.message.edit_text(f"✅ **Premium removed for user {user_id}**")
    
    await query.answer()

