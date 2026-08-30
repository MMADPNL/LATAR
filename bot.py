import asyncio
import logging
import re
import uuid
from decimal import Decimal

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
    CURRENCY,
    MAX_ROUNDS,
    DICE_MULTIPLIER,
    BOWLING_MULTIPLIER,
    DART_MULTIPLIER,
    BASKETBALL_MULTIPLIER,
)


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


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

    number = int(value)

    return number if number > 0 else None


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
        user.username or ""
    )


# =========================================================
# عضویت
# =========================================================

async def check_join(update, context):
    user = update.effective_user

    if not user:
        return False

    if is_owner(user.id):
        return True

    try:
        member = await context.bot.get_chat_member(
            FORCE_CHAT,
            user.id
        )

        if member.status in (
            "member",
            "administrator",
            "creator"
        ):
            return True

    except Exception as e:
        logger.warning("Join check failed: %s", e)

    await update.effective_message.reply_text(
        "⛔ ابتدا عضو کانال/گپ زیر شوید:\n\n"
        f"{FORCE_CHAT}\n\n"
        "سپس دوباره امتحان کنید."
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
# انتقال
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
            "❌ انتقال به ربات امکان‌پذیر نیست."
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
            "❌ فرمت صحیح:\nانتقال 100"
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
        f"transfer:{uuid.uuid4().hex}"
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
# بازی تاس / بولینگ / دارت
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

    if game not in GAME_EMOJIS:
        return None

    if amount is None:
        return None

    if round_number > MAX_ROUNDS:
        return None

    return round_number, game, amount


async def play_game(update, context):
    message = update.effective_message
    user = update.effective_user

    if not await check_join(update, context):
        return

    ensure_user(user)

    parsed = parse_game(message.text)

    if not parsed:
        return

    round_number, game, amount = parsed

    if not database.is_bot_enabled():
        await message.reply_text("🔴 بات خاموش است.")
        return

    current_balance = database.get_balance(user.id)

    if current_balance < amount:
        await message.reply_text(
            f"❌ موجودی کافی نیست.\n"
            f"💰 موجودی: {money(current_balance)} {CURRENCY}"
        )
        return

    game_id = uuid.uuid4().hex

    if not database.create_game(
        game_id,
        message.chat_id,
        message.message_id,
        user.id,
        f"bot:{game}",
        amount
    ):
        await message.reply_text(
            "❌ خطا در ساخت بازی."
        )
        return

    emoji = GAME_EMOJIS[game]

    # اول کاربر
    user_roll = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji=emoji,
        reply_to_message_id=message.message_id
    )

    await asyncio.sleep(2)

    # بعد ربات
    bot_roll = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji=emoji,
        reply_to_message_id=message.message_id
    )

    user_value = user_roll.dice.value
    bot_value = bot_roll.dice.value

    if user_value > bot_value:
        result = "user"
    elif bot_value > user_value:
        result = "bot"
    else:
        result = "draw"

    # مساوی
    if result == "draw":
        database.finish_game(
            game_id,
            "draw",
            0
        )

        await message.reply_text(
            f"{emoji} {game}\n\n"
            f"👤 شما: {user_value}\n"
            f"🤖 ربات: {bot_value}\n\n"
            "🤝 مساوی شد.\n"
            "💰 موجودی تغییر نکرد."
        )
        return

    # برد
    if result == "user":

        payout = int(
            Decimal(amount) *
            Decimal(str(GAME_MULTIPLIERS[game]))
        )

        payment = database.add_balance(
            user.id,
            payout,
            f"game:{game_id}:win",
            f"برد {game}"
        )

        database.finish_game(
            game_id,
            f"user:{user_value}-bot:{bot_value}",
            payout
        )

        if not payment["success"]:
            await message.reply_text(
                "❌ خطا در ثبت برد."
            )
            return

        await message.reply_text(
            f"{emoji} {game}\n\n"
            f"👤 شما: {user_value}\n"
            f"🤖 ربات: {bot_value}\n\n"
            "🏆 برنده شدی!\n\n"
            f"💰 شرط: {money(amount)} {CURRENCY}\n"
            "✅ مبلغ شرط از موجودی کم نشد.\n"
            f"➕ {money(payout)} {CURRENCY} اضافه شد.\n\n"
            f"💳 موجودی جدید: "
            f"{money(payment['balance'])} {CURRENCY}"
        )
        return

    # باخت
    loss = database.withdraw_balance(
        user.id,
        amount,
        f"game:{game_id}:loss",
        f"باخت {game}"
    )

    database.finish_game(
        game_id,
        f"user:{user_value}-bot:{bot_value}",
        0
    )

    if not loss["success"]:
        await message.reply_text(
            "❌ خطا در ثبت باخت."
        )
        return

    await message.reply_text(
        f"{emoji} {game}\n\n"
        f"👤 شما: {user_value}\n"
        f"🤖 ربات: {bot_value}\n\n"
        "❌ باختی.\n\n"
        f"➖ {money(amount)} {CURRENCY} کسر شد.\n"
        f"💳 موجودی جدید: "
        f"{money(loss['balance'])} {CURRENCY}"
    )


