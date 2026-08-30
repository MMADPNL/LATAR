import os 
import sqlite3
import threading
from contextlib import contextmanager

try:
    from config import DATABASE_PATH
except ImportError:
    DATABASE_PATH = "data/database.db"


# =========================================================
# تنظیمات
# =========================================================

DB_PATH = DATABASE_PATH or "data/database.db"

_db_lock = threading.RLock()


# =========================================================
# اتصال دیتابیس
# =========================================================

def _prepare_database_path():
    folder = os.path.dirname(DB_PATH)

    if folder:
        os.makedirs(folder, exist_ok=True)


@contextmanager
def get_db():
    _prepare_database_path()

    with _db_lock:
        conn = sqlite3.connect(
            DB_PATH,
            timeout=30,
            isolation_level=None,
        )

        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")

            yield conn

        finally:
            conn.close()


# =========================================================
# ساخت جداول
# =========================================================

def init_db():
    _prepare_database_path()

    with get_db() as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                balance INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                tx_key TEXT NOT NULL UNIQUE,

                user_id INTEGER NOT NULL,

                amount INTEGER NOT NULL,

                balance_after INTEGER NOT NULL,

                description TEXT NOT NULL DEFAULT '',

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_transactions_user
            ON transactions(user_id)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_transactions_created
            ON transactions(created_at)
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                game_id TEXT PRIMARY KEY,

                chat_id INTEGER NOT NULL,

                message_id INTEGER NOT NULL,

                user_id INTEGER NOT NULL,

                game_type TEXT NOT NULL,

                amount INTEGER NOT NULL DEFAULT 0,

                result TEXT NOT NULL DEFAULT '',

                reward INTEGER NOT NULL DEFAULT 0,

                finished INTEGER NOT NULL DEFAULT 0,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_games_user
            ON games(user_id)
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        db.execute("""
            INSERT OR IGNORE INTO settings(key, value)
            VALUES('bot_enabled', '1')
        """)


# =========================================================
# کاربر
# =========================================================

def register_user(
    user_id,
    first_name="",
    username="",
):
    init_db()

    user_id = int(user_id)

    with get_db() as db:
        db.execute("""
            INSERT INTO users(
                user_id,
                first_name,
                username,
                balance
            )
            VALUES (?, ?, ?, 0)

            ON CONFLICT(user_id)
            DO UPDATE SET
                first_name = excluded.first_name,
                username = excluded.username,
                updated_at = CURRENT_TIMESTAMP
        """, (
            user_id,
            str(first_name or ""),
            str(username or ""),
        ))


# =========================================================
# اطمینان از وجود کاربر
# =========================================================

def ensure_user(user_id):
    init_db()

    user_id = int(user_id)

    with get_db() as db:
        db.execute("""
            INSERT OR IGNORE INTO users(
                user_id,
                balance
            )
            VALUES (?, 0)
        """, (user_id,))


# =========================================================
# موجودی
# =========================================================

def get_balance(user_id):
    init_db()

    user_id = int(user_id)

    with get_db() as db:
        row = db.execute("""
            SELECT balance
            FROM users
            WHERE user_id=?
        """, (user_id,)).fetchone()

        if row is None:
            db.execute("""
                INSERT INTO users(
                    user_id,
                    balance
                )
                VALUES (?, 0)
            """, (user_id,))

            return 0

        return int(row["balance"])


# =========================================================
# تغییر موجودی امن
#
# tx_key باعث می‌شود یک عملیات دوبار اعمال نشود.
# =========================================================

