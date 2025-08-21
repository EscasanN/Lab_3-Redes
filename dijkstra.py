from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import heapq

@dataclass
class PathResult:
    dist: Dict[str, float]
    prev: Dict[str, Optional[str]]
    next_hop: Dict[str, Optional[str]]

def _compute_next_hops(prev: Dict[str, Optional[str]], source: str) -> Dict[str, Optional[str]]:
    """
    Cálculo de next-hop por destino
    """
    nh: Dict[str, Optional[str]] = {}
    for dst in prev:
        if dst == source:
            nh[dst] = source
            continue
        if prev[dst] is None:
            nh[dst] = None
            continue
        cur, prv = dst, prev[dst]
        while prv is not None and prv != source:
            cur, prv = prv, prev[prv]
        nh[dst] = cur if prv == source else None
    return nh

def dijkstra(topology: Dict[str, Dict[str, float]], source: str) -> PathResult:
    """
    Dijkstra clásico con cálculo de next_hop para tabla de ruteo.
    - topology: {node: {neighbor: weight, ...}, ...}
    - source: nodo origen
    Retorna distancias, predecesores y next_hop desde 'source'.
    """
    
    dist = {v: float('inf') for v in topology}
    prev: Dict[str, Optional[str]] = {v: None for v in topology}
    dist[source] = 0.0

    pq: List[Tuple[float, str]] = [(0.0, source)]
    visited = set()

    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        for v, w in topology.get(u, {}).items():
            alt = d + w
            if alt < dist[v]:
                dist[v] = alt
                prev[v] = u
                heapq.heappush(pq, (alt, v))

    next_hop = _compute_next_hops(prev, source)
    return PathResult(dist=dist, prev=prev, next_hop=next_hop)

def build_routing_table(result: PathResult, me: str) -> Dict[str, Dict[str, float | str | None]]:
    """
    Construcción de tabla de ruteo a partir de distancias y next_hop.
    """
    table: Dict[str, Dict[str, float | str | None]] = {}
    for dst, d in result.dist.items():
        table[dst] = {"next_hop": result.next_hop.get(dst), "cost": d}
    # Ajuste self
    table[me]["next_hop"] = me
    table[me]["cost"] = 0.0
    return table
