import socket
import threading
import time
import json
from typing import Dict, Tuple
from messages import make_msg, parse_msg
from dijkstra import dijkstra, build_routing_table

BUFFER_SIZE = 65536

class RouterNode:
    """
    Nodo simple para Fase 1 con 2 hilos:
      - forwarding_loop: recibe y reenvía paquetes (DATA/INFO/HELLO)
      - routing_loop: mantiene la tabla de ruteo (Dijkstra) a partir de la topología local
    Comunicación: sockets TCP locales (host:puerto por nodo).
    """

    def __init__(self, node_id: str, nodes_map: Dict[str, Tuple[str, int]], topo: Dict[str, Dict[str, float]]):
        self.node_id = node_id
        self.nodes_map = nodes_map  # {node: (host, port)}
        self.topology = topo        # (solo para Fase 1 / pruebas de Dijkstra)
        self.routing_table = {}     # {dst: {next_hop, cost}}
        self.running = False

        self._host, self._port = nodes_map[node_id]
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._host, self._port))
        self._server.listen(16)

        self._lock = threading.Lock()

    # ============ Infra: Forwarding ============
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
                data = conn.recv(BUFFER_SIZE)
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
        ttl = msg.get("ttl", 0)

        if ttl <= 0:
            return  # descartar

        if to == self.node_id and mtype in {"message", "data"}:
            print(f"[{self.node_id}] DATA para mí de {msg.get('from')}: {msg.get('payload')}")
            return

        if mtype == "hello":
            # Responder eco sencillo (latency demo)
            reply = {
                "rtt_echo": time.time(),
                "ts_recv": time.time(),
            }
            self._send(msg["from"], make_msg(proto, "echo", self.node_id, msg["from"], ttl-1, reply))
            return

        if mtype == "info":
            # En Fase 1 no integramos INFO dinámico todavía; solo mostramos
            print(f"[{self.node_id}] INFO recibido de {msg.get('from')}: {msg.get('payload')}")
            return

        # Forward de DATA (o tipos no-recibidos por mí)
        next_hop = None
        with self._lock:
            if msg["to"] in self.routing_table:
                next_hop = self.routing_table[msg["to"]]["next_hop"]
        if next_hop is None:
            print(f"[{self.node_id}] No tengo ruta a {msg['to']}, descartando.")
            return

        fwd = msg.copy()
        fwd["ttl"] = ttl - 1
        wire = json.dumps(fwd)
        self._send(next_hop, wire)
        print(f"[{self.node_id}] FWD → {next_hop} destino final {msg['to']}")

    def _send(self, target_node: str, wire: str):
        host, port = self.nodes_map[target_node]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(1.5)
            s.connect((host, port))
            s.sendall(wire.encode("utf-8"))
        except Exception as e:
            print(f"[{self.node_id}] Error enviando a {target_node}: {e}")
        finally:
            s.close()

    # ============ Routing (Dijkstra) ============
    def routing_loop(self):
        # Recalcula tabla cada N segundos (permite cambios de topología en pruebas)
        while self.running:
            try:
                res = dijkstra(self.topology, self.node_id)
                table = build_routing_table(res, self.node_id)
                with self._lock:
                    self.routing_table = table
                time.sleep(1.0)
            except Exception as e:
                print(f"[{self.node_id}] Error en routing_loop: {e}")
                time.sleep(1.0)

    def start(self):
        self.running = True
        self._t_fwd = threading.Thread(target=self.forwarding_loop, daemon=True)
        self._t_rte = threading.Thread(target=self.routing_loop, daemon=True)
        self._t_fwd.start()
        self._t_rte.start()
        print(f"[{self.node_id}] Iniciado en {self._host}:{self._port}")

    def stop(self):
        self.running = False
        try:
            self._server.close()
        except Exception:
            pass