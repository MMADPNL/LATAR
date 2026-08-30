import random

from config import (
    LOTTERY_ODD_EVEN,
    LOTTERY_RED_WHITE,
    LOTTERY_GOAL_OUT,
    BOT_GAME,
    MAX_ROUNDS,
)


# =========================================================
# ابزارهای عمومی
# =========================================================

def normalize_text(text):
    if not text:
        return ""

    text = str(text).strip()

    replacements = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# =========================================================
# لاتاری زوج / فرد
# =========================================================

def lottery_odd_even(choice, dice_value):
    """
    choice:
        زوج
        فرد

    dice_value:
        عدد تاس 1 تا 6

    نتیجه:
        win / lose
    """

    choice = normalize_text(choice)

    dice_value = to_int(dice_value)

    if dice_value is None:
        return {
            "valid": False,
            "reason": "invalid_dice"
        }

    if dice_value < 1 or dice_value > 6:
        return {
            "valid": False,
            "reason": "invalid_dice"
        }

    if choice not in ("زوج", "فرد"):
        return {
            "valid": False,
            "reason": "invalid_choice"
        }

    is_even = dice_value % 2 == 0

    if choice == "زوج":
        won = is_even
    else:
        won = not is_even

    return {
        "valid": True,
        "won": won,
        "choice": choice,
        "value": dice_value,
        "result": "زوج" if is_even else "فرد",
        "multiplier": LOTTERY_ODD_EVEN,
    }


# =========================================================
# لاتاری قرمز / سفید
# =========================================================

def lottery_red_white(choice, result):
    """
    choice:
        قرمز
        سفید

    result:
        قرمز
        سفید
    """

    choice = normalize_text(choice)
    result = normalize_text(result)

    if choice not in ("قرمز", "سفید"):
        return {
            "valid": False,
            "reason": "invalid_choice"
        }

    if result not in ("قرمز", "سفید"):
        return {
            "valid": False,
            "reason": "invalid_result"
        }

    won = choice == result

    return {
        "valid": True,
        "won": won,
        "choice": choice,
        "result": result,
        "multiplier": LOTTERY_RED_WHITE,
    }


# =========================================================
# لاتاری گل / بیرون
# =========================================================

def lottery_goal_out(choice, result):
    """
    choice:
        گل
        بیرون

    result:
        گل
        بیرون
    """

    choice = normalize_text(choice)
    result = normalize_text(result)

    if choice not in ("گل", "بیرون"):
        return {
            "valid": False,
            "reason": "invalid_choice"
        }

    if result not in ("گل", "بیرون"):
        return {
            "valid": False,
            "reason": "invalid_result"
        }

    won = choice == result

    return {
        "valid": True,
        "won": won,
        "choice": choice,
        "result": result,
        "multiplier": LOTTERY_GOAL_OUT,
    }


# =========================================================
# محاسبه پرداخت
# =========================================================

def calculate_payout(bet, multiplier):
    bet = to_int(bet)

    if bet is None or bet <= 0:
        return 0

    # برای جلوگیری از خطای اعشاری
    return int(bet * float(multiplier))


def lottery_payout(bet, lottery_type):
    """
    پرداخت لاتاری:

    زوج/فرد = 1.8
    قرمز/سفید = 1.8
    گل/بیرون = 1.5
    """

    multipliers = {
        "زوج": LOTTERY_ODD_EVEN,
        "فرد": LOTTERY_ODD_EVEN,
        "قرمز": LOTTERY_RED_WHITE,
        "سفید": LOTTERY_RED_WHITE,
        "گل": LOTTERY_GOAL_OUT,
        "بیرون": LOTTERY_GOAL_OUT,
    }

    multiplier = multipliers.get(normalize_text(lottery_type))

    if multiplier is None:
        return 0

    return calculate_payout(bet, multiplier)


# =========================================================
# بازی با ربات - تاس
# =========================================================

def dice_roll():
    return random.randint(1, 6)


def compare_dice(user_value, bot_value):
    user_value = to_int(user_value)
    bot_value = to_int(bot_value)

    if user_value is None or bot_value is None:
        return "invalid"

    if user_value > bot_value:
        return "user"

    if bot_value > user_value:
        return "bot"

    return "draw"


# =========================================================
# بازی با ربات - بولینگ
# =========================================================

