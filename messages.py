# messages.py — Formato Mathew + compat
from __future__ import annotations
from typing import Any, Dict, List, Optional
import json, uuid, time

<<<<<<< HEAD
PROTO_VALUES = {"dijkstra", "flooding", "lsr", "dvr"}
TYPE_VALUES = {"data", "message", "hello", "echo", "info"}
=======
# Tipos “de cable”
WIRE_TYPES = {"message", "hello", "hello_ack", "lsp", "info", "echo"}  # echo opcional
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7

def now_ms() -> int:
    return int(time.time() * 1000)

def new_header(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    h = {"id": str(uuid.uuid4()), "ts": now_ms()}
    if extra:
        h.update(extra)
    return h

def get_header(msg: Dict, key: str, default=None):
    for h in msg.get("headers", []):
        if key in h:
            return h[key]
    return default

def set_header(msg: Dict, key: str, value) -> None:
    hs = list(msg.get("headers", []))
    # mantén el primer header (id/ts), agrega/actualiza al final
    for i, h in enumerate(hs):
        if key in h:
            hs[i] = {**h, key: value}
            msg["headers"] = hs
            return
    hs.append({key: value})
    msg["headers"] = hs

def ensure_header_id_ts(msg: Dict) -> None:
    hs: List[Dict] = msg.get("headers") or []
    if not hs:
        msg["headers"] = [new_header()]
        return
    h0 = dict(hs[0])
    changed = False
    if "id" not in h0:
        h0["id"] = str(uuid.uuid4()); changed = True
    if "ts" not in h0:
        h0["ts"] = now_ms(); changed = True
    if changed:
        hs[0] = h0
        msg["headers"] = hs

def parse_any(data) -> Dict:
    if isinstance(data, bytes):
        return json.loads(data.decode("utf-8"))
    if isinstance(data, str):
        return json.loads(data)
    if isinstance(data, dict):
<<<<<<< HEAD
        return data
    raise TypeError("parse_msg espera bytes/str/dict")


def normalize_type(t: str) -> str:
    if not isinstance(t, str):
        return "data"
    t = t.lower()
    return "data" if t == "message" else t


def payload_text(payload: dict) -> str | None:
    try:
        if isinstance(payload, dict):
            return payload.get("text") or payload.get("data")
    except Exception:
        pass
    return None
=======
        return dict(data)
    raise TypeError("parse_any espera bytes|str|dict")

def normalize_incoming(raw) -> Dict:
    """
    Acepta nuestro formato viejo y lo adapta al de Mathew:
      - ttl -> hops
      - type 'data' -> 'message'
      - asegura headers[0].id/ts
    """
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
        # si venía {'text': '...'}, permitimos texto plano
        if isinstance(p, dict) and set(p.keys()) == {"text"}:
            msg["payload"] = p["text"]

    # asegura headers y (id, ts)
    if "headers" not in msg or not isinstance(msg["headers"], list):
        msg["headers"] = []
    ensure_header_id_ts(msg)

    # aserciones mínimas
    msg.setdefault("from", "")
    msg.setdefault("to", "")
    msg.setdefault("type", "message")
    msg.setdefault("payload", None)
    msg.setdefault("hops", 0)
    return msg

def make_wire(mtype: str,
              from_wire: str,
              to_wire: str,
              hops: int,
              payload: Any,
              header_extra: Optional[Dict[str, Any]] = None) -> str:
    assert mtype in WIRE_TYPES, f"type inválido: {mtype}"
    msg = {
        "type": mtype,
        "from": from_wire,
        "to": to_wire,
        "hops": int(hops),
        "headers": [new_header(header_extra)],
        "payload": payload
    }
    return json.dumps(msg, ensure_ascii=False)

def dumps(msg: Dict) -> str:
    """Dump sin tocar headers ni id (para forward)."""
    ensure_header_id_ts(msg)
    return json.dumps(msg, ensure_ascii=False)
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
