# messages.py
from __future__ import annotations
from typing import Any, Dict
import json

PROTO_VALUES = {"dijkstra", "flooding", "lsr", "dvr"}
TYPE_VALUES = {"data", "hello", "echo", "info"}

def make_msg(
    proto: str,
    mtype: str,
    from_id: str,
    to_id: str,
    ttl: int,
    payload: Any,
    headers: list[dict] | None = None
) -> str:
    assert proto in PROTO_VALUES, f"proto inválido: {proto}"
    assert mtype in TYPE_VALUES, f"type inválido: {mtype}"
    msg = {
        "proto": proto,
        "type": mtype,
        "from": from_id,
        "to": to_id,
        "ttl": int(ttl),
        "hops": 0,
        "headers": headers or [],
        "payload": payload,
    }
    return json.dumps(msg, ensure_ascii=False)

def get_header(msg: dict, key: str, default=None):
    for h in msg.get("headers", []):
        if key in h:
            return h[key]
    return default

def set_header(msg: dict, key: str, value) -> None:
    hs = msg.get("headers", [])
    hs = [h for h in hs if key not in h]
    hs.append({key: value})
    msg["headers"] = hs

def parse_msg(data: bytes) -> dict:
    if isinstance(data, bytes):
        return json.loads(data.decode("utf-8"))
    if isinstance(data, str):
        return json.loads(data)
    if isinstance(data, dict):
        return data
    raise TypeError("parse_msg espera bytes/str/dict")
