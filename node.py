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
LOG_LEVELS = {"ERROR": 0, "WARN": 1, "INFO": 2, "DEBUG": 3}

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

    def __init__(self, node_id: str, nodes_map: Dict[str, Tuple[str, int]],
                 topo: Dict[str, Dict[str, float]], mode: str = "dijkstra",
                 log_level: str = "INFO", hello_period: float = 5.0, dead_after: float = 10.0):
        assert mode in {"dijkstra", "flooding", "lsr", "dvr"}
        self.node_id = node_id
        self.mode = mode
        self.nodes_map = nodes_map
        self._host, self._port = nodes_map[node_id]

        # logging/timers
        self.log_level = log_level.upper()
        self._log_lvl = LOG_LEVELS.get(self.log_level, 2)
        self.hello_period = float(hello_period)
        self.dead_after = float(dead_after)

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

    # ========= Logging =========
    def _log(self, level: str, msg: str, tag: str | None = None):
        lvl = LOG_LEVELS.get(level.upper(), 2)
        if lvl <= self._log_lvl:
            prefix = f"[{self.node_id}/{(tag or self.mode).upper()}]"
            print(f"{prefix} {msg}")

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
        ts = msg.get("payload", {}).get("ts")
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
            self._log("INFO", f"ECHO {src} seq={seq} RTT={rtt_ms:.1f} ms", tag="echo")
            if self.mode == "dvr" and self.dvr:
                self.dvr.changed = True
                # Triggered update inmediato
                self.dvr.trigger_update()

    def cost_to(self, neighbor: str) -> float:
        """Costo actual hacia un vecino (usado por LSR/DVR)."""
        m = self.nei_metrics.get(neighbor)
        return m.rtt_ms if m and m.rtt_ms != float("inf") else 1.0

    # ========= Transporte local =========
    def _send(self, target_node: str, wire: str):
        host, port = self.nodes_map[target_node]
        last_err = None
        for _ in range(3):
            try:
                with socket.create_connection((host, port), timeout=1.2) as s:
                    s.sendall(wire.encode("utf-8"))
                return
            except Exception as e:
                last_err = e
                time.sleep(0.05)
        self._log("WARN", f"Error enviando a {target_node}: {last_err}")

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
        proto = msg.get("proto")   # reservado por si quieres validar
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
            self._on_hello(msg)
            return
        if mtype == "echo":
            self._on_echo(msg)
            return

        # INFO
        if mtype == "info":
            if self.mode == "lsr" and self.lsr:
                self.lsr.on_receive_info(self, msg)
                return
            if self.mode == "flooding" and self.flood:
                self.flood.handle_info(self, msg)
                return
            if self.mode == "dvr" and self.dvr:
                self.dvr.on_receive_info(self, msg)
                # Publica inmediatamente (evita perder el 'changed' por recompute del loop)
                table = self.dvr.build_routing_table()
                with self._lock:
                    self.routing_table = table
                self._dump_table("Tabla DVR actualizada (RX)")
                return
            self.info_in.put(msg)
            return

        # DATA
        if mtype == "data":
            if self.mode == "flooding" and self.flood:
                self.flood.handle_data(self, msg)
                return
            elif self.mode in {"dijkstra", "lsr", "dvr"}:
                payload = msg.get("payload") or {}

                # Si el paquete es para mí
                if to == self.node_id:
                    kind = payload.get("kind")

                    # Respuesta a PING con PONG (para medir RTT end-to-end)
                    if kind == "ping":
                        orig_ts = float(payload.get("ts", self._now()))
                        with self._lock:
                            nh_back = self.routing_table.get(src, {}).get("next_hop")
                        if nh_back:
                            pong = make_msg(self.mode, "data", self.node_id, src, 12,
                                            {"kind": "pong", "ts": orig_ts})
                            self._send(nh_back, pong)
                            self._log("INFO", f"PONG → {src} via {nh_back}", tag="RECV")
                        else:
                            self._log("WARN", f"No next-hop para responder PONG a {src}", tag="RECV")
                        return

                    # Recepción de PONG: calcula RTT total
                    if kind == "pong":
                        try:
                            rtt_ms = (self._now() - float(payload.get("ts", self._now()))) * 1000.0
                            self._log("INFO", f"PONG from {src} RTT={rtt_ms:.1f} ms", tag="RECV")
                        except Exception:
                            self._log("WARN", f"PONG from {src} (ts inválido)", tag="RECV")
                        return

                    # Otros DATA para mí
                    self._log("INFO", f"DATA de {src}: {payload}", tag="RECV")
                    return

                # El paquete no es para mí → forward
                with self._lock:
                    nh = self.routing_table.get(to, {}).get("next_hop")
                if not nh:
                    self._log("WARN", f"Sin ruta a {to} ({self.mode}).", tag="FWD")
                    return
                msg["ttl"] = ttl - 1
                self._send(nh, json.dumps(msg, ensure_ascii=False))
                self._log("INFO", f"FWD {to} via {nh}", tag="FWD")
                return
            else:
                self._log("INFO", f"(modo {self.mode}) DATA recibido; fwd se implementa en fase siguiente.", tag="FWD")
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
                    # Mantenimiento y recomputo
                    self.dvr.expire(self)
                    self.dvr.update_local_links(self)

                    # Publicar si hubo cambios
                    if self.dvr.changed:
                        table = self.dvr.build_routing_table()
                        with self._lock:
                            self.routing_table = table
                        self._dump_table("Tabla DVR actualizada")

                    # Anunciar si corresponde
                    if self.dvr.should_advertise():
                        self.dvr.advertise(self)

                time.sleep(1.0)
            except Exception as e:
                self._log("ERROR", f"Error en routing_loop: {e}", tag="loop")
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
            time.sleep(self.hello_period)

    # ========= Ciclo de vida =========
    def start(self):
        self.running = True
        self._t_fwd = threading.Thread(target=self.forwarding_loop, daemon=True)
        self._t_rte = threading.Thread(target=self.routing_loop, daemon=True)
        self._t_hlo = threading.Thread(target=self.hello_loop, daemon=True)
        self._t_fwd.start()
        self._t_rte.start()
        self._t_hlo.start()
        self._log("INFO", f"Iniciado ({self.mode}) en {self._host}:{self._port} vecinos={sorted(self.neighbors)}", tag="start")

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
            self._log("INFO", title, tag="rte")
        for dst, row in sorted(rt.items()):
            self._log("INFO", f"dst={dst} nh={row.get('next_hop')} cost={row.get('cost')}", tag="rte")
