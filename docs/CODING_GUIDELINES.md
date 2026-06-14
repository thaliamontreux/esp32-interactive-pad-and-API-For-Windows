# Coding Guidelines

## Python

- Python 3.11+
- Type hints required
- Keep modules focused
- Use Pydantic for API schemas
- Keep secrets out of logs
- Use tests for security-critical behavior

## API

- Version all endpoints under `/api/v1`
- Validate request bodies
- Return structured JSON errors
- Audit important actions

## Security

- Use `secrets` for random values
- Hash secrets
- Validate HMAC signatures
- Validate nonces
- Validate timestamps
- Rate-limit button events

## Windows

Keep all Windows-only code inside:

```text
src/displaypad_server/windows/
```

## ESP32

The ESP32 must not decide macro behavior.  
It displays API-provided buttons and sends signed button events.
