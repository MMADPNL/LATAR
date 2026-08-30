import asyncio
import logging
import os
import re
import uuid
from decimal import Decimal, ROUND_DOWN

from telegram import Update
from telegram.constants import ChatType
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
    MAX_ROUNDS,
    LOTTERY_ODD_EVEN,
    LOTTERY_RED_WHITE,
    LOTTERY_GOAL_OUT,
    BOT_GAME,
)


# =========================================================
# تنظیمات
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# ابزارها
# =========================================================

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ENGLISH_DIGITS = "0123456789"


def normalize_digits(text):
    if not text:
        return ""

    text = str(text)

    for i, char in enumerate(PERSIAN_DIGITS):
        text = text.replace(char, ENGLISH_DIGITS[i])

    for i, char in enumerate(ARABIC_DIGITS):
        text = text.replace(char, ENGLISH_DIGITS[i])

    return text


def normalize_text(text):
    text = normalize_digits(text or "").strip()

    replacements = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def parse_amount(text):
    text = normalize_digits(text)

    match = re.fullmatch(r"\s*(\d+)\s*", text)

    if not match:
        return None

    amount = int(match.group(1))

    if amount <= 0:
        return None

    return amount


def money(value):
    return f"{int(value):,}"


def user_display(user):
    name = user.first_name or "کاربر"

    if user.last_name:
        name += f" {user.last_name}"

    return name


def unique_key(prefix):
    return f"{prefix}:{uuid.uuid4().hex}"


# =========================================================
# دیتابیس
# =========================================================

database.init_db()


def ensure_user(tg_user):
    database.register_user(
        tg_user.id,
        tg_user.first_name or "",
        tg_user.username or "",
    )


# =========================================================
# مالک
# =========================================================

def is_owner(user_id):
    try:
        return int(user_id) == int(OWNER_ID)
    except Exception:
        return False


# =========================================================
# عضویت اجباری
# =========================================================

