# run.py
import os, sys, json, time, socket, subprocess, threading
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
PY = sys.executable  # usa el mismo intérprete que ejecuta run.py
RUN_NODE = str(ROOT / "run_node.py")
SEND_CLI = str(ROOT / "send_cli.py")  # opcional (no lo usamos ya)
NODES_JSON = str(ROOT / "config" / "nodes.json")
TOPO_JSON  = str(ROOT / "config" / "topo.json")
LOGS_DIR   = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# --------- util TCP ----------
def wait_port_open(host: str, port: int, timeout: float = 8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.6)
        try:
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            time.sleep(0.15)
    return False

def send_tcp(entry, wire: str, timeout: float = 2.5):
    host, port = entry
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.sendall(wire.encode("utf-8"))
    finally:
        try: s.close()
        except: pass

def make_msg(proto, mtype, from_id, to_id, ttl, payload, headers=None):
    return json.dumps({
        "proto": proto,
        "type": mtype,
        "from": from_id,
        "to": to_id,
        "ttl": int(ttl),
        "headers": headers or [],
        "payload": payload,
    }, ensure_ascii=False)

# --------- procesos de nodos ----------
class NodeProc:
    def __init__(self, node_id: str, mode: str, nodes_map: dict, log_level="INFO",
                 hello_period=5.0, dead_after=10.0):
        self.node_id = node_id
        self.mode = mode
        self.nodes_map = nodes_map
        self.log_level = log_level
        self.hello_period = hello_period
        self.dead_after = dead_after
        self.p: subprocess.Popen | None = None
        self.log_path = LOGS_DIR / f"{node_id}_{mode}.log"
        self.logfp = None

    def start(self):
        self.logfp = open(self.log_path, "a", buffering=1, encoding="utf-8")
        # encabezado de sesión
        self.logfp.write(f"\n----- start {datetime.now().isoformat(timespec='seconds')} -----\n")
        self.logfp.flush()

        cmd = [
            PY, "-u",  # unbuffered
            RUN_NODE,
            "--me", self.node_id,
            "--mode", self.mode,
            "--nodes", NODES_JSON,
            "--topo", TOPO_JSON,
            "--log-level", self.log_level,
            "--hello-period", str(self.hello_period),
            "--dead-after", str(self.dead_after),
        ]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        creationflags = 0
        if os.name == "nt":
            try:
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            except Exception:
                creationflags = 0

        self.p = subprocess.Popen(
            cmd, cwd=str(ROOT), env=env,
            stdout=self.logfp, stderr=self.logfp,
            text=True, creationflags=creationflags
        )
        return self.p

    def stop(self):
        if not self.p: return
        try:
            if os.name == "nt":
                # mata proceso por PID (sin matar la consola actual)
                subprocess.run(["taskkill", "/PID", str(self.p.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.p.terminate()
        except Exception:
            pass
        finally:
            try:
                self.p.wait(timeout=2.0)
            except Exception:
                pass
            self.p = None
            if self.logfp:
                self.logfp.write(f"----- stop {datetime.now().isoformat(timespec='seconds')} -----\n")
                try: self.logfp.flush()
                except: pass
                try: self.logfp.close()
                except: pass
                self.logfp = None

    def restart(self):
        self.stop()
        time.sleep(0.4)
        self.start()


# --------- helpers de menú ----------
def load_nodes_map():
    with open(NODES_JSON, "r", encoding="utf-8") as f:
        nodes_map = json.load(f)["config"]
        return {k: tuple(v) for k, v in nodes_map.items()}

def prompt(msg, default=None):
    s = input(msg).strip()
    if not s and default is not None:
        return default
    return s

def tail_file(path: Path, lines: int = 120):
    if not path.exists():
        print("(aún no existe el log)")
        return
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        data = f.readlines()
    print("".join(data[-lines:]), end="")
    print("----- fin -----")

def menu_tail(nodes: dict[str, NodeProc]):
    nid = prompt("¿Log de qué nodo (A/B/C/D)? ").upper()
    if nid not in nodes:
        print("Nodo inválido.")
        return
    print(f"\n----- tail {nid} ({nodes[nid].log_path.name}) -----")
    tail_file(nodes[nid].log_path)

def build_and_send(mode: str, nodes_map: dict, kind: str):
    """
    kind: 'data' | 'ping' | 'info'
    Siempre enviamos al puerto del nodo A (entrada al sistema).
    """
    A_entry = nodes_map["A"]
    if kind == "data":
        wire = make_msg(mode, "data", "A", "D", 12, {"kind": "message", "text": "hola desde run.py"})
    elif kind == "ping":
        # 10 pings
        for _ in range(10):
            wire = make_msg(mode, "data", "A", "D", 12, {"kind": "ping", "ts": time.time()})
            try: send_tcp(A_entry, wire)
            except Exception as e: print(f"[RUN] error ping: {e}")
            time.sleep(0.25)
        return
    elif kind == "info":
        wire = make_msg(mode, "info", "A", "*", 12, {"note": "broadcast desde run.py"})
    else:
        return

    try:
        send_tcp(A_entry, wire)
    except Exception as e:
        print(f"[RUN] error al enviar: {e}")

# --------- main ----------
def pick_mode():
    print("\nElige algoritmo:")
    print("  1) dijkstra")
    print("  2) flooding")
    print("  3) lsr")
    print("  4) dvr")
    opt = prompt("Opción [1-4]: ", "1")
    return {"1":"dijkstra","2":"flooding","3":"lsr","4":"dvr"}.get(opt, "dijkstra")

def boot_all(mode: str, log_level="INFO", hello_period=5.0, dead_after=10.0) -> dict[str, NodeProc]:
    nodes_map = load_nodes_map()
    print(f"\n[RUN] Levantando nodos en modo {mode} ...")
    procs: dict[str, NodeProc] = {}
    for nid in ["A","B","C","D"]:
        np = NodeProc(nid, mode, nodes_map, log_level=log_level,
                      hello_period=hello_period, dead_after=dead_after)
        np.start()
        procs[nid] = np

    # espera a que abran puertos
    for nid in ["A","B","C","D"]:
        host, port = nodes_map[nid]
        ok = wait_port_open(host, port, timeout=10.0)
        if ok:
            print(f"[RUN] {nid} OK en {host}:{port}")
        else:
            print(f"[RUN] {nid} no abrió el puerto {port} a tiempo (revisa logs).")
    print("[RUN] Listo. Menú habilitado.\n")
    return procs

def kill_all(procs: dict[str, NodeProc]):
    print("[RUN] Saliendo…")
    for nid in ["A","B","C","D"]:
        try: procs[nid].stop()
        except Exception: pass

def main_menu(mode: str):
    nodes_map = load_nodes_map()
    procs = boot_all(mode, log_level="INFO", hello_period=5.0, dead_after=10.0)

    while True:
        print("""
=== Menú ===
 1) Enviar DATA A→D (mensaje de prueba)
 2) Enviar PING lógico A→D (10 intentos)
 3) Pedir INFO genérica (A→*)
 4) Reiniciar un nodo
 5) Ver tail de log de un nodo
 0) Salir (mata nodos)
""".rstrip())
        opt = prompt("Elige: ")

        if opt == "1":
            build_and_send(mode, nodes_map, "data")
            print("[RUN] DATA enviado. Usa opción 5 para ver logs.")
        elif opt == "2":
            build_and_send(mode, nodes_map, "ping")
            print("[RUN] PINGs enviados. Usa opción 5 para ver logs.")
        elif opt == "3":
            build_and_send(mode, nodes_map, "info")
            print("[RUN] INFO enviado (broadcast).")
        elif opt == "4":
            nid = prompt("¿Qué nodo (A/B/C/D)? ").upper()
            if nid not in procs:
                print("Nodo inválido.")
                continue
            print(f"[RUN] Reiniciando {nid}… (ver logs en {procs[nid].log_path.name})")
            procs[nid].restart()
            host, port = nodes_map[nid]
            if wait_port_open(host, port, timeout=8.0):
                print(f"[RUN] {nid} OK en {host}:{port}")
        elif opt == "5":
            menu_tail(procs)
        elif opt == "0":
            kill_all(procs); break
        else:
            print("Opción inválida.")

if __name__ == "__main__":
    mode = pick_mode()
    try:
        main_menu(mode)
    except KeyboardInterrupt:
        print("\n[RUN] Cancelado por usuario.")
