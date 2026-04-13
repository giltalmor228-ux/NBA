from itsdangerous import BadSignature, URLSafeSerializer

from app.config import get_settings


def _serializer() -> URLSafeSerializer:
    settings = get_settings()
    return URLSafeSerializer(settings.secret_key, salt="nba-playoff-pool")


def encode_session(membership_id: str) -> str:
    return _serializer().dumps({"membership_id": membership_id})


def decode_session(value: str | None) -> str | None:
    if not value:
        return None
    try:
        data = _serializer().loads(value)
    except BadSignature:
        return None
    return data.get("membership_id")
