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
    CURRENCY,
    MAX_ROUNDS,
)


# =========================================================
# LOG
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# تنظیمات
# =========================================================

MAX_ROUNDS = min(int(MAX_ROUNDS), 4)

GAMES = {
    "تاس": "🎲",
    "دارت": "🎯",
    "بولینگ": "🎳",
}


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
    text = normalize_digits(text)

    return (
        text.strip()
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


# =========================================================
# کاربر
# =========================================================

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


def display_name(user):
    name = user.first_name or "کاربر"

    if user.last_name:
        name += " " + user.last_name

    return name


# =========================================================
# عضویت اجباری
# =========================================================

async def check_join(update, context):

    user = update.effective_user

    if not user:
        return False

    # مالک بدون بررسی عضویت
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

    except Exception as e:
        logger.warning(
            "JOIN CHECK ERROR: %s",
            e,
        )

    await update.effective_message.reply_text(
        "⛔ ابتدا عضو کانال شوید:\n\n"
        f"{FORCE_CHAT}\n\n"
        "بعد دوباره دستور را بفرستید."
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

    amount = database.get_balance(
        user.id
    )

    await update.effective_message.reply_text(
        f"💰 موجودی شما:\n"
        f"{money(amount)} {CURRENCY}"
    )


# =========================================================
# انتقال
# =========================================================

async def transfer(update, context):

    if not await check_join(update, context):
        return

    message = update.effective_message
    user = update.effective_user

    # فقط گپ
    if message.chat.type == "private":

        await message.reply_text(
            "❌ انتقال فقط داخل گپ انجام می‌شود."
        )

        return

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
            "❌ نمی‌توانی به خودت انتقال بدهی."
        )

        return

    parts = normalize_text(
        message.text
    ).split()

    if len(parts) != 2:

        await message.reply_text(
            "❌ مثال:\n"
            "انتقال 100"
        )

        return

    amount = parse_amount(
        parts[1]
    )

    if amount is None:

        await message.reply_text(
            "❌ مبلغ صحیح نیست."
        )

        return

    ensure_user(user)
    ensure_user(target)

    tx_key = (
        "transfer:"
        f"{message.chat_id}:"
        f"{message.message_id}"
    )

    result = database.transfer_balance(
        user.id,
        target.id,
        amount,
        tx_key,
    )

    if not result["success"]:

        if result.get(
            "reason"
        ) == "insufficient_balance":

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
# شارژ مالک
# =========================================================

async def charge(update, context):

    user = update.effective_user

    # ضد دستور
    if not is_owner(user.id):
        return

    message = update.effective_message

    if message.chat.type == "private":

        await message.reply_text(
            "❌ شارژ را داخل گپ و با Reply انجام بده."
        )

        return

    reply = message.reply_to_message

    if not reply or not reply.from_user:

        await message.reply_text(
            "❌ روی پیام کاربر Reply کن.\n\n"
            "مثال:\n"
            "شارژ 100"
        )

        return

    target = reply.from_user

    if target.is_bot:
        return

    parts = normalize_text(
        message.text
    ).split()

    if len(parts) != 2:
        return

    amount = parse_amount(
        parts[1]
    )

    if amount is None:
        return

    ensure_user(target)

    tx_key = (
        "charge:"
        f"{message.chat_id}:"
        f"{message.message_id}"
    )

    result = database.add_balance(
        target.id,
        amount,
        tx_key,
        "شارژ توسط مالک",
    )

    if not result["success"]:
        return

    # نتیجه شارژ برای کاربر در گپ نمایش داده نمی‌شود.
    # فقط مالک در PV نتیجه را می‌گیرد.
    try:

        await context.bot.send_message(
            chat_id=user.id,
            text=(
                "✅ شارژ انجام شد.\n\n"
                f"👤 کاربر: {display_name(target)}\n"
                f"➕ {money(amount)} {CURRENCY}\n"
                f"💳 موجودی جدید: "
                f"{money(result['balance'])} {CURRENCY}"
            ),
        )

    except Exception:
        pass


# =========================================================
# کسر مالک
# =========================================================

async def deduct(update, context):

    user = update.effective_user

    if not is_owner(user.id):
        return

    message = update.effective_message

    if message.chat.type == "private":

        await message.reply_text(
            "❌ کسر را داخل گپ و با Reply انجام بده."
        )

        return

    reply = message.reply_to_message

    if not reply or not reply.from_user:

        await message.reply_text(
            "❌ روی پیام کاربر Reply کن.\n\n"
            "مثال:\n"
            "کسر 100"
        )

        return

    target = reply.from_user

    if target.is_bot:
        return

    parts = normalize_text(
        message.text
    ).split()

    if len(parts) != 2:
        return

    amount = parse_amount(
        parts[1]
    )

    if amount is None:
        return

    ensure_user(target)

    tx_key = (
        "deduct:"
        f"{message.chat_id}:"
        f"{message.message_id}"
    )

    result = database.withdraw_balance(
        target.id,
        amount,
        tx_key,
        "کسر توسط مالک",
    )

    if not result["success"]:

        if result.get(
            "reason"
        ) == "insufficient_balance":

            await message.reply_text(
                "❌ موجودی کاربر کافی نیست."
            )

        return

    try:

        await context.bot.send_message(
            chat_id=user.id,
            text=(
                "✅ کسر انجام شد.\n\n"
                f"👤 کاربر: {display_name(target)}\n"
                f"➖ {money(amount)} {CURRENCY}\n"
                f"💳 موجودی جدید: "
                f"{money(result['balance'])} {CURRENCY}"
            ),
        )

    except Exception:
        pass


# =========================================================
# روشن
# =========================================================

async def turn_on(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    database.set_bot_enabled(True)

    await update.effective_message.reply_text(
        "🟢 بات روشن شد."
    )


# =========================================================
# خاموش
# =========================================================

async def turn_off(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    database.set_bot_enabled(False)

    await update.effective_message.reply_text(
        "🔴 بات خاموش شد."
    )


# =========================================================
# بازی با ربات
#
# فرمت:
#
# 1 تاس 60
# 2 تاس 60
# 4 تاس 60
#
# اول کاربر
# بعد ربات
# حداکثر 4 راند
# =========================================================

def parse_bot_game(text):

    parts = normalize_text(
        text
    ).split()

    if len(parts) != 3:
        return None

    rounds = parse_amount(
        parts[0]
    )

    game = parts[1]

    amount = parse_amount(
        parts[2]
    )

    if rounds is None:
        return None

    if amount is None:
        return None

    if game not in GAMES:
        return None

    if rounds < 1 or rounds > MAX_ROUNDS:
        return None

    return rounds, game, amount


async def play_bot(update, context):

    if not await check_join(
        update,
        context,
    ):
        return

    message = update.effective_message
    user = update.effective_user

    parsed = parse_bot_game(
        message.text
    )

    if not parsed:
        return

    rounds, game, amount = parsed

    if not database.is_bot_enabled():

        await message.reply_text(
            "🔴 بات خاموش است."
        )

        return

    ensure_user(user)

    current_balance = database.get_balance(
        user.id
    )

    if current_balance < amount:

        await message.reply_text(
            "❌ موجودی کافی نیست.\n"
            f"💰 موجودی: "
            f"{money(current_balance)} {CURRENCY}"
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
            "❌ بازی ایجاد نشد."
        )

        return

    emoji = GAMES[game]

    user_wins = 0
    bot_wins = 0
    draws = 0

    result_lines = []

    for round_no in range(
        1,
        rounds + 1,
    ):

        # ---------------------------------------------
        # اول کاربر
        # ---------------------------------------------

        user_roll = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji=emoji,
            reply_to_message_id=message.message_id,
        )

        await asyncio.sleep(2)

        user_value = user_roll.dice.value

        # ---------------------------------------------
        # بعد ربات
        # ---------------------------------------------

        bot_roll = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji=emoji,
            reply_to_message_id=message.message_id,
        )

        await asyncio.sleep(1)

        bot_value = bot_roll.dice.value

        # ---------------------------------------------
        # نتیجه
        # ---------------------------------------------

        if user_value > bot_value:

            user_wins += 1
            result = "👤 شما"

        elif bot_value > user_value:

            bot_wins += 1
            result = "🤖 ربات"

        else:

            draws += 1
            result = "🤝 مساوی"

        result_lines.append(
            f"راند {round_no}: "
            f"👤 {user_value} | "
            f"🤖 {bot_value} "
            f"→ {result}"
        )

    # ---------------------------------------------
    # برنده نهایی
    # ---------------------------------------------

    if user_wins > bot_wins:

        final_result = (
            "🏆 شما برنده شدید!"
        )

    elif bot_wins > user_wins:

        final_result = (
            "🤖 ربات برنده شد!"
        )

    else:

        final_result = (
            "🤝 بازی مساوی شد!"
        )

    database.finish_game(
        game_id,
        (
            f"user={user_wins};"
            f"bot={bot_wins};"
            f"draw={draws}"
        ),
        0,
    )

    await message.reply_text(
        f"{emoji} بازی {game} با ربات\n\n"
        + "\n".join(result_lines)
        + "\n\n"
        f"👤 بردهای شما: {user_wins}\n"
        f"🤖 بردهای ربات: {bot_wins}\n"
        f"🤝 مساوی: {draws}\n\n"
        f"{final_result}\n\n"
        f"💰 موجودی: "
        f"{money(database.get_balance(user.id))} "
        f"{CURRENCY}"
    )


# =========================================================
# لاتاری
#
# تاس:
# 60 زوج
# 60 فرد
#
# بسکتبال:
# 60 گل
# 60 بیرون
#
# دارت:
# فعلاً نتیجه عددی Telegram
# =========================================================

def parse_lottery(text):

    parts = normalize_text(
        text
    ).split()

    if len(parts) != 2:
        return None

    amount = parse_amount(
        parts[0]
    )

    choice = parts[1]

    if amount is None:
        return None

    if choice in (
        "زوج",
        "فرد",
    ):
        return (
            "تاس",
            amount,
            choice,
        )

    if choice in (
        "گل",
        "بیرون",
    ):
        return (
            "بسکتبال",
            amount,
            choice,
        )

    if choice in (
        "قرمز",
        "سفید",
    ):
        return (
            "دارت",
            amount,
            choice,
        )

    return None


async def lottery(update, context):

    if not await check_join(
        update,
        context,
    ):
        return

    message = update.effective_message
    user = update.effective_user

    parsed = parse_lottery(
        message.text
    )

    if not parsed:
        return

    game, amount, choice = parsed

    if not database.is_bot_enabled():

        await message.reply_text(
            "🔴 بات خاموش است."
        )

        return

    ensure_user(user)

    # =====================================================
    # تاس
    # =====================================================

    if game == "تاس":

        roll = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🎲",
            reply_to_message_id=message.message_id,
        )

        await asyncio.sleep(2)

        value = roll.dice.value

        result = (
            "زوج"
            if value % 2 == 0
            else "فرد"
        )

        won = result == choice

        if won:

            result_text = (
                "🏆 برنده شدی!"
            )

        else:

            result_text = (
                "❌ باختی!"
            )

        await message.reply_text(
            "🎲 لاتاری تاس\n\n"
            f"🎯 عدد: {value}\n"
            f"👤 انتخاب: {choice}\n"
            f"📊 نتیجه: {result}\n\n"
            f"{result_text}\n"
            f"💰 مبلغ: {money(amount)} {CURRENCY}"
        )

        return

    # =====================================================
    # بسکتبال
    # =====================================================

    if game == "بسکتبال":

        roll = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🏀",
            reply_to_message_id=message.message_id,
        )

        await asyncio.sleep(2)

        value = roll.dice.value

        result = (
            "گل"
            if value in (4, 5)
            else "بیرون"
        )

        won = result == choice

        if won:

            result_text = (
                "🏆 برنده شدی!"
            )

        else:

            result_text = (
                "❌ باختی!"
            )

        await message.reply_text(
            "🏀 لاتاری بسکتبال\n\n"
            f"🎯 نتیجه پرتاب: {result}\n"
            f"👤 انتخاب: {choice}\n\n"
            f"{result_text}\n"
            f"💰 مبلغ: {money(amount)} {CURRENCY}"
        )

        return

    # =====================================================
    # دارت
    # =====================================================

    if game == "دارت":

        roll = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🎯",
            reply_to_message_id=message.message_id,
        )

        await asyncio.sleep(2)

        value = roll.dice.value

        await message.reply_text(
            "🎯 لاتاری دارت\n\n"
            f"🎯 عدد پرتاب: {value}\n"
            f"👤 انتخاب: {choice}\n\n"
            "⚠️ تلگرام برای دارت عدد پرتاب را "
            "می‌دهد و رنگ قرمز/سفید را مستقیم "
            "در API اعلام نمی‌کند.\n\n"
            f"💰 مبلغ: {money(amount)} {CURRENCY}"
        )

        return


