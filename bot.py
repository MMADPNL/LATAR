import os
import re
import sqlite3
import asyncio
import logging
import uuid
import random
from contextlib import closing

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# تنظیمات اصلی
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# آیدی عددی مالک
OWNER_ID = int(os.getenv("OWNER_ID", "8552447077"))

# کانال/گپ اجباری
FORCE_CHAT = "@LATAR_tek"

# واحد موجودی
CURRENCY = "DOGS"

# حداکثر راند بازی با ربات
MAX_ROUNDS = 4

# ضریب بازی با ربات
BOT_MULTIPLIER = 2

# ضریب لاتاری تاس
DICE_LOTTERY_MULTIPLIER = 2

# ضریب لاتاری دارت
DART_LOTTERY_MULTIPLIER = 2

# ضریب لاتاری بسکتبال
BASKETBALL_LOTTERY_MULTIPLIER = 1.5

# فایل دیتابیس
DB_FILE = "latar.db"


# =========================================================
# LOG
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("LATAR")


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

    number = int(value)

    if number <= 0:
        return None

    return number


def money(value):
    return f"{int(value):,}"


# =========================================================
# DATABASE
# =========================================================

def db():
    connection = sqlite3.connect(
        DB_FILE,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_db():

    with closing(db()) as con:

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                balance INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_key TEXT UNIQUE,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                tx_type TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                game_id TEXT PRIMARY KEY,
                chat_id INTEGER,
                message_id INTEGER,
                user_id INTEGER,
                game_type TEXT,
                amount INTEGER,
                result TEXT DEFAULT '',
                reward INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        con.execute(
            """
            INSERT OR IGNORE INTO settings(key, value)
            VALUES('bot_enabled', '1')
            """
        )

        con.commit()


def ensure_user(user):

    with closing(db()) as con:

        con.execute(
            """
            INSERT INTO users(
                user_id,
                first_name,
                username
            )
            VALUES(?, ?, ?)

            ON CONFLICT(user_id)
            DO UPDATE SET
                first_name=excluded.first_name,
                username=excluded.username
            """,
            (
                user.id,
                user.first_name or "",
                user.username or "",
            ),
        )

        con.commit()


def get_balance(user_id):

    with closing(db()) as con:

        row = con.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()

        if not row:
            return 0

        return int(row["balance"])


def change_balance(
    user_id,
    amount,
    tx_key,
    tx_type,
    description="",
):

    amount = int(amount)

    with closing(db()) as con:

        try:

            con.execute("BEGIN IMMEDIATE")

            row = con.execute(
                """
                SELECT balance
                FROM users
                WHERE user_id=?
                """,
                (user_id,),
            ).fetchone()

            if not row:
                con.rollback()

                return {
                    "success": False,
                    "reason": "user_not_found",
                }

            old_balance = int(
                row["balance"]
            )

            new_balance = old_balance + amount

            if new_balance < 0:

                con.rollback()

                return {
                    "success": False,
                    "reason": "insufficient_balance",
                    "balance": old_balance,
                }

            con.execute(
                """
                UPDATE users
                SET balance=?
                WHERE user_id=?
                """,
                (
                    new_balance,
                    user_id,
                ),
            )

            con.execute(
                """
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    tx_type,
                    description
                )
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    tx_key,
                    user_id,
                    amount,
                    tx_type,
                    description,
                ),
            )

            con.commit()

            return {
                "success": True,
                "balance": new_balance,
            }

        except sqlite3.IntegrityError:

            con.rollback()

            row = con.execute(
                """
                SELECT balance
                FROM users
                WHERE user_id=?
                """,
                (user_id,),
            ).fetchone()

            return {
                "success": True,
                "balance": int(row["balance"])
                if row else 0,
                "duplicate": True,
            }

        except Exception as e:

            con.rollback()

            logger.exception(
                "BALANCE ERROR: %s",
                e,
            )

            return {
                "success": False,
                "reason": "database_error",
            }


def add_balance(
    user_id,
    amount,
    tx_key,
    description="",
):

    return change_balance(
        user_id,
        abs(int(amount)),
        tx_key,
        "credit",
        description,
    )


def withdraw_balance(
    user_id,
    amount,
    tx_key,
    description="",
):

    return change_balance(
        user_id,
        -abs(int(amount)),
        tx_key,
        "debit",
        description,
    )


def transfer_balance(
    sender_id,
    receiver_id,
    amount,
    tx_key,
):

    amount = int(amount)

    if amount <= 0:
        return {
            "success": False,
            "reason": "invalid_amount",
        }

    with closing(db()) as con:

        try:

            con.execute("BEGIN IMMEDIATE")

            sender = con.execute(
                """
                SELECT balance
                FROM users
                WHERE user_id=?
                """,
                (sender_id,),
            ).fetchone()

            receiver = con.execute(
                """
                SELECT balance
                FROM users
                WHERE user_id=?
                """,
                (receiver_id,),
            ).fetchone()

            if not sender or not receiver:

                con.rollback()

                return {
                    "success": False,
                    "reason": "user_not_found",
                }

            sender_balance = int(
                sender["balance"]
            )

            receiver_balance = int(
                receiver["balance"]
            )

            if sender_balance < amount:

                con.rollback()

                return {
                    "success": False,
                    "reason": "insufficient_balance",
                    "sender_balance": sender_balance,
                }

            con.execute(
                """
                UPDATE users
                SET balance=balance-?
                WHERE user_id=?
                """,
                (
                    amount,
                    sender_id,
                ),
            )

            con.execute(
                """
                UPDATE users
                SET balance=balance+?
                WHERE user_id=?
                """,
                (
                    amount,
                    receiver_id,
                ),
            )

            con.execute(
                """
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    tx_type,
                    description
                )
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    tx_key,
                    sender_id,
                    -amount,
                    "transfer_out",
                    f"انتقال به {receiver_id}",
                ),
            )

            receiver_tx_key = (
                tx_key + ":receiver"
            )

            con.execute(
                """
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    tx_type,
                    description
                )
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    receiver_tx_key,
                    receiver_id,
                    amount,
                    "transfer_in",
                    f"انتقال از {sender_id}",
                ),
            )

            con.commit()

            return {
                "success": True,
                "sender_balance":
                    sender_balance - amount,
                "receiver_balance":
                    receiver_balance + amount,
            }

        except sqlite3.IntegrityError:

            con.rollback()

            return {
                "success": False,
                "reason": "duplicate",
            }

        except Exception as e:

            con.rollback()

            logger.exception(
                "TRANSFER ERROR: %s",
                e,
            )

            return {
                "success": False,
                "reason": "database_error",
            }


def create_game(
    game_id,
    chat_id,
    message_id,
    user_id,
    game_type,
    amount,
):

    with closing(db()) as con:

        try:

            con.execute(
                """
                INSERT INTO games(
                    game_id,
                    chat_id,
                    message_id,
                    user_id,
                    game_type,
                    amount
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    chat_id,
                    message_id,
                    user_id,
                    game_type,
                    amount,
                ),
            )

            con.commit()

            return True

        except sqlite3.IntegrityError:

            return False


