from __future__ import annotations
from typing import Dict, Optional, Set
import time
INF = 1e9

class DVR:
    def __init__(self, me: str):
        self.me = me
        self.dv_from: Dict[str, Dict[str, float]] = {}
        self.dv_from_ts: Dict[str, float] = {}
        self.dv_self: Dict[str, float] = {me: 0.0}
        self.next_hop: Dict[str, Optional[str]] = {me: me}
        self.changed = True
        self.last_adv = 0.0

    def _now(self) -> float:
        return time.time()

    def _alive_neighbors(self, node) -> Set[str]:
        return set(node.neighbors)

    def _cost_to_neighbor(self, node, n: str) -> float:
        return node.cost_to(n)

    def _destinations(self, node) -> Set[str]:
        dests = set(self.dv_self.keys()) | set(node.neighbors) | {self.me}
        for _, dv in self.dv_from.items():
            dests |= set(dv.keys())
        return dests

    def update_local_links(self, node) -> None:
        # Recompute from scratch
        dests = self._destinations(node)
        new_dv: Dict[str, float] = {self.me: 0.0}
        new_nh: Dict[str, Optional[str]] = {self.me: self.me}
        for dst in dests:
            if dst == self.me:
                continue
            best_cost, best_nh = INF, None
            if dst in node.neighbors:
                c = self._cost_to_neighbor(node, dst)
                if c < best_cost:
                    best_cost, best_nh = c, dst
            for n in node.neighbors:
                via = self._cost_to_neighbor(node, n) + self.dv_from.get(n, {}).get(dst, INF)
                if via < best_cost:
                    best_cost, best_nh = via, n
            new_dv[dst] = best_cost
            new_nh[dst] = best_nh
        changed = (new_dv != self.dv_self) or (new_nh != self.next_hop)
        self.dv_self, self.next_hop = new_dv, new_nh
        self.changed = changed

    def build_routing_table(self) -> Dict[str, Dict[str, float | str | None]]:
        table: Dict[str, Dict[str, float | str | None]] = {}
        for dst, cost in self.dv_self.items():
            nh = self.next_hop.get(dst)
            table[dst] = {"next_hop": nh, "cost": float(cost)}
        return table

    def should_advertise(self) -> bool:
        return (self._now() - self.last_adv) > 10.0

    def advertise(self, node) -> None:
        # Broadcast a tiny "info" control to neighbors (not parsed by peers)
        msg = {
            "type": "info",
            "from": node._to_wire_id(self.me),
            "to": "*",
            "hops": 6,
            "headers": [{"id": f"dv-{self.me}-{int(self._now()*1000)}", "ts": int(self._now()*1000), "table_version": int(self._now())}],
            "payload": {"routing_table": []}
        }
        node._broadcast_wire(json.dumps(msg))
        self.last_adv = self._now()
        self.changed = False

    def on_receive_info(self, node, msg: dict) -> None:
        pass

    def expire(self, node, dv_max_age: float = 30.0) -> None:
        # No-op in stub
        return
