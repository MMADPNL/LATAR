import logging
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
    DICE_REWARD,
    BOWLING_REWARD,
    DART_REWARD,
    BASKETBALL_REWARD,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ENGLISH_DIGITS = "0123456789"


database.init_db()


# =========================================================
# ابزار
# =========================================================

def normalize_digits(text):

    text = str(text or "")

    for i, char in enumerate(PERSIAN_DIGITS):
        text = text.replace(
            char,
            ENGLISH_DIGITS[i]
        )

    for i, char in enumerate(ARABIC_DIGITS):
        text = text.replace(
            char,
            ENGLISH_DIGITS[i]
        )

    return text


def normalize(text):

    text = normalize_digits(
        text or ""
    ).strip()

    replacements = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
    }

    for old, new in replacements.items():
        text = text.replace(
            old,
            new
        )

    return text


def get_number(text):

    try:

        value = int(
            normalize_digits(text)
        )

        if value <= 0:
            return None

        return value

    except Exception:

        return None


def money(value):

    return f"{int(value):,}"


def display_name(user):

    name = user.first_name or "کاربر"

    if user.last_name:
        name += " " + user.last_name

    return name


def ensure_user(user):

    database.register_user(
        user.id,
        user.first_name or "",
        user.username or ""
    )


def owner(user_id):

    try:
        return int(user_id) == int(OWNER_ID)
    except Exception:
        return False


# =========================================================
# عضویت اجباری
# =========================================================

async def check_join(
    update,
    context
):

    user = update.effective_user

    if user is None:
        return False

    if owner(user.id):
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

    except Exception as error:

        logger.warning(
            "Membership check error: %s",
            error
        )

    await update.effective_message.reply_text(
        "⛔ برای استفاده از بات ابتدا عضو شو:\n\n"
        f"{FORCE_CHAT}\n\n"
        "بعد دوباره امتحان کن."
    )

    return False


# =========================================================
# شروع
# =========================================================

async def start(
    update,
    context
):

    user = update.effective_user

    if user:
        ensure_user(user)

    if not await check_join(
        update,
        context
    ):
        return

    await update.effective_message.reply_text(
        "🎮 به LATAR خوش آمدی!\n\n"

        "💰 موجودی:\n"
        "م\n"
        "یا\n"
        "موجودی\n\n"

        "🎮 بازی:\n"
        "۱ تاس ۵۰\n"
        "۱ بولینگ ۵۰\n"
        "۱ دارت ۵۰\n"
        "۱ بسکتبال ۵۰\n\n"

        "🔄 انتقال:\n"
        "روی پیام کاربر Reply کن:\n"
        "انتقال 100"
    )


# =========================================================
# موجودی
# =========================================================

async def balance(
    update,
    context
):

    if not await check_join(
        update,
        context
    ):
        return

    user = update.effective_user

    ensure_user(user)

    value = database.get_balance(
        user.id
    )

    await update.effective_message.reply_text(
        f"💰 موجودی شما: {money(value)} DOGS"
    )


# =========================================================
# انتقال Reply
# =========================================================

async def transfer(
    update,
    context
):

    if not await check_join(
        update,
        context
    ):
        return

    message = update.effective_message
    user = update.effective_user

    reply = message.reply_to_message

    if reply is None:

        await message.reply_text(
            "❌ باید روی پیام کاربر Reply کنی.\n\n"
            "مثال:\n"
            "انتقال 100"
        )

        return

    target = reply.from_user

    if target is None:

        await message.reply_text(
            "❌ کاربر پیدا نشد."
        )

        return

    if target.is_bot:

        await message.reply_text(
            "❌ انتقال به ربات امکان‌پذیر نیست."
        )

        return

    parts = normalize(
        message.text
    ).split()

    if len(parts) != 2:

        await message.reply_text(
            "❌ فرمت صحیح:\n"
            "انتقال 100"
        )

        return

    amount = get_number(
        parts[1]
    )

    if amount is None:

        await message.reply_text(
            "❌ مقدار صحیح نیست."
        )

        return

    if target.id == user.id:

        await message.reply_text(
            "❌ نمی‌توانی به خودت انتقال بدهی."
        )

        return

    ensure_user(user)
    ensure_user(target)

    result = database.transfer_balance(
        sender_id=user.id,
        receiver_id=target.id,
        amount=amount,
        tx_key="transfer:" + uuid.uuid4().hex
    )

    if not result["success"]:

        if result.get("reason") == "insufficient_balance":

            await message.reply_text(
                "❌ موجودی کافی نیست.\n\n"
                f"💳 موجودی شما: "
                f"{money(result['balance'])} DOGS"
            )

            return

        await message.reply_text(
            "❌ انتقال انجام نشد."
        )

        return

    await message.reply_text(
        "✅ انتقال انجام شد.\n\n"
        f"👤 گیرنده: {display_name(target)}\n"
        f"💰 مبلغ: {money(amount)} DOGS\n"
        f"💳 موجودی شما: "
        f"{money(result['sender_balance'])} DOGS"
    )