def _change_balance(
    user_id,
    amount,
    tx_key,
    description="",
):
    init_db()

    user_id = int(user_id)
    amount = int(amount)

    if not tx_key:
        return {
            "success": False,
            "reason": "missing_tx_key",
        }

    if amount == 0:
        return {
            "success": False,
            "reason": "zero_amount",
        }

    with get_db() as db:

        db.execute("BEGIN IMMEDIATE")

        try:

            # ---------------------------------------------
            # ضدتکرار
            # ---------------------------------------------

            old_tx = db.execute("""
                SELECT
                    balance_after
                FROM transactions
                WHERE tx_key=?
            """, (
                tx_key,
            )).fetchone()

            if old_tx is not None:

                db.execute("COMMIT")

                return {
                    "success": True,
                    "duplicate": True,
                    "balance": int(
                        old_tx["balance_after"]
                    ),
                }

            # ---------------------------------------------
            # ساخت کاربر در صورت نبودن
            # ---------------------------------------------

            db.execute("""
                INSERT OR IGNORE INTO users(
                    user_id,
                    balance
                )
                VALUES (?, 0)
            """, (
                user_id,
            ))

            # ---------------------------------------------
            # گرفتن موجودی فعلی
            # ---------------------------------------------

            row = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id=?
            """, (
                user_id,
            )).fetchone()

            old_balance = int(row["balance"])

            # ---------------------------------------------
            # موجودی جدید
            # ---------------------------------------------

            new_balance = old_balance + amount

            # ---------------------------------------------
            # ضد موجودی منفی
            # ---------------------------------------------

            if new_balance < 0:

                db.execute("ROLLBACK")

                return {
                    "success": False,
                    "reason": "insufficient_balance",
                    "balance": old_balance,
                }

            # ---------------------------------------------
            # تغییر موجودی
            # ---------------------------------------------

            db.execute("""
                UPDATE users
                SET
                    balance=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (
                new_balance,
                user_id,
            ))

            # ---------------------------------------------
            # ثبت تراکنش
            # ---------------------------------------------

            db.execute("""
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    balance_after,
                    description
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                tx_key,
                user_id,
                amount,
                new_balance,
                str(description or ""),
            ))

            db.execute("COMMIT")

            return {
                "success": True,
                "duplicate": False,
                "balance": new_balance,
                "amount": amount,
            }

        except Exception:

            db.execute("ROLLBACK")

            raise


# =========================================================
# شارژ
# =========================================================

def add_balance(
    user_id,
    amount,
    tx_key,
    description="",
):
    amount = int(amount)

    if amount <= 0:
        return {
            "success": False,
            "reason": "invalid_amount",
        }

    return _change_balance(
        user_id=user_id,
        amount=amount,
        tx_key=tx_key,
        description=description,
    )


# =========================================================
# کسر
# =========================================================

def withdraw_balance(
    user_id,
    amount,
    tx_key,
    description="",
):
    amount = int(amount)

    if amount <= 0:
        return {
            "success": False,
            "reason": "invalid_amount",
        }

    return _change_balance(
        user_id=user_id,
        amount=-amount,
        tx_key=tx_key,
        description=description,
    )


# =========================================================
# انتقال
#
# هر دو تغییر در یک تراکنش SQLite انجام می‌شوند.
# =========================================================

def transfer_balance(
    sender_id,
    receiver_id,
    amount,
    tx_key,
):
    init_db()

    sender_id = int(sender_id)
    receiver_id = int(receiver_id)
    amount = int(amount)

    if sender_id == receiver_id:
        return {
            "success": False,
            "reason": "same_user",
        }

    if amount <= 0:
        return {
            "success": False,
            "reason": "invalid_amount",
        }

    if not tx_key:
        return {
            "success": False,
            "reason": "missing_tx_key",
        }

    with get_db() as db:

        db.execute("BEGIN IMMEDIATE")

        try:

            # ---------------------------------------------
            # ضدتکرار انتقال
            # ---------------------------------------------

            old_tx = db.execute("""
                SELECT
                    balance_after
                FROM transactions
                WHERE tx_key=?
            """, (
                tx_key,
            )).fetchone()

            if old_tx is not None:

                sender = db.execute("""
                    SELECT balance
                    FROM users
                    WHERE user_id=?
                """, (
                    sender_id,
                )).fetchone()

                receiver = db.execute("""
                    SELECT balance
                    FROM users
                    WHERE user_id=?
                """, (
                    receiver_id,
                )).fetchone()

                db.execute("COMMIT")

                return {
                    "success": True,
                    "duplicate": True,
                    "sender_balance": (
                        int(sender["balance"])
                        if sender
                        else 0
                    ),
                    "receiver_balance": (
                        int(receiver["balance"])
                        if receiver
                        else 0
                    ),
                }

            # ---------------------------------------------
            # ساخت کاربران
            # ---------------------------------------------

            db.execute("""
                INSERT OR IGNORE INTO users(
                    user_id,
                    balance
                )
                VALUES (?, 0)
            """, (
                sender_id,
            ))

            db.execute("""
                INSERT OR IGNORE INTO users(
                    user_id,
                    balance
                )
                VALUES (?, 0)
            """, (
                receiver_id,
            ))

            # ---------------------------------------------
            # موجودی فرستنده
            # ---------------------------------------------

            sender = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id=?
            """, (
                sender_id,
            )).fetchone()

            receiver = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id=?
            """, (
                receiver_id,
            )).fetchone()

            sender_balance = int(
                sender["balance"]
            )

            receiver_balance = int(
                receiver["balance"]
            )

            # ---------------------------------------------
            # موجودی کافی نیست
            # ---------------------------------------------

            if sender_balance < amount:

                db.execute("ROLLBACK")

                return {
                    "success": False,
                    "reason": "insufficient_balance",
                    "sender_balance": sender_balance,
                }

            # ---------------------------------------------
            # محاسبه
            # ---------------------------------------------

            new_sender_balance = (
                sender_balance - amount
            )

            new_receiver_balance = (
                receiver_balance + amount
            )

            # ---------------------------------------------
            # فرستنده
            # ---------------------------------------------

            db.execute("""
                UPDATE users
                SET
                    balance=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (
                new_sender_balance,
                sender_id,
            ))

            # ---------------------------------------------
            # گیرنده
            # ---------------------------------------------

            db.execute("""
                UPDATE users
                SET
                    balance=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (
                new_receiver_balance,
                receiver_id,
            ))

            # ---------------------------------------------
            # تراکنش فرستنده
            # ---------------------------------------------

            db.execute("""
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    balance_after,
                    description
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                tx_key + ":sender",
                sender_id,
                -amount,
                new_sender_balance,
                "انتقال",
            ))

            # ---------------------------------------------
            # تراکنش گیرنده
            # ---------------------------------------------

            db.execute("""
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    balance_after,
                    description
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                tx_key + ":receiver",
                receiver_id,
                amount,
                new_receiver_balance,
                "دریافت انتقال",
            ))

            # ---------------------------------------------
            # کلید اصلی انتقال
            # ---------------------------------------------

            db.execute("""
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    balance_after,
                    description
                )
                VALUES (?, ?, 0, ?, ?)
            """, (
                tx_key,
                sender_id,
                new_sender_balance,
                "انتقال",
            ))

            db.execute("COMMIT")

            return {
                "success": True,
                "duplicate": False,
                "sender_balance": new_sender_balance,
                "receiver_balance": new_receiver_balance,
            }

        except Exception:

            db.execute("ROLLBACK")

            raise


# =========================================================
# بازی
# =========================================================

def create_game(
    game_id,
    chat_id,
    message_id,
    user_id,
    game_type,
    amount=0,
):
    init_db()

    with get_db() as db:

        try:

            db.execute("""
                INSERT INTO games(
                    game_id,
                    chat_id,
                    message_id,
                    user_id,
                    game_type,
                    amount
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                str(game_id),
                int(chat_id),
                int(message_id),
                int(user_id),
                str(game_type),
                int(amount),
            ))

            return True

        except sqlite3.IntegrityError:

            return False


