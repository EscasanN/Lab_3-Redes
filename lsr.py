# lsr.py — LSR con LSP tipo 'lsp' (formato Mathew)
from __future__ import annotations
import time
from typing import Dict, List, Any
from messages import make_wire, get_header

class LSR:
    """
    - Emite LSP 'type: lsp' con headers[0]: id/ts + {seq, origin}
    - payload: {'node': <A>, 'neighbors': [B,C,...], 'sequence': N, 'costs': {B:1.0,...} (opcional)}
    - LSDB: guarda el último seq por origin
    """

    def __init__(self, me: str):
        self.me = me
        self.seq = 0
        self.lsdb: Dict[str, Dict] = {}          # origin -> {seq, ts, neighbors:{}, costs:{}}
        self.last_adv: float = 0.0
        self.last_local: Dict[str, float] = {}   # snapshot de costos a vecinos
        self.changed = True

    def _now(self) -> float:
        return time.time()

    def _alive_snapshot(self, node) -> Dict[str, float]:
        snap: Dict[str, float] = {}
        now = self._now()
        DEAD = getattr(node, "dead_after", 10.0)
        bootstrap = (self.seq == 0)
        for n in list(node.neighbors):
            met = node.nei_metrics.get(n)
            if bootstrap or (met and met.last_seen > 0 and (now - met.last_seen) <= DEAD):
                snap[n] = float(node.cost_to(n) or 1.0)
        return snap

    def _differs(self, a: Dict[str, float], b: Dict[str, float], thr: float) -> bool:
        if set(a.keys()) != set(b.keys()):
            return True
        for k in b:
            if abs(a.get(k, 1e9) - b[k]) > thr:
                return True
        return False

    def should_advertise(self, node, min_interval=3.0, change_threshold=0.01) -> bool:
        now = self._now()
        if self.seq == 0 or (now - self.last_adv) >= min_interval:
            current = self._alive_snapshot(node)
            if self._differs(self.last_local, current, change_threshold) or (now - self.last_adv) >= 10.0:
                self.last_local = current
                return True
        return False

    def advertise(self, node) -> None:
        self.seq += 1
        neighbors = list(sorted(self.last_local.keys()))
        costs = {n: float(c) for n, c in self.last_local.items()}

        # Persisto mi LSP en LSDB
        self.lsdb[self.me] = {"seq": self.seq, "ts": self._now(), "neighbors": set(neighbors), "costs": costs}
        self.last_adv = self._now()
        self.changed = True

        payload = {"node": self.me, "neighbors": neighbors, "sequence": self.seq, "costs": costs}
        wire = make_wire(
            mtype="lsp",
            from_wire=node._to_wire_id(self.me),
            to_wire="*",
            hops=16,
            payload=payload,
            header_extra={"seq": self.seq, "origin": self.me}
        )
        # Difunde usando el forwarder del nodo (se reenviará por flooding en el pipeline normal)
        node._broadcast_wire(wire)

    # ---- recepción LSP ----
    def on_receive_lsp(self, node, msg: Dict) -> None:
        p = msg.get("payload") or {}
        origin = p.get("node") or msg.get("from")
        if not origin:
            return
        try:
            seq = int(p.get("sequence", 0))
        except Exception:
            seq = 0

        cur = self.lsdb.get(origin)
        if cur and seq <= int(cur.get("seq", 0)):
            return  # viejo/duplicado

        neighs = p.get("neighbors") or []
        costs = p.get("costs") or {}
        if isinstance(neighs, dict):  # compat si llegarán en dict
            costs = {k: float(v) for k, v in neighs.items()}
            neighs = list(neighs.keys())

        self.lsdb[origin] = {
            "seq": seq,
            "ts": time.time(),
            "neighbors": set(neighs),
            "costs": {k: float(costs.get(k, 1.0)) for k in neighs}
        }
        self.changed = True

    def expire(self, max_age=30.0) -> bool:
        now = self._now()
        stale = [o for o, rec in self.lsdb.items() if (now - rec["ts"]) > max_age]
        if not stale:
            return False
        for o in stale:
            del self.lsdb[o]
        self.changed = True
        return True

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
