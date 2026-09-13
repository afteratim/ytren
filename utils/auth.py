from config import ALLOWED_USERS

def is_allowed(user_id: int) -> bool:
    return bool(user_id and user_id in ALLOWED_USERS)
