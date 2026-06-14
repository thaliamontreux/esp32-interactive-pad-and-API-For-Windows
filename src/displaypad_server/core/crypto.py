import hmac
import hashlib
import secrets
from secrets import compare_digest


def generate_secure_token(byte_length: int = 32) -> str:
    return secrets.token_urlsafe(byte_length)


def generate_pairing_code(length: int = 6) -> str:
    if length < 4 or length > 10:
        raise ValueError("Pairing code length must be between 4 and 10 digits.")
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_secret(secret: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256$200000${salt}${digest.hex()}"


def verify_secret(secret: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        test_digest = hashlib.pbkdf2_hmac(
            "sha256", secret.encode("utf-8"), salt.encode("utf-8"), iterations
        ).hex()
        return compare_digest(test_digest, digest_hex)
    except Exception:
        return False


def hmac_sign(secret: str, message: str) -> str:
    """Generate HMAC signature - always returns UPPERCASE hex."""
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest().upper()


def hmac_verify(secret: str, message: str, signature: str) -> bool:
    """Verify HMAC signature - compares UPPERCASE versions."""
    expected = hmac_sign(secret, message).upper()
    return compare_digest(expected, signature.upper())
