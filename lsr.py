from __future__ import annotations
import time
from typing import Dict, List, Any
from messages import make_wire, get_header

class LSR:
    def __init__(self, me: str):
        self.me = me
        self.seq = 0
        self.lsdb: Dict[str, Dict[str, Any]] = {}
        self.last_local: Dict[str, float] = {}
        self.last_adv = 0.0
        self.changed = True

    def _now(self) -> float:
        return time.time()

    def expire(self, max_age: float = 30.0) -> None:
        now = self._now()
        for k in list(self.lsdb.keys()):
            if (now - self.lsdb[k]["ts"]) > max_age:
                self.lsdb.pop(k, None)
                self.changed = True

    def should_advertise(self, node) -> bool:
        # advertise if neighbors changed or every ~15s
        now = self._now()
        current = {n: node.cost_to(n) for n in node.neighbors}
        if current != self.last_local:
            self.last_local = current
            return True
        if (now - self.last_adv) > 15.0:
            return True
        return False

    def advertise(self, node) -> None:
        self.seq += 1
        neighbors = list(sorted(self.last_local.keys()))
        costs = {n: float(c) for n, c in self.last_local.items()}
        self.lsdb[self.me] = {"seq": self.seq, "ts": self._now(), "neighbors": set(neighbors), "costs": costs}
        self.last_adv = self._now()
        self.changed = True

        payload = {"node": self.me, "neighbors": neighbors, "sequence": self.seq, "costs": costs}
        wire = make_wire("lsp", node._to_wire_id(self.me), "*", 16, payload, {"seq": self.seq, "origin": self.me})
        node._broadcast_wire(wire)

    def on_receive_lsp(self, node, msg: Dict) -> None:
        p = msg.get("payload") or {}
        origin = p.get("node") or msg.get("from")
        seq = int(p.get("sequence", 0))
        costs = p.get("costs") or {}
        neighbors = set(p.get("neighbors") or [])
        rec = self.lsdb.get(origin)
        if rec and seq <= int(rec["seq"]):
            return
        self.lsdb[origin] = {"seq": seq, "ts": self._now(), "neighbors": set(neighbors), "costs": costs}
        self.changed = True

    def build_topology(self) -> Dict[str, Dict[str, float]]:
        topo: Dict[str, Dict[str, float]] = {}
        for origin, rec in self.lsdb.items():
            topo.setdefault(origin, {})
            for n in rec["neighbors"]:
                c = float(rec["costs"].get(n, 1.0))
                topo[origin][n] = c
                topo.setdefault(n, {})
                if origin not in topo[n] or topo[n][origin] > c:
                    topo[n][origin] = c
        return topo
