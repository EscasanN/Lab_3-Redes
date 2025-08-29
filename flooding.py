# flooding.py — Flooding con hops y deduplicación por header.id
import time
from typing import Dict, Set
from messages import get_header, set_header, ensure_header_id_ts, dumps

class Flooding:
    """Inundación con deduplicación por headers[0].id y supresión por 'prev'."""
    def __init__(self):
        self.seen: Set[str] = set()

    def _msg_id(self, msg: Dict) -> str:
        ensure_header_id_ts(msg)
        return get_header(msg, "id")

    def _flood(self, node, msg: Dict) -> None:
        try:
            hops = int(msg.get("hops", 0))
        except Exception:
            hops = 0
        if hops <= 0:
            return

        prev = get_header(msg, "prev")
        # Clona y reduce hops
        fwd = dict(msg)
        fwd["hops"] = hops - 1
        set_header(fwd, "prev", node.node_id)

        now = time.time()
        DEAD = getattr(node, "dead_after", 10.0)
        wire = dumps(fwd)

        for n in list(node.neighbors):
            if n == prev or fwd["hops"] <= 0:
                continue
            met = node.nei_metrics.get(n)
            if met and met.last_seen > 0 and (now - met.last_seen) > DEAD:
                continue
            node._send(n, wire)
            node._log("INFO", f"FWD(flooding) → {n} (dst={msg.get('to')}, id={self._msg_id(msg)})", tag="FWD")

    # ---- entradas con deduplicación ----
    def handle_message(self, node, msg: Dict) -> None:
        mid = self._msg_id(msg)
        if mid in self.seen:
            return
        self.seen.add(mid)

        # ¿soy destino?
        if msg.get("to") == node._to_wire_id(node.node_id):
            node._log("INFO", f"DATA para mí de {msg.get('from')}: {msg.get('payload')}", tag="RECV")
            return
        self._flood(node, msg)

    def handle_control(self, node, msg: Dict) -> None:
        mid = self._msg_id(msg)
        if mid in self.seen:
            return
        self.seen.add(mid)
        self._flood(node, msg)