def finish_game(
    game_id,
    result,
    reward,
):

    with closing(db()) as con:

        con.execute(
            """
            UPDATE games
            SET result=?,
                reward=?
            WHERE game_id=?
            """,
            (
                result,
                reward,
                game_id,
            ),
        )

        con.commit()


def is_bot_enabled():

    with closing(db()) as con:

        row = con.execute(
            """
            SELECT value
            FROM settings
            WHERE key='bot_enabled'
            """
        ).fetchone()

        if not row:
            return True

        return row["value"] == "1"


def set_bot_enabled(enabled):

    with closing(db()) as con:

        con.execute(
            """
            INSERT INTO settings(
                key,
                value
            )
            VALUES('bot_enabled', ?)

            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
            """,
            (
                "1" if enabled else "0",
            ),
        )

        con.commit()


def get_all_users():

    with closing(db()) as con:

        return con.execute(
            """
            SELECT
                user_id,
                first_name,
                username,
                balance
            FROM users
            ORDER BY balance DESC
            """
        ).fetchall()


# =========================================================
# USER HELPERS
# =========================================================

def is_owner(user_id):

    try:
        return int(user_id) == int(OWNER_ID)

    except Exception:
        return False


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

    if is_owner(user.id):
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
            "JOIN CHECK: %s",
            e,
        )

    await update.effective_message.reply_text(
        "⛔ ابتدا عضو کانال زیر شوید:\n\n"
        "https://t.me/LATAR_tek\n\n"
        "بعد دوباره دستور را ارسال کنید."
    )

    return False


