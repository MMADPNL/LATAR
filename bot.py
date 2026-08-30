import asyncio
import logging
import re
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import database
from config import (
    BOT_TOKEN,
    OWNER_ID,
    FORCE_CHAT,
    MAX_ROUNDS,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

CURRENCY = "DOGS"

PERSIAN = "۰۱۲۳۴۵۶۷۸۹"
ARABIC = "٠١٢٣٤٥٦٧٨٩"
ENGLISH = "0123456789"


def normalize_digits(text):
    text = str(text or "")

    for i, c in enumerate(PERSIAN):
        text = text.replace(c, ENGLISH[i])

    for i, c in enumerate(ARABIC):
        text = text.replace(c, ENGLISH[i])

    return text


def normalize_text(text):
    text = normalize_digits(text).strip()

    return (
        text
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
    )


def parse_amount(text):
    text = normalize_digits(text)

    if not re.fullmatch(r"\d+", text):
        return None

    value = int(text)

    return value if value > 0 else None


def money(value):
    return f"{int(value):,}"


def display_name(user):
    name = user.first_name or "کاربر"

    if user.last_name:
        name += " " + user.last_name

    return name


def owner(user_id):
    try:
        return int(user_id) == int(OWNER_ID)
    except Exception:
        return False


database.init_db()


def ensure_user(user):
    database.register_user(
        user.id,
        user.first_name or "",
        user.username or "",
    )


async def member_check(update, context):
    user = update.effective_user

    if user is None:
        return False

    if owner(user.id):
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
        logger.warning("Membership check: %s", e)

    await update.effective_message.reply_text(
        "⛔ برای استفاده از بات ابتدا عضو این گپ شوید:\n\n"
        f"{FORCE_CHAT}"
    )

    return False


async def balance(update, context):
    if not await member_check(update, context):
        return

    user = update.effective_user
    ensure_user(user)

    value = database.get_balance(user.id)

    await update.effective_message.reply_text(
        f"💰 موجودی امتیازی شما: {money(value)} {CURRENCY}\n\n"
        "ℹ️ این DOGS فقط امتیاز داخلی بازی است."
    )


async def transfer(update, context):
    if not await member_check(update, context):
        return

    message = update.effective_message
    sender = update.effective_user

    reply = message.reply_to_message

    if not reply or not reply.from_user:
        await message.reply_text(
            "❌ روی پیام کاربر Reply کن و بنویس:\n"
            "انتقال 100"
        )
        return

    receiver = reply.from_user

    if receiver.is_bot:
        await message.reply_text(
            "❌ به ربات نمی‌توان انتقال داد."
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
            "❌ مقدار صحیح نیست."
        )
        return

    ensure_user(sender)
    ensure_user(receiver)

    result = database.transfer_balance(
        sender.id,
        receiver.id,
        amount,
        "transfer:" + uuid.uuid4().hex,
    )

    if not result["success"]:
        if result.get("reason") == "insufficient_balance":
            await message.reply_text(
                "❌ امتیاز کافی نیست."
            )
        else:
            await message.reply_text(
                "❌ انتقال انجام نشد."
            )
        return

    await message.reply_text(
        "✅ انتقال امتیاز انجام شد.\n\n"
        f"👤 گیرنده: {display_name(receiver)}\n"
        f"💰 مقدار: {money(amount)} {CURRENCY}\n"
        f"💳 موجودی شما: "
        f"{money(result['sender_balance'])} {CURRENCY}"
    )


# =========================================================
# بازی‌های امتیازی
# =========================================================

async def dice_game(update, context):
    if not await member_check(update, context):
        return

    if not database.is_bot_enabled():
        await update.effective_message.reply_text(
            "🔴 بات خاموش است."
        )
        return

    message = update.effective_message
    user = update.effective_user

    parts = normalize_text(message.text).split()

    if len(parts) != 3:
        return

    round_number = parse_amount(parts[0])
    game = parts[1]
    amount = parse_amount(parts[2])

    if game not in ("تاس", "دارت", "بولینگ"):
        return

    if round_number is None or amount is None:
        return

    if not 1 <= round_number <= MAX_ROUNDS:
        await message.reply_text(
            f"❌ شماره بازی باید بین 1 تا {MAX_ROUNDS} باشد."
        )
        return

    ensure_user(user)

    # در این نسخه amount فقط امتیاز بازی است،
    # و برای شرط‌بندی یا پرداخت برد/باخت استفاده نمی‌شود.

    emoji = {
        "تاس": "🎲",
        "دارت": "🎯",
        "بولینگ": "🎳",
    }[game]

    await message.reply_text(
        f"{emoji} بازی {game} - راند {round_number}\n\n"
        f"👤 {display_name(user)}"
    )

    player = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji=emoji,
        reply_to_message_id=message.message_id,
    )

    await asyncio.sleep(1)

    bot = await context.bot.send_dice(
        chat_id=message.chat_id,
        emoji=emoji,
        reply_to_message_id=message.message_id,
    )

    player_value = player.dice.value
    bot_value = bot.dice.value

    if player_value > bot_value:
        result = "🏆 شما امتیاز بیشتری گرفتید."
    elif bot_value > player_value:
        result = "🤖 ربات امتیاز بیشتری گرفت."
    else:
        result = "🤝 مساوی شد."

    await message.reply_text(
        f"{emoji} نتیجه راند {round_number}\n\n"
        f"👤 شما: {player_value}\n"
        f"🤖 ربات: {bot_value}\n\n"
        f"{result}\n\n"
        f"ℹ️ مقدار {money(amount)} {CURRENCY} "
        "فقط به‌عنوان امتیاز اعلام‌شده بازی است و "
        "به‌عنوان پول یا دارایی واقعی استفاده نمی‌شود."
    )