def finish_game(
    game_id,
    result,
    reward=0,
):
    init_db()

    with get_db() as db:

        cursor = db.execute("""
            UPDATE games
            SET
                result=?,
                reward=?,
                finished=1
            WHERE game_id=?
              AND finished=0
        """, (
            str(result),
            int(reward),
            str(game_id),
        ))

        return cursor.rowcount == 1


# =========================================================
# وضعیت ربات
# =========================================================

def is_bot_enabled():
    init_db()

    with get_db() as db:

        row = db.execute("""
            SELECT value
            FROM settings
            WHERE key='bot_enabled'
        """).fetchone()

        if row is None:
            return True

        return row["value"] == "1"


def set_bot_enabled(enabled):
    init_db()

    with get_db() as db:

        db.execute("""
            INSERT INTO settings(
                key,
                value
            )
            VALUES('bot_enabled', ?)

            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value
        """, (
            "1" if enabled else "0",
        ))


# =========================================================
# کاربران
# =========================================================

def get_all_users():
    init_db()

    with get_db() as db:

        return db.execute("""
            SELECT
                user_id,
                first_name,
                username,
                balance,
                created_at,
                updated_at
            FROM users
            ORDER BY balance DESC
        """).fetchall()


# =========================================================
# اطلاعات کاربر
# =========================================================

def get_user(user_id):
    init_db()

    with get_db() as db:

        return db.execute("""
            SELECT
                user_id,
                first_name,
                username,
                balance,
                created_at,
                updated_at
            FROM users
            WHERE user_id=?
        """, (
            int(user_id),
        )).fetchone()


# =========================================================
# تاریخچه تراکنش‌ها
# =========================================================

def get_transactions(
    user_id,
    limit=50,
):
    init_db()

    limit = max(1, min(int(limit), 500))

    with get_db() as db:

        return db.execute("""
            SELECT
                id,
                tx_key,
                user_id,
                amount,
                balance_after,
                description,
                created_at
            FROM transactions
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT ?
        """, (
            int(user_id),
            limit,
        )).fetchall()


# =========================================================
# حذف نکن
# تست اولیه دیتابیس
# =========================================================

init_db()
