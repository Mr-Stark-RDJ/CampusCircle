# utils/otp.py
import secrets
import string

def make_otp(length: int = 6) -> str:
    """Return a cryptographically strong numeric OTP string."""
    digits = string.digits
    return ''.join(secrets.choice(digits) for _ in range(length))
