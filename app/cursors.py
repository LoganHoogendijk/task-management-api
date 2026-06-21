import base64
import json
import uuid

def encode_cursor(value, id: uuid.UUID) -> str:
    payload = json.dumps({"v": value, "id": str(id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()

def decode_cursor(cursor: str) -> tuple:
    payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return payload["v"], uuid.UUID(payload["id"])