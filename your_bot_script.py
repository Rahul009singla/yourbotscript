from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from html import escape
import pymongo
import random
import string
from datetime import datetime
import stripe
import asyncio

import os
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")


# MongoDB setup
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["marketplace_bot"]
users = db["users"]
orders = db["orders"]

BOT_TOKEN = "8079620440:AAEVIXQ5-W3JtnWGZk6oykTJzxXswMdobvQ"
ADMIN_TELEGRAM_ID = 7873637618

def generate_credentials():
    username = "user_" + ''.join(random.choices(string.digits, k=3))
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    return username, password

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("💼 Wallet", callback_data='wallet')],
        [InlineKeyboardButton("🛒 Orders", callback_data='orders')],
        [InlineKeyboardButton("🧾 Previous Orders", callback_data='history')],
        [InlineKeyboardButton("💬 Support", callback_data='support')],
        [InlineKeyboardButton("➕ Recharge Wallet", callback_data='recharge')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_package_menu():
    keyboard = [
        [InlineKeyboardButton("🔹 10 Upvotes – $0.50", callback_data='buy_10')],
        [InlineKeyboardButton("🔹 50 Upvotes – $2.25", callback_data='buy_50')],
        [InlineKeyboardButton("🔹 100 Upvotes – $4.00", callback_data='buy_100')],
        [InlineKeyboardButton("⬅️ Back", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def process_purchase(query, user, amount, upvotes):
    balance = user.get("wallet", 0.0)
    if balance >= amount:
        new_balance = balance - amount
        users.update_one({"telegram_id": user["telegram_id"]}, {"$set": {"wallet": new_balance}})
        orders.insert_one({
            "telegram_id": user["telegram_id"],
            "username": user["username"],
            "package": f"{upvotes} Reddit Upvotes",
            "amount": amount,
            "timestamp": datetime.now().isoformat(),
            "order_id": f"ORD{random.randint(10000, 99999)}",
            "status": "pending"
        })
        await query.edit_message_text(
            f"✅ Order placed for {upvotes} upvotes!\n💰 ${amount:.2f} deducted.\n🧾 Balance: ${new_balance:.2f}"
        )
    else:
        await query.edit_message_text(
            f"❌ Insufficient funds.\nYou need ${amount:.2f}, but have ${balance:.2f}."
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Your Telegram ID is: {update.effective_user.id}")
    telegram_id = update.effective_user.id
    user = users.find_one({"telegram_id": telegram_id})
    if user:
        msg = f"👋 Welcome back!\n\n🧑 Username: {user['username']}\n🔐 Password: {user['password']}"
    else:
        username, password = generate_credentials()
        users.insert_one({
            "telegram_id": telegram_id,
            "username": username,
            "password": password,
            "joined": datetime.utcnow(),
            "wallet": 0.0
        })
        msg = f"🎉 Welcome! Here are your credentials:\n\n🧑 Username: {username}\n🔐 Password: {password}"

    await update.message.reply_text(msg)
    await update.message.reply_text("👇 Select from the menu below:", reply_markup=get_main_menu())

async def show_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Unauthorized access.")
        return
    message = ""
    for user in users.find({}, {"username": 1, "wallet": 1}):
        message += f"{user['username']} – ₹{user.get('wallet', 0):.2f}\n"
    await update.message.reply_text("📋 All Users:\n\n" + message if message else "No users found.")

#admin pannel
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("🚫 You are not authorized to access this.")
        return

    keyboard = [
        [InlineKeyboardButton("✅ Pending Orders", callback_data="admin_pending_orders")],
        [InlineKeyboardButton("📣 Broadcast Message", callback_data="admin_broadcast")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "<b>Admin Panel</b>\nChoose an action below:",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

    
#pending orders
async def pending_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message if update.message else update.callback_query.message    # Support both command and button click

    pending = list(orders.find({"status": "pending"}))

    if not pending:
        await message.reply_text("✅ No pending orders.")
        return

    for order in pending:
        text = (
            f"🆔 Order ID: {order.get('order_id', 'N/A')}\n"
            f"👤 User: {order.get('username', 'N/A')}\n"
            f"💰 Amount: ${order.get('amount', 0):.2f}\n"
            f"🔗 Post: {order.get('post_url', 'N/A')}"   #post url uploaded here
        )


        buttons = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{order['order_id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{order['order_id']}")
            ]
        ]

        await message.reply_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

async def handle_order_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # print("✅ handle_order_decision triggered")
    print(f"Callback data: {update.callback_query.data}")

    query = update.callback_query
    await query.answer()

    data = query.data
    # print(f"DEBUG callback data: {data}")

    if "_" not in data:
        await query.edit_message_text("⚠️ Invalid order data.")
        return

    action, order_id = data.split("_", 1)


    # ✅ Fetch order from DB
    order = orders.find_one({"order_id": order_id})
    if not order:
        await query.edit_message_text("⚠️ Order not found.")
        return

    if action == "approve":
        orders.update_one({"order_id": order_id}, {"$set": {"status": "approved"}})

        await query.edit_message_text("✅ Order approved.")
        await context.bot.send_message(
            chat_id=order["telegram_id"],
            text=f"✅ Your order for <b>{escape(order['package'])}</b> has been approved and is being processed.",
            parse_mode=ParseMode.HTML
        )

    elif action == "reject":
        orders.update_one({"order_id": order_id}, {"$set": {"status": "rejected"}})

        # Refund to wallet
        users.update_one(
            {"telegram_id": order["telegram_id"]},
            {"$inc": {"wallet": order["amount"]}}
        )

        await query.edit_message_text(
            f"❌ Rejected order for @{order['username']}.\n💰 Refunded ${order['amount']:.2f}."
        )

        # ✅ Notify the user
        try:
            print(f"Sending rejection message to user ID {order['telegram_id']}")
            await context.bot.send_message(
                chat_id=order["telegram_id"],
                text=f"❌ Your order for <b>{escape(order['package'])}</b> was rejected.\n💰 ${order['amount']:.2f} has been refunded to your wallet.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            print(f"❌ Failed to send message to user: {e}")

# # ✅ Notify user directly
#     print(f"Sending rejection message to user ID {order['telegram_id']}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # print(f"⚠️ Uncaught callback data: {query.data}")

    telegram_id = query.from_user.id
    user = users.find_one({"telegram_id": telegram_id})
    choice = query.data

    if choice == 'wallet':
        balance = user.get("wallet", 0.0)
        await query.edit_message_text(f"💼 Your Wallet\nBalance: ₹{balance:.2f}")

    elif choice == 'orders':
        await query.edit_message_text("📦 Choose a Reddit Upvote package:", reply_markup=get_package_menu())

    elif choice == 'buy_10':
        await process_purchase(query, user, amount=0.50, upvotes=10)
    elif choice == 'buy_50':
        await process_purchase(query, user, amount=2.25, upvotes=50)
    elif choice == 'buy_100':
        await process_purchase(query, user, amount=4.00, upvotes=100)

    elif choice == 'main_menu':
        await query.edit_message_text("👇 What would you like to do next?", reply_markup=get_main_menu())

    elif choice == 'support':
        await query.edit_message_text("🛠️ Support\nContact us at @YourSupportUsername")

    elif choice == 'recharge':
        keyboard = [
            [InlineKeyboardButton("$5", callback_data='recharge_5')],
            [InlineKeyboardButton("$10", callback_data='recharge_10')],
            [InlineKeyboardButton("$20", callback_data='recharge_20')],
            [InlineKeyboardButton("⬅️ Back", callback_data='main_menu')]
        ]
        await query.edit_message_text("💳 Choose amount to recharge:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif choice.startswith('recharge_'):
        amount = int(choice.split('_')[1])
        url = create_payment_link(user['telegram_id'], amount)
        await query.edit_message_text(
            f"💳 Click to recharge <b>${amount}</b>:\n\n{url}\n\n✅ Balance updates after payment.",
            parse_mode=ParseMode.HTML
        )

    elif choice == 'history':
        recent_orders = orders.find({"telegram_id": telegram_id}).sort("timestamp", -1).limit(3)
        order_list = ""
        for order in recent_orders:
            order_list += (
                f"📦 Package: {order['package']}\n"
                f"💵 Amount: ${order['amount']:.2f}\n"
                f"🕒 Date: {order['timestamp']}\n\n"
            )
        await query.edit_message_text(
            f"🧾 Last Orders:\n\n{order_list}" if order_list else "❌ No orders yet."
        )

    elif choice == "admin_pending_orders":
        await pending_orders(update, context)  # Already implemented

    elif choice == "admin_broadcast":
        await query.edit_message_text("✍️ Send a broadcast message using:\n<b>/broadcast Your message here</b>", parse_mode="HTML")

def create_payment_link(telegram_id, amount_usd):
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'unit_amount': int(amount_usd * 100),
                'product_data': {'name': f'Wallet Top-Up (${amount_usd})'},
            },
            'quantity': 1,
        }],
        metadata={"telegram_id": str(telegram_id), "amount": str(amount_usd)},
        mode='payment',
        success_url='https://yourdomain.com/success',
        cancel_url='https://yourdomain.com/cancel',
    )
    return session.url

#broadcast message

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /broadcast Your message here")
        return

    message_to_send = " ".join(context.args)
    success = 0
    failed = 0

    for user in users.find({}, {"telegram_id": 1}):
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text=message_to_send,
                parse_mode=ParseMode.HTML  # or remove if you're not using HTML formatting
            )
            
            success += 1
        except Exception as e:
            print(f"❌ Failed to message user {user['telegram_id']}: {e}")
            failed += 1
        await asyncio.sleep(0.1)
    await update.message.reply_text(
        f"📣 Broadcast sent!\n✅ Delivered: {success}\n❌ Failed: {failed}"
    )

# Start bot
app = ApplicationBuilder().token(BOT_TOKEN).build()

#handler
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("users", show_all_users))
app.add_handler(CommandHandler("pending_orders", pending_orders))
# app.add_handler(CallbackQueryHandler(button_handler, pattern="^(?!approve:|reject:)"))
app.add_handler(CallbackQueryHandler(handle_order_decision, pattern="^(approve|reject)_"))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CommandHandler("admin", admin_panel))

print("Bot is running...")
app.run_polling()