def bowling_score(value):
    """
    مقدار score باید امتیاز واقعی ارسال‌شده
    از Telegram باشد.
    """

    value = to_int(value)

    if value is None:
        return None

    return value


def compare_bowling(user_value, bot_value):
    user_value = bowling_score(user_value)
    bot_value = bowling_score(bot_value)

    if user_value is None or bot_value is None:
        return "invalid"

    if user_value > bot_value:
        return "user"

    if bot_value > user_value:
        return "bot"

    return "draw"


# =========================================================
# بازی با ربات - دارت
# =========================================================

def dart_score(value):
    """
    امتیاز دارت از نتیجه واقعی Telegram دریافت می‌شود.
    """

    value = to_int(value)

    if value is None:
        return None

    return value


def compare_dart(user_value, bot_value):
    user_value = dart_score(user_value)
    bot_value = dart_score(bot_value)

    if user_value is None or bot_value is None:
        return "invalid"

    if user_value > bot_value:
        return "user"

    if bot_value > user_value:
        return "bot"

    return "draw"


# =========================================================
# بررسی تعداد راند
# =========================================================

def valid_round(round_number):
    round_number = to_int(round_number)

    if round_number is None:
        return False

    return 1 <= round_number <= MAX_ROUNDS


# =========================================================
# وضعیت بازی چندراندی
# =========================================================

def new_match(game_type, bet):
    return {
        "game_type": normalize_text(game_type),
        "bet": int(bet),
        "round": 0,
        "user_score": 0,
        "bot_score": 0,
        "draws": 0,
        "finished": False,
        "winner": None,
    }


def add_round_result(match, result):
    """
    result:
        user
        bot
        draw
    """

    if not isinstance(match, dict):
        raise ValueError("match must be a dictionary")

    if match.get("finished"):
        return match

    current_round = int(match.get("round", 0)) + 1

    if current_round > MAX_ROUNDS:
        match["finished"] = True
        return match

    match["round"] = current_round

    if result == "user":
        match["user_score"] += 1

    elif result == "bot":
        match["bot_score"] += 1

    elif result == "draw":
        match["draws"] += 1

    else:
        raise ValueError("invalid round result")

    # بعد از راند چهارم بازی تمام می‌شود
    if current_round >= MAX_ROUNDS:
        match["finished"] = True
        match["winner"] = match_winner(match)

    return match


def match_winner(match):
    user_score = int(match.get("user_score", 0))
    bot_score = int(match.get("bot_score", 0))

    if user_score > bot_score:
        return "user"

    if bot_score > user_score:
        return "bot"

    return "draw"


# =========================================================
# پرداخت بازی با ربات
# =========================================================

def bot_game_payout(bet, winner):
    """
    ضریب بازی با ربات = 2

    برد کاربر:
        bet * 2

    باخت:
        0

    مساوی:
        0
    """

    bet = to_int(bet)

    if bet is None or bet <= 0:
        return 0

    if winner == "user":
        return calculate_payout(bet, BOT_GAME)

    return 0


# =========================================================
# تشخیص نوع لاتاری
# =========================================================

def get_lottery_type(choice):
    choice = normalize_text(choice)

    if choice in ("زوج", "فرد"):
        return "odd_even"

    if choice in ("قرمز", "سفید"):
        return "red_white"

    if choice in ("گل", "بیرون"):
        return "goal_out"

    return None


# =========================================================
# اعتبارسنجی شرط لاتاری
# =========================================================

def validate_lottery_choice(choice):
    choice = normalize_text(choice)

    return choice in (
        "زوج",
        "فرد",
        "قرمز",
        "سفید",
        "گل",
        "بیرون",
    )


# =========================================================
# اعتبارسنجی بازی با ربات
# =========================================================

def validate_bot_game(game_type):
    game_type = normalize_text(game_type)

    return game_type in (
        "تاس",
        "دارت",
        "بولینگ",
    )


# =========================================================
# ساخت نتیجه قابل نمایش
# =========================================================

def result_text(result):
    if result == "user":
        return "🏆 شما برنده شدید!"

    if result == "bot":
        return "❌ ربات برنده شد."

    if result == "draw":
        return "🤝 بازی مساوی شد."

    return "⚠️ نتیجه نامعتبر است."
