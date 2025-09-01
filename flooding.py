from __future__ import annotations
from typing import Dict, Set
from messages import get_header, set_header, ensure_header_id_ts, dumps

class Flooding:
    """Simple flooding with dedup (headers[0].id) and suppression using 'prev' header."""
    def __init__(self):
        self.seen: Set[str] = set()

    def _msg_id(self, msg: Dict) -> str:
        ensure_header_id_ts(msg)
        return str(get_header(msg, "id"))

    def _flood(self, node, msg: Dict) -> None:
        try:
            hops = int(msg.get("hops", 0))
        except Exception:
            hops = 0
        if hops <= 0:
            return

        prev = get_header(msg, "prev")
        fwd = dict(msg)
        fwd["hops"] = hops - 1
        set_header(fwd, "prev", node.node_id)
        wire = dumps(fwd)

        for n in list(node.neighbors):
            if n == prev or fwd["hops"] <= 0:
                continue
            if not node.is_neighbor_active(n):
                # Skip inactive neighbors (if node tracks health)
                continue
            node._send(n, wire)
            node._log("INFO", f"FWD(flood) → {n} (dst={msg.get('to')}, id={self._msg_id(msg)})", tag="FWD")

    # ---- entries with dedup ----
    def handle_message(self, node, msg: Dict) -> None:
        mid = self._msg_id(msg)
        if mid in self.seen:
            return
        self.seen.add(mid)

        # deliver locally?
        if msg.get("to") in (node._to_wire_id(node.node_id), node.node_id, "*"):
            node._log("INFO", f"DATA for me from {msg.get('from')}: {msg.get('payload')}", tag="RECV")
            node.on_data_local(msg)
            # For broadcast, also continue flooding
            if msg.get("to") != "*":
                return
        self._flood(node, msg)

    def handle_control(self, node, msg: Dict) -> None:
        mid = self._msg_id(msg)
        if mid in self.seen:
            return
        self.seen.add(mid)
        self._flood(node, msg)
