from __future__ import annotations
import socket, threading, time, json
from dataclasses import dataclass
from typing import Dict, Tuple, Optional, Set, Any
from queue import Queue

try:
    import redis
except Exception:
    redis = None

from messages import normalize_incoming, make_wire, dumps, get_header, set_header
from flooding import Flooding
from lsr import LSR
from dvr import DVR

LOG_LEVELS = {"ERROR": 0, "WARN": 1, "INFO": 2, "DEBUG": 3}

@dataclass
class NeighborMetrics:
    rtt_ms: float = float("inf")
    last_seen: float = 0.0

class RouterNode:
    """
    Modes: dijkstra | flooding | lsr | dvr (we implement flooding + lsr + minimal dvr)
    Transport: tcp | redis
    Messaging: Mathew format (type/from/to/hops/headers/payload). 
    """
    def __init__(self, node_id: str, nodes_map: Dict[str, Tuple[str, int] | str],
                 topo: Dict[str, Dict[str, float]], mode: str = "flooding",
                 log_level: str = "INFO",
                 transport: str = "tcp",
                 redis_host: Optional[str] = None, redis_port: Optional[int] = None, redis_pwd: Optional[str] = None,
                 hello_period: float = 5.0, dead_after: float = 15.0):
        assert mode in {"dijkstra", "flooding", "lsr", "dvr"}
        self.node_id = node_id
        self.mode = mode
        self.nodes_map = nodes_map
        self.topology = topo
        self.transport = (transport or "tcp").lower()
        self._server = None
        self.running = False
        self._lock = threading.Lock()
        self._seq = 0

        if self.transport == "tcp":
            host, port = nodes_map[node_id]
            self._host, self._port = host, int(port)
            self._inv_names = {}
        else:
            self._channel = str(nodes_map[node_id])
            self._redis_host = redis_host or "lab3.redesuvg.cloud"
            self._redis_port = int(redis_port or 6379)
            self._redis_pwd = redis_pwd or "UVGRedis2025"
            if redis is None:
                raise RuntimeError("Install redis: pip install redis")
            self._redis = redis.Redis(host=self._redis_host, port=self._redis_port, password=self._redis_pwd)
            self._pubsub = self._redis.pubsub()
            self._pubsub.subscribe(self._channel)
            # map channel->node id for logging
            self._inv_names = {str(v): str(k) for k, v in self.nodes_map.items()}

        # logging/timers
        self.log_level = log_level.upper()
        self._log_lvl = LOG_LEVELS.get(self.log_level, 2)
        self.hello_period = float(hello_period)
        self.dead_after = float(dead_after)

        # state
        self.neighbors: Set[str] = set(self.topology.get(self.node_id, {}).keys())
        self.nei_metrics: Dict[str, NeighborMetrics] = {}
        self.routing_table: Dict[str, Dict[str, Any]] = {}
        self._hello_out: Dict[str, float] = {}

        # helpers
        self.flood = Flooding()
        self.lsr = LSR(self.node_id) if mode == "lsr" else None
        self.dvr = DVR(self.node_id) if mode == "dvr" else None

    # ========= Helpers ==========
    def _log(self, level: str, msg: str, tag: str | None = None):
        lvl = LOG_LEVELS.get(level.upper(), 2)
        if lvl <= self._log_lvl:
            prefix = f"[{self.node_id}/{(tag or self.mode).upper()}]"
            print(f"{prefix} {msg}")

    def _now(self) -> float:
        return time.time()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _to_wire_id(self, nid: str) -> str:
        # For redis, convert node-id -> channel address. For tcp, keep node-id.
        return str(self.nodes_map[nid]) if self.transport == "redis" else nid

    def _from_wire_id(self, wid: str) -> str:
        if self.transport == "redis":
            return self._inv_names.get(str(wid), str(wid))
        return str(wid)

    def is_neighbor_active(self, n: str) -> bool:
        m = self.nei_metrics.get(n)
        if not m:
            return True
        return (self._now() - m.last_seen) < self.dead_after

    def cost_to(self, neighbor: str) -> float:
        m = self.nei_metrics.get(neighbor)
        return m.rtt_ms if (m and m.rtt_ms != float('inf')) else float(self.topology.get(self.node_id, {}).get(neighbor, 1.0))

    # ========= Sending ==========
    def _bind_tcp(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        host, port = self._host, self._port
        s.bind((host, port))
        s.listen(8)
        self._server = s

    def _send(self, target_node: str, wire: str):
        if self.transport == "redis":
            channel = str(self.nodes_map[target_node])
            try:
                self._redis.publish(channel, wire)
            except Exception as e:
                self._log("WARN", f"Redis publish error to {channel}: {e}")
            return
        # tcp
        host, port = self.nodes_map[target_node]
        try:
            with socket.create_connection((host, port), timeout=1.2) as s:
                s.sendall(wire.encode("utf-8"))
        except Exception as e:
            self._log("WARN", f"TCP send error to {target_node}: {e}")

    def _broadcast_wire(self, wire: str):
        for n in list(self.neighbors):
            self._send(n, wire)

    # ========= Control handling ==========
    def _send_hello(self, n: str):
        wire = make_wire("hello", self._to_wire_id(self.node_id), self._to_wire_id(n), 1, "HELLO", {"alg": self.mode})
        msg = json.loads(wire)
        hid = get_header(msg, "id")
        self._hello_out[hid] = self._now()
        self._send(n, wire)

    def _on_hello(self, msg: dict) -> None:
        src = self._from_wire_id(msg.get("from"))
        self._update_last_seen(src)
        # reply with echo (compatible with counterparty)
        echo = {
            "type": "echo",
            "from": self._to_wire_id(self.node_id),
            "to": msg.get("from"),
            "hops": 1,
            "headers": [ {"id": get_header(msg, "id"), "ts": get_header(msg, "ts"), "reply_to": get_header(msg, "id")} ],
            "payload": {"seq": self._next_seq(), "ts": self._now()}
        }
        self._send(src, dumps(echo))

    def _on_echo(self, msg: dict) -> None:
        src = self._from_wire_id(msg.get("from"))
        self._update_last_seen(src)
        rid = get_header(msg, "reply_to")
        if rid:
            ts_sent = self._hello_out.pop(rid, None)
            if ts_sent is not None:
                rtt_ms = (self._now() - ts_sent) * 1000.0
                m = self.nei_metrics.get(src) or NeighborMetrics()
                m.rtt_ms = rtt_ms; m.last_seen = self._now()
                self.nei_metrics[src] = m
                self._log("INFO", f"ECHO from {src} RTT={rtt_ms:.1f} ms", tag="HELLO")

    def _update_last_seen(self, n: str) -> None:
        m = self.nei_metrics.get(n) or NeighborMetrics()
        m.last_seen = self._now()
        self.nei_metrics[n] = m

    # deliver local data hook
    def on_data_local(self, msg: dict) -> None:
        # If it's an echo request targeted to me, bounce back
        if msg.get("type") == "echo" and msg.get("to") in (self._to_wire_id(self.node_id), self.node_id):
            reply = {
                "type": "echo",
                "from": self._to_wire_id(self.node_id),
                "to": msg.get("from"),
                "hops": 1,
                "headers": [ {"id": get_header(msg, "id"), "ts": get_header(msg, "ts"), "reply_to": get_header(msg, "id")} ],
                "payload": msg.get("payload")
            }
            self._send(self._from_wire_id(msg.get("from")), dumps(reply))

    # ========= Message processing ==========
    def _process_msg(self, msg: dict) -> None:
        try:
            mtype = msg.get("type")
        except Exception:
            return
        # normalize hops
        try:
            hops = int(msg.get("hops", 0))
        except Exception:
            hops = 0
        if hops <= 0 and mtype not in ("hello", "echo"):
            return

        # control
        if mtype == "hello":
            self._on_hello(msg); return
        if mtype == "echo":
            self._on_echo(msg); 
            # Continue no-op
            return
        if mtype == "lsp":
            if self.mode == "lsr" and self.lsr:
                self.lsr.on_receive_lsp(self, msg)
            self.flood.handle_control(self, msg)
            return
        if mtype == "info":
            self.flood.handle_control(self, msg)
            return

        # data (message)
        if mtype == "message":
            self.flood.handle_message(self, msg)
            return

        # unknown types: ignore
        self._log("DEBUG", f"Ignored type={mtype}", tag="PROC")

    # ========= Loops =========
    def forwarding_loop(self):
        if self.transport == "redis":
            while self.running:
                try:
                    for message in self._pubsub.listen():
                        if not self.running:
                            break
                        if message.get("type") != "message":
                            continue
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

        # TCP server
        self._bind_tcp()
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
                    data = conn.recv(65536)
                except Exception:
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
                # LSR dynamic topo
                if self.mode == "lsr" and self.lsr:
                    self.lsr.expire()
                    if self.lsr.should_advertise(self):
                        self.lsr.advertise(self)
                    if self.lsr.changed:
                        dyn_topo = self.lsr.build_topology()
                        dyn_topo.setdefault(self.node_id, {})
                        # No full dijkstra here; flooding handles forwarding
                        self.lsr.changed = False
                # DVR stub updates
                if self.mode == "dvr" and self.dvr:
                    self.dvr.update_local_links(self)
                    self.routing_table = self.dvr.build_routing_table()
                    if self.dvr.should_advertise():
                        self.dvr.advertise(self)
                time.sleep(1.0)
            except Exception as e:
                self._log("WARN", f"routing_loop error: {e}")

    def hello_loop(self):
        while self.running:
            for n in list(self.neighbors):
                self._send_hello(n)
            time.sleep(self.hello_period)

    # ========= Lifecycle =========
    def start(self):
        self.running = True
        self._t_fwd = threading.Thread(target=self.forwarding_loop, daemon=True)
        self._t_rte = threading.Thread(target=self.routing_loop, daemon=True)
        self._t_hlo = threading.Thread(target=self.hello_loop, daemon=True)
        self._t_fwd.start(); self._t_rte.start(); self._t_hlo.start()
        addr = f"TCP {getattr(self, '_host', '')}:{getattr(self, '_port', '')}" if self.transport == "tcp" \
               else f"Redis ch={self._channel}"
        self._log("INFO", f"Started ({self.mode}) {addr} neighbors={sorted(self.neighbors)}", tag="start")

    def stop(self):
        self.running = False
        try:
            if self._server: self._server.close()
        except Exception:
            pass
        if self.transport == "redis":
            try:
                self._pubsub.unsubscribe()
            except Exception:
                pass
