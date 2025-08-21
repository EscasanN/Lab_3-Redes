# dvr.py
from __future__ import annotations
import time
from typing import Dict, Optional, Set
from messages import make_msg

INF = 1e12

class DVR:
    """
    Distance-Vector con Split Horizon + Poisoned Reverse, triggered updates y hold-down opcional.
    """

    def __init__(self, me: str, use_static_costs: bool = True, poisoned_reverse: bool = True,
                 hold_down_secs: float | None = 8.0, change_threshold: float = 1e-6):
        self.me = me
        self.use_static_costs = use_static_costs
        self.poisoned_reverse = poisoned_reverse
        self.hold_down_secs = hold_down_secs
        self.change_threshold = change_threshold

        # Estado local
        self.dv_self: Dict[str, float] = {me: 0.0}
        self.next_hop: Dict[str, Optional[str]] = {me: me}

        # DV recibidos por vecino
        self.dv_from: Dict[str, Dict[str, float]] = {}
        self.dv_from_ts: Dict[str, float] = {}

        # control
        self.seq = 0
        self.last_adv = 0.0
        self.changed = True
        self._triggered = False
        self._last_change_time = 0.0
        self.hold_until: Dict[str, float] = {}  # dst -> epoch

    # ======= util =======
    def _now(self) -> float:
        return time.time()

    def _alive_neighbors(self, node, dead_after: float | None = None) -> Set[str]:
        if dead_after is None:
            dead_after = getattr(node, "dead_after", 10.0)
        now = self._now()
        alive = set()
        for n in list(node.neighbors):
            met = node.nei_metrics.get(n)
            if met and met.last_seen > 0 and (now - met.last_seen) <= dead_after:
                alive.add(n)
        return alive

    def _cost_to_neighbor(self, node, n: str) -> float:
        if self.use_static_costs:
            return float(node.topology.get(node.node_id, {}).get(n, 1.0))
        return float(node.cost_to(n))  # RTT o 1.0 si no medido

    def _destinations(self, node) -> Set[str]:
        dests = set(self.dv_self.keys()) | set(node.neighbors) | {self.me}
        for _, dv in self.dv_from.items():
            dests |= set(dv.keys())
        return dests

    def trigger_update(self) -> None:
        """Fuerza un anuncio rápido (triggered update) respetando un pequeño backoff en should_advertise()."""
        self._triggered = True

    # ======= núcleo Bellman-Ford =======
    def recompute(self, node) -> None:
        now = self._now()
        alive = self._alive_neighbors(node)
        dests = self._destinations(node)

        new_dv: Dict[str, float] = {self.me: 0.0}
        new_nh: Dict[str, Optional[str]] = {self.me: self.me}

        for dst in dests:
            if dst == self.me:
                continue

            best_cost = INF
            best_nh: Optional[str] = None

            # enlace directo
            if dst in alive:
                cdir = self._cost_to_neighbor(node, dst)
                if cdir < best_cost:
                    best_cost, best_nh = cdir, dst

            # vía vecinos
            for n in alive:
                via = self._cost_to_neighbor(node, n) + self.dv_from.get(n, {}).get(dst, INF)
                if via < best_cost:
                    best_cost, best_nh = via, n

            # hold-down: si acaba de empeorar y luego aparece algo 'mejor' demasiado pronto, ignóralo
            prev_cost = self.dv_self.get(dst, INF)
            if self.hold_down_secs and dst in self.hold_until and now < self.hold_until[dst]:
                if best_cost < prev_cost:  # mejora durante hold-down
                    best_cost, best_nh = prev_cost, self.next_hop.get(dst)

            new_dv[dst] = best_cost
            new_nh[dst] = best_nh

        # detectar cambios (y activar hold-down cuando empeora mucho)
        changed = False
        all_dsts = set(new_dv.keys()) | set(self.dv_self.keys())
        for d in all_dsts:
            old = self.dv_self.get(d, INF)
            new = new_dv.get(d, INF)
            if abs(old - new) > self.change_threshold or self.next_hop.get(d) != new_nh.get(d):
                changed = True
                # si empeora de forma notable, inicia hold-down
                if self.hold_down_secs and (new > old + 1.0 or (old < INF/2 and new >= INF/2)):
                    self.hold_until[d] = self._now() + float(self.hold_down_secs)

        self.dv_self = new_dv
        self.next_hop = new_nh
        self.changed = changed
        if changed:
            self._last_change_time = now
            self._triggered = True  # anuncia rápido

    # ======= anuncio =======
    def should_advertise(self, min_interval: float = 1.0, refresh_every: float = 8.0) -> bool:
        now = self._now()
        if self.seq == 0:
            return True
        # triggered update con pequeño backoff (200ms)
        if self._triggered and (now - self.last_adv) >= 0.2:
            return True
        if (now - self.last_adv) >= min_interval and (self.changed or (now - self.last_adv) >= refresh_every):
            return True
        return False

    def _vector_for_neighbor(self, nei: str) -> Dict[str, float]:
        if not self.poisoned_reverse:
            return dict(self.dv_self)
        vec = {}
        for dst, cost in self.dv_self.items():
            nh = self.next_hop.get(dst)
            if nh == nei and dst != nei:
                vec[dst] = INF  # poison
            else:
                vec[dst] = cost
        return vec

    def advertise(self, node) -> None:
        alive = self._alive_neighbors(node)
        if not alive:
            return
        self.seq += 1
        for nei in alive:
            dv_vec = self._vector_for_neighbor(nei)
            wire = make_msg("dvr", "info", self.me, nei, 8, {"seq": self.seq, "dv": dv_vec})
            node._send(nei, wire)
        self.last_adv = self._now()
        self._triggered = False
        self.changed = False  # tabla ya anunciada

    # ======= recepción =======
    def on_receive_info(self, node, msg: dict) -> None:
        src = msg.get("from")
        if not src:
            return
        # Sólo aceptamos DV de vecinos (no trampa)
        if src not in node.neighbors:
            return
        payload = msg.get("payload") or {}
        dv_vec = payload.get("dv") or {}
        # guarda DV del vecino y marca ts
        self.dv_from[src] = {k: float(v) for k, v in dv_vec.items()}
        self.dv_from_ts[src] = self._now()
        # recomputa y dispara triggered update
        self.recompute(node)

    # ======= mantenimiento =======
    def expire(self, node, dv_max_age: float = 20.0) -> None:
        now = self._now()
        removed = False
        for n, ts in list(self.dv_from_ts.items()):
            if (now - ts) > dv_max_age or n not in node.neighbors:
                self.dv_from.pop(n, None)
                self.dv_from_ts.pop(n, None)
                removed = True
        if removed:
            self.recompute(node)

    def update_local_links(self, node) -> None:
        self.recompute(node)

    # ======= tabla de ruteo =======
    def build_routing_table(self) -> Dict[str, Dict[str, float | str | None]]:
        table: Dict[str, Dict[str, float | str | None]] = {}
        for dst, cost in self.dv_self.items():
            nh = self.next_hop.get(dst)
            # Mejor manejo de INF para la tabla
            if cost >= INF/2:
                table[dst] = {"next_hop": None, "cost": INF}
            else:
                table[dst] = {"next_hop": nh, "cost": float(cost)}
        table[self.me] = {"next_hop": self.me, "cost": 0.0}
        return table
