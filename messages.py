import json
from typing import Any, Dict

PROTO_VALUES = {"dijkstra", "flooding", "lsr", "dvr"}
TYPE_VALUES = {"message", "echo", "info", "hello", "data"}


def make_msg(proto: str, mtype: str, from_id: str, to_id: str, ttl: int, payload: Any, headers: list[dict] | None = None) -> str:
    assert proto in PROTO_VALUES, f"proto inválido: {proto}"
    assert mtype in TYPE_VALUES, f"type inválido: {mtype}"
    msg: Dict[str, Any] = {
        "proto": proto,
        "type": mtype,
        "from": from_id,
        "to": to_id,
        "ttl": ttl,
        "headers": headers or [],
        "payload": payload,
    }
    return json.dumps(msg)


def parse_msg(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))