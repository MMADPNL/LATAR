import asyncio
import logging
import re
import uuid
import random

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

MAX_GAME_ROUNDS = min(int(MAX_ROUNDS), 4)

# ضریب بازی با ربات
BOT_GAME_MULTIPLIER = 2

# ضریب لاتاری بسکتبال
BASKETBALL_MULTIPLIER = 1.5


# =========================================================
# ایموجی بازی
# =========================================================

GAME_EMOJIS = {
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

    # مالک نیاز به بررسی عضویت ندارد
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

async def show_balance(update, context):

    if not await check_join(update, context):
        return

    user = update.effective_user

    ensure_user(user)

    balance = database.get_balance(
        user.id
    )

    await update.effective_message.reply_text(
        "💰 موجودی شما:\n\n"
        f"{money(balance)} {CURRENCY}"
    )


# =========================================================
# انتقال
#
# داخل گپ:
# Reply روی پیام کاربر
# انتقال 100
# انتقال ۱۰۰
# =========================================================

async def transfer(update, context):

    if not await check_join(update, context):
        return

    message = update.effective_message
    user = update.effective_user

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
            "❌ مثال صحیح:\n"
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

    # کلید ضدتکرار
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
#
# فقط داخل گپ
# فقط Reply
# فقط مالک
#
# نتیجه شارژ در گپ نمایش داده نمی‌شود.
# =========================================================

async def admin_charge(update, context):

    user = update.effective_user

    if not is_owner(user.id):
        return

    message = update.effective_message

    if message.chat.type == "private":

        await message.reply_text(
            "❌ شارژ را داخل گپ انجام بده."
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
        "admin_charge:"
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

    # نتیجه فقط برای مالک
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

async def admin_deduct(update, context):

    user = update.effective_user

    if not is_owner(user.id):
        return

    message = update.effective_message

    if message.chat.type == "private":

        await message.reply_text(
            "❌ کسر را داخل گپ انجام بده."
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
        "admin_deduct:"
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
# روشن / خاموش
# =========================================================

async def admin_on(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    database.set_bot_enabled(True)

    await update.effective_message.reply_text(
        "🟢 بات روشن شد."
    )


async def admin_off(update, context):

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
# 1 تاس 100
# 2 تاس 100
# 4 تاس 100
#
# اول کاربر
# بعد ربات
# حداکثر 4 راند
#
# برد:
# مبلغ بازی از قبل کسر نمی‌شود
# مبلغ برد = مبلغ × 2
#
# باخت:
# مبلغ بازی کسر می‌شود
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

    if game not in GAME_EMOJIS:
        return None

    if rounds < 1:
        return None

    if rounds > MAX_GAME_ROUNDS:
        return None

    return rounds, game, amount


async def play_bot_game(update, context):

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

    balance_before = database.get_balance(
        user.id
    )

    if balance_before < amount:

        await message.reply_text(
            "❌ موجودی کافی نیست.\n\n"
            f"💰 موجودی: "
            f"{money(balance_before)} {CURRENCY}"
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
            "❌ بازی قبلاً ثبت شده است."
        )

        return

    emoji = GAME_EMOJIS[game]

    user_wins = 0
    bot_wins = 0
    draws = 0

    result_lines = []

    # =====================================================
    # راندها
    # =====================================================

    for round_number in range(
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

        await asyncio.sleep(2)

        bot_value = bot_roll.dice.value

        # ---------------------------------------------
        # نتیجه راند
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
            f"راند {round_number}\n"
            f"👤 شما: {user_value}\n"
            f"🤖 ربات: {bot_value}\n"
            f"نتیجه: {result}"
        )

    # =====================================================
    # نتیجه نهایی
    # =====================================================

    if user_wins > bot_wins:

        # ---------------------------------------------
        # برد
        # مبلغ از قبل کم نشده
        # مبلغ برد 2 برابر اضافه می‌شود
        # ---------------------------------------------

        reward = int(
            amount * BOT_GAME_MULTIPLIER
        )

        payment = database.add_balance(
            user.id,
            reward,
            f"game:{game_id}:win",
            f"برد {game}",
        )

        if not payment["success"]:

            await message.reply_text(
                "❌ خطا در ثبت برد."
            )

            return

        database.finish_game(
            game_id,
            (
                f"user={user_wins};"
                f"bot={bot_wins};"
                f"draw={draws};"
                "WIN"
            ),
            reward,
        )

        final_text = (
            "🏆 برنده شدی!\n\n"
            f"➕ {money(reward)} {CURRENCY} اضافه شد.\n"
            f"ℹ️ مبلغ بازی از حسابت کسر نشد.\n"
            f"💳 موجودی جدید: "
            f"{money(payment['balance'])} {CURRENCY}"
        )

    elif bot_wins > user_wins:

        # ---------------------------------------------
        # باخت
        # مبلغ بازی کسر می‌شود
        # ---------------------------------------------

        loss = database.withdraw_balance(
            user.id,
            amount,
            f"game:{game_id}:loss",
            f"باخت {game}",
        )

        if not loss["success"]:

            await message.reply_text(
                "❌ خطا در کسر موجودی."
            )

            return

        database.finish_game(
            game_id,
            (
                f"user={user_wins};"
                f"bot={bot_wins};"
                f"draw={draws};"
                "LOSS"
            ),
            0,
        )

        final_text = (
            "❌ باختی.\n\n"
            f"➖ {money(amount)} {CURRENCY} کسر شد.\n"
            f"💳 موجودی جدید: "
            f"{money(loss['balance'])} {CURRENCY}"
        )

    else:

        # ---------------------------------------------
        # مساوی
        # ---------------------------------------------

        database.finish_game(
            game_id,
            (
                f"user={user_wins};"
                f"bot={bot_wins};"
                f"draw={draws};"
                "DRAW"
            ),
            0,
        )

        final_text = (
            "🤝 مساوی شد.\n\n"
            "💰 موجودی تغییر نکرد."
        )

    await message.reply_text(
        f"{emoji} {game} با ربات\n\n"
        + "\n\n".join(result_lines)
        + "\n\n"
        f"📊 شما: {user_wins} برد\n"
        f"🤖 ربات: {bot_wins} برد\n"
        f"🤝 مساوی: {draws}\n\n"
        f"{final_text}"
    )


# =========================================================
# لاتاری
#
# تاس:
# 300 زوج
# 300 فرد
#
# بسکتبال:
# 400 گل
# 400 بیرون
#
# دارت:
# 400 قرمز
# 400 سفید
#
# در لاتاری فقط خود کاربر یک پرتاب می‌زند.
#
# برد:
# مبلغ × ضریب اضافه می‌شود
#
# باخت:
# مبلغ کسر می‌شود
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

    # -----------------------------
    # تاس
    # -----------------------------

    if choice in (
        "زوج",
        "فرد",
    ):

        return (
            "تاس",
            amount,
            choice,
        )

    # -----------------------------
    # بسکتبال
    # -----------------------------

    if choice in (
        "گل",
        "بیرون",
    ):

        return (
            "بسکتبال",
            amount,
            choice,
        )

    # -----------------------------
    # دارت
    # -----------------------------

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


# =========================================================
# اجرای لاتاری
# =========================================================

async def play_lottery(update, context):

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

    balance_before = database.get_balance(
        user.id
    )

    if balance_before < amount:

        await message.reply_text(
            "❌ موجودی کافی نیست.\n\n"
            f"💰 موجودی: "
            f"{money(balance_before)} {CURRENCY}"
        )

        return

    game_id = uuid.uuid4().hex

    created = database.create_game(
        game_id,
        message.chat_id,
        message.message_id,
        user.id,
        f"lottery:{game}:{choice}",
        amount,
    )

    if not created:

        await message.reply_text(
            "❌ بازی قبلاً ثبت شده است."
        )

        return

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

        multiplier = 2

        game_title = "🎲 لاتاری تاس"

    # =====================================================
    # بسکتبال
    # =====================================================

    elif game == "بسکتبال":

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

        multiplier = BASKETBALL_MULTIPLIER

        game_title = "🏀 لاتاری بسکتبال"

    # =====================================================
    # دارت
    #
    # Telegram عدد دارت را می‌دهد.
    # برای لاتاری رنگ را به‌صورت تصادفی تعیین می‌کنیم.
    # =====================================================

    else:

        roll = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🎯",
            reply_to_message_id=message.message_id,
        )

        await asyncio.sleep(2)

        value = roll.dice.value

        result = random.choice(
            ["قرمز", "سفید"]
        )

        won = result == choice

        multiplier = 2

        game_title = "🎯 لاتاری دارت"

    # =====================================================
    # برد
    # =====================================================

    if won:

        reward = int(
            amount * multiplier
        )

        payment = database.add_balance(
            user.id,
            reward,
            f"lottery:{game_id}:win",
            f"برد لاتاری {game}",
        )

        if not payment["success"]:

            await message.reply_text(
                "❌ خطا در ثبت برد."
            )

            return

        database.finish_game(
            game_id,
            f"WIN:{result}",
            reward,
        )

        await message.reply_text(
            f"{game_title}\n\n"
            f"👤 انتخاب شما: {choice}\n"
            f"🎯 نتیجه: {result}\n\n"
            "🏆 برنده شدی!\n\n"
            f"➕ {money(reward)} {CURRENCY} اضافه شد.\n"
            f"ℹ️ مبلغ بازی از حسابت کسر نشد.\n"
            f"📈 ضریب: {multiplier}x\n"
            f"💳 موجودی جدید: "
            f"{money(payment['balance'])} {CURRENCY}"
        )

        return

    # =====================================================
    # باخت
    # =====================================================

    loss = database.withdraw_balance(
        user.id,
        amount,
        f"lottery:{game_id}:loss",
        f"باخت لاتاری {game}",
    )

    if not loss["success"]:

        await message.reply_text(
            "❌ خطا در کسر موجودی."
        )

        return

    database.finish_game(
        game_id,
        f"LOSS:{result}",
        0,
    )

    await message.reply_text(
        f"{game_title}\n\n"
        f"👤 انتخاب شما: {choice}\n"
        f"🎯 نتیجه: {result}\n\n"
        "❌ باختی!\n\n"
        f"➖ {money(amount)} {CURRENCY} کسر شد.\n"
        f"💳 موجودی جدید: "
        f"{money(loss['balance'])} {CURRENCY}"
    )


# =========================================================
# پنل مدیریت
# =========================================================

async def admin_panel(update, context):

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
        "Reply → کسر 100\n\n"
        "انتقال:\n"
        "Reply → انتقال 100"
    )


async def admin_users(update, context):

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


async def admin_status(update, context):

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
        f"📊 وضعیت بات: {state}"
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

        "🔄 انتقال داخل گپ:\n"
        "Reply + انتقال 100\n\n"

        "👑 شارژ مالک:\n"
        "Reply + شارژ 100\n\n"

        "👑 کسر مالک:\n"
        "Reply + کسر 100\n\n"

        "🎲 بازی با ربات:\n"
        "1 تاس 100\n"
        "1 دارت 100\n"
        "1 بولینگ 100\n"
        "حداکثر 4 راند\n\n"

        "🎲 لاتاری تاس:\n"
        "300 زوج\n"
        "300 فرد\n\n"

        "🎯 لاتاری دارت:\n"
        "300 قرمز\n"
        "300 سفید\n\n"

        "🏀 لاتاری بسکتبال:\n"
        "400 گل\n"
        "400 بیرون\n\n"

        f"💰 واحد: {CURRENCY}\n"
        "🛡️ سیستم ضدتکرار فعال است."
    )


# =========================================================
# ROUTER ضد دستور
#
# هر پیام فقط یک دستور را اجرا می‌کند.
#
# ترتیب:
# 1 مالک
# 2 موجودی
# 3 انتقال
# 4 بازی با ربات
# 5 لاتاری
# 6 هیچ کاری
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
    # مالک
    # =====================================================

    if is_owner(user.id):

        if text in (
            "پنل",
            "پنل مدیریت",
        ):

            await admin_panel(
                update,
                context,
            )

            return

        if text == "روشن":

            await admin_on(
                update,
                context,
            )

            return

        if text == "خاموش":

            await admin_off(
                update,
                context,
            )

            return

        if text == "کاربران":

            await admin_users(
                update,
                context,
            )

            return

        if text == "وضعیت":

            await admin_status(
                update,
                context,
            )

            return

        if text.startswith(
            "شارژ "
        ):

            await admin_charge(
                update,
                context,
            )

            return

        if text.startswith(
            "کسر "
        ):

            await admin_deduct(
                update,
                context,
            )

            return

    # =====================================================
    # موجودی
    # =====================================================

    if text in (
        "م",
        "موجودی",
    ):

        await show_balance(
            update,
            context,
        )

        return

    # =====================================================
    # انتقال
    # =====================================================

    if text.startswith(
        "انتقال "
    ):

        await transfer(
            update,
            context,
        )

        return

    # =====================================================
    # بازی با ربات
    # =====================================================

    if parse_bot_game(text):

        await play_bot_game(
            update,
            context,
        )

        return

    # =====================================================
    # لاتاری
    # =====================================================

    if parse_lottery(text):

        await play_lottery(
            update,
            context,
        )

        return

    # =====================================================
    # ضد دستور
    # پیام ناشناخته = هیچ کاری نکن
    # =====================================================

    return


# =========================================================
# ERROR HANDLER
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
            show_balance,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_panel,
        )
    )

    # فقط یک MessageHandler
    # بنابراین هر پیام فقط یک بار وارد Router می‌شود.
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
