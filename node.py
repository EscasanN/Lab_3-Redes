# node.py — RouterNode con formato Mathew, HELLO/ACK y soporte LSP
from __future__ import annotations
import socket, threading, time, json
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
from queue import Queue

try:
    import redis
except Exception:
    redis = None

from messages import normalize_incoming, make_wire, dumps, get_header, set_header
from flooding import Flooding
from dijkstra import dijkstra, build_routing_table
from lsr import LSR
from dvr import DVR  # opcional

BUFFER_SIZE = 65536
LOG_LEVELS = {"ERROR": 0, "WARN": 1, "INFO": 2, "DEBUG": 3}

@dataclass
class NeighborMetrics:
    rtt_ms: float = float("inf")
    last_seen: float = 0.0

class RouterNode:
    """
    Modos: dijkstra | flooding | lsr | dvr
    Transporte: tcp | redis
    Mensajería: formato Mathew (type/from/to/hops/headers/payload)
    - HELLO/HELLO_ACK automáticos cada hello_period (con reply_to para RTT)
    - LSR: 'lsp' con flooding
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
            self._inv_names = {str(v): str(k) for k, v in self.nodes_map.items()}
        # TCP no necesita map inverso
        if self.transport == "tcp":
            self._inv_names = {}

        # logging/timers
        self.log_level = log_level.upper()
        self._log_lvl = LOG_LEVELS.get(self.log_level, 2)
        self.hello_period = float(hello_period)
        self.dead_after = float(dead_after)

        # Flooding (se usa en modo flooding y para difundir LSP/control)
        self.flood = Flooding()

        # Topología/vecinos
        self.topology = topo
        self.neighbors = set(topo.get(node_id, {}).keys())

        # Estado
        self.routing_table: Dict[str, Dict[str, float | str | None]] = {}
        self.info_in: Queue = Queue()
        self.nei_metrics: Dict[str, NeighborMetrics] = {n: NeighborMetrics() for n in self.neighbors}
        self._hello_out: Dict[str, float] = {}  # id_hello -> ts_enviado
        self._seq = 0

        # protocolos
        self.lsr = LSR(self.node_id) if mode == "lsr" else None
        self.dvr = DVR(self.node_id) if mode == "dvr" else None

        self.running = False
        self._lock = threading.Lock()

        # Servidor TCP o Redis
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

    def _to_wire_id(self, nid: str) -> str:
        return str(self.nodes_map[nid]) if self.transport == "redis" else nid

    def _from_wire_id(self, wid: str) -> str:
        if self.transport == "redis":
            return self._inv_names.get(str(wid), str(wid))
        return str(wid)

    # ========= Logging =========
    def _log(self, level: str, msg: str, tag: str | None = None):
        lvl = LOG_LEVELS.get(level.upper(), 2)
        if lvl <= self._log_lvl:
            prefix = f"[{self.node_id}/{(tag or self.mode).upper()}]"
            print(f"{prefix} {msg}")

    def _update_last_seen(self, n: str) -> None:
        m = self.nei_metrics.get(n) or NeighborMetrics()
        m.last_seen = self._now()
        self.nei_metrics[n] = m

    def cost_to(self, neighbor: str) -> float:
        m = self.nei_metrics.get(neighbor)
        return m.rtt_ms if (m and m.rtt_ms != float("inf")) else 1.0

    # ========= Transporte =========
    def _send(self, target_node: str, wire: str):
        """target_node es ID local (A/B/..). Se resuelve a canal si Redis."""
        if self.transport == "redis":
            channel = str(self.nodes_map[target_node])
            try:
                self._redis.publish(channel, wire)
            except Exception as e:
                self._log("WARN", f"Redis publish error a {channel}: {e}")
            return
        host, port = self.nodes_map[target_node]
        try:
            with socket.create_connection((host, port), timeout=1.2) as s:
                s.sendall(wire.encode("utf-8"))
        except Exception as e:
            self._log("WARN", f"Error enviando a {target_node}: {e}")

    def _broadcast_wire(self, wire: str):
        """Publica un control (p.ej. LSP) via flooding local (distribución por vecinos)."""
        try:
            msg = normalize_incoming(wire)
        except Exception:
            return
        # Entra por el mismo pipeline (control), se inundará
        self._handle_control(msg)

    # ========= HELLO / ACK =========
    def _send_hello(self, n: str):
        # Envío HELLO (hops=1) con payload 'HELLO'
        wire = make_wire("hello", self._to_wire_id(self.node_id), self._to_wire_id(n), 1, "HELLO")
        msg = json.loads(wire)
        hid = get_header(msg, "id")
        self._hello_out[hid] = self._now()
        self._send(n, wire)

    def _on_hello(self, msg: dict) -> None:
        # responder hello con hello_ack y reply_to
        src_wire = msg.get("from")
        src = self._from_wire_id(src_wire)
        self._update_last_seen(src)
        inc_id = get_header(msg, "id")
        ack = {
            "type": "hello_ack",
            "from": self._to_wire_id(self.node_id),
            "to": self._to_wire_id(src),
            "hops": 1,
            "headers": [ {"id": get_header(msg, "id"), "ts": get_header(msg, "ts"), "reply_to": inc_id} ],
            "payload": "HELLO_ACK",
        }
        self._send(src, dumps(ack))

    def _on_hello_ack(self, msg: dict) -> None:
        src = self._from_wire_id(msg.get("from"))
        self._update_last_seen(src)
        rid = get_header(msg, "reply_to")
        ts_sent = self._hello_out.pop(rid, None)
        if ts_sent is not None:
            rtt_ms = (self._now() - ts_sent) * 1000.0
            m = self.nei_metrics.get(src) or NeighborMetrics()
            m.rtt_ms = rtt_ms; m.last_seen = self._now()
            self.nei_metrics[src] = m
            self._log("INFO", f"HELLO_ACK {src} RTT={rtt_ms:.1f} ms", tag="HELLO")

    # ========= Procesamiento =========
    def _handle_control(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "lsp":
            if self.mode == "lsr" and self.lsr:
                self.lsr.on_receive_lsp(self, msg)
            # en cualquier modo, un LSP se reenvía por flooding para confiabilidad
            self.flood.handle_control(self, msg)
            return

        if mtype == "info":
            # DV opcional: reenviar si quieres; por simplicidad no re-interpretamos DV de otros
            self.flood.handle_control(self, msg)
            return

        # otros controles no flood (hello/ack) no se reenvían

    def _process_msg(self, msg: dict) -> None:
        try:
            to_wire = msg.get("to")
            from_wire = msg.get("from")
            mtype = msg.get("type")
            hops = int(msg.get("hops", 0))
        except Exception:
            return
        if hops <= 0:
            return

        to = self._from_wire_id(to_wire) if to_wire != "*" else "*"
        src = self._from_wire_id(from_wire)

        # HELLO / ACK
        if mtype == "hello":
            self._on_hello(msg); return
        if mtype == "hello_ack":
            self._on_hello_ack(msg); return

        # CONTROL (LSP/INFO)
        if mtype in ("lsp", "info"):
            self._handle_control(msg); return

        # MENSAJES DE USUARIO
        if mtype == "message" and to == self.node_id:
            payload = msg.get("payload")
            # soporte a 'pong' ad hoc si lo usas
            if isinstance(payload, dict) and payload.get("kind") == "pong":
                try:
                    rtt_ms = (self._now() - float(payload.get("ts", self._now()))) * 1000.0
                    self._log("INFO", f"PONG from {src} RTT={rtt_ms:.1f} ms", tag="RECV")
                except Exception:
                    self._log("WARN", f"PONG from {src} ts inválido", tag="RECV")
                return
            self._log("INFO", f"DATA de {src}: {payload}", tag="RECV")
            return

        # Forwarding (no soy destino)
        with self._lock:
            nh = self.routing_table.get(to, {}).get("next_hop")
        if not nh and to in self.neighbors:
            nh = to
            self._log("DEBUG", f"Sin ruta; usando vecino directo {to}", tag="FWD")
        if not nh:
            self._log("WARN", f"Sin ruta a {to} ({self.mode}).", tag="FWD")
            return

        # Decrementa hops y forward sin cambiar id
        msg["hops"] = hops - 1
        self._send(nh, dumps(msg))
        self._log("INFO", f"FWD {self.node_id} → {nh} (dst={to})", tag="FWD")

    # ========= Loops =========
    def forwarding_loop(self):
        if self.transport == "redis":
            while self.running:
                try:
                    for message in self._pubsub.listen():
                        if not self.running: break
                        if message.get("type") != "message": continue
                        data = message.get("data")
                        try:
                            msg = normalize_incoming(data)
                        except Exception:
                            continue
                        self._process_msg(msg)
                except Exception as e:
                    self._log("WARN", f"Redis listen error: {e}")
                    time.sleep(0.2)
            return

        # TCP
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
                    msg = normalize_incoming(data)
                except Exception:
                    continue
                self._process_msg(msg)

    def routing_loop(self):
        while self.running:
            try:
                if self.mode == "dijkstra":
                    res = dijkstra(self.topology, self.node_id)
                    table = build_routing_table(res, self.node_id)
                    with self._lock: self.routing_table = table

                elif self.mode == "lsr" and self.lsr:
                    self.lsr.expire()
                    if self.lsr.should_advertise(self):
                        self.lsr.advertise(self)
                    if self.lsr.changed:
                        dyn_topo = self.lsr.build_topology()
                        dyn_topo.setdefault(self.node_id, {})
                        res = dijkstra(dyn_topo, self.node_id)
                        with self._lock:
                            self.routing_table = build_routing_table(res, self.node_id)
                        self.lsr.changed = False

                elif self.mode == "dvr" and self.dvr:
                    self.dvr.expire(self)
                    self.dvr.update_local_links(self)
                    if self.dvr.changed:
                        with self._lock:
                            self.routing_table = self.dvr.build_routing_table()
                    if self.dvr.should_advertise():
                        self.dvr.advertise(self)

                time.sleep(1.0)
            except Exception as e:
                self._log("ERROR", f"Error en routing_loop: {e}", tag="loop")
                time.sleep(1.0)

    def hello_loop(self):
        while self.running:
            for n in list(self.neighbors):
                self._send_hello(n)
            time.sleep(self.hello_period)

    # ========= Ciclo de vida =========
    def start(self):
        self.running = True
        self._t_fwd = threading.Thread(target=self.forwarding_loop, daemon=True)
        self._t_rte = threading.Thread(target=self.routing_loop, daemon=True)
        self._t_hlo = threading.Thread(target=self.hello_loop, daemon=True)
        self._t_fwd.start(); self._t_rte.start(); self._t_hlo.start()
        addr = f"TCP {self._host}:{self._port}" if self.transport == "tcp" else f"Redis ch={self._channel}"
        self._log("INFO", f"Iniciado ({self.mode}) {addr} vecinos={sorted(self.neighbors)}", tag="start")

    def stop(self):
        self.running = False
        try:
            if self._server: self._server.close()
        except Exception:
            pass
        if self.transport == "redis":
            try: self._pubsub.unsubscribe()
            except Exception: pass

    def _dump_table(self, title: str = ""):
        with self._lock: rt = dict(self.routing_table)
        if title: self._log("INFO", title, tag="rte")
        for dst, row in sorted(rt.items()):
            self._log("INFO", f"dst={dst} nh={row.get('next_hop')} cost={row.get('cost')}", tag="rte")
