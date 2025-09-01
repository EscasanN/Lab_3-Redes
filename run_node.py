import argparse, json, sys, time
from pathlib import Path
from node import RouterNode

def load_json(path: str):
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_names(path: str) -> dict[str, str]:
    data = load_json(path)
    cfg = data.get("config", data)
    out: dict[str, str] = {}
    for k, v in cfg.items():
        out[str(k)] = str(v)
    return out

def load_nodes(path: str) -> dict[str, tuple[str, int]]:
    data = load_json(path)
    cfg = data.get("config", data)
    out: dict[str, tuple[str, int]] = {}
    for k, v in cfg.items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            host, port = v[0], int(v[1])
        elif isinstance(v, dict) and "host" in v and "port" in v:
            host, port = v["host"], int(v["port"])
        else:
            raise ValueError(f"Invalid node format for {k}: {v}")
        out[str(k)] = (str(host), int(port))
    return out

def load_topo(path: str) -> dict:
    data = load_json(path)
    cfg = data.get("config", data)
    topo_out: dict[str, dict[str, float]] = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            topo_out[str(k)] = {str(n): float(c) for n, c in v.items()}
        elif isinstance(v, list):
            topo_out[str(k)] = {str(n): 1.0 for n in v}
        else:
            raise ValueError(f"Invalid topo for {k}: {v}")
    return topo_out

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", required=True, help="Node id in topology, e.g. A")
    ap.add_argument("--mode", default="flooding", choices=["dijkstra","flooding","lsr","dvr"])
    ap.add_argument("--transport", default="redis", choices=["tcp","redis"])
    ap.add_argument("--nodes", help="Path to nodes.json (TCP)")
    ap.add_argument("--names", help="Path to names-*.json (Redis)")
    ap.add_argument("--topo", required=True, help="Path to topo-*.json")
    ap.add_argument("--redis-host", default="lab3.redesuvg.cloud")
    ap.add_argument("--redis-port", type=int, default=6379)
    ap.add_argument("--redis-pwd", default="UVGRedis2025")
    ap.add_argument("--log", default="INFO")
    ap.add_argument("--hello-period", type=float, default=5.0)
    ap.add_argument("--dead-after", type=float, default=15.0)
    return ap.parse_args()

def main():
    args = parse_args()
    topo = load_topo(args.topo)
    if args.transport == "tcp":
        if not args.nodes:
            print("--nodes required for tcp", file=sys.stderr); sys.exit(2)
        nodes_map = load_nodes(args.nodes)
    else:
        if not args.names:
            print("--names required for redis", file=sys.stderr); sys.exit(2)
        nodes_map = load_names(args.names)
    try:
        rn = RouterNode(args.me, nodes_map, topo, mode=args.mode, log_level=args.log,
                        transport=args.transport, redis_host=args.redis_host, redis_port=args.redis_port,
                        redis_pwd=args.redis_pwd, hello_period=args.hello_period, dead_after=args.dead_after)
        rn.start()
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            rn.stop()
        except Exception:
            pass

if __name__ == "__main__":
    main()
