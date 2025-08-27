# send_cli.py
import argparse
import json
import socket
import time
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
                raise RuntimeError('Debe instalar redis-py para usar transport redis')
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

def interactive_cli(transport: str, nodes_json: str, topo_json: str,
                    names_path: str, redis_host: str, redis_port: int, redis_pwd: str):
    tr = Transport(transport, nodes_json, names_path, redis_host, redis_port, redis_pwd)
    print('\n== Consola de pruebas ==')
    print('Formatos soportados: DATA/MESSAGE, DATA/PING, INFO genérico (payload libre)')
    while True:
        print('\n1) DATA/MESSAGE')
        print('2) DATA/PING')
        print('3) INFO')
        print('0) Salir')
        opt = input('Elige: ').strip()
        if opt == '0':
            return
        entry = input('Nodo por el que se inyecta (A/B/C/D): ').strip().upper() or 'A'
        src = input('Fuente (A/B/C/D): ').strip().upper() or 'A'
        dst = input('Destino (A/B/C/D/*): ').strip().upper() or 'D'
        mode = input('Modo (dijkstra/flooding/lsr/dvr) [dvr]: ').strip() or 'dvr'
        ttl = int(input('TTL [12]: ').strip() or '12')
        if opt == '1':
            text = input('Texto: ').strip() or 'hola'
            payload = {'text': text}
            wire = make_msg(mode, 'data', src, dst, ttl, payload)
        elif opt == '2':
            payload = {'kind': 'ping', 'ts': time.time()}
            wire = make_msg(mode, 'data', src, dst, ttl, payload)
        elif opt == '3':
            key = input('INFO key: ').strip() or 'prueba'
            payload = {'info': {'key': key}}
            wire = make_msg(mode, 'info', src, dst, ttl, payload)
        else:
            print('Opción inválida.'); continue
        if tr.transport == 'tcp':
            tr.send_tcp(entry, wire)
        else:
            tr.send_redis(entry, wire)
        print('Enviado.')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', required=True)
    ap.add_argument('--topo', required=True)
    ap.add_argument('--names', default='config/names-sample.txt')
    ap.add_argument('--transport', choices=['tcp','redis'], default='tcp')
    ap.add_argument('--redis-host', default='lab3.redesuvg.cloud')
    ap.add_argument('--redis-port', type=int, default=6379)
    ap.add_argument('--redis-pwd', default='UVGRedis2025')
    ap.add_argument('--entry', default=None, help='Nodo por el que se inyecta el mensaje (A/B/C/D)')
    ap.add_argument('--src', default=None)
    ap.add_argument('--dst', default=None)
    ap.add_argument('--mode', choices=['dijkstra','flooding','lsr','dvr'], default='dvr')
    ap.add_argument('--ttl', type=int, default=12)
    ap.add_argument('--text', default=None)
    ap.add_argument('--ping', action='store_true')
    ap.add_argument('--info', default=None)
    args = ap.parse_args()

    if not any([args.text, args.ping, args.info]):
        return interactive_cli(args.transport, args.nodes, args.topo, args.names, args.redis_host, args.redis_port, args.redis_pwd)

    entry = (args.entry or args.src or 'A').upper()
    src = (args.src or 'A').upper()
    dst = (args.dst or 'D').upper()
    tr = Transport(args.transport, args.nodes, args.names, args.redis_host, args.redis_port, args.redis_pwd)

    if args.text is not None:
        payload = {'text': args.text}
        wire = make_msg(args.mode, 'data', src, dst, args.ttl, payload)
        t0 = time.time()
        (tr.send_tcp(entry, wire) if tr.transport=='tcp' else tr.send_redis(entry, wire))
        t1 = time.time()
        print(f'DATA enviado {src}->{dst}, envío took {1000*(t1-t0):.1f} ms')
    elif args.ping:
        payload = {'kind': 'ping', 'ts': time.time()}
        wire = make_msg(args.mode, 'data', src, dst, args.ttl, payload)
        t0 = time.time()
        (tr.send_tcp(entry, wire) if tr.transport=='tcp' else tr.send_redis(entry, wire))
        t1 = time.time()
        print(f'PING enviado {src}->{dst}, envío took {1000*(t1-t0):.1f} ms (no RTT)')
    elif args.info is not None:
        payload = {'info': {'key': args.info}}
        wire = make_msg(args.mode, 'info', src, dst, args.ttl, payload)
        (tr.send_tcp(entry, wire) if tr.transport=='tcp' else tr.send_redis(entry, wire))
        print(f'INFO enviado {src}->{dst}')

if __name__ == '__main__':
    main()
