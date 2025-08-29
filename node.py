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
<<<<<<< HEAD
import threading
import time
import json
import re
from flooding import Flooding
from dataclasses import dataclass
from typing import Dict, Tuple
from queue import Queue

from messages import make_msg, parse_msg, normalize_type, payload_text
=======

from messages import normalize_incoming, make_wire, dumps, get_header, set_header
from flooding import Flooding
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
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
<<<<<<< HEAD
=======
    """
    Modos: dijkstra | flooding | lsr | dvr
    Transporte: tcp | redis
    Mensajería: formato Mathew (type/from/to/hops/headers/payload)
    - HELLO/HELLO_ACK automáticos cada hello_period (con reply_to para RTT)
    - LSR: 'lsp' con flooding
    """

>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
    def __init__(self, node_id: str, nodes_map: Dict[str, Tuple[str, int] | str],
                 topo: Dict[str, Dict[str, float]], mode: str = "dijkstra",
                 log_level: str = "INFO", hello_period: float = 5.0, dead_after: float = 10.0,
                 transport: str = "tcp",
                 redis_host: str | None = None,
                 redis_port: int | None = None,
                 redis_pwd: str | None = None,
                 addresses_map: Dict[str, str] | None = None):
        assert mode in {"dijkstra", "flooding", "lsr", "dvr"}
        self.node_id = node_id
        self.mode = mode
        self.nodes_map = nodes_map
        self.addresses_map = addresses_map or {}
        self.transport = (transport or "tcp").lower()
        if self.transport == "tcp":
            self._host, self._port = nodes_map[node_id]  # ("127.0.0.1", 5001)
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

<<<<<<< HEAD
        self.node_to_user: Dict[str, str] = {}
        self.user_to_node: Dict[str, str] = {}
        if self.transport == "redis":
            for n, ch in self.nodes_map.items():
                # Preferred username/address comes from addresses_map when provided
                uname = self.addresses_map.get(str(n)) or self._derive_username(str(ch)) or str(n)
                self.node_to_user[str(n)] = uname
                # map canonical username -> node id
                self.user_to_node.setdefault(uname, str(n))
                # also map full channel name and case variants
                self.user_to_node.setdefault(str(ch), str(n))
                self.user_to_node.setdefault(str(n).lower(), str(n))
                self.user_to_node.setdefault(str(n).upper(), str(n))

        # Servidor TCP local o Redis
=======
        # Servidor TCP o Redis
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
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

<<<<<<< HEAD
    # ========= Compat helpers =========
    @staticmethod
    def _derive_username(channel: str) -> str | None:
        if channel.startswith("(") and "," in channel and "127.0.0.1" in channel:
            return None
        m = re.search(r'([A-Za-z0-9_+-]+)$', channel)
        return m.group(1).lower() if m else None

    def _id_to_user(self, node_id: str) -> str:
        if self.transport != "redis":
            return node_id
        return self.node_to_user.get(node_id, node_id)

    def _user_to_id(self, user_or_channel: str) -> str:
        if self.transport != "redis":
            return user_or_channel
        return self.user_to_node.get(user_or_channel, user_or_channel)

    def _normalize_outgoing_ids(self, msg: dict) -> dict:
        if self.transport != "redis":
            return msg
        out = dict(msg)
        out["from"] = self._id_to_user(str(out.get("from", self.node_id)))
        to_val = out.get("to")
        if isinstance(to_val, str) and to_val in self.node_to_user:
            out["to"] = self._id_to_user(to_val)
        return out

    def _normalize_incoming_ids(self, msg: dict) -> dict:
        if self.transport != "redis":
            return msg
        out = dict(msg)
        frm = out.get("from")
        to = out.get("to")
        if isinstance(frm, str):
            out["from"] = self._user_to_id(frm)
        if isinstance(to, str):
            out["to"] = self._user_to_id(to)
        return out
=======
    def _to_wire_id(self, nid: str) -> str:
        return str(self.nodes_map[nid]) if self.transport == "redis" else nid

    def _from_wire_id(self, wid: str) -> str:
        if self.transport == "redis":
            return self._inv_names.get(str(wid), str(wid))
        return str(wid)
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7

    # ========= Logging =========
    def _log(self, level: str, msg: str, tag: str | None = None):
        lvl = LOG_LEVELS.get(level.upper(), 2)
        if lvl <= self._log_lvl:
            prefix = f"[{self.node_id}/{(tag or self.mode).upper()}]"
            print(f"{prefix} {msg}")

    def _update_last_seen(self, n: str) -> None:
        m = self.nei_metrics.get(n) or NeighborMetrics()
        m.last_seen = self._now()
<<<<<<< HEAD

    def _on_hello(self, msg: dict) -> None:
        src = msg.get("from")
        self._update_last_seen(src)
        seq = msg.get("payload", {}).get("seq")
        ts = msg.get("payload", {}).get("ts")
        echo = {
            "proto": self.mode, "type": "echo",
            "from": self.node_id, "to": src, "ttl": 4, "hops": 0,
            "headers": [], "payload": {"seq": seq, "ts": ts}
        }
        self._send_msg(src, echo)

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
            self._log("INFO", f"ECHO {src} seq={seq} RTT={rtt_ms:.1f} ms", tag="ECHO")
            if self.mode == "dvr" and self.dvr:
                self.dvr.changed = True
                self.dvr.trigger_update()
=======
        self.nei_metrics[n] = m
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7

    def cost_to(self, neighbor: str) -> float:
        m = self.nei_metrics.get(neighbor)
        return m.rtt_ms if (m and m.rtt_ms != float("inf")) else 1.0

<<<<<<< HEAD
    # ========= Transporte local =========
    def _send_wire(self, target_node: str, wire: str):
