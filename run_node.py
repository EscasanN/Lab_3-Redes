# run_node.py
import argparse
import json
import time
from node import RouterNode

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Router Node – Fase 0")
    parser.add_argument("--me", required=True, help="ID del nodo local, p.ej. A")
    parser.add_argument("--mode", choices=["dijkstra", "flooding", "lsr", "dvr"], default="dijkstra")
    parser.add_argument("--nodes", default="config/nodes.json", help="ruta a nodes.json")
    parser.add_argument("--topo", default="config/topo.json", help="ruta a topo.json")
    args = parser.parse_args()

    with open(args.nodes, "r", encoding="utf-8") as f:
        nodes_map = json.load(f)["config"]  # {"A": ["127.0.0.1", 5001], ...}
        nodes_map = {k: tuple(v) for k, v in nodes_map.items()}

    with open(args.topo, "r", encoding="utf-8") as f:
        topo = json.load(f)["config"]       # {"A": {"B":1, "C":2}, ...}

    node = RouterNode(args.me, nodes_map, topo, mode=args.mode)
    node.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        node.stop()