# =========================================================
# موجودی
# =========================================================

async def show_balance(
    update,
    context,
):

    if not await check_join(
        update,
        context,
    ):
        return

    user = update.effective_user

    ensure_user(user)

    balance = get_balance(
        user.id
    )

    await update.effective_message.reply_text(
        "💰 موجودی شما:\n\n"
        f"{money(balance)} {CURRENCY}"
    )


# =========================================================
# انتقال
# فقط در گپ
# Reply + انتقال 100
# =========================================================

async def transfer(
    update,
    context,
):

    if not await check_join(
        update,
        context,
    ):
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
            "❌ به ربات نمی‌توانی انتقال بدهی."
        )

        return

    if target.id == user.id:

        await message.reply_text(
            "❌ انتقال به خودت امکان‌پذیر نیست."
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

    tx_key = (
        "transfer:"
        f"{message.chat_id}:"
        f"{message.message_id}"
    )

    result = transfer_balance(
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
        f"{money(result['sender_balance'])} "
        f"{CURRENCY}"
    )


# =========================================================
# شارژ مالک
#
# نتیجه در گپ نمایش داده نمی‌شود.
# =========================================================

async def admin_charge(
    update,
    context,
):

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
            "❌ روی پیام کاربر Reply کن."
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

    result = add_balance(
        target.id,
        amount,
        tx_key,
        "شارژ توسط مالک",
    )

    if not result["success"]:
        return

    # نتیجه برای مالک در خصوصی
    # اگر ربات اجازه ارسال خصوصی داشته باشد.
    try:

        await context.bot.send_message(
            chat_id=user.id,
            text=(
                "✅ شارژ انجام شد.\n\n"
                f"👤 کاربر: "
                f"{display_name(target)}\n"
                f"➕ {money(amount)} {CURRENCY}\n"
                f"💳 موجودی جدید: "
                f"{money(result['balance'])} "
                f"{CURRENCY}"
            ),
        )

    except Exception:

        # در گپ هیچ نتیجه‌ای چاپ نمی‌کنیم.
        pass


# =========================================================
# کسر مالک
# =========================================================

async def admin_deduct(
    update,
    context,
):

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
            "❌ روی پیام کاربر Reply کن."
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

    result = withdraw_balance(
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
                f"👤 کاربر: "
                f"{display_name(target)}\n"
                f"➖ {money(amount)} {CURRENCY}\n"
                f"💳 موجودی جدید: "
                f"{money(result['balance'])} "
                f"{CURRENCY}"
            ),
        )

    except Exception:
        pass


# =========================================================
# مدیریت روشن / خاموش
# =========================================================

async def admin_on(
    update,
    context,
):

    if not is_owner(
        update.effective_user.id
    ):
        return

    set_bot_enabled(True)

    await update.effective_message.reply_text(
        "🟢 بات روشن شد."
    )


async def admin_off(
    update,
    context,
):

    if not is_owner(
        update.effective_user.id
    ):
        return

    set_bot_enabled(False)

    await update.effective_message.reply_text(
        "🔴 بات خاموش شد."
    )


# =========================================================
# بازی با ربات
#
# 1 تاس 100
# 1 دارت 100
# 1 بولینگ 100
#
# 1 تا 4 راند
#
# اول کاربر
# بعد ربات
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

    if game not in (
        "تاس",
        "دارت",
        "بولینگ",
    ):
        return None

    if rounds > MAX_ROUNDS:
        return None

    return (
        rounds,
        game,
        amount,
    )