# =========================================================
# پنل مدیریت
# =========================================================

async def admin(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    await update.effective_message.reply_text(
        "👑 پنل مدیریت\n\n"
        "روشن\n"
        "خاموش\n"
        "کاربران\n"
        "وضعیت\n\n"
        "شارژ داخل گپ:\n"
        "Reply → شارژ 100\n\n"
        "کسر داخل گپ:\n"
        "Reply → کسر 100"
    )


async def users(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    rows = database.get_all_users()

    if not rows:

        await update.effective_message.reply_text(
            "👥 کاربری وجود ندارد."
        )

        return

    text = "👥 کاربران:\n\n"

    for row in rows:

        name = (
            row["first_name"]
            or "کاربر"
        )

        text += (
            f"👤 {name}\n"
            f"🆔 {row['user_id']}\n"
            f"💰 {money(row['balance'])} "
            f"{CURRENCY}\n\n"
        )

    for i in range(
        0,
        len(text),
        3500,
    ):

        await update.effective_message.reply_text(
            text[i:i + 3500]
        )


async def status(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    state = (
        "🟢 روشن"
        if database.is_bot_enabled()
        else "🔴 خاموش"
    )

    await update.effective_message.reply_text(
        f"📊 وضعیت: {state}"
    )


# =========================================================
# START
# =========================================================

async def start(update, context):

    if not await check_join(
        update,
        context,
    ):
        return

    ensure_user(
        update.effective_user
    )

    await update.effective_message.reply_text(
        "🎮 LATAR آماده است.\n\n"

        "💰 موجودی:\n"
        "موجودی\n"
        "م\n\n"

        "🔄 انتقال:\n"
        "Reply + انتقال 100\n\n"

        "🎲 بازی با ربات:\n"
        "1 تاس 60\n"
        "1 دارت 60\n"
        "1 بولینگ 60\n"
        "حداکثر 4 راند\n\n"

        "🎲 لاتاری تاس:\n"
        "60 زوج\n"
        "60 فرد\n\n"

        "🎯 لاتاری دارت:\n"
        "60 قرمز\n"
        "60 سفید\n\n"

        "🏀 لاتاری بسکتبال:\n"
        "60 گل\n"
        "60 بیرون\n\n"

        f"💰 واحد: {CURRENCY}"
    )


# =========================================================
# ROUTER ضد دستور
#
# مهم:
# هر پیام فقط یک بار پردازش می‌شود.
# اول دستورهای خاص بررسی می‌شوند.
# بعد فقط اولین تطابق اجرا می‌شود.
# =========================================================

async def router(update, context):

    message = update.effective_message

    if not message:
        return

    if not message.text:
        return

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    text = normalize_text(
        message.text
    )

    # =====================================================
    # 1 - مالک
    # =====================================================

    if is_owner(user.id):

        if text in (
            "پنل",
            "پنل مدیریت",
        ):

            await admin(
                update,
                context,
            )

            return

        if text == "روشن":

            await turn_on(
                update,
                context,
            )

            return

        if text == "خاموش":

            await turn_off(
                update,
                context,
            )

            return

        if text == "کاربران":

            await users(
                update,
                context,
            )

            return

        if text == "وضعیت":

            await status(
                update,
                context,
            )

            return

        if text.startswith("شارژ "):

            await charge(
                update,
                context,
            )

            return

        if text.startswith("کسر "):

            await deduct(
                update,
                context,
            )

            return

    # =====================================================
    # 2 - موجودی
    # =====================================================

    if text in (
        "م",
        "موجودی",
    ):

        await balance(
            update,
            context,
        )

        return

    # =====================================================
    # 3 - انتقال
    # =====================================================

    if text.startswith("انتقال "):

        await transfer(
            update,
            context,
        )

        return

    # =====================================================
    # 4 - بازی با ربات
    # =====================================================

    if parse_bot_game(text):

        await play_bot(
            update,
            context,
        )

        return

    # =====================================================
    # 5 - لاتاری
    # =====================================================

    if parse_lottery(text):

        await lottery(
            update,
            context,
        )

        return

    # =====================================================
    # هیچ دستوری نبود
    # هیچ کاری نکن
    # =====================================================

    return


# =========================================================
# ERROR
# =========================================================

async def error_handler(
    update,
    context,
):

    logger.exception(
        "BOT ERROR",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN تنظیم نشده است."
        )

    database.init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "balance",
            balance,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            router,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "LATAR BOT STARTED"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
