import asyncio
import logging
import re
import uuid

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import database

from config import (
    BOT_TOKEN,
    OWNER_ID,
    FORCE_CHAT,
)


# =========================================================
# تنظیمات
# =========================================================

CURRENCY = "DOGS"
MAX_ROUNDS = 4

# فقط نمایش ضریب، بدون پرداخت واقعی
DICE_MULTIPLIER = 2
BOWLING_MULTIPLIER = 2
DART_MULTIPLIER = 2
BASKETBALL_MULTIPLIER = 1.5


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# اعداد فارسی / عربی / انگلیسی
# =========================================================

PERSIAN = "۰۱۲۳۴۵۶۷۸۹"
ARABIC = "٠١٢٣٤٥٦٧٨٩"
ENGLISH = "0123456789"


def normalize_digits(text):
    text = str(text or "")

    for i, char in enumerate(PERSIAN):
        text = text.replace(char, ENGLISH[i])

    for i, char in enumerate(ARABIC):
        text = text.replace(char, ENGLISH[i])

    return text


def normalize_text(text):
    text = normalize_digits(text).strip()

    return (
        text
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
    )


def parse_amount(value):
    value = normalize_digits(value)

    if not re.fullmatch(r"\d+", value):
        return None

    amount = int(value)

    if amount <= 0:
        return None

    return amount


def money(value):
    return f"{int(value):,}"


def display_name(user):
    name = user.first_name or "کاربر"

    if user.last_name:
        name += " " + user.last_name

    return name


def is_owner(user_id):
    try:
        return int(user_id) == int(OWNER_ID)
    except Exception:
        return False


def ensure_user(user):
    database.register_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )


# =========================================================
# عضویت اجباری
# =========================================================

async def check_join(update, context):
    user = update.effective_user

    if user is None:
        return False

    if is_owner(user.id):
        return True

    if not FORCE_CHAT:
        return True

    try:
        member = await context.bot.get_chat_member(
            FORCE_CHAT,
            user.id,
        )

        if member.status in (
            "member",
            "administrator",
            "creator",
        ):
            return True

    except Exception as error:
        logger.warning("Join check error: %s", error)

    await update.effective_message.reply_text(
        "⛔ ابتدا عضو گپ زیر شوید:\n\n"
        f"{FORCE_CHAT}\n\n"
        "بعد دوباره امتحان کنید."
    )

    return False


# =========================================================
# موجودی
# =========================================================

async def balance(update, context):
    if not await check_join(update, context):
        return

    user = update.effective_user

    ensure_user(user)

    amount = database.get_balance(user.id)

    await update.effective_message.reply_text(
        f"💰 موجودی شما: {money(amount)} {CURRENCY}"
    )


# =========================================================
# انتقال با Reply
# =========================================================

async def transfer(update, context):
    if not await check_join(update, context):
        return

    message = update.effective_message
    user = update.effective_user

    reply = message.reply_to_message

    if not reply or not reply.from_user:
        await message.reply_text(
            "❌ روی پیام کاربر Reply کن.\n\n"
            "مثال:\n"
            "انتقال 100"
        )
        return

    target = reply.from_user

    if target.is_bot:
        await message.reply_text(
            "❌ نمی‌توانی به ربات انتقال بدهی."
        )
        return

    if target.id == user.id:
        await message.reply_text(
            "❌ انتقال به خودت امکان‌پذیر نیست."
        )
        return

    parts = normalize_text(message.text).split()

    if len(parts) != 2:
        await message.reply_text(
            "❌ مثال:\nانتقال 100"
        )
        return

    amount = parse_amount(parts[1])

    if amount is None:
        await message.reply_text(
            "❌ مبلغ صحیح نیست."
        )
        return

    ensure_user(user)
    ensure_user(target)

    result = database.transfer_balance(
        user.id,
        target.id,
        amount,
        f"transfer:{uuid.uuid4().hex}",
    )

    if not result["success"]:

        if result.get("reason") == "insufficient_balance":
            await message.reply_text(
                "❌ موجودی کافی نیست."
            )
        else:
            await message.reply_text(
                "❌ انتقال انجام نشد."
            )

        return

    await message.reply_text(
        "✅ انتقال انجام شد.\n\n"
        f"👤 گیرنده: {display_name(target)}\n"
        f"💰 مبلغ: {money(amount)} {CURRENCY}\n"
        f"💳 موجودی شما: "
        f"{money(result['sender_balance'])} {CURRENCY}"
    )


