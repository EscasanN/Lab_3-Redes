# node.py
from __future__ import annotations
import socket
import threading
import time
import json
from flooding import Flooding
from dataclasses import dataclass
from typing import Dict, Tuple
from queue import Queue

from messages import make_msg, parse_msg
from dijkstra import dijkstra, build_routing_table
from lsr import LSR  
from dvr import DVR  

BUFFER_SIZE = 65536

@dataclass
class NeighborMetrics:
    rtt_ms: float = float("inf")
    last_seen: float = 0.0

class RouterNode:
    """
    Fase 0/1
    - Modos: dijkstra | flooding | lsr | dvr
    - HELLO/ECHO con RTT y last_seen
    - Dijkstra (estático) y LSR (dinámico, con flooding de LSP)
    """

    def __init__(self, node_id: str, nodes_map: Dict[str, Tuple[str, int]], topo: Dict[str, Dict[str, float]], mode: str = "dijkstra"):
        assert mode in {"dijkstra", "flooding", "lsr", "dvr"}
        self.node_id = node_id
        self.mode = mode
        self.nodes_map = nodes_map                 # {node: (host, port)}
        self._host, self._port = nodes_map[node_id]

        # Flooding: se usa en modo 'flooding' y también para propagar LSP en 'lsr'
        self.flood = Flooding() if mode in {"flooding", "lsr"} else None

        # Topología/vecinos (Fase 0: vecinos de archivo; LSR anunciará dinámico)
        self.topology = topo
        self.neighbors = set(topo.get(node_id, {}).keys())

        # Estado
        self.routing_table: Dict[str, Dict[str, float | str | None]] = {}
        self.info_in: Queue = Queue()
        self.seen = set()
        self.nei_metrics: Dict[str, NeighborMetrics] = {n: NeighborMetrics() for n in self.neighbors}
        self._hello_out: Dict[Tuple[str, int], float] = {}  # (neighbor, seq) -> ts_sent
        self._seq = 0

        # LSR
        self.lsr = LSR(self.node_id) if mode == "lsr" else None
        # DVR
        self.dvr = DVR(self.node_id, use_static_costs=True, poisoned_reverse=True) if mode == "dvr" else None

        self.running = False
        self._lock = threading.Lock()

        # Servidor TCP local
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._host, self._port))
        self._server.listen(16)

    # ========= Utilidades =========
    def _seq_next(self) -> int:
        self._seq += 1
        return self._seq

    def _now(self) -> float:
        return time.time()

    def _update_last_seen(self, n: str) -> None:
        m = self.nei_metrics.get(n)
        if not m:
            m = NeighborMetrics()
            self.nei_metrics[n] = m
        m.last_seen = self._now()

    def _on_hello(self, msg: dict) -> None:
        src = msg.get("from")
        self._update_last_seen(src)
        seq = msg.get("payload", {}).get("seq")
        ts  = msg.get("payload", {}).get("ts")
        echo = make_msg(self.mode, "echo", self.node_id, src, 4, {"seq": seq, "ts": ts})
        self._send(src, echo)

    def _on_echo(self, msg: dict) -> None:
        src = msg.get("from")
        self._update_last_seen(src)
        seq = msg.get("payload", {}).get("seq")
        key = (src, seq)
        ts_sent = self._hello_out.pop(key, None)
        if ts_sent is not None:
            rtt_ms = (self._now() - ts_sent) * 1000.0
            m = self.nei_metrics.get(src) or NeighborMetrics()
            m.rtt_ms = rtt_ms
            m.last_seen = self._now()
            self.nei_metrics[src] = m
            print(f"[{self.node_id}] ECHO {src} seq={seq} RTT={rtt_ms:.1f} ms")
           
            if self.mode == "dvr" and self.dvr:
                self.dvr.changed = True

    def cost_to(self, neighbor: str) -> float:
        """Costo actual hacia un vecino (usado por LSR/DVR)."""
        m = self.nei_metrics.get(neighbor)
        return m.rtt_ms if m and m.rtt_ms != float("inf") else 1.0

    # ========= Transporte local =========
    def _send(self, target_node: str, wire: str):
        host, port = self.nodes_map[target_node]
        try:
            with socket.create_connection((host, port), timeout=0.4) as s:
                s.sendall(wire.encode("utf-8"))
        except Exception as e:
            print(f"[{self.node_id}] Error enviando a {target_node}: {e}")

    # ========= Forwarding =========
    def forwarding_loop(self):
        while self.running:
            try:
                self._server.settimeout(1.0)
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with conn:
                try:
                    data = conn.recv(BUFFER_SIZE)
                except ConnectionResetError:
                    # Ignora cierres abruptos del lado remoto (Windows suele disparar esto)
                    continue

                if not data:
                    continue
                try:
                    msg = parse_msg(data)
                except Exception:
                    continue
                self._handle_message(msg)

    def _handle_message(self, msg: dict):
        mtype = msg.get("type")
        proto = msg.get("proto")
        to = msg.get("to")
        ttl = int(msg.get("ttl", 0))
        src = msg.get("from")

        if ttl <= 0:
            return

        # Marca actividad del vecino emisor
        if src:
            self._update_last_seen(src)

        # HELLO/ECHO
        if mtype == "hello":
            self._on_hello(msg); return
        if mtype == "echo":
            self._on_echo(msg); return

        # INFO
        if mtype == "info":
            if self.mode == "lsr" and self.lsr:
                self.lsr.on_receive_info(self, msg); return
            if self.mode == "flooding" and self.flood:
                self.flood.handle_info(self, msg); return
            if self.mode == "dvr" and self.dvr:
                self.dvr.on_receive_info(self, msg)
                # Publica inmediatamente (evita perder el 'changed' por recompute del loop)
                table = self.dvr.build_routing_table()
                with self._lock:
                    self.routing_table = table
                self._dump_table("Tabla DVR actualizada (RX)")
                return
            self.info_in.put(msg); return


        # DATA
        if mtype == "data":
            if self.mode == "flooding" and self.flood:
                self.flood.handle_data(self, msg); return
            elif self.mode in {"dijkstra", "lsr", "dvr"}:
                if to == self.node_id:
                    print(f"[{self.node_id}] DATA para mí de {src}: {msg.get('payload')}"); return
                with self._lock:
                    nh = self.routing_table.get(msg["to"], {}).get("next_hop")
                if not nh:
                    print(f"[{self.node_id}] Sin ruta a {msg['to']} ({self.mode})."); return
                msg["ttl"] = ttl - 1
                self._send(nh, json.dumps(msg, ensure_ascii=False))
                print(f"[{self.node_id}] FWD({self.mode}) {msg['to']} vía {nh}")
                return
            else:
                print(f"[{self.node_id}] (modo {self.mode}) DATA recibido; fwd se implementa en fase siguiente.")
                return

    # ========= Routing =========
    def routing_loop(self):
        while self.running:
            try:
                if self.mode == "dijkstra":
                    # Grafo estático desde archivo
                    res = dijkstra(self.topology, self.node_id)
                    table = build_routing_table(res, self.node_id)
                    with self._lock:
                        self.routing_table = table

                elif self.mode == "lsr" and self.lsr:
                    # 1) Purga entradas viejas
                    self.lsr.expire()

                    # 2) Anuncio periódico/por cambio
                    if self.lsr.should_advertise(self):
                        self.lsr.advertise(self)

                    # 3) Recompute si LSDB cambió
                    if self.lsr.changed:
                        dyn_topo = self.lsr.build_topology()
                        # Asegúrate de incluirte si aún no apareces (sin vecinos vivos)
                        dyn_topo.setdefault(self.node_id, {})
                        res = dijkstra(dyn_topo, self.node_id)
                        table = build_routing_table(res, self.node_id)
                        with self._lock:
                            self.routing_table = table
                        self.lsr.changed = False
                elif self.mode == "dvr" and self.dvr:
                    self.dvr.expire(self)
                    self.dvr.update_local_links(self)

                    if self.dvr.changed:
                        table = self.dvr.build_routing_table()
                        with self._lock:
                            self.routing_table = table
                        self._dump_table("Tabla DVR actualizada")

                    if self.dvr.should_advertise():  # (min_interval=2s por defecto)
                        self.dvr.advertise(self)


                # DVR vendrá después
                time.sleep(1.0)
            except Exception as e:
                print(f"[{self.node_id}] Error en routing_loop: {e}")
                time.sleep(1.0)

    # ========= HELLO periódico =========
    def hello_loop(self):
        while self.running:
            for n in list(self.neighbors):
                seq = self._seq_next()
                ts = self._now()
                self._hello_out[(n, seq)] = ts
                hello = make_msg(self.mode, "hello", self.node_id, n, 4, {"seq": seq, "ts": ts})
                self._send(n, hello)
            time.sleep(5.0)

    # ========= Ciclo de vida =========
    def start(self):
        self.running = True
        self._t_fwd = threading.Thread(target=self.forwarding_loop, daemon=True)
        self._t_rte = threading.Thread(target=self.routing_loop, daemon=True)
        self._t_hlo = threading.Thread(target=self.hello_loop, daemon=True)
        self._t_fwd.start()
        self._t_rte.start()
        self._t_hlo.start()
        print(f"[{self.node_id}] Iniciado ({self.mode}) en {self._host}:{self._port} vecinos={sorted(self.neighbors)}")

    def stop(self):
        self.running = False
        try:
            self._server.close()
        except Exception:
            pass
    def _dump_table(self, title: str = ""):
        with self._lock:
            rt = dict(self.routing_table)
        if title:
            print(f"[{self.node_id}] {title}")
        for dst, row in sorted(rt.items()):
            print(f"[{self.node_id}]   dst={dst}  nh={row.get('next_hop')}  cost={row.get('cost')}")
