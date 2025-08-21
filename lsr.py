# lsr.py
from __future__ import annotations
import time
from typing import Dict

class LSR:
    """
    Link-State Routing (LSR) simple:
    - Emite LSP (origin, seq, neighbors[cost]) cuando cambian costos o por temporizador
    - Mantiene LSDB con el LSP más reciente por origen
    - Reconstruye la topología y deja que Dijkstra compute next_hops
    - Difunde LSP usando flooding (deduplicación por header 'mid' = 'origin:seq')
    """

    def __init__(self, me: str):
        self.me = me
        self.seq = 0
        self.lsdb: Dict[str, Dict] = {}
        self.last_adv: Dict[str, float] = {}
        self.last_local: Dict[str, float] = {}
        self.changed = True  
    def _now(self) -> float:
        return time.time()

    def _local_neighbors_snapshot(self, node) -> Dict[str, float]:
        """
        Snapshot de costos hacia vecinos.
        En el primer anuncio (seq==0) incluye TODOS los vecinos configurados (bootstrap),
        luego filtra por vecinos 'vivos' según last_seen.
        """
        snap: Dict[str, float] = {}
        now = self._now()
        DEAD_AFTER = 10.0
        bootstrap = (self.seq == 0)
        for n in list(node.neighbors):
            met = node.nei_metrics.get(n)
            if bootstrap:
                snap[n] = float(node.cost_to(n))  
            else:
                if met and met.last_seen > 0 and (now - met.last_seen) <= DEAD_AFTER:
                    snap[n] = float(node.cost_to(n))
        return snap

    def _differs(self, a: Dict[str, float], b: Dict[str, float], thr: float) -> bool:
        """
        ¿Cambió el conjunto de vecinos o los costos más allá de 'thr'?
        """
        if set(a.keys()) != set(b.keys()):
            return True
        for k in b:
            if abs(a.get(k, float("inf")) - b[k]) > thr:
                return True
        return False

    def should_advertise(self, node, min_interval=3.0, change_threshold=0.01) -> bool:
        """
        Dispara anuncio si:
        - Pasó 'min_interval' desde el último anuncio y hay cambios relevantes, o
        - Pasaron ~10s desde el último anuncio (refresco).
        """
        now = self._now()
        last = self.last_adv.get(self.me, 0.0)
        if self.seq == 0 or (now - last) >= min_interval:
            current = self._local_neighbors_snapshot(node)
            if self._differs(self.last_local, current, change_threshold) or (now - last) >= 10.0:
                self.last_local = current
                return True
        return False

    def make_lsp(self, node) -> dict:
        self.seq += 1
        neighbors = [{"id": n, "cost": c} for n, c in sorted(self.last_local.items())]
        lsp = {"origin": self.me, "seq": self.seq, "age": 0, "neighbors": neighbors}
        # Guarda también mi LSP en LSDB
        self.lsdb[self.me] = {
            "seq": self.seq,
            "ts": self._now(),
            "neighbors": {e["id"]: float(e["cost"]) for e in neighbors},
        }
        self.last_adv[self.me] = self._now()
        self.changed = True
        return lsp

    def advertise(self, node):
        """
        Construye y difunde un LSP usando flooding.
        Fija 'mid' = 'origin:seq' para deduplicación consistente.
        """
        lsp = self.make_lsp(node)
        msg = {
            "proto": "lsr",
            "type": "info",
            "from": self.me,
            "to": "*",
            "ttl": 16,
            "headers": [{"mid": f"{self.me}:{lsp['seq']}"}],
            "payload": {"lsp": lsp},
        }
        node.flood.handle_info(node, msg)

    def handle_lsp(self, node, lsp: dict) -> bool:
        """
        Inserta/actualiza LSP en LSDB si es nuevo.
        Devuelve True si la LSDB cambió (para forzar recomputar rutas).
        """
        origin = lsp.get("origin")
        if origin is None:
            return False
        seq = int(lsp.get("seq", 0))
        cur = self.lsdb.get(origin)
        if cur and seq <= cur["seq"]:
            return False  # viejo/duplicado
        neighs = {d["id"]: float(d["cost"]) for d in lsp.get("neighbors", [])}
        self.lsdb[origin] = {"seq": seq, "ts": self._now(), "neighbors": neighs}
        self.changed = True
        return True

    def on_receive_info(self, node, msg: dict) -> None:
        """
        Procesa un INFO con payload.lsp y lo re-difunde (reliable flooding).
        """
        lsp = (msg.get("payload") or {}).get("lsp")
        if not lsp:
            return
        self.handle_lsp(node, lsp)
        node.flood.handle_info(node, msg)

    def expire(self, max_age=30.0) -> bool:
        """Elimina entradas viejas. True si hay cambios."""
        now = self._now()
        to_del = [o for o, rec in self.lsdb.items() if (now - rec["ts"]) > max_age]
        if not to_del:
            return False
        for o in to_del:
            del self.lsdb[o]
        self.changed = True
        return True

    def build_topology(self) -> Dict[str, Dict[str, float]]:
        """
        Construye un grafo NO dirigido a partir de la LSDB.
        Si hay costos divergentes en una arista, se toma el menor.
        """
        topo: Dict[str, Dict[str, float]] = {}
        for origin, rec in self.lsdb.items():
            topo.setdefault(origin, {})
            for nbr, cost in rec["neighbors"].items():
                topo[origin][nbr] = float(cost)
                topo.setdefault(nbr, {})
                if origin not in topo[nbr] or topo[nbr][origin] > cost:
                    topo[nbr][origin] = float(cost)
        return topo