async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(
            FORCE_CHAT,
            user_id,
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception as e:
        logger.warning(
            "Membership check failed: %s",
            e,
        )

        return False


async def check_force_join(update, context):
    user = update.effective_user

    if user is None:
        return False

    if is_owner(user.id):
        return True

    if await is_member(
        context.bot,
        user.id,
    ):
        return True

    if update.effective_message:
        await update.effective_message.reply_text(
            "⛔ برای استفاده از بات ابتدا باید عضو گپ زیر شوید:\n\n"
            f"{FORCE_CHAT}\n\n"
            "بعد دوباره پیام خود را ارسال کنید."
        )

    return False


# =========================================================
# موجودی
# =========================================================

async def balance_command(update, context):
    if not await check_force_join(update, context):
        return

    user = update.effective_user

    ensure_user(user)

    balance = database.get_balance(user.id)

    await update.effective_message.reply_text(
        f"💰 موجودی شما: {money(balance)} DOGS"
    )


async def balance_text(update, context):
    text = normalize_text(
        update.effective_message.text
    )

    if text not in ("م", "موجودی"):
        return

    await balance_command(
        update,
        context,
    )


# =========================================================
# انتقال با Reply
# =========================================================

async def transfer_command(update, context):
    if not await check_force_join(update, context):
        return

    message = update.effective_message
    user = update.effective_user

    ensure_user(user)

    reply = message.reply_to_message

    if reply is None or reply.from_user is None:
        await message.reply_text(
            "❌ برای انتقال باید روی پیام کاربر Reply کنی.\n\n"
            "مثال:\n"
            "انتقال 100"
        )
        return

    receiver = reply.from_user

    if receiver.is_bot:
        await message.reply_text(
            "❌ انتقال به ربات امکان‌پذیر نیست."
        )
        return

    if receiver.id == user.id:
        await message.reply_text(
            "❌ نمی‌توانی به خودت انتقال بدهی."
        )
        return

    parts = normalize_text(message.text).split()

    if len(parts) != 2:
        await message.reply_text(
            "❌ فرمت صحیح:\n"
            "انتقال 100"
        )
        return

    amount = parse_amount(parts[1])

    if amount is None:
        await message.reply_text(
            "❌ مقدار انتقال صحیح نیست."
        )
        return

    ensure_user(receiver)

    result = database.transfer_balance(
        sender_id=user.id,
        receiver_id=receiver.id,
        amount=amount,
        transfer_key=unique_key("transfer"),
    )

    if not result["success"]:

        reason = result.get("reason")

        if reason == "insufficient_balance":
            await message.reply_text(
                "❌ موجودی کافی نیست."
            )
            return

        if reason == "self_transfer":
            await message.reply_text(
                "❌ انتقال به خودت ممکن نیست."
            )
            return

        await message.reply_text(
            "❌ انتقال انجام نشد."
        )
        return

    await message.reply_text(
        "✅ انتقال انجام شد.\n\n"
        f"👤 گیرنده: {user_display(receiver)}\n"
        f"💰 مبلغ: {money(amount)} DOGS\n"
        f"💳 موجودی شما: {money(result['sender_balance'])} DOGS"
    )


# =========================================================
# ساخت شرط لاتاری
# =========================================================

LOTTERY_CHOICES = {
    "زوج",
    "فرد",
    "قرمز",
    "سفید",
    "گل",
    "بیرون",
}


def parse_lottery(text):
    text = normalize_text(text)

    parts = text.split()

    if len(parts) != 2:
        return None

    amount = parse_amount(parts[0])
    choice = parts[1]

    if amount is None:
        return None

    if choice not in LOTTERY_CHOICES:
        return None

    return amount, choice


# =========================================================
# ثبت بازی لاتاری
# =========================================================

async def lottery_message(update, context):
    if not await check_force_join(update, context):
        return

    message = update.effective_message
    user = update.effective_user

    parsed = parse_lottery(message.text)

    if parsed is None:
        return

    amount, choice = parsed

    ensure_user(user)

    # برای هر شرط یک کلید یکتا
    game_id = uuid.uuid4().hex

    withdrawal = database.withdraw_balance(
        user.id,
        amount,
        tx_key=f"game:{game_id}:bet",
        description=f"شرط لاتاری {choice}",
    )

    if not withdrawal["success"]:

        if withdrawal.get("reason") == "insufficient_balance":
            await message.reply_text(
                f"❌ موجودی کافی نیست.\n"
                f"💰 موجودی: {money(withdrawal['balance'])} DOGS"
            )
            return

        await message.reply_text(
            "❌ ثبت شرط انجام نشد."
        )
        return

    created = database.create_game(
        game_id=game_id,
        chat_id=message.chat_id,
        message_id=message.message_id,
        user_id=user.id,
        game_type=f"lottery:{choice}",
        bet=amount,
    )

    if not created:
        # حالت بسیار نادر؛ شرط را برمی‌گردانیم
        database.add_balance(
            user.id,
            amount,
            tx_key=f"rollback:{game_id}",
            description="برگشت شرط ناموفق",
        )

        await message.reply_text(
            "❌ خطا در ثبت بازی؛ مبلغ به موجودی شما برگشت داده شد."
        )
        return

    # -----------------------------------------------------
    # زوج / فرد
    # -----------------------------------------------------

    if choice in ("زوج", "فرد"):

        dice = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🎲",
            reply_to_message_id=message.message_id,
        )

        value = dice.dice.value

        even = value % 2 == 0
        result_name = "زوج" if even else "فرد"

        won = (
            choice == result_name
        )

        await finish_lottery(
            update=update,
            game_id=game_id,
            user_id=user.id,
            amount=amount,
            choice=choice,
            result=result_name,
            won=won,
            multiplier=LOTTERY_ODD_EVEN,
            result_value=value,
        )

        return

    # -----------------------------------------------------
    # قرمز / سفید
    # -----------------------------------------------------

    if choice in ("قرمز", "سفید"):

        dart = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🎯",
            reply_to_message_id=message.message_id,
        )

        value = dart.dice.value

        # تلگرام برای دارت رنگ قرمز/سفید را در فیلد
        # نتیجه ارسال نمی‌کند.
        #
        # بنابراین مقدار واقعی دارت را نمایش می‌دهیم
        # و نتیجه رنگی را جعل نمی‌کنیم.

        result_name = f"نتیجه دارت: {value}"

        await context.bot.send_message(
            chat_id=message.chat_id,
            text=(
                "🎯 لاتاری قرمز/سفید\n\n"
                f"🎯 مقدار دارت: {value}\n\n"
                "⚠️ تلگرام رنگ قرمز/سفید دارت را به بات "
                "ارسال نمی‌کند؛ بنابراین این نوع شرط "
                "بدون منطق خارجی قابل تعیین نیست."
            ),
            reply_to_message_id=message.message_id,
        )

        database.finish_game(
            game_id,
            result_name,
            0,
        )

        # چون رنگ قابل تشخیص نیست، مبلغ شرط برمی‌گردد
        database.add_balance(
            user.id,
            amount,
            tx_key=f"refund:{game_id}",
            description="برگشت شرط قرمز/سفید",
        )

        return

    # -----------------------------------------------------
    # گل / بیرون
    # -----------------------------------------------------

    if choice in ("گل", "بیرون"):

        basketball = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🏀",
            reply_to_message_id=message.message_id,
        )

        value = basketball.dice.value

        # Telegram مقدار 1 تا 5 را برمی‌گرداند.
        # اینجا یک تعریف ثابت برای گل/بیرون می‌گذاریم:
        # 4 و 5 = گل
        # 1 و 2 و 3 = بیرون
        #
        # اگر تعریف مدنظر تو متفاوت باشد فقط همین قسمت عوض می‌شود.

        result_name = (
            "گل"
            if value in (4, 5)
            else "بیرون"
        )

        won = choice == result_name

        await finish_lottery(
            update=update,
            game_id=game_id,
            user_id=user.id,
            amount=amount,
            choice=choice,
            result=result_name,
            won=won,
            multiplier=LOTTERY_GOAL_OUT,
            result_value=value,
        )

        return