# =========================================================
# لاتاری
#
# مثال:
# 100 زوج
# 100 فرد
# 100 گل
# 100 بیرون
# =========================================================

def parse_lottery(text):
    parts = normalize_text(text).split()

    if len(parts) != 2:
        return None

    amount = parse_amount(parts[0])
    choice = parts[1]

    if amount is None:
        return None

    if choice not in (
        "زوج",
        "فرد",
        "گل",
        "بیرون"
    ):
        return None

    return amount, choice


async def lottery(update, context):
    message = update.effective_message
    user = update.effective_user

    if not await check_join(update, context):
        return

    ensure_user(user)

    parsed = parse_lottery(message.text)

    if not parsed:
        return

    amount, choice = parsed

    if not database.is_bot_enabled():
        await message.reply_text(
            "🔴 بات خاموش است."
        )
        return

    current_balance = database.get_balance(user.id)

    if current_balance < amount:
        await message.reply_text(
            f"❌ موجودی کافی نیست.\n"
            f"💰 موجودی: {money(current_balance)} {CURRENCY}"
        )
        return

    game_id = uuid.uuid4().hex

    if not database.create_game(
        game_id,
        message.chat_id,
        message.message_id,
        user.id,
        f"lottery:{choice}",
        amount
    ):
        await message.reply_text(
            "❌ خطا در ثبت لاتاری."
        )
        return

    # زوج / فرد
    if choice in ("زوج", "فرد"):

        roll = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🎲",
            reply_to_message_id=message.message_id
        )

        value = roll.dice.value

        result = "زوج" if value % 2 == 0 else "فرد"

        won = result == choice

        if won:

            payout = int(
                Decimal(amount) *
                Decimal("2.0")
            )

            payment = database.add_balance(
                user.id,
                payout,
                f"lottery:{game_id}:win",
                f"برد لاتاری {choice}"
            )

            database.finish_game(
                game_id,
                result,
                payout
            )

            await message.reply_text(
                "🎟️ لاتاری\n\n"
                f"🎯 انتخاب: {choice}\n"
                f"🎲 عدد: {value}\n"
                f"📌 نتیجه: {result}\n\n"
                "🏆 برنده شدی!\n"
                "✅ مبلغ شرط از موجودی کم نشد.\n"
                f"➕ {money(payout)} {CURRENCY} اضافه شد.\n"
                f"💳 موجودی: "
                f"{money(payment['balance'])} {CURRENCY}"
            )

        else:

            loss = database.withdraw_balance(
                user.id,
                amount,
                f"lottery:{game_id}:loss",
                f"باخت لاتاری {choice}"
            )

            database.finish_game(
                game_id,
                result,
                0
            )

            await message.reply_text(
                "🎟️ لاتاری\n\n"
                f"🎯 انتخاب: {choice}\n"
                f"🎲 عدد: {value}\n"
                f"📌 نتیجه: {result}\n\n"
                "❌ باختی.\n"
                f"➖ {money(amount)} {CURRENCY} کسر شد.\n"
                f"💳 موجودی: "
                f"{money(loss['balance'])} {CURRENCY}"
            )

        return

    # گل / بیرون
    if choice in ("گل", "بیرون"):

        roll = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🏀",
            reply_to_message_id=message.message_id
        )

        value = roll.dice.value

        # 4 و 5 = گل
        # 1 و 2 و 3 = بیرون
        result = "گل" if value in (4, 5) else "بیرون"

        won = result == choice

        if won:

            payout = int(
                Decimal(amount) *
                Decimal(str(BASKETBALL_MULTIPLIER))
            )

            payment = database.add_balance(
                user.id,
                payout,
                f"lottery:{game_id}:win",
                f"برد لاتاری {choice}"
            )

            database.finish_game(
                game_id,
                result,
                payout
            )

            await message.reply_text(
                "🏀 لاتاری بسکتبال\n\n"
                f"🎯 انتخاب: {choice}\n"
                f"🏀 عدد: {value}\n"
                f"📌 نتیجه: {result}\n\n"
                "🏆 برنده شدی!\n"
                "✅ مبلغ شرط از موجودی کم نشد.\n"
                f"➕ {money(payout)} {CURRENCY} اضافه شد.\n"
                f"💳 موجودی: "
                f"{money(payment['balance'])} {CURRENCY}"
            )

        else:

            loss = database.withdraw_balance(
                user.id,
                amount,
                f"lottery:{game_id}:loss",
                f"باخت لاتاری {choice}"
            )

            database.finish_game(
                game_id,
                result,
                0
            )

            await message.reply_text(
                "🏀 لاتاری بسکتبال\n\n"
                f"🎯 انتخاب: {choice}\n"
                f"🏀 عدد: {value}\n"
                f"📌 نتیجه: {result}\n\n"
                "❌ باختی.\n"
                f"➖ {money(amount)} {CURRENCY} کسر شد.\n"
                f"💳 موجودی: "
                f"{money(loss['balance'])} {CURRENCY}"
            )


# =========================================================
# مدیریت
# =========================================================

