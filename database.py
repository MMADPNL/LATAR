import sqlite3
import threading
from contextlib import contextmanager

DB_FILE = "latar.db"

_db_lock = threading.RLock()


@contextmanager
def get_db():
    with _db_lock:
        conn = sqlite3.connect(
            DB_FILE,
            timeout=30,
            isolation_level=None,
        )

        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()


def init_db():
    with get_db() as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                balance INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_key TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                game_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                game_type TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                result TEXT DEFAULT '',
                reward INTEGER NOT NULL DEFAULT 0,
                finished INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
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


def register_user(user_id, first_name="", username=""):
    init_db()

    with get_db() as db:
        db.execute("""
            INSERT INTO users(
                user_id,
                first_name,
                username
            )
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                first_name=excluded.first_name,
                username=excluded.username,
                updated_at=CURRENT_TIMESTAMP
        """, (
            int(user_id),
            first_name or "",
            username or "",
        ))


def get_balance(user_id):
    init_db()

    with get_db() as db:
        row = db.execute("""
            SELECT balance
            FROM users
            WHERE user_id=?
        """, (int(user_id),)).fetchone()

        if row is None:
            register_user(user_id)
            return 0

        return int(row["balance"])


def _change_balance(
    user_id,
    amount,
    tx_key,
    description="",
    allow_negative=False,
):
    init_db()

    user_id = int(user_id)
    amount = int(amount)

    if not tx_key:
        return {
            "success": False,
            "reason": "missing_tx_key",
        }

    with get_db() as db:

        db.execute("BEGIN IMMEDIATE")

        try:
            old_tx = db.execute("""
                SELECT
                    user_id,
                    balance_after
                FROM transactions
                WHERE tx_key=?
            """, (tx_key,)).fetchone()

            if old_tx is not None:
                db.execute("COMMIT")

                return {
                    "success": True,
                    "duplicate": True,
                    "balance": int(old_tx["balance_after"]),
                }

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

                old_balance = 0

            else:
                old_balance = int(row["balance"])

            new_balance = old_balance + amount

            if not allow_negative and new_balance < 0:
                db.execute("ROLLBACK")

                return {
                    "success": False,
                    "reason": "insufficient_balance",
                    "balance": old_balance,
                }

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
                description or "",
            ))

            db.execute("COMMIT")

            return {
                "success": True,
                "duplicate": False,
                "balance": new_balance,
            }

        except Exception:
            db.execute("ROLLBACK")
            raise


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
        user_id,
        amount,
        tx_key,
        description,
        False,
    )


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
        user_id,
        -amount,
        tx_key,
        description,
        False,
    )


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
            old_tx = db.execute("""
                SELECT balance_after
                FROM transactions
                WHERE tx_key=?
            """, (tx_key,)).fetchone()

            if old_tx is not None:
                sender = db.execute("""
                    SELECT balance
                    FROM users
                    WHERE user_id=?
                """, (sender_id,)).fetchone()

                receiver = db.execute("""
                    SELECT balance
                    FROM users
                    WHERE user_id=?
                """, (receiver_id,)).fetchone()

                db.execute("COMMIT")

                return {
                    "success": True,
                    "duplicate": True,
                    "sender_balance": (
                        int(sender["balance"])
                        if sender else 0
                    ),
                    "receiver_balance": (
                        int(receiver["balance"])
                        if receiver else 0
                    ),
                }

            db.execute("""
                INSERT OR IGNORE INTO users(user_id, balance)
                VALUES (?, 0)
            """, (sender_id,))

            db.execute("""
                INSERT OR IGNORE INTO users(user_id, balance)
                VALUES (?, 0)
            """, (receiver_id,))

            sender = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id=?
            """, (sender_id,)).fetchone()

            receiver = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id=?
            """, (receiver_id,)).fetchone()

            sender_balance = int(sender["balance"])
            receiver_balance = int(receiver["balance"])

            if sender_balance < amount:
                db.execute("ROLLBACK")

                return {
                    "success": False,
                    "reason": "insufficient_balance",
                    "sender_balance": sender_balance,
                }

            new_sender = sender_balance - amount
            new_receiver = receiver_balance + amount

            db.execute("""
                UPDATE users
                SET balance=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (
                new_sender,
                sender_id,
            ))

            db.execute("""
                UPDATE users
                SET balance=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (
                new_receiver,
                receiver_id,
            ))

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
                new_sender,
                "انتقال",
            ))

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
                new_receiver,
                "دریافت انتقال",
            ))

            db.execute("""
                INSERT OR IGNORE INTO transactions(
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
                new_sender,
                "انتقال",
            ))

            db.execute("COMMIT")

            return {
                "success": True,
                "duplicate": False,
                "sender_balance": new_sender,
                "receiver_balance": new_receiver,
            }

        except Exception:
            db.execute("ROLLBACK")
            raise


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
                game_id,
                int(chat_id),
                int(message_id),
                int(user_id),
                game_type,
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
        result = db.execute("""
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
            game_id,
        ))

        return result.rowcount > 0


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
            INSERT INTO settings(key, value)
            VALUES('bot_enabled', ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
        """, (
            "1" if enabled else "0",
        ))


def get_all_users():
    init_db()

    with get_db() as db:
        return db.execute("""
            SELECT
                user_id,
                first_name,
                username,
                balance,
                created_at
            FROM users
            ORDER BY balance DESC
        """).fetchall()