# =========================================================
# پایان لاتاری
# =========================================================

async def finish_lottery(
    update,
    game_id,
    user_id,
    amount,
    choice,
    result,
    won,
    multiplier,
    result_value,
):

    payout = 0

    if won:
        payout = int(
            Decimal(amount)
            * Decimal(str(multiplier))
        )

    finished = database.finish_game(
        game_id,
        result,
        payout,
    )

    if not finished["success"]:
        return

    # اگر قبلاً تمام شده، دوباره پرداخت نکن
    if finished.get("duplicate"):
        return

    if payout > 0:

        payment = database.add_balance(
            user_id,
            payout,
            tx_key=f"game:{game_id}:payout",
            description=f"برد لاتاری {choice}",
        )

        if not payment["success"]:
            logger.error(
                "Lottery payout failed: %s",
                payment,
            )

            return

    if won:

        await update.effective_message.reply_text(
            "🏆 لاتاری\n\n"
            f"🎯 انتخاب شما: {choice}\n"
            f"🎲 نتیجه: {result}\n"
            f"💰 شرط: {money(amount)} DOGS\n"
            f"📈 ضریب: {multiplier}x\n"
            f"💵 پرداخت: {money(payout)} DOGS\n\n"
            "✅ برنده شدید!"
        )

    else:

        await update.effective_message.reply_text(
            "🎟️ لاتاری\n\n"
            f"🎯 انتخاب شما: {choice}\n"
            f"🎲 نتیجه: {result}\n"
            f"💰 شرط: {money(amount)} DOGS\n\n"
            "❌ باختید."
        )


# =========================================================
# بازی با ربات
# =========================================================

BOT_GAME_NAMES = {
    "تاس": "🎲",
    "دارت": "🎯",
    "بولینگ": "🎳",
}


def parse_bot_game(text):
    text = normalize_text(text)

    parts = text.split()

    if len(parts) != 3:
        return None

    round_number = parse_amount(parts[0])
    game_type = parts[1]
    amount = parse_amount(parts[2])

    if round_number is None:
        return None

    if amount is None:
        return None

    if game_type not in BOT_GAME_NAMES:
        return None

    if round_number < 1 or round_number > MAX_ROUNDS:
        return None

    return (
        round_number,
        game_type,
        amount,
    )