async def admin(update, context):
    if not is_owner(update.effective_user.id):
        return

    await update.effective_message.reply_text(
        "👑 پنل مدیریت\n\n"
        "🟢 روشن\n"
        "🔴 خاموش\n"
        "👥 کاربران\n"
        "📊 وضعیت\n\n"
        "شارژ کاربر:\n"
        "Reply + شارژ 100\n\n"
        "کسر کاربر:\n"
        "Reply + کسر 100"
    )


async def admin_charge(update, context):
    if not is_owner(update.effective_user.id):
        return

    message = update.effective_message
    reply = message.reply_to_message

    if not reply or not reply.from_user:
        await message.reply_text(
            "❌ روی پیام کاربر Reply کن."
        )
        return

    parts = normalize_text(message.text).split()

    if len(parts) != 2:
        return

    amount = parse_amount(parts[1])

    if amount is None:
        return

    target = reply.from_user
    ensure_user(target)

    result = database.add_balance(
        target.id,
        amount,
        f"admin_charge:{uuid.uuid4().hex}",
        "شارژ توسط مالک"
    )

    await message.reply_text(
        "✅ شارژ شد.\n\n"
        f"👤 {display_name(target)}\n"
        f"➕ {money(amount)} {CURRENCY}\n"
        f"💳 موجودی: {money(result['balance'])} {CURRENCY}"
    )


async def admin_deduct(update, context):
    if not is_owner(update.effective_user.id):
        return

    message = update.effective_message
    reply = message.reply_to_message

    if not reply or not reply.from_user:
        await message.reply_text(
            "❌ روی پیام کاربر Reply کن."
        )
        return

    parts = normalize_text(message.text).split()

    if len(parts) != 2:
        return

    amount = parse_amount(parts[1])

    if amount is None:
        return

    target = reply.from_user
    ensure_user(target)

    result = database.withdraw_balance(
        target.id,
        amount,
        f"admin_deduct:{uuid.uuid4().hex}",
        "کسر توسط مالک"
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
        f"💳 موجودی: {money(result['balance'])} {CURRENCY}"
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
        f"📊 وضعیت: {status}"
    )


# =========================================================
# Router
# =========================================================

async def router(update, context):

    message = update.effective_message

    if not message or not message.text:
        return

    text = normalize_text(message.text)

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    # -----------------------------
    # مالک
    # -----------------------------

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

    # -----------------------------
    # موجودی
    # -----------------------------

    if text in ("م", "موجودی"):
        await balance(update, context)
        return

    # -----------------------------
    # انتقال
    # -----------------------------

    if text.startswith("انتقال "):
        await transfer(update, context)
        return

    # -----------------------------
    # بازی تاس / بولینگ / دارت
    # -----------------------------

    if parse_game(text):
        await play_game(update, context)
        return

    # -----------------------------
    # لاتاری
    # -----------------------------

    if parse_lottery(text):
        await lottery(update, context)
        return


# =========================================================
# Start
# =========================================================

async def start(update, context):

    if not await check_join(update, context):
        return

    user = update.effective_user

    if user:
        ensure_user(user)

    await update.effective_message.reply_text(
        "🎮 بات آماده است.\n\n"

        "💰 موجودی:\n"
        "م\n"
        "موجودی\n\n"

        "🎲 بازی تاس:\n"
        "1 تاس 100\n"
        "۱ تاس ۱۰۰\n\n"

        "🎳 بازی بولینگ:\n"
        "1 بولینگ 100\n"
        "۱ بولینگ ۱۰۰\n\n"

        "🎯 بازی دارت:\n"
        "1 دارت 100\n"
        "۱ دارت ۱۰۰\n\n"

        "🎟️ لاتاری:\n"
        "100 زوج\n"
        "100 فرد\n"
        "100 گل\n"
        "100 بیرون\n\n"

        "🔄 انتقال:\n"
        "روی پیام کاربر Reply کن:\n"
        "انتقال 100\n\n"

        "📌 تاس / بولینگ / دارت:\n"
        "ضریب برد 2x\n\n"

        "📌 بسکتبال گل / بیرون:\n"
        "ضریب برد 1.5x\n\n"

        "💎 واحد: DOGS (مجازی)"
    )


async def help_command(update, context):

    if not await check_join(update, context):
        return

    await update.effective_message.reply_text(
        "📖 راهنما\n\n"

        "🎲 تاس:\n"
        "1 تاس 100\n\n"

        "🎳 بولینگ:\n"
        "1 بولینگ 100\n\n"

        "🎯 دارت:\n"
        "1 دارت 100\n\n"

        "🎟️ لاتاری:\n"
        "100 زوج\n"
        "100 فرد\n"
        "100 گل\n"
        "100 بیرون\n\n"

        "🔄 انتقال:\n"
        "Reply → انتقال 100\n\n"

        "💰 موجودی:\n"
        "م\n"
        "موجودی"
    )


async def error_handler(update, context):
    logger.exception(
        "Telegram error:",
        exc_info=context.error
    )


def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN تنظیم نشده است."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("balance", balance)
    )

    application.add_handler(
        CommandHandler("admin", admin)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            router
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info("BOT STARTED")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
