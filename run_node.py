import argparse
import json
import sys
import time
from pathlib import Path

from node import RouterNode

def load_json(path: str):
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_names(path: str) -> dict[str, str]:
    """Load Redis channels mapping: {"A": "channelA", "B": "channelB"}."""
    data = load_json(path)
    cfg = data.get("config", data)
    # Ensure values are strings
    out: dict[str, str] = {}
    for k, v in cfg.items():
        out[str(k)] = str(v)
    return out

def load_nodes(path: str) -> dict[str, tuple[str, int]]:
    """Load TCP host/port mapping: {"A": ["127.0.0.1", 5001], "B": ["127.0.0.1", 5002]}."""
    data = load_json(path)
    out: dict[str, tuple[str, int]] = {}
    for k, v in data.items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            host, port = v[0], int(v[1])
        elif isinstance(v, dict) and "host" in v and "port" in v:
            host, port = v["host"], int(v["port"])
        else:
            raise ValueError(f"Formato inválido para nodo {k}: {v}")
        out[str(k)] = (str(host), int(port))
    return out

def load_topo(path: str) -> dict:
    """Load topology adjacency dict; accepts {"type":"topo","config":{...}} or just {...}."""
    data = load_json(path)
    if isinstance(data, dict) and "config" in data and data.get("type") in (None, "topo"):
        return data["config"]
    return data

def parse_args():
    ap = argparse.ArgumentParser(description="Run a routing node (TCP or Redis).")
    ap.add_argument("--me", required=True, help="Node ID (e.g., A)")
    ap.add_argument("--mode", default="dvr",
                    choices=["dijkstra", "flooding", "lsr", "dvr"],
                    help="Routing mode")
    ap.add_argument("--transport", default="tcp", choices=["tcp", "redis"],
                    help="Transport to use (tcp sockets or redis pub/sub)")

    # Config files
    ap.add_argument("--nodes", help="Path to nodes.json (TCP host/port map)")
    ap.add_argument("--names", help="Path to names-*.txt (Redis channels map)")
    ap.add_argument("--topo", required=True, help="Path to topo-*.txt (topology)")

    # Redis options
    ap.add_argument("--redis-host", default="lab3.redesuvg.cloud")
    ap.add_argument("--redis-port", type=int, default=6379)
    ap.add_argument("--redis-pwd", default="UVGRedis2025")

    # Misc
    ap.add_argument("--log", default="INFO", help="Log level: ERROR|WARN|INFO|DEBUG")
    ap.add_argument("--hello-period", type=float, default=5.0,
                    help="HELLO period seconds")
    ap.add_argument("--dead-after", type=float, default=10.0,
                    help="Neighbor considered dead after N seconds without HELLO/ECHO")

    return ap.parse_args()

def main():
    args = parse_args()

    # Load topology
    try:
        topo = load_topo(args.topo)
    except Exception as e:
        print(f"[run_node] ERROR cargando topo: {e}", file=sys.stderr)
        sys.exit(2)

    # Choose nodes_map based on transport
    if args.transport == "redis":
        if not args.names:
            print("[run_node] ERROR: --names es obligatorio cuando --transport redis", file=sys.stderr)
            sys.exit(2)
        try:
            nodes_map = load_names(args.names)  # {"A": "redis.channel.A", ...}
        except Exception as e:
            print(f"[run_node] ERROR cargando names: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        if not args.nodes:
            print("[run_node] ERROR: --nodes es obligatorio cuando --transport tcp", file=sys.stderr)
            sys.exit(2)
        try:
            nodes_map = load_nodes(args.nodes)  # {"A": ("127.0.0.1", 5001), ...}
        except Exception as e:
            print(f"[run_node] ERROR cargando nodes: {e}", file=sys.stderr)
            sys.exit(2)

    # Validate presence of this node in map
    if args.me not in nodes_map:
        print(f"[run_node] ERROR: el id '{args.me}' no existe en el mapa ({'names' if args.transport=='redis' else 'nodes'})", file=sys.stderr)
        sys.exit(2)

    # Build and start node
    try:
        rn = RouterNode(
            node_id=args.me,
            nodes_map=nodes_map,
            topo=topo,
            mode=args.mode,
            log_level=args.log,
            hello_period=args.hello_period,
            dead_after=args.dead_after,
            transport=args.transport,
            redis_host=args.redis_host,
            redis_port=args.redis_port,
            redis_pwd=args.redis_pwd
        )
        rn.start()
        # Keep alive until CTRL+C
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[run_node] ERROR al iniciar el nodo: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            rn.stop()
        except Exception:
            pass

if __name__ == "__main__":
    main()
