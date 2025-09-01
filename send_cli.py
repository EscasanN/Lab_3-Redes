import argparse, json, socket, time
try:
    import redis
except Exception:
    redis = None
from messages import make_msg

class Transport:
    def __init__(self, transport: str, nodes_path: str = None, names_path: str = None,
                 redis_host: str = None, redis_port: int = None, redis_pwd: str = None):
        self.transport = transport
        self.nodes = {}
        self.channels = {}
        self.r = None
        if transport == 'tcp':
            with open(nodes_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)['config']
            self.nodes = {k: (v[0], int(v[1])) for k, v in cfg.items()}
        else:
            if redis is None:
                raise RuntimeError('Install redis to use transport=redis')
            with open(names_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)['config']
            self.channels = {k: str(v) for k, v in cfg.items()}
            self.r = redis.Redis(host=redis_host or 'lab3.redesuvg.cloud',
                                 port=int(redis_port or 6379),
                                 password=redis_pwd or 'UVGRedis2025')

    def send_tcp(self, entry_node: str, wire: str, timeout=1.2):
        host, port = self.nodes[entry_node]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(wire.encode('utf-8'))
        s.close()

    def send_redis(self, entry_node: str, wire: str):
        ch = self.channels[entry_node]
        self.r.publish(ch, wire)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--transport', choices=['tcp','redis'], default='redis')
    ap.add_argument('--nodes')
    ap.add_argument('--names')
    ap.add_argument('--redis-host', default='lab3.redesuvg.cloud')
    ap.add_argument('--redis-port', type=int, default=6379)
    ap.add_argument('--redis-pwd', default='UVGRedis2025')
    ap.add_argument('--entry', default='A')
    ap.add_argument('--src', default='A')
    ap.add_argument('--dst', default='B')
    ap.add_argument('--mode', choices=['dijkstra','flooding','lsr','dvr'], default='flooding')
    ap.add_argument('--ttl', type=int, default=8)
    ap.add_argument('--text', default='hola mundo')
    args = ap.parse_args()

    if args.transport == 'tcp' and not args.nodes:
        ap.error('--nodes required for tcp')
    if args.transport == 'redis' and not args.names:
        ap.error('--names required for redis')

    tr = Transport(args.transport, nodes_path=args.nodes, names_path=args.names,
                   redis_host=args.redis_host, redis_port=args.redis_port, redis_pwd=args.redis_pwd)

    payload = {'text': args.text}
    wire = make_msg(args.mode, 'data', args.src, args.dst, args.ttl, payload)
    if args.transport == 'tcp':
        tr.send_tcp(args.entry, wire)
    else:
        tr.send_redis(args.entry, wire)
    print('Sent.')

if __name__ == '__main__':
    main()
