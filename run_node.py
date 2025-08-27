import argparse
import json
import time
from node import RouterNode

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Router Node – Fase 2 (TCP/Redis)")
    parser.add_argument("--me", required=True, help="ID del nodo local, p.ej. A")
    parser.add_argument("--mode", choices=["dijkstra", "flooding", "lsr", "dvr"], default="dijkstra")
    parser.add_argument("--nodes", default="config/nodes.json", help="ruta a nodes.json (TCP)")
    parser.add_argument("--names", default="config/names-sample.txt", help="ruta a names-*.txt (Redis)")
    parser.add_argument("--transport", choices=["tcp","redis"], default="tcp")
    parser.add_argument("--redis-host", default="lab3.redesuvg.cloud")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--redis-pwd", default="UVGRedis2025")
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
        transport=args.transport,
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_pwd=args.redis_pwd,
    )
    node.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        node.stop()