# =========================================================
# بازی‌ها
# =========================================================

GAME_EMOJIS = {
    "تاس": "🎲",
    "بولینگ": "🎳",
    "دارت": "🎯",
}

GAME_MULTIPLIERS = {
    "تاس": DICE_MULTIPLIER,
    "بولینگ": BOWLING_MULTIPLIER,
    "دارت": DART_MULTIPLIER,
}


def parse_game(text):
    parts = normalize_text(text).split()

    if len(parts) != 3:
        return None

    round_number = parse_amount(parts[0])
    game = parts[1]
    amount = parse_amount(parts[2])

    if round_number is None:
        return None

    if amount is None:
        return None

    if game not in GAME_EMOJIS:
        return None

    if round_number < 1 or round_number > MAX_ROUNDS:
        return None

    return round_number, game, amount


async def play_game(update, context):
    message = update.effective_message
    user = update.effective_user

    if not await check_join(update, context):
        return

    parsed = parse_game(message.text)

    if parsed is None:
        return

    round_number, game, amount = parsed

    ensure_user(user)

    if not database.is_bot_enabled():
        await message.reply_text(
            "🔴 بات خاموش است."
        )
        return

    balance_now = database.get_balance(user.id)

    if balance_now < amount:
        await message.reply_text(
            f"❌ موجودی کافی نیست.\n"
            f"💰 موجودی: {money(balance_now)} {CURRENCY}"
        )
        return

    game_id = uuid.uuid4().hex

    created = database.create_game(
        game_id,
        message.chat_id,
        message.message_id,
        user.id,
        f"bot:{game}",
        amount,
    )

    if not created:
        await message.reply_text(
            "❌ این بازی قبلاً ثبت شده."
        )
        return

    emoji = GAME_EMOJIS[game]

    # =====================================================
    # اول کاربر
    # =====================================================

    user_roll = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji=emoji,
        reply_to_message_id=message.message_id,
    )

    await asyncio.sleep(2)

    user_value = user_roll.dice.value

    # =====================================================
    # بعد ربات
    # =====================================================

    bot_roll = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji=emoji,
        reply_to_message_id=message.message_id,
    )

    await asyncio.sleep(1)

    bot_value = bot_roll.dice.value

    # =====================================================
    # مقایسه
    # =====================================================

    if user_value > bot_value:
        result_text = "🏆 شما برنده شدید!"

    elif bot_value > user_value:
        result_text = "🤖 ربات برنده شد!"

    else:
        result_text = "🤝 مساوی شد!"

    multiplier = GAME_MULTIPLIERS[game]

    database.finish_game(
        game_id,
        f"user:{user_value}-bot:{bot_value}",
        0,
    )

    await message.reply_text(
        f"{emoji} {game}\n\n"
        f"👤 شما: {user_value}\n"
        f"🤖 ربات: {bot_value}\n\n"
        f"{result_text}\n\n"
        f"💰 مبلغ بازی: {money(amount)} {CURRENCY}\n"
        f"📈 ضریب نمایش بازی: {multiplier}x\n"
        "ℹ️ این بازی تفریحی است و مبلغ بازی از موجودی کسر نمی‌شود."
    )


# =========================================================
# بسکتبال
# =========================================================

def parse_basket(text):
    parts = normalize_text(text).split()

    if len(parts) != 2:
        return None

    amount = parse_amount(parts[0])
    choice = parts[1]

    if amount is None:
        return None

    if choice not in ("گل", "بیرون"):
        return None

    return amount, choice