async def play_bot_game(
    update,
    context,
):

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

    if not is_bot_enabled():

        await message.reply_text(
            "🔴 بات خاموش است."
        )

        return

    ensure_user(user)

    current_balance = get_balance(
        user.id
    )

    if current_balance < amount:

        await message.reply_text(
            "❌ موجودی کافی نیست.\n\n"
            f"💰 موجودی: "
            f"{money(current_balance)} "
            f"{CURRENCY}"
        )

        return

    game_id = uuid.uuid4().hex

    if not create_game(
        game_id,
        message.chat_id,
        message.message_id,
        user.id,
        f"bot:{game}",
        amount,
    ):

        await message.reply_text(
            "❌ این بازی قبلاً ثبت شده."
        )

        return

    emoji = {
        "تاس": "🎲",
        "دارت": "🎯",
        "بولینگ": "🎳",
    }[game]

    user_wins = 0
    bot_wins = 0
    draws = 0

    lines = []

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
        # نتیجه
        # ---------------------------------------------

        if user_value > bot_value:

            user_wins += 1

            winner = "👤 شما"

        elif bot_value > user_value:

            bot_wins += 1

            winner = "🤖 ربات"

        else:

            draws += 1

            winner = "🤝 مساوی"

        lines.append(
            f"🎮 راند {round_number}\n"
            f"👤 شما: {user_value}\n"
            f"🤖 ربات: {bot_value}\n"
            f"🏁 {winner}"
        )

    # =====================================================
    # کاربر برنده
    # =====================================================

    if user_wins > bot_wins:

        reward = int(
            amount * BOT_MULTIPLIER
        )

        payment = add_balance(
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

        finish_game(
            game_id,
            (
                f"WIN|"
                f"user={user_wins}|"
                f"bot={bot_wins}|"
                f"draw={draws}"
            ),
            reward,
        )

        final = (
            "🏆 برنده شدی!\n\n"
            f"➕ {money(reward)} {CURRENCY} "
            "اضافه شد.\n"
            "ℹ️ مبلغ بازی از حسابت کسر نشد.\n"
            f"📈 ضریب: {BOT_MULTIPLIER}x\n"
            f"💳 موجودی جدید: "
            f"{money(payment['balance'])} "
            f"{CURRENCY}"
        )

    # =====================================================
    # ربات برنده
    # =====================================================

    elif bot_wins > user_wins:

        loss = withdraw_balance(
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

        finish_game(
            game_id,
            (
                f"LOSS|"
                f"user={user_wins}|"
                f"bot={bot_wins}|"
                f"draw={draws}"
            ),
            0,
        )

        final = (
            "❌ باختی.\n\n"
            f"➖ {money(amount)} {CURRENCY} "
            "کسر شد.\n"
            f"💳 موجودی جدید: "
            f"{money(loss['balance'])} "
            f"{CURRENCY}"
        )

    # =====================================================
    # مساوی
    # =====================================================

    else:

        finish_game(
            game_id,
            (
                f"DRAW|"
                f"user={user_wins}|"
                f"bot={bot_wins}|"
                f"draw={draws}"
            ),
            0,
        )

        final = (
            "🤝 بازی مساوی شد.\n\n"
            "💰 موجودی تغییر نکرد."
        )

    await message.reply_text(
        f"{emoji} بازی {game} با ربات\n\n"
        + "\n\n".join(lines)
        + "\n\n"
        f"📊 شما: {user_wins} برد\n"
        f"🤖 ربات: {bot_wins} برد\n"
        f"🤝 مساوی: {draws}\n\n"
        + final
    )


# =========================================================
# لاتاری
#
# تاس:
# 300 زوج
# 300 فرد
#
# بسکتبال:
# 300 گل
# 300 بیرون
#
# دارت:
# 300 قرمز
# 300 سفید
#
# فقط کاربر پرتاب می‌کند.
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


# =========================================================
# لاتاری
# =========================================================

async def play_lottery(
    update,
    context,
):

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

    if not is_bot_enabled():

        await message.reply_text(
            "🔴 بات خاموش است."
        )

        return

    ensure_user(user)

    current_balance = get_balance(
        user.id
    )

    if current_balance < amount:

        await message.reply_text(
            "❌ موجودی کافی نیست.\n\n"
            f"💰 موجودی: "
            f"{money(current_balance)} "
            f"{CURRENCY}"
        )

        return

    game_id = uuid.uuid4().hex

    if not create_game(
        game_id,
        message.chat_id,
        message.message_id,
        user.id,
        f"lottery:{game}:{choice}",
        amount,
    ):

        await message.reply_text(
            "❌ این بازی قبلاً ثبت شده."
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

        multiplier = DICE_LOTTERY_MULTIPLIER

        title = "🎲 لاتاری تاس"

        detail = (
            f"🎲 عدد: {value}\n"
            f"🎯 نتیجه: {result}"
        )

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

        multiplier = BASKETBALL_LOTTERY_MULTIPLIER

        title = "🏀 لاتاری بسکتبال"

        detail = (
            f"🏀 نتیجه پرتاب: {result}"
        )

    # =====================================================
    # دارت
    #
    # دارت Telegram عدد می‌دهد.
    # برای لاتاری قرمز/سفید:
    # زوج = قرمز
    # فرد = سفید
    #
    # =====================================================

    else:

        roll = await context.bot.send_dice(
            chat_id=message.chat_id,
            emoji="🎯",
            reply_to_message_id=message.message_id,
        )

        await asyncio.sleep(2)

        value = roll.dice.value

        result = (
            "قرمز"
            if value % 2 == 0
            else "سفید"
        )

        won = result == choice

        multiplier = DART_LOTTERY_MULTIPLIER

        title = "🎯 لاتاری دارت"

        detail = (
            f"🎯 عدد دارت: {value}\n"
            f"🎯 نتیجه: {result}"
        )

    # =====================================================
    # برد
    # =====================================================

    if won:

        reward = int(
            amount * multiplier
        )

        payment = add_balance(
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

        finish_game(
            game_id,
            f"WIN:{result}",
            reward,
        )

        await message.reply_text(
            f"{title}\n\n"
            f"👤 انتخاب شما: {choice}\n"
            f"{detail}\n\n"
            "🏆 برنده شدی!\n\n"
            f"➕ {money(reward)} {CURRENCY} "
            "اضافه شد.\n"
            "ℹ️ مبلغ بازی از حسابت کسر نشد.\n"
            f"📈 ضریب: {multiplier}x\n"
            f"💳 موجودی جدید: "
            f"{money(payment['balance'])} "
            f"{CURRENCY}"
        )

        return

    # =====================================================
    # باخت
    # =====================================================

    loss = withdraw_balance(
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

    finish_game(
        game_id,
        f"LOSS:{result}",
        0,
    )

    await message.reply_text(
        f"{title}\n\n"
        f"👤 انتخاب شما: {choice}\n"
        f"{detail}\n\n"
        "❌ باختی!\n\n"
        f"➖ {money(amount)} {CURRENCY} "
        "کسر شد.\n"
        f"💳 موجودی جدید: "
        f"{money(loss['balance'])} "
        f"{CURRENCY}"
    )


# =========================================================
# پنل
# =========================================================

async def admin_panel(
    update,
    context,
):

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
        "داخل گپ:\n"
        "Reply → شارژ 100\n"
        "Reply → کسر 100\n"
        "Reply → انتقال 100"
    )


async def admin_users(
    update,
    context,
):

    if not is_owner(
        update.effective_user.id
    ):
        return

    rows = get_all_users()

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


async def admin_status(
    update,
    context,
):

    if not is_owner(
        update.effective_user.id
    ):
        return

    state = (
        "🟢 روشن"
        if is_bot_enabled()
        else "🔴 خاموش"
    )

    await update.effective_message.reply_text(
        f"📊 وضعیت: {state}"
    )


# =========================================================
# START
# =========================================================

async def start(
    update,
    context,
):

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
        "Reply → انتقال 100\n\n"

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
        "300 گل\n"
        "300 بیرون\n\n"

        "📌 برد بازی با ربات:\n"
        "2 برابر مبلغ اضافه می‌شود.\n\n"

        "📌 برد لاتاری بسکتبال:\n"
        "1.5 برابر مبلغ اضافه می‌شود.\n\n"

        "🛡️ ضد دستور و ضد دوباره‌پردازش فعال است.\n"
        f"💰 واحد: {CURRENCY} مجازی"
    )


# =========================================================
# ROUTER
#
# مهم:
# فقط یک MessageHandler داریم.
# هر پیام فقط یک بار بررسی می‌شود.
# =========================================================

async def router(
    update,
    context,
):

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
    # دستورات مالک
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

    bot_game = parse_bot_game(
        text
    )

    if bot_game:

        await play_bot_game(
            update,
            context,
        )

        return

    # =====================================================
    # لاتاری
    # =====================================================

    lottery = parse_lottery(
        text
    )

    if lottery:

        await play_lottery(
            update,
            context,
        )

        return

    # =====================================================
    # ضد دستور
    #
    # پیام ناشناخته هیچ کاری نمی‌کند.
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

    init_db()

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN در Environment Variables قرار داده نشده است."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    # /balance
    application.add_handler(
        CommandHandler(
            "balance",
            show_balance,
        )
    )

    # /admin
    application.add_handler(
        CommandHandler(
            "admin",
            admin_panel,
        )
    )

    # فقط یک Router برای متن
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
