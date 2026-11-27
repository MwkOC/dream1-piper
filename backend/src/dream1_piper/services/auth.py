import hmac
from uuid import uuid4

from itsdangerous import BadSignature, URLSafeTimedSerializer


class SessionAuth:
    def __init__(self, operator_token: str | None, secret: str, ttl_seconds: int):
        self.operator_token = operator_token
        self.ttl_seconds = ttl_seconds
        self.serializer = URLSafeTimedSerializer(secret, salt="dream1-piper-ui-session")
        self.revoked = set()

    def login(self, token: str) -> str:
        if not self.operator_token or not hmac.compare_digest(token, self.operator_token):
            raise PermissionError("invalid operator token")
        return self.serializer.dumps({"sid": str(uuid4())})

    def validate(self, cookie: str | None) -> bool:
        if not cookie:
            return False
        try:
            payload = self.serializer.loads(cookie, max_age=self.ttl_seconds)
            sid = payload.get("sid")
            return bool(sid and sid not in self.revoked)
        except (BadSignature, TypeError, ValueError):
            return False

    def revoke(self, cookie: str | None) -> None:
        if not self.validate(cookie):
            return
        try:
            payload = self.serializer.loads(cookie, max_age=self.ttl_seconds)
        except (BadSignature, TypeError, ValueError):
            return
        self.revoked.add(payload["sid"])
