# sender.py
import argparse, socket, json
from messages import make_msg

parser = argparse.ArgumentParser()
parser.add_argument("--src", default="A")
parser.add_argument("--dst", default="D")
parser.add_argument("--mode", choices=["dijkstra","flooding","lsr","dvr"], default="dijkstra")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=5001)  # puerto del nodo destino inicial
parser.add_argument("--text", default="hola mundo")
args = parser.parse_args()

wire = make_msg(args.mode, "data", args.src, args.dst, 12, {"text": args.text})
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((args.host, args.port))
s.sendall(wire.encode("utf-8"))
s.close()
