import bcrypt

from app.config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        # bcrypt.checkpw requires bytes
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False

def authenticate_user(username: str, password: str):
    """
    Authenticate against static accounts.
    Returns (user_id, role) or (None, None)
    """
    if username == settings.admin_username:
        if verify_password(password, settings.admin_password_hash):
            return "hr_admin", "admin"
            
    elif username == settings.user_username:
        if verify_password(password, settings.user_password_hash):
            return "hr_user", "user"
            
    return None, None