async def basketball(update, context):
    message = update.effective_message
    user = update.effective_user

    if not await check_join(update, context):
        return

    parsed = parse_basket(message.text)

    if parsed is None:
        return

    amount, choice = parsed

    ensure_user(user)

    if not database.is_bot_enabled():
        await message.reply_text(
            "🔴 بات خاموش است."
        )
        return

    balance_now = database.get_balance(user.id)

    if balance_now < amount:
        await message.reply_text(
            f"❌ موجودی کافی نیست.\n"
            f"💰 موجودی: {money(balance_now)} {CURRENCY}"
        )
        return

    game_id = uuid.uuid4().hex

    created = database.create_game(
        game_id,
        message.chat_id,
        message.message_id,
        user.id,
        f"basketball:{choice}",
        amount,
    )

    if not created:
        return

    # اول کاربر
    user_roll = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji="🏀",
        reply_to_message_id=message.message_id,
    )

    await asyncio.sleep(2)

    # بعد ربات
    bot_roll = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji="🏀",
        reply_to_message_id=message.message_id,
    )

    await asyncio.sleep(1)

    user_value = user_roll.dice.value
    bot_value = bot_roll.dice.value

    # 4 و 5 = گل
    user_result = (
        "گل"
        if user_value in (4, 5)
        else "بیرون"
    )

    bot_result = (
        "گل"
        if bot_value in (4, 5)
        else "بیرون"
    )

    if user_result == choice:
        result_text = "🏆 انتخاب شما درست بود!"

    else:
        result_text = "❌ انتخاب شما درست نبود."

    database.finish_game(
        game_id,
        f"user:{user_result},bot:{bot_result}",
        0,
    )

    await message.reply_text(
        "🏀 بسکتبال\n\n"
        f"👤 شما: {user_result}\n"
        f"🤖 ربات: {bot_result}\n\n"
        f"{result_text}\n\n"
        f"💰 مبلغ بازی: {money(amount)} {CURRENCY}\n"
        f"📈 ضریب نمایش: {BASKETBALL_MULTIPLIER}x\n"
        "ℹ️ مبلغ بازی از موجودی کسر نمی‌شود."
    )


# =========================================================
# پنل مالک
# =========================================================

