# dvr.py
from __future__ import annotations
import time
import json
from typing import Dict, Optional, Set
from messages import make_msg

INF = 1e12

class DVR:
    """
    Distance-Vector Routing (Bellman-Ford distribuido) con Split Horizon + Poisoned Reverse.
    - Intercambia DV sólo con vecinos.
    - Usa costos estáticos (topo.json) o dinámicos (RTT) según configuración.
    - Maneja expiración de vecinos/entradas y recomputa next_hop.
    """

    def __init__(self, me: str, use_static_costs: bool = True, poisoned_reverse: bool = True):
        self.me = me
        self.use_static_costs = use_static_costs
        self.poisoned_reverse = poisoned_reverse

        # Estado local
        self.dv_self: Dict[str, float] = {me: 0.0}
        self.next_hop: Dict[str, Optional[str]] = {me: me}

        # DV recibidos por vecino
        self.dv_from: Dict[str, Dict[str, float]] = {}
        self.dv_from_ts: Dict[str, float] = {}

        self.seq = 0
        self.last_adv = 0.0
        self.changed = True

    # ======= util =======
    def _now(self) -> float:
        return time.time()

    def _alive_neighbors(self, node, dead_after: float = 10.0) -> Set[str]:
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
        # dinámico por RTT (fallback 1.0 si no medido)
        return float(node.cost_to(n))

    def _destinations(self, node) -> Set[str]:
        # Unión de todos los destinos conocidos por mí, mis vecinos y sus DV
        dests = set(self.dv_self.keys()) | set(node.neighbors) | {self.me}
        for n, dv in self.dv_from.items():
            dests |= set(dv.keys())
        return dests

    # ======= núcleo Bellman-Ford =======
    def recompute(self, node) -> None:
        alive = self._alive_neighbors(node)
        dests = self._destinations(node)

        new_dv: Dict[str, float] = {self.me: 0.0}
        new_nh: Dict[str, Optional[str]] = {self.me: self.me}

        for dst in dests:
            if dst == self.me:
                continue

            best_cost = INF
            best_nh: Optional[str] = None

            # Opción 1: enlace directo (si es vecino vivo)
            if dst in alive:
                cdir = self._cost_to_neighbor(node, dst)
                if cdir < best_cost:
                    best_cost = cdir
                    best_nh = dst

            # Opción 2: vía cada vecino vivo
            for n in alive:
                via = self._cost_to_neighbor(node, n) + self.dv_from.get(n, {}).get(dst, INF)
                if via < best_cost:
                    best_cost = via
                    best_nh = n

            new_dv[dst] = best_cost
            new_nh[dst] = best_nh

        # Detecta cambios
        changed = False
        eps = 1e-9
        all_dsts = set(new_dv.keys()) | set(self.dv_self.keys())
        for d in all_dsts:
            old = self.dv_self.get(d, INF)
            new = new_dv.get(d, INF)
            if abs(old - new) > eps or self.next_hop.get(d) != new_nh.get(d):
                changed = True
                break

        self.dv_self = new_dv
        self.next_hop = new_nh
        self.changed = changed

    # ======= anuncio =======
    def should_advertise(self, min_interval: float = 1.0, refresh_every: float = 8.0) -> bool:
        now = self._now()
        if self.seq == 0:
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
            wire = make_msg(
                proto="dvr",
                mtype="info",
                from_id=self.me,
                to_id=nei,
                ttl=8,
                payload={"seq": self.seq, "dv": dv_vec}
            )
            node._send(nei, wire)

        self.last_adv = self._now()

    # ======= recepción =======
    def on_receive_info(self, node, msg: dict) -> None:
        src = msg.get("from")
        if not src:
            return
        payload = msg.get("payload") or {}
        dv_vec = payload.get("dv") or {}

        # Guarda DV del vecino y marca timestamp
        self.dv_from[src] = {k: float(v) for k, v in dv_vec.items()}
        self.dv_from_ts[src] = self._now()
        # Recomputa
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
        """
        Si cambian los costos de enlaces (RTT o archivo), recomputa.
        """
        # Recomputar siempre es barato (pequeñas redes del lab)
        self.recompute(node)

    # ======= tabla de ruteo =======
    def build_routing_table(self) -> Dict[str, Dict[str, float | str | None]]:
        table: Dict[str, Dict[str, float | str | None]] = {}
        for dst, cost in self.dv_self.items():
            nh = self.next_hop.get(dst)
            table[dst] = {"next_hop": nh, "cost": float(cost)}
        # self
        table[self.me] = {"next_hop": self.me, "cost": 0.0}
        return table
