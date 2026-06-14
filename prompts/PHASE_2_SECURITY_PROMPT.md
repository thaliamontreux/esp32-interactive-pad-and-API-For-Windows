# Phase 2 Security Prompt

Implement security core.

Requirements:

1. `core/crypto.py`
   - generate_secure_token
   - generate_pairing_code
   - hash_secret
   - verify_secret
   - hmac_sign
   - hmac_verify

2. `core/security.py`
   - timestamp validation
   - nonce validation
   - button event verification skeleton
   - sensitive log redaction helper

3. Pairing codes:
   - numeric
   - fresh every session
   - default length 6
   - expire after 120 seconds
   - single-use

4. PIN:
   - numeric only
   - default `00000000`
   - max 8 digits
   - recommended exactly 8 digits
   - never store plain PIN

5. Add tests for:
   - token uniqueness
   - pairing code length
   - PIN validation
   - HMAC verify success/failure
   - timestamp skew rejection
