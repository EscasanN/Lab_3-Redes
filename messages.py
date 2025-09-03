from __future__ import annotations
from typing import Any, Dict, List, Optional, Union
import json, uuid, time

# Supported wire-level types
WIRE_TYPES = {"message", "hello", "hello_ack", "lsp", "info", "echo"}

def now_ms() -> int:
    return int(time.time() * 1000)

def new_header(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a base header with id/ts; merge any extra fields."""
    h = {"id": str(uuid.uuid4()), "ts": now_ms()}
    if extra:
        h.update(extra)
    return h

def _headers_to_dict(hs: Union[List[Dict[str, Any]], Dict[str, Any], None]) -> Dict[str, Any]:
    if isinstance(hs, dict):
        return dict(hs)
    out: Dict[str, Any] = {}
    if isinstance(hs, list):
        for h in hs:
            if isinstance(h, dict):
                out.update(h)
    return out

def _headers_from_dict(hd: Dict[str, Any]) -> List[Dict[str, Any]]:
    # We keep first element as the "main" header (id/ts live here)
    return [dict(hd)] if hd else [new_header()]

def ensure_header_id_ts(msg: Dict) -> None:
    """Guarantee headers exist and contain id and ts in the first header."""
    hs = msg.get("headers")
    hd = _headers_to_dict(hs)
    changed = False
    if "id" not in hd:
        hd["id"] = str(uuid.uuid4()); changed = True
    if "ts" not in hd:
        hd["ts"] = now_ms(); changed = True
    if changed or not isinstance(hs, dict):
        msg["headers"] = _headers_from_dict(hd)

def parse_any(data: Union[bytes, str, Dict]) -> Dict:
    if isinstance(data, bytes):
        return json.loads(data.decode("utf-8"))
    if isinstance(data, str):
        return json.loads(data)
    if isinstance(data, dict):
        return dict(data)
    raise TypeError("parse_any expects bytes|str|dict")

def normalize_incoming(raw) -> Dict:
    msg = parse_any(raw)

    # ttl -> hops (compat)
    if "hops" not in msg and "ttl" in msg:
        try:
            msg["hops"] = int(msg.pop("ttl"))
        except Exception:
            msg["hops"] = 0

    # data -> message (compat)
    if msg.get("type") == "data":
        msg["type"] = "message"
        p = msg.get("payload")
        if isinstance(p, dict) and set(p.keys()) == {"text"}:
            msg["payload"] = p["text"]

    # headers normalize + id/ts
    ensure_header_id_ts(msg)

    # minimal defaults
    msg.setdefault("from", "")
    msg.setdefault("to", "")
    msg.setdefault("type", "message")
    msg.setdefault("payload", None)
    msg.setdefault("hops", 0)
    return msg

def get_header(msg: Dict, key: str, default: Any = None) -> Any:
    hs = msg.get("headers")
    hd = _headers_to_dict(hs)
    return hd.get(key, default)

def set_header(msg: Dict, key: str, value: Any) -> None:
    hs = msg.get("headers")
    hd = _headers_to_dict(hs)
    hd[key] = value
    msg["headers"] = _headers_from_dict(hd)

def make_wire(mtype: str,
              from_wire: str,
              to_wire: str,
              hops: int,
              payload: Any,
              header_extra: Optional[Dict[str, Any]] = None) -> str:
    assert mtype in WIRE_TYPES, f"invalid type: {mtype}"
    msg = {
        "type": mtype,
        "from": from_wire,
        "to": to_wire,
        "hops": int(hops),
        "headers": new_header(header_extra),
        "payload": payload
    }
    return json.dumps(msg, ensure_ascii=False)

def dumps(msg: Dict) -> str:
    """Dump without changing ids beyond ensuring id/ts."""
    ensure_header_id_ts(msg)
    return json.dumps(msg, ensure_ascii=False)

# Convenience for CLI/tools: mirror the sample protocol in message.txt
def make_msg(algorithm: str,
             mtype: str,
             src: str,
             dst: str,
             ttl: int,
             payload: Any) -> str:
    """
    algorithm: flooding|lsr|dijkstra|dvr (stored in header 'alg')
    mtype: data|message|hello|echo|info|lsp
    src/dst: router node ids (A/B/...) when TCP, or channel ids when Redis
    """
    wire_type = "message" if mtype == "data" else mtype
    header_extra = {"alg": algorithm}
    return make_wire(wire_type, src, dst, ttl, payload, header_extra)