async def admin(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    await update.effective_message.reply_text(
        "👑 پنل مدیریت\n\n"
        "روشن\n"
        "خاموش\n"
        "کاربران\n"
        "وضعیت\n\n"
        "برای شارژ:\n"
        "Reply + شارژ 100\n\n"
        "برای کسر:\n"
        "Reply + کسر 100"
    )


async def admin_charge(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    message = update.effective_message
    reply = message.reply_to_message

    if not reply or not reply.from_user:
        await message.reply_text(
            "❌ باید روی پیام کاربر Reply کنی."
        )
        return

    parts = normalize_text(message.text).split()

    if len(parts) != 2:
        await message.reply_text(
            "❌ مثال: شارژ 100"
        )
        return

    amount = parse_amount(parts[1])

    if amount is None:
        await message.reply_text(
            "❌ مبلغ صحیح نیست."
        )
        return

    target = reply.from_user

    if target.is_bot:
        await message.reply_text(
            "❌ نمی‌توانی حساب ربات را شارژ کنی."
        )
        return

    ensure_user(target)

    result = database.add_balance(
        target.id,
        amount,
        f"admin_charge:{uuid.uuid4().hex}",
        "شارژ توسط مالک",
    )

    await message.reply_text(
        "✅ شارژ شد.\n\n"
        f"👤 {display_name(target)}\n"
        f"➕ {money(amount)} {CURRENCY}\n"
        f"💳 موجودی: "
        f"{money(result['balance'])} {CURRENCY}"
    )


async def admin_deduct(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    message = update.effective_message
    reply = message.reply_to_message

    if not reply or not reply.from_user:
        await message.reply_text(
            "❌ باید روی پیام کاربر Reply کنی."
        )
        return

    parts = normalize_text(message.text).split()

    if len(parts) != 2:
        await message.reply_text(
            "❌ مثال: کسر 100"
        )
        return

    amount = parse_amount(parts[1])

    if amount is None:
        await message.reply_text(
            "❌ مبلغ صحیح نیست."
        )
        return

    target = reply.from_user

    if target.is_bot:
        await message.reply_text(
            "❌ نمی‌توانی حساب ربات را کسر کنی."
        )
        return

    ensure_user(target)

    result = database.withdraw_balance(
        target.id,
        amount,
        f"admin_deduct:{uuid.uuid4().hex}",
        "کسر توسط مالک",
    )

    if not result["success"]:
        await message.reply_text(
            "❌ موجودی کاربر کافی نیست."
        )
        return

    await message.reply_text(
        "✅ کسر شد.\n\n"
        f"👤 {display_name(target)}\n"
        f"➖ {money(amount)} {CURRENCY}\n"
        f"💳 موجودی: "
        f"{money(result['balance'])} {CURRENCY}"
    )


async def admin_on(update, context):
    if not is_owner(update.effective_user.id):
        return

    database.set_bot_enabled(True)

    await update.effective_message.reply_text(
        "🟢 بات روشن شد."
    )


async def admin_off(update, context):
    if not is_owner(update.effective_user.id):
        return

    database.set_bot_enabled(False)

    await update.effective_message.reply_text(
        "🔴 بات خاموش شد."
    )


async def admin_users(update, context):
    if not is_owner(update.effective_user.id):
        return

    users = database.get_all_users()

    if not users:
        await update.effective_message.reply_text(
            "👥 کاربری وجود ندارد."
        )
        return

    text = "👥 کاربران:\n\n"

    for row in users:
        name = row["first_name"] or "کاربر"

        text += (
            f"👤 {name}\n"
            f"🆔 {row['user_id']}\n"
            f"💰 {money(row['balance'])} {CURRENCY}\n\n"
        )

    for i in range(0, len(text), 3500):
        await update.effective_message.reply_text(
            text[i:i + 3500]
        )


async def admin_status(update, context):
    if not is_owner(update.effective_user.id):
        return

    status = (
        "🟢 روشن"
        if database.is_bot_enabled()
        else "🔴 خاموش"
    )

    await update.effective_message.reply_text(
        f"📊 وضعیت بات: {status}"
    )


# =========================================================
# Router ضد دستور
# هر پیام فقط یک مسیر
# =========================================================

async def router(update, context):
    message = update.effective_message

    if not message or not message.text:
        return

    user = update.effective_user

    if not user:
        return

    text = normalize_text(message.text)

    ensure_user(user)

    # -----------------------------------------------------
    # مالک
    # -----------------------------------------------------

    if is_owner(user.id):

        if text in ("پنل", "پنل مدیریت"):
            await admin(update, context)
            return

        if text == "روشن":
            await admin_on(update, context)
            return

        if text == "خاموش":
            await admin_off(update, context)
            return

        if text == "کاربران":
            await admin_users(update, context)
            return

        if text == "وضعیت":
            await admin_status(update, context)
            return

        if text.startswith("شارژ "):
            await admin_charge(update, context)
            return

        if text.startswith("کسر "):
            await admin_deduct(update, context)
            return

    # -----------------------------------------------------
    # موجودی
    # -----------------------------------------------------

    if text in ("م", "موجودی"):
        await balance(update, context)
        return

    # -----------------------------------------------------
    # انتقال
    # -----------------------------------------------------

    if text.startswith("انتقال "):
        await transfer(update, context)
        return

    # -----------------------------------------------------
    # تاس / بولینگ / دارت
    # -----------------------------------------------------

    game = parse_game(text)

    if game is not None:
        await play_game(update, context)
        return

    # -----------------------------------------------------
    # بسکتبال
    # -----------------------------------------------------

    basket = parse_basket(text)

    if basket is not None:
        await basketball(update, context)
        return

    # -----------------------------------------------------
    # هیچ دستوری نبود
    # -----------------------------------------------------

    return


# =========================================================
# Start
# =========================================================

async def start(update, context):

    if not await check_join(update, context):
        return

    await update.effective_message.reply_text(
        "🎮 LATAR آماده است.\n\n"

        "💰 موجودی:\n"
        "م\n"
        "موجودی\n\n"

        "🎲 تاس:\n"
        "1 تاس 50\n"
        "۱ تاس ۵۰\n\n"

        "🎳 بولینگ:\n"
        "1 بولینگ 50\n"
        "۱ بولینگ ۵۰\n\n"

        "🎯 دارت:\n"
        "1 دارت 50\n"
        "۱ دارت ۵۰\n\n"

        "🏀 بسکتبال:\n"
        "50 گل\n"
        "۵۰ گل\n"
        "50 بیرون\n"
        "۵۰ بیرون\n\n"

        "🔄 انتقال:\n"
        "روی پیام کاربر Reply کن:\n"
        "انتقال 100\n\n"

        "📌 تاس / بولینگ / دارت: ضریب نمایش 2x\n"
        "📌 بسکتبال: ضریب نمایش 1.5x\n\n"

        "ℹ️ DOGS این نسخه مجازی است."
    )


# =========================================================
# Error
# =========================================================

async def error_handler(update, context):
    logger.exception(
        "Telegram bot error",
        exc_info=context.error,
    )


# =========================================================
# Main
# =========================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN در config.py تنظیم نشده است."
        )

    database.init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("balance", balance)
    )

    application.add_handler(
        CommandHandler("admin", admin)
    )

    # فقط یک MessageHandler
    # تمام پیام‌ها از Router ضد دستور عبور می‌کنند.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            router,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info("LATAR BOT STARTED")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