async def bot_game_message(update, context):
    if not await check_force_join(update, context):
        return

    message = update.effective_message
    user = update.effective_user

    parsed = parse_bot_game(message.text)

    if parsed is None:
        return

    round_number, game_type, amount = parsed

    ensure_user(user)

    game_id = uuid.uuid4().hex

    withdrawal = database.withdraw_balance(
        user.id,
        amount,
        tx_key=f"botgame:{game_id}:bet",
        description=f"بازی با ربات {game_type}",
    )

    if not withdrawal["success"]:

        if withdrawal.get("reason") == "insufficient_balance":
            await message.reply_text(
                f"❌ موجودی کافی نیست.\n"
                f"💰 موجودی: {money(withdrawal['balance'])} DOGS"
            )
            return

        await message.reply_text(
            "❌ ثبت بازی انجام نشد."
        )
        return

    created = database.create_game(
        game_id=game_id,
        chat_id=message.chat_id,
        message_id=message.message_id,
        user_id=user.id,
        game_type=f"bot:{game_type}",
        bet=amount,
    )

    if not created:

        database.add_balance(
            user.id,
            amount,
            tx_key=f"rollback:{game_id}",
            description="برگشت شرط بازی",
        )

        await message.reply_text(
            "❌ خطا در ثبت بازی؛ مبلغ برگشت داده شد."
        )
        return

    emoji = BOT_GAME_NAMES[game_type]

    # -----------------------------------------------------
    # پرتاب کاربر
    # -----------------------------------------------------

    user_roll = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji=emoji,
        reply_to_message_id=message.message_id,
    )

    await asyncio.sleep(1)

    # -----------------------------------------------------
    # پرتاب ربات
    # -----------------------------------------------------

    bot_roll = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji=emoji,
        reply_to_message_id=message.message_id,
    )

    user_value = user_roll.dice.value
    bot_value = bot_roll.dice.value

    # -----------------------------------------------------
    # مقایسه
    # -----------------------------------------------------

    if user_value > bot_value:
        winner = "user"

    elif bot_value > user_value:
        winner = "bot"

    else:
        winner = "draw"

    payout = 0

    if winner == "user":
        payout = int(
            Decimal(amount)
            * Decimal(str(BOT_GAME))
        )

    database.finish_game(
        game_id,
        winner,
        payout,
    )

    if payout > 0:

        payment = database.add_balance(
            user.id,
            payout,
            tx_key=f"botgame:{game_id}:payout",
            description=f"برد بازی {game_type}",
        )

        if not payment["success"]:
            logger.error(
                "Bot game payout failed: %s",
                payment,
            )

    # -----------------------------------------------------
    # نتیجه
    # -----------------------------------------------------

    if winner == "user":

        await message.reply_text(
            f"{emoji} بازی {game_type}\n\n"
            f"👤 شما: {user_value}\n"
            f"🤖 ربات: {bot_value}\n\n"
            "🏆 شما برنده شدید!\n"
            f"💰 شرط: {money(amount)} DOGS\n"
            f"📈 ضریب: {BOT_GAME}x\n"
            f"💵 پرداخت: {money(payout)} DOGS"
        )

    elif winner == "bot":

        await message.reply_text(
            f"{emoji} بازی {game_type}\n\n"
            f"👤 شما: {user_value}\n"
            f"🤖 ربات: {bot_value}\n\n"
            "❌ ربات برنده شد.\n"
            f"💰 شرط: {money(amount)} DOGS"
        )

    else:

        # مساوی = مبلغ شرط برمی‌گردد
        refund = database.add_balance(
            user.id,
            amount,
            tx_key=f"botgame:{game_id}:draw_refund",
            description="برگشت شرط بازی مساوی",
        )

        await message.reply_text(
            f"{emoji} بازی {game_type}\n\n"
            f"👤 شما: {user_value}\n"
            f"🤖 ربات: {bot_value}\n\n"
            "🤝 مساوی شد.\n"
            f"💰 {money(amount)} DOGS برگشت داده شد."
        )


# =========================================================
# پنل مالک
# =========================================================

