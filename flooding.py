# flooding.py
import json
import time

class Flooding:
    """Reenvío por inundación con control de duplicados y salto previo."""
    def __init__(self):
        self.seen: set[str] = set()

    # ---- helpers de headers ----
    def _get_header(self, msg: dict, key: str, default=None):
        for h in msg.get("headers", []):
            if key in h:
                return h[key]
        return default

    def _set_header(self, msg: dict, key: str, value) -> None:
        hs = msg.get("headers", [])
        hs = [h for h in hs if key not in h]
        hs.append({key: value})
        msg["headers"] = hs

    def _ensure_mid(self, msg: dict) -> str:
        mid = self._get_header(msg, "mid")
        if mid:
            return mid
        src = msg.get("from", "?")
        seq = self._get_header(msg, "seq")
        if seq is None:
            seq = msg.get("payload", {}).get("id") or msg.get("payload", {}).get("seq")
        if seq is None:
            seq = int(time.time() * 1_000_000)
        mid = f"{src}:{seq}"
        self._set_header(msg, "mid", mid)
        return mid

    # ---- núcleo de inundación ----
    def _flood(self, node, msg: dict) -> None:
        ttl = int(msg.get("ttl", 0))
        if ttl <= 0:
            return

        prev = self._get_header(msg, "prev", default=None)
        mid = self._get_header(msg, "mid") or self._ensure_mid(msg)

        fwd = dict(msg)
        fwd["ttl"] = ttl - 1
        self._set_header(fwd, "prev", node.node_id)
        wire = json.dumps(fwd, ensure_ascii=False)

        now = time.time()
        DEAD_AFTER = 10.0  
        for n in list(node.neighbors):
            if n == prev or fwd["ttl"] <= 0:
                continue
            met = node.nei_metrics.get(n)
            if met and met.last_seen > 0 and (now - met.last_seen) > DEAD_AFTER:
                continue 
            node._send(n, wire)
            print(f"[{node.node_id}] FWD(flooding) → {n} (dst={msg.get('to')}, mid={mid})")

    # ---- entradas con deduplicación ----
    def handle_data(self, node, msg: dict) -> None:
        mid = self._ensure_mid(msg)
        if mid in self.seen:
            return
        self.seen.add(mid)

        if msg.get("to") == node.node_id:
            print(f"[{node.node_id}] DATA para mí de {msg.get('from')}: {msg.get('payload')}")
            return
        self._flood(node, msg)

    def handle_info(self, node, msg: dict) -> None:
        mid = self._ensure_mid(msg)
        if mid in self.seen:
            return
        self.seen.add(mid)
        self._flood(node, msg)
