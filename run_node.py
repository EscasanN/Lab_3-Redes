import argparse
import json
import time
from node import RouterNode

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Router Node – Fase 0/1")
    parser.add_argument("--me", required=True, help="ID del nodo local, p.ej. A")
    parser.add_argument("--mode", choices=["dijkstra", "flooding", "lsr", "dvr"], default="dijkstra")
    parser.add_argument("--nodes", default="config/nodes.json", help="ruta a nodes.json")
    parser.add_argument("--topo", default="config/topo.json", help="ruta a topo.json")
    parser.add_argument("--log-level", choices=["ERROR","WARN","INFO","DEBUG"], default="INFO")
    parser.add_argument("--hello-period", type=float, default=5.0)
    parser.add_argument("--dead-after", type=float, default=10.0)
    args = parser.parse_args()

    with open(args.nodes, "r", encoding="utf-8") as f:
        nodes_map = json.load(f)["config"]
        nodes_map = {k: tuple(v) for k, v in nodes_map.items()}

    with open(args.topo, "r", encoding="utf-8") as f:
        topo = json.load(f)["config"]

    node = RouterNode(
        args.me, nodes_map, topo, mode=args.mode,
        log_level=args.log_level,
        hello_period=args.hello_period,
        dead_after=args.dead_after,
    )
    node.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        node.stop()
