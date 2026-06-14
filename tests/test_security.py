from displaypad_server.core.crypto import generate_pairing_code, generate_secure_token, hmac_sign, hmac_verify
from displaypad_server.core.security import validate_pin


def test_pairing_code_length() -> None:
    code = generate_pairing_code(6)
    assert len(code) == 6
    assert code.isdigit()


def test_tokens_are_unique() -> None:
    assert generate_secure_token() != generate_secure_token()


def test_pin_validation() -> None:
    assert validate_pin("00000000")
    assert validate_pin("12345678")
    assert not validate_pin("1234abcd")
    assert not validate_pin("123456789")


def test_hmac() -> None:
    sig = hmac_sign("secret", "message")
    assert hmac_verify("secret", "message", sig)
    assert not hmac_verify("secret", "tampered", sig)
