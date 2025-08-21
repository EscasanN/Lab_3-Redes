# send_cli.py
import argparse
import json
import socket
import time
from pathlib import Path
from messages import make_msg

# -------- Transporte (TCP hoy / XMPP en Fase 2) --------
class Transport:
    def __init__(self, nodes_path: str):
        with open(nodes_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)["config"]
        # {"A": ["127.0.0.1", 5001], ...}
        self.nodes = {k: (v[0], int(v[1])) for k, v in cfg.items()}

    def send_tcp(self, entry_node: str, wire: str, timeout=1.2):
        host, port = self.nodes[entry_node]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(wire.encode("utf-8"))
        s.close()

    # --- Fase 2: XMPP ---
    # def send_xmpp(self, entry_jid: str, wire: str):
    #     """
    #     TODO: implementar envío por XMPP (stanza <message> con body=wire o <iq>).
    #     Recomendado: envolver 'wire' como JSON en el body y usar un 'namespace' propio.
    #     """
    #     raise NotImplementedError

# -------- CLI --------
def interactive_cli(nodes_json: str, topo_json: str):
    tr = Transport(nodes_json)
    print("\n== Consola de pruebas ==")
    print("Formatos soportados: DATA/MESSAGE, DATA/PING, INFO genérico (payload libre)")
    while True:
        print("\n1) DATA/MESSAGE")
        print("2) DATA/PING")
        print("3) INFO")
        print("0) salir")
        op = input("elige: ").strip()
        if op == "0":
            return
        entry = input("entry-node para inyectar (A/B/C/D) [A]: ").strip().upper() or "A"
        src   = input("from [A]: ").strip().upper() or "A"
        dst   = input("to [D/*]: ").strip().upper() or "D"
        mode  = input("mode [dvr]: ").strip().lower() or "dvr"
        ttl   = int(input("ttl [12]: ").strip() or "12")

        if op == "1":
            text = input("mensaje: ").strip() or "hola"
            payload = {"text": text}
            wire = make_msg(mode, "data", src, dst, ttl, payload)
            tr.send_tcp(entry, wire)
            print(f"DATA enviado via {entry} {src}->{dst}")
        elif op == "2":
            # PING lógico (no espera PONG del nodo; sirve para testear forwarding)
            payload = {"kind": "ping", "ts": time.time()}
            wire = make_msg(mode, "data", src, dst, ttl, payload)
            t0 = time.time()
            tr.send_tcp(entry, wire)
            t1 = time.time()
            print(f"PING enviado {src}->{dst}, envío took {1000*(t1-t0):.1f} ms (no RTT)")
        elif op == "3":
            key = input("clave info [probe]: ").strip() or "probe"
            value = input("valor info [1]: ").strip() or "1"
            payload = {"info": {key: value}}
            wire = make_msg(mode, "info", src, dst, ttl, payload)
            tr.send_tcp(entry, wire)
            print(f"INFO enviado {src}->{dst}")
        else:
            print("Opción inválida.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--topo", required=True)
    ap.add_argument("--entry", default=None, help="Nodo por el que se inyecta el mensaje (A/B/C/D)")
    ap.add_argument("--src", default=None)
    ap.add_argument("--dst", default=None)
    ap.add_argument("--mode", choices=["dijkstra","flooding","lsr","dvr"], default="dvr")
    ap.add_argument("--ttl", type=int, default=12)

    # DATA/MESSAGE rápido
    ap.add_argument("--text", default=None)

    # PING lógico
    ap.add_argument("--ping", action="store_true")

    # INFO genérico
    ap.add_argument("--info", default=None)

    args = ap.parse_args()

    # Modo interactivo si no hay parámetros de envío directo
    if not any([args.text, args.ping, args.info]):
        return interactive_cli(args.nodes, args.topo)

    tr = Transport(args.nodes)
    entry = (args.entry or args.src or "A").upper()
    src = (args.src or "A").upper()
    dst = (args.dst or "D").upper()

    if args.text is not None:
        payload = {"text": args.text}
        wire = make_msg(args.mode, "data", src, dst, args.ttl, payload)
        tr.send_tcp(entry, wire)
        print(f"DATA enviado via {entry} {src}->{dst}")

    elif args.ping:
        payload = {"kind": "ping", "ts": time.time()}
        wire = make_msg(args.mode, "data", src, dst, args.ttl, payload)
        t0 = time.time()
        tr.send_tcp(entry, wire)
        t1 = time.time()
        print(f"PING enviado {src}->{dst}, envío took {1000*(t1-t0):.1f} ms (no RTT)")

    elif args.info is not None:
        payload = {"info": {"key": args.info}}
        wire = make_msg(args.mode, "info", src, dst, args.ttl, payload)
        tr.send_tcp(entry, wire)
        print(f"INFO enviado {src}->{dst}")

if __name__ == "__main__":
    main()
