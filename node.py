from __future__ import annotations
import socket
try:
    import redis
except Exception:
    redis = None
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

    def __init__(self, node_id: str, nodes_map: Dict[str, Tuple[str, int] | str],
                 topo: Dict[str, Dict[str, float]], mode: str = "dijkstra",
                 log_level: str = "INFO", hello_period: float = 5.0, dead_after: float = 10.0,
                 transport: str = "tcp",
                 redis_host: str | None = None,
                 redis_port: int | None = None,
                 redis_pwd: str | None = None):
        assert mode in {"dijkstra", "flooding", "lsr", "dvr"}
        self.node_id = node_id
        self.mode = mode
        self.nodes_map = nodes_map
        self.transport = (transport or "tcp").lower()
        if self.transport == "tcp":
            self._host, self._port = nodes_map[node_id]
        else:
            self._channel = str(nodes_map[node_id])
            self._redis_host = redis_host or "lab3.redesuvg.cloud"
            self._redis_port = int(redis_port or 6379)
            self._redis_pwd = redis_pwd or "UVGRedis2025"
            if redis is None:
                raise RuntimeError("Debe instalar redis-py: pip install redis")
            self._redis = redis.Redis(host=self._redis_host, port=self._redis_port, password=self._redis_pwd)
            self._pubsub = self._redis.pubsub()
            self._pubsub.subscribe(self._channel)

        # logging/timers
        self.log_level = log_level.upper()
        self._log_lvl = LOG_LEVELS.get(self.log_level, 2)
        self.hello_period = float(hello_period)
        self.dead_after = float(dead_after)

        # Flooding: se usa en modo 'flooding' y también para propagar LSP en 'lsr'
        self.flood = Flooding() if mode in {"flooding", "lsr"} else None

        # Topología/vecinos 
        self.topology = topo
        self.neighbors = set(topo.get(node_id, {}).keys())

        # Estado
        self.routing_table: Dict[str, Dict[str, float | str | None]] = {}
        self.info_in: Queue = Queue()
        self.seen = set()
        self.nei_metrics: Dict[str, NeighborMetrics] = {n: NeighborMetrics() for n in self.neighbors}
        self._hello_out: Dict[Tuple[str, int], float] = {}  
        self._seq = 0

        # LSR
        self.lsr = LSR(self.node_id) if mode == "lsr" else None
        # DVR
        self.dvr = DVR(self.node_id, use_static_costs=True, poisoned_reverse=True) if mode == "dvr" else None

        self.running = False
        self._lock = threading.Lock()

        # Servidor TCP local o Redis
        if self.transport == "tcp":
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind((self._host, self._port))
            self._server.listen(16)
        else:
            self._server = None

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
                self.dvr.trigger_update()

    def cost_to(self, neighbor: str) -> float:
        m = self.nei_metrics.get(neighbor)
        return m.rtt_ms if m and m.rtt_ms != float("inf") else 1.0

    # ========= Transporte local =========
    def _send(self, target_node: str, wire: str):
        if self.transport == "redis":
            channel = str(self.nodes_map[target_node])
            try:
                self._redis.publish(channel, wire)
                return
            except Exception as e:
                self._log("WARN", f"Redis publish error a {channel}: {e}")
                return
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

    # ========= Procesamiento de mensajes =========
    def _process_msg(self, msg: dict) -> None:
        try:
            to = msg.get("to")
            src = msg.get("from")
            proto = msg.get("proto")
            mtype = msg.get("type")
            ttl = int(msg.get("ttl", 0))
        except Exception:
            return

        if ttl <= 0:
            return

        # Cuenta hops
        try:
            msg["hops"] = int(msg.get("hops", 0)) + 1
        except Exception:
            msg["hops"] = 1

        if mtype == "hello":
            self._on_hello(msg); return
        if mtype == "echo":
            self._on_echo(msg); return

        if mtype == "info":
            if self.mode == "lsr" and self.lsr:
                self.lsr.on_receive_info(self, msg); return
            if self.mode == "flooding" and self.flood:
                self.flood.handle_info(self, msg); return
            self._log("DEBUG", f"INFO recibido y descartado en modo {self.mode}")
            return

        if self.mode == "flooding" and self.flood:
            if mtype == "data":
                self.flood.handle_data(self, msg)
                return

        payload = msg.get("payload") or {}

        if to == self.node_id:
            kind = payload.get("kind")
            if kind == "ping":
                orig_ts = float(payload.get("ts", self._now()))
                with self._lock:
                    nh_back = self.routing_table.get(src, {}).get("next_hop")
                if nh_back:
                    pong = make_msg(self.mode, "data", self.node_id, src, 12, {"kind": "pong", "ts": orig_ts})
                    self._send(nh_back, pong)
                    self._log("INFO", f"PONG → {src} via {nh_back}", tag="RECV")
                else:
                    self._log("WARN", f"No next-hop para responder PONG a {src}", tag="RECV")
                return

            if kind == "pong":
                try:
                    rtt_ms = (self._now() - float(payload.get("ts", self._now()))) * 1000.0
                    self._log("INFO", f"PONG from {src} RTT={rtt_ms:.1f} ms", tag="RECV")
                except Exception:
                    self._log("WARN", f"PONG from {src} (ts inválido)", tag="RECV")
                return

            self._log("INFO", f"DATA de {src}: {payload}", tag="RECV")
            return

        with self._lock:
            nh = self.routing_table.get(to, {}).get("next_hop")
        # Hotfix: si no hay ruta pero el destino es vecino directo, envía directo.
        if not nh and to in self.neighbors:
            nh = to
            self._log("DEBUG", f"Sin ruta en tabla; usando vecino directo {to}", tag="FWD")
        if not nh:
            self._log("WARN", f"Sin ruta a {to} ({self.mode}).", tag="FWD")
            return
        # decrementa TTL antes de reenviar
        msg["ttl"] = ttl - 1
        try:
            wire = json.dumps(msg, ensure_ascii=False)
        except Exception:
            return
        self._send(nh, wire)
        self._log("INFO", f"FWD {self.node_id} → {nh} (dst={to})", tag="FWD")

    # ========= Forwarding =========
    def forwarding_loop(self):
        if self.transport == "redis":
            while self.running:
                try:
                    for message in self._pubsub.listen():
                        if not self.running:
                            break
                        if message.get('type') != 'message':
                            continue
                        data = message.get('data')
                        try:
                            msg = parse_msg(data)
                        except Exception:
                            continue
                        self._process_msg(msg)
                except Exception as e:
                    self._log("WARN", f"Redis listen error: {e}")
                    time.sleep(0.2)
            return

        # TCP branch
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
                    continue

                if not data:
                    continue
                try:
                    msg = parse_msg(data)
                except Exception:
                    continue
                self._process_msg(msg)

    def routing_loop(self):
        while self.running:
            try:
                if self.mode == "dijkstra":
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
        addr = f"TCP {self._host}:{self._port}" if self.transport == 'tcp' else f"Redis ch={self._channel}"
        self._log("INFO", f"Iniciado ({self.mode}) {addr} vecinos={sorted(self.neighbors)}", tag="start")

    def stop(self):
        self.running = False
        try:
            if self._server:
                self._server.close()
        except Exception:
            pass
        if self.transport == 'redis':
            try:
                self._pubsub.unsubscribe()
            except Exception:
                pass

    def _dump_table(self, title: str = ""):
        with self._lock:
            rt = dict(self.routing_table)
        if title:
            self._log("INFO", title, tag="rte")
        for dst, row in sorted(rt.items()):
            self._log("INFO", f"dst={dst} nh={row.get('next_hop')} cost={row.get('cost')}", tag="rte")