async def lottery(update, context):
    if not await member_check(update, context):
        return

    if not database.is_bot_enabled():
        await update.effective_message.reply_text(
            "🔴 بات خاموش است."
        )
        return

    message = update.effective_message

    parts = normalize_text(message.text).split()

    if len(parts) != 2:
        return

    amount = parse_amount(parts[0])
    choice = parts[1]

    choices = {
        "زوج",
        "فرد",
        "قرمز",
        "سفید",
        "گل",
        "بیرون",
    }

    if amount is None or choice not in choices:
        return

    # زوج / فرد
    if choice in ("زوج", "فرد"):
        result = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🎲",
            reply_to_message_id=message.message_id,
        )

        value = result.dice.value
        outcome = "زوج" if value % 2 == 0 else "فرد"

    # قرمز / سفید
    elif choice in ("قرمز", "سفید"):
        # تلگرام رنگ دارت را به‌صورت فیلد مستقل
        # در اختیار بات قرار نمی‌دهد؛ بنابراین نتیجه
        # را خود بات به شکل شفاف و تصادفی تعیین می‌کند.
        import secrets

        result = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🎯",
            reply_to_message_id=message.message_id,
        )

        outcome = secrets.choice(
            ["قرمز", "سفید"]
        )

    # گل / بیرون
    else:
        result = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🏀",
            reply_to_message_id=message.message_id,
        )

        value = result.dice.value

        outcome = (
            "گل"
            if value in (4, 5)
            else "بیرون"
        )

    won = choice == outcome

    await message.reply_text(
        "🎟️ نتیجه بازی امتیازی\n\n"
        f"🎯 انتخاب شما: {choice}\n"
        f"🎲 نتیجه: {outcome}\n"
        f"📌 امتیاز بازی: {money(amount)} {CURRENCY}\n\n"
        + (
            "🏆 نتیجه: برنده"
            if won
            else "❌ نتیجه: بازنده"
        )
        + "\n\n"
        "ℹ️ DOGS در این بات فقط امتیاز مجازی "
        "داخل بازی است و ارزش یا برداشت واقعی ندارد."
    )


# =========================================================
# پنل مالک
# =========================================================

def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🟢 روشن",
                callback_data="admin:on"
            ),
            InlineKeyboardButton(
                "🔴 خاموش",
                callback_data="admin:off"
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 کاربران",
                callback_data="admin:users"
            ),
            InlineKeyboardButton(
                "📊 وضعیت",
                callback_data="admin:status"
            ),
        ],
    ])


async def admin(update, context):
    user = update.effective_user

    if not owner(user.id):
        return

    await update.effective_message.reply_text(
        "👑 پنل مدیریت\n\n"
        "از دکمه‌های زیر استفاده کن.\n\n"
        "شارژ امتیاز با Reply:\n"
        "شارژ 500\n\n"
        "کسر امتیاز با Reply:\n"
        "کسر 100",
        reply_markup=admin_keyboard(),
    )


async def admin_callback(update, context):
    query = update.callback_query

    await query.answer()

    user = query.from_user

    if not owner(user.id):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True,
        )
        return

    action = query.data.split(":", 1)[1]

    if action == "on":
        database.set_bot_enabled(True)

        await query.edit_message_text(
            "👑 پنل مدیریت\n\n"
            "🟢 بات روشن شد.",
            reply_markup=admin_keyboard(),
        )
        return

    if action == "off":
        database.set_bot_enabled(False)

        await query.edit_message_text(
            "👑 پنل مدیریت\n\n"
            "🔴 بات خاموش شد.",
            reply_markup=admin_keyboard(),
        )
        return

    if action == "status":
        status = (
            "🟢 روشن"
            if database.is_bot_enabled()
            else "🔴 خاموش"
        )

        await query.edit_message_text(
            f"👑 پنل مدیریت\n\n"
            f"📊 وضعیت: {status}",
            reply_markup=admin_keyboard(),
        )
        return

    if action == "users":
        users = database.get_all_users()

        if not users:
            text = "👥 کاربری ثبت نشده."
        else:
            lines = ["👥 کاربران:\n"]

            for row in users:
                name = row["first_name"] or "کاربر"

                lines.append(
                    f"👤 {name} — "
                    f"{money(row['balance'])} {CURRENCY}"
                )

            text = "\n".join(lines)

        await query.edit_message_text(
            text[:4000],
            reply_markup=admin_keyboard(),
        )


