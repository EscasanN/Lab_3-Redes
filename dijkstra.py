from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import heapq

@dataclass
class PathResult:
    dist: Dict[str, float]
    prev: Dict[str, Optional[str]]
    next_hop: Dict[str, Optional[str]]


def dijkstra(topology: Dict[str, Dict[str, float]], source: str) -> PathResult:
    """
    Dijkstra clásico con cálculo de next_hop para tabla de ruteo.
    - topology: {node: {neighbor: weight, ...}, ...}
    - source: nodo origen
    Retorna distancias, predecesores y next_hop desde 'source'.
    """
    # Inicialización
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

    # Cálculo de next-hop por destino
    next_hop: Dict[str, Optional[str]] = {}
    for dest in topology:
        if dest == source or dist[dest] == float('inf'):
            next_hop[dest] = None if dest == source else None
            continue
        # retroceder desde dest hasta source para hallar el primer salto
        cur = dest
        while prev[cur] is not None and prev[cur] != source:
            cur = prev[cur]
        # si prev[cur] == source, el primer salto es 'cur'
        if prev[cur] == source:
            next_hop[dest] = cur
        else:
            # Dest es vecino directo
            next_hop[dest] = dest if prev[dest] == source else None

    return PathResult(dist=dist, prev=prev, next_hop=next_hop)


def build_routing_table(result: PathResult, me: str) -> Dict[str, Dict[str, float | str | None]]:
    table = {}
    for dst, d in result.dist.items():
        table[dst] = {
            "next_hop": result.next_hop.get(dst),
            "cost": d,
        }
    # Ajuste para self
    table[me]["next_hop"] = me
    table[me]["cost"] = 0.0
    return table