async def admin_command(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    await show_admin_panel(update)


async def show_admin_panel(update):

    message = update.effective_message

    await message.reply_text(
        "👑 پنل مدیریت\n\n"

        "🟢 روشن\n"
        "🔴 خاموش\n"
        "💰 شارژ [مقدار] با Reply\n"
        "➖ کسر [مقدار] با Reply\n"
        "👥 کاربران\n"
        "📊 وضعیت\n\n"

        "مثال:\n"
        "شارژ 500\n"
        "کسر 100"
    )


# =========================================================
# روشن / خاموش
# =========================================================

async def admin_on(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    database.set_bot_enabled(True)

    await update.effective_message.reply_text(
        "🟢 بات روشن شد."
    )


async def admin_off(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    database.set_bot_enabled(False)

    await update.effective_message.reply_text(
        "🔴 بات خاموش شد."
    )


# =========================================================
# شارژ مالک
# =========================================================

async def admin_charge(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    message = update.effective_message
    reply = message.reply_to_message

    if reply is None or reply.from_user is None:
        await message.reply_text(
            "❌ روی پیام کاربر Reply کن.\n"
            "مثال:\n"
            "شارژ 500"
        )
        return

    parts = normalize_text(message.text).split()

    if len(parts) != 2:
        await message.reply_text(
            "❌ مثال:\nشارژ 500"
        )
        return

    amount = parse_amount(parts[1])

    if amount is None:
        await message.reply_text(
            "❌ مقدار صحیح نیست."
        )
        return

    target = reply.from_user

    ensure_user(target)

    result = database.add_balance(
        target.id,
        amount,
        tx_key=unique_key("admin_charge"),
        description=f"شارژ توسط مالک {user.id}",
    )

    if not result["success"]:
        await message.reply_text(
            "❌ شارژ انجام نشد."
        )
        return

    await message.reply_text(
        "✅ شارژ انجام شد.\n\n"
        f"👤 {user_display(target)}\n"
        f"💰 +{money(amount)} DOGS\n"
        f"💳 موجودی: {money(result['balance'])} DOGS"
    )


# =========================================================
# کسر مالک
# =========================================================

async def admin_deduct(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    message = update.effective_message
    reply = message.reply_to_message

    if reply is None or reply.from_user is None:
        await message.reply_text(
            "❌ روی پیام کاربر Reply کن.\n"
            "مثال:\n"
            "کسر 100"
        )
        return

    parts = normalize_text(message.text).split()

    if len(parts) != 2:
        await message.reply_text(
            "❌ مثال:\nکسر 100"
        )
        return

    amount = parse_amount(parts[1])

    if amount is None:
        await message.reply_text(
            "❌ مقدار صحیح نیست."
        )
        return

    target = reply.from_user

    ensure_user(target)

    result = database.withdraw_balance(
        target.id,
        amount,
        tx_key=unique_key("admin_deduct"),
        description=f"کسر توسط مالک {user.id}",
    )

    if not result["success"]:

        if result.get("reason") == "insufficient_balance":
            await message.reply_text(
                "❌ موجودی کاربر کافی نیست."
            )
            return

        await message.reply_text(
            "❌ کسر انجام نشد."
        )
        return

    await message.reply_text(
        "✅ کسر انجام شد.\n\n"
        f"👤 {user_display(target)}\n"
        f"💰 -{money(amount)} DOGS\n"
        f"💳 موجودی: {money(result['balance'])} DOGS"
    )


# =========================================================
# موجودی همه کاربران
# فقط اسم + موجودی
# =========================================================

async def admin_users(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    users = database.get_all_users()

    if not users:
        await update.effective_message.reply_text(
            "👥 هنوز کاربری ثبت نشده."
        )
        return

    lines = [
        "👥 موجودی کاربران\n"
    ]

    for row in users:

        name = row["first_name"] or "کاربر"

        lines.append(
            f"👤 {name} — {money(row['balance'])} DOGS"
        )

    # تلگرام محدودیت طول پیام دارد
    text = "\n".join(lines)

    chunks = []

    while len(text) > 3500:
        cut = text.rfind(
            "\n",
            0,
            3500,
        )

        if cut == -1:
            cut = 3500

        chunks.append(text[:cut])
        text = text[cut:].lstrip()

    chunks.append(text)

    for chunk in chunks:
        await update.effective_message.reply_text(
            chunk
        )


# =========================================================
# وضعیت
# =========================================================

async def admin_status(update, context):
    user = update.effective_user

    if not is_owner(user.id):
        return

    enabled = database.is_bot_enabled()

    status = (
        "🟢 روشن"
        if enabled
        else "🔴 خاموش"
    )

    await update.effective_message.reply_text(
        f"📊 وضعیت بات: {status}"
    )


# =========================================================
# پردازش دستورات متنی
# =========================================================

async def text_router(update, context):

    message = update.effective_message

    if message is None:
        return

    text = normalize_text(
        message.text
    )

    if not text:
        return

    user = update.effective_user

    if user is None:
        return

    ensure_user(user)

    # -----------------------------------------------------
    # مالک
    # -----------------------------------------------------

    if is_owner(user.id):

        if text in ("پنل", "پنل مدیریت"):
            await show_admin_panel(update)
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
        await balance_command(update, context)
        return

    # -----------------------------------------------------
    # انتقال
    # -----------------------------------------------------

    if text.startswith("انتقال "):
        await transfer_command(update, context)
        return

    # -----------------------------------------------------
    # اول بازی با ربات
    # -----------------------------------------------------

    bot_game = parse_bot_game(text)

    if bot_game:
        if database.is_bot_enabled():
            await bot_game_message(
                update,
                context,
            )
        return

    # -----------------------------------------------------
    # لاتاری
    # -----------------------------------------------------

    lottery = parse_lottery(text)

    if lottery:

        if not database.is_bot_enabled():

            await message.reply_text(
                "🔴 بات در حال حاضر خاموش است."
            )
            return

        await lottery_message(
            update,
            context,
        )


# =========================================================
# دستورات
# =========================================================

async def start_command(update, context):

    user = update.effective_user

    if user:
        ensure_user(user)

    if not await check_force_join(
        update,
        context,
    ):
        return

    await update.effective_message.reply_text(
        "🎟️ به بات لاتاری خوش آمدید.\n\n"

        "💰 موجودی:\n"
        "م\n"
        "یا\n"
        "موجودی\n\n"

        "🎲 لاتاری زوج:\n"
        "60 زوج\n\n"

        "🎲 لاتاری فرد:\n"
        "60 فرد\n\n"

        "🏀 لاتاری گل:\n"
        "60 گل\n\n"

        "🏀 لاتاری بیرون:\n"
        "60 بیرون\n\n"

        "🤖 بازی با ربات:\n"
        "1 تاس 100\n"
        "1 دارت 100\n"
        "1 بولینگ 100\n\n"

        "🔄 انتقال:\n"
        "روی پیام شخص Reply کن و بنویس:\n"
        "انتقال 100"
    )


async def help_command(update, context):

    if not await check_force_join(
        update,
        context,
    ):
        return

    await update.effective_message.reply_text(
        "📖 راهنما\n\n"

        "🎟️ لاتاری:\n"
        "60 زوج\n"
        "60 فرد\n"
        "60 گل\n"
        "60 بیرون\n\n"

        "🎮 بازی با ربات:\n"
        "1 تاس 100\n"
        "1 دارت 100\n"
        "1 بولینگ 100\n\n"

        "حداکثر راند: "
        f"{MAX_ROUNDS}\n\n"

        "💰 ضریب لاتاری زوج/فرد: "
        f"{LOTTERY_ODD_EVEN}x\n"

        "💰 ضریب گل/بیرون: "
        f"{LOTTERY_GOAL_OUT}x\n"

        "🤖 ضریب بازی با ربات: "
        f"{BOT_GAME}x"
    )


# =========================================================
# خطایابی
# =========================================================

async def error_handler(update, context):

    logger.exception(
        "Telegram update error:",
        exc_info=context.error,
    )


# =========================================================
# اجرای بات
# =========================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN تنظیم نشده است."
        )

    if not OWNER_ID:
        raise RuntimeError(
            "OWNER_ID تنظیم نشده است."
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "balance",
            balance_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_router,
        )
    )

    app.add_error_handler(
        error_handler
    )

    logger.info(
        "Lottery bot started."
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