# =========================================================
# بازی
# =========================================================

GAME_DATA = {

    "تاس": {
        "emoji": "🎲",
        "reward": DICE_REWARD
    },

    "بولینگ": {
        "emoji": "🎳",
        "reward": BOWLING_REWARD
    },

    "دارت": {
        "emoji": "🎯",
        "reward": DART_REWARD
    },

    "بسکتبال": {
        "emoji": "🏀",
        "reward": BASKETBALL_REWARD
    },
}


def parse_game(text):

    parts = normalize(text).split()

    if len(parts) != 3:
        return None

    rounds = get_number(parts[0])
    game_name = parts[1]
    amount = get_number(parts[2])

    if rounds is None:
        return None

    if amount is None:
        return None

    if rounds < 1:
        return None

    if game_name not in GAME_DATA:
        return None

    return (
        rounds,
        game_name,
        amount
    )


async def game_handler(
    update,
    context
):

    if not await check_join(
        update,
        context
    ):
        return

    if not database.is_bot_enabled():

        await update.effective_message.reply_text(
            "🔴 بازی‌ها خاموش هستند."
        )

        return

    message = update.effective_message
    user = update.effective_user

    parsed = parse_game(
        message.text
    )

    if parsed is None:
        return

    rounds, game_name, display_amount = parsed

    ensure_user(user)

    data = GAME_DATA[game_name]

    emoji = data["emoji"]
    reward = data["reward"]

    # =====================================================
    # اول کاربر بازی را می‌ریزد
    # =====================================================

    await message.reply_text(
        f"🎮 {game_name}\n\n"
        "👤 اول نوبت شماست.\n"
        f"لطفاً خودت {emoji} را ارسال کن."
    )

    # =====================================================
    # منتظر ایموجی واقعی کاربر
    # =====================================================

    user_dice = None

    for _ in range(60):

        try:

            updates = await context.bot.get_updates(
                timeout=1,
                allowed_updates=["message"]
            )

        except Exception:

            updates = []

        found = False

        for item in updates:

            msg = getattr(
                item,
                "message",
                None
            )

            if msg is None:
                continue

            if msg.chat_id != message.chat_id:
                continue

            if msg.from_user.id != user.id:
                continue

            if msg.message_id <= message.message_id:
                continue

            dice = getattr(
                msg,
                "dice",
                None
            )

            if dice is None:
                continue

            if dice.emoji != emoji:
                continue

            user_dice = dice
            found = True
            break

        if found:
            break

    # =====================================================
    # اگر کاربر بازی را نفرستاد
    # =====================================================

    if user_dice is None:

        await message.reply_text(
            f"❌ {emoji} از طرف شما دریافت نشد."
        )

        return

    user_value = user_dice.value

    # =====================================================
    # بعد ربات بازی را می‌ریزد
    # =====================================================

    bot_message = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji=emoji
    )

    bot_value = bot_message.dice.value

    # =====================================================
    # نتیجه
    # =====================================================

    if user_value > bot_value:

        result = "win"

    elif user_value < bot_value:

        result = "lose"

    else:

        result = "draw"

    # =====================================================
    # جایزه
    # =====================================================

    added = 0

    if result == "win":

        added = reward

        payment = database.add_balance(
            user.id,
            added,
            "reward:" + uuid.uuid4().hex,
            f"جایزه برد {game_name}"
        )

        new_balance = payment["balance"]

    else:

        new_balance = database.get_balance(
            user.id
        )

    database.save_game(
        user_id=user.id,
        chat_id=message.chat_id,
        game_type=game_name,
        display_amount=display_amount,
        user_value=user_value,
        bot_value=bot_value,
        result=result,
        reward=added
    )

    # =====================================================
    # پیام برد
    # =====================================================

    if result == "win":

        await message.reply_text(
            "🏆 بردی!\n\n"

            f"{emoji} بازی: {game_name}\n"
            f"👤 شما: {user_value}\n"
            f"🤖 ربات: {bot_value}\n\n"

            "💰 از موجودی شما کسر نشد.\n"
            f"➕ {money(added)} DOGS "
            "به موجودی شما اضافه شد.\n"

            f"💳 موجودی جدید: "
            f"{money(new_balance)} DOGS"
        )

        return

    # =====================================================
    # مساوی
    # =====================================================

    if result == "draw":

        await message.reply_text(
            "🤝 مساوی شد!\n\n"

            f"{emoji} بازی: {game_name}\n"
            f"👤 شما: {user_value}\n"
            f"🤖 ربات: {bot_value}\n\n"

            "💰 موجودی شما کسر نشد.\n"
            f"💳 موجودی فعلی: "
            f"{money(new_balance)} DOGS"
        )

        return

    # =====================================================
    # باخت
    # =====================================================

    await message.reply_text(
        "❌ باختی!\n\n"

        f"{emoji} بازی: {game_name}\n"
        f"👤 شما: {user_value}\n"
        f"🤖 ربات: {bot_value}\n\n"

        "💰 از موجودی شما کسر نشد.\n"
        f"💳 موجودی فعلی: "
        f"{money(new_balance)} DOGS"
    )