=======
    # ========= Transporte =========
    def _send(self, target_node: str, wire: str):
        """target_node es ID local (A/B/..). Se resuelve a canal si Redis."""
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
        if self.transport == "redis":
            channel = str(self.nodes_map[target_node])
            try:
                self._redis.publish(channel, wire)
            except Exception as e:
                self._log("WARN", f"Redis publish error a {channel}: {e}")
            return
        host, port = self.nodes_map[target_node]
<<<<<<< HEAD
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

    def _send_msg(self, target_node: str, msg: dict):
        try:
            wire_msg = self._normalize_outgoing_ids(msg)
            wire = json.dumps(wire_msg, ensure_ascii=False)
        except Exception as e:
            self._log("WARN", f"No se pudo serializar msg: {e}", tag="SER")
            return
        self._send_wire(target_node, wire)

    # ========= Procesamiento de mensajes =========
    def _process_msg(self, msg: dict) -> None:
        msg = self._normalize_incoming_ids(msg)

        try:
            to = msg.get("to")
            src = msg.get("from")
            mtype = normalize_type(msg.get("type"))
            ttl = int(msg.get("ttl", 0))
=======
        try:
            with socket.create_connection((host, port), timeout=1.2) as s:
                s.sendall(wire.encode("utf-8"))
        except Exception as e:
            self._log("WARN", f"Error enviando a {target_node}: {e}")

    def _broadcast_wire(self, wire: str):
        """Publica un control (p.ej. LSP) via flooding local (distribución por vecinos)."""
        try:
            msg = normalize_incoming(wire)
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
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

<<<<<<< HEAD
        try:
            msg["hops"] = int(msg.get("hops", 0)) + 1
        except Exception:
            msg["hops"] = 1

        if mtype == "hello":
            self._on_hello(msg); return
        if mtype == "echo":
            self._on_echo(msg); return

=======
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
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

<<<<<<< HEAD
        if to == self.node_id:
            kind = payload.get("kind")
            if kind == "ping":
                orig_ts = float(payload.get("ts", self._now()))
                with self._lock:
                    nh_back = self.routing_table.get(src, {}).get("next_hop")
                if nh_back:
                    pong = {
                        "proto": self.mode, "type": "data",
                        "from": self.node_id, "to": src, "ttl": 12, "hops": 0,
                        "headers": [], "payload": {"kind": "pong", "ts": orig_ts}
                    }
                    self._send_msg(nh_back, pong)
                    self._log("INFO", f"PONG → {src} via {nh_back}", tag="RECV")
                else:
                    self._log("WARN", f"No next-hop para responder PONG a {src}", tag="RECV")
                return
=======
        to = self._from_wire_id(to_wire) if to_wire != "*" else "*"
        src = self._from_wire_id(from_wire)
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7

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

<<<<<<< HEAD
        msg["ttl"] = ttl - 1
        self._send_msg(nh, msg)
=======
        # Decrementa hops y forward sin cambiar id
        msg["hops"] = hops - 1
        self._send(nh, dumps(msg))
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
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

<<<<<<< HEAD
=======
        # TCP
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
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
<<<<<<< HEAD
                            self.routing_table = table
                        self._dump_table("Tabla DVR actualizada")

=======
                            self.routing_table = self.dvr.build_routing_table()
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
                    if self.dvr.should_advertise():
                        self.dvr.advertise(self)

                time.sleep(1.0)
            except Exception as e:
                self._log("ERROR", f"Error en routing_loop: {e}", tag="loop")
                time.sleep(1.0)

    def hello_loop(self):
        while self.running:
            for n in list(self.neighbors):
<<<<<<< HEAD
                seq = self._seq_next()
                ts = self._now()
                self._hello_out[(n, seq)] = ts
                hello = {
                    "proto": self.mode, "type": "hello",
                    "from": self.node_id, "to": n, "ttl": 4, "hops": 0,
                    "headers": [], "payload": {"seq": seq, "ts": ts}
                }
                self._send_msg(n, hello)
=======
                self._send_hello(n)
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
            time.sleep(self.hello_period)

    # ========= Ciclo de vida =========
    def start(self):
        self.running = True
        self._t_fwd = threading.Thread(target=self.forwarding_loop, daemon=True)
        self._t_rte = threading.Thread(target=self.routing_loop, daemon=True)
        self._t_hlo = threading.Thread(target=self.hello_loop, daemon=True)
<<<<<<< HEAD
        self._t_fwd.start()
        self._t_rte.start()
        self._t_hlo.start()
        addr = f"TCP {self._host}:{self._port}" if self.transport == 'tcp' else f"Redis ch={self._channel}"
        self._log("INFO", f"Iniciado ({self.mode}) {addr} vecinos={sorted(self.neighbors)}", tag="START")
=======
        self._t_fwd.start(); self._t_rte.start(); self._t_hlo.start()
        addr = f"TCP {self._host}:{self._port}" if self.transport == "tcp" else f"Redis ch={self._channel}"
        self._log("INFO", f"Iniciado ({self.mode}) {addr} vecinos={sorted(self.neighbors)}", tag="start")
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7

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
<<<<<<< HEAD
        with self._lock:
            rt = dict(self.routing_table)
        if title:
            self._log("INFO", title, tag="RTE")
=======
        with self._lock: rt = dict(self.routing_table)
        if title: self._log("INFO", title, tag="rte")
>>>>>>> 57f9c98fd2e17c148f4995740eb8182169573bc7
        for dst, row in sorted(rt.items()):
            self._log("INFO", f"dst={dst} nh={row.get('next_hop')} cost={row.get('cost')}", tag="RTE")
