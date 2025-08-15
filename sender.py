from messages import make_msg
import socket, json
host, port = "127.0.0.1", 5001  # A
wire = make_msg("dijkstra", "data", "A", "D", 8, {"text":"hola mundo"})
s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.connect((host,port)); s.sendall(wire.encode()); s.close()