# =========================================================
# پنل مدیریت
# =========================================================

async def admin(
    update,
    context
):

    user = update.effective_user

    if not owner(user.id):
        return

    await update.effective_message.reply_text(
        "👑 پنل مدیریت\n\n"

        "🟢 روشن\n"
        "🔴 خاموش\n"
        "👥 کاربران\n"
        "📊 وضعیت\n\n"

        "➕ شارژ با Reply:\n"
        "شارژ 100\n\n"

        "➖ کسر با Reply:\n"
        "کسر 100"
    )


async def admin_text(
    update,
    context
):

    user = update.effective_user

    if not owner(user.id):
        return

    text = normalize(
        update.effective_message.text
    )

    # روشن
    if text == "روشن":

        database.set_bot_enabled(True)

        await update.effective_message.reply_text(
            "🟢 بات روشن شد."
        )

        return

    # خاموش
    if text == "خاموش":

        database.set_bot_enabled(False)

        await update.effective_message.reply_text(
            "🔴 بات خاموش شد."
        )

        return

    # وضعیت
    if text == "وضعیت":

        status = (
            "🟢 روشن"
            if database.is_bot_enabled()
            else "🔴 خاموش"
        )

        await update.effective_message.reply_text(
            f"📊 وضعیت بات: {status}"
        )

        return

    # کاربران
    if text == "کاربران":

        users = database.get_all_users()

        if not users:

            await update.effective_message.reply_text(
                "👥 هنوز کاربری ثبت نشده."
            )

            return

        lines = [
            "👥 کاربران:\n"
        ]

        for row in users:

            name = (
                row["first_name"]
                or "کاربر"
            )

            lines.append(
                f"👤 {name} — "
                f"{money(row['balance'])} DOGS"
            )

        result = "\n".join(lines)

        # شکستن پیام‌های خیلی بلند
        while len(result) > 3500:

            await update.effective_message.reply_text(
                result[:3500]
            )

            result = result[3500:]

        if result:

            await update.effective_message.reply_text(
                result
            )

        return

    # شارژ
    if text.startswith("شارژ "):

        reply = (
            update.effective_message
            .reply_to_message
        )

        if reply is None:

            await update.effective_message.reply_text(
                "❌ روی پیام کاربر Reply کن."
            )

            return

        parts = text.split()

        if len(parts) != 2:
            return

        amount = get_number(
            parts[1]
        )

        if amount is None:
            return

        target = reply.from_user

        ensure_user(target)

        result = database.add_balance(
            target.id,
            amount,
            "admin_charge:" + uuid.uuid4().hex,
            "شارژ توسط مالک"
        )

        await update.effective_message.reply_text(
            "✅ شارژ انجام شد.\n\n"
            f"👤 {display_name(target)}\n"
            f"➕ {money(amount)} DOGS\n"
            f"💳 موجودی جدید: "
            f"{money(result['balance'])} DOGS"
        )

        return

    # کسر
    if text.startswith("کسر "):

        reply = (
            update.effective_message
            .reply_to_message
        )

        if reply is None:

            await update.effective_message.reply_text(
                "❌ روی پیام کاربر Reply کن."
            )

            return

        parts = text.split()

        if len(parts) != 2:
            return

        amount = get_number(
            parts[1]
        )

        if amount is None:
            return

        target = reply.from_user

        ensure_user(target)

        result = database.remove_balance(
            target.id,
            amount,
            "admin_deduct:" + uuid.uuid4().hex,
            "کسر توسط مالک"
        )

        if not result["success"]:

            await update.effective_message.reply_text(
                "❌ موجودی کاربر کافی نیست."
            )

            return

        await update.effective_message.reply_text(
            "✅ کسر انجام شد.\n\n"
            f"👤 {display_name(target)}\n"
            f"➖ {money(amount)} DOGS\n"
            f"💳 موجودی جدید: "
            f"{money(result['balance'])} DOGS"
        )


# =========================================================
# Router
# =========================================================

async def router(
    update,
    context
):

    message = update.effective_message

    if message is None:
        return

    if not message.text:
        return

    text = normalize(
        message.text
    )

    user = update.effective_user

    if user is None:
        return

    ensure_user(user)

    # موجودی
    if text in (
        "م",
        "موجودی"
    ):

        await balance(
            update,
            context
        )

        return

    # انتقال
    if text.startswith(
        "انتقال "
    ):

        await transfer(
            update,
            context
        )

        return

    # بازی
    game = parse_game(text)

    if game is not None:

        await game_handler(
            update,
            context
        )

        return

    # پنل مالک
    if owner(user.id):

        if text == "پنل":

            await admin(
                update,
                context
            )

            return

        await admin_text(
            update,
            context
        )


# =========================================================
# اجرای بات
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN در Secrets تنظیم نشده است."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin
        )
    )

    application.add_handler(
        CommandHandler(
            "balance",
            balance
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            router
        )
    )

    logger.info(
        "LATAR bot started."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