async def admin_charge(update, context):
    user = update.effective_user

    if not owner(user.id):
        return

    message = update.effective_message
    reply = message.reply_to_message

    if not reply or not reply.from_user:
        await message.reply_text(
            "❌ روی پیام کاربر Reply کن و بنویس:\n"
            "شارژ 500"
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
        "admin_charge:" + uuid.uuid4().hex,
        "افزایش امتیاز توسط مالک",
    )

    await message.reply_text(
        "✅ امتیاز اضافه شد.\n\n"
        f"👤 {display_name(target)}\n"
        f"➕ {money(amount)} {CURRENCY}\n"
        f"💳 موجودی: "
        f"{money(result['balance'])} {CURRENCY}"
    )


async def admin_deduct(update, context):
    user = update.effective_user

    if not owner(user.id):
        return

    message = update.effective_message
    reply = message.reply_to_message

    if not reply or not reply.from_user:
        await message.reply_text(
            "❌ روی پیام کاربر Reply کن و بنویس:\n"
            "کسر 100"
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
        "admin_deduct:" + uuid.uuid4().hex,
        "کاهش امتیاز توسط مالک",
    )

    if not result["success"]:
        await message.reply_text(
            "❌ امتیاز کافی نیست."
        )
        return

    await message.reply_text(
        "✅ امتیاز کم شد.\n\n"
        f"👤 {display_name(target)}\n"
        f"➖ {money(amount)} {CURRENCY}\n"
        f"💳 موجودی: "
        f"{money(result['balance'])} {CURRENCY}"
    )


async def start(update, context):
    user = update.effective_user

    if user:
        ensure_user(user)

    if not await member_check(update, context):
        return

    await update.effective_message.reply_text(
        "🎟️ بات بازی امتیازی\n\n"
        "💰 موجودی:\n"
        "م\n"
        "یا\n"
        "موجودی\n\n"
        "🎲 زوج / فرد:\n"
        "60 زوج\n"
        "60 فرد\n\n"
        "🎯 قرمز / سفید:\n"
        "60 قرمز\n"
        "60 سفید\n\n"
        "🏀 گل / بیرون:\n"
        "60 گل\n"
        "60 بیرون\n\n"
        "🤖 بازی با ربات:\n"
        "1 تاس 100\n"
        "1 دارت 100\n"
        "1 بولینگ 100\n\n"
        "🔄 انتقال امتیاز:\n"
        "روی پیام کاربر Reply کن:\n"
        "انتقال 100"
    )


async def text_router(update, context):
    message = update.effective_message

    if not message or not message.text:
        return

    text = normalize_text(message.text)
    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    if owner(user.id):
        if text in ("پنل", "پنل مدیریت"):
            await admin(update, context)
            return

        if text.startswith("شارژ "):
            await admin_charge(update, context)
            return

        if text.startswith("کسر "):
            await admin_deduct(update, context)
            return

        if text == "روشن":
            database.set_bot_enabled(True)
            await message.reply_text("🟢 بات روشن شد.")
            return

        if text == "خاموش":
            database.set_bot_enabled(False)
            await message.reply_text("🔴 بات خاموش شد.")
            return

    if text in ("م", "موجودی"):
        await balance(update, context)
        return

    if text.startswith("انتقال "):
        await transfer(update, context)
        return

    parts = text.split()

    if len(parts) == 3:
        if (
            parse_amount(parts[0])
            and parts[1] in ("تاس", "دارت", "بولینگ")
            and parse_amount(parts[2])
        ):
            await dice_game(update, context)
            return

    if len(parts) == 2:
        if (
            parse_amount(parts[0])
            and parts[1] in (
                "زوج",
                "فرد",
                "قرمز",
                "سفید",
                "گل",
                "بیرون",
            )
        ):
            await lottery(update, context)
            return


async def error_handler(update, context):
    logger.exception(
        "Telegram update error",
        exc_info=context.error,
    )


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
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("balance", balance)
    )

    app.add_handler(
        CommandHandler("admin", admin)
    )

    app.add_handler(
        CommandHandler("help", start)
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern=r"^admin:"
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    app.add_error_handler(
        error_handler
    )

    logger.info("Bot started")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
