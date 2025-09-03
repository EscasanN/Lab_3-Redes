
# Lab_3-Redes

Sistema de enrutamiento entre nodos con soporte para **flooding**, **LSR (Link State Routing)**, **DVR (Distance Vector Routing)** y **Dijkstra**. 
Funciona con transporte **Redis** (publicación/suscripción por canales) y **TCP** (sockets), y estandariza el **formato de mensajes** para interoperar entre proyectos.

---

## Integrantes
- Nelson Escalante
- Rodrigo Mansilla

---

## Protocolo de mensajes (wire)

Todos los mensajes que circulan entre nodos siguen esta estructura común:

```json
{
  "type": "hello|message|info|echo",
  "from": "sec10.grupospares.nombreOrigen",
  "to": "sec10.grupospares.nombreDestino|"*"",
  "hops": 8,
  "headers": { "alg": "dijkstra|flooding|lsr|dvr" },
  "seq_num": 0,              // solo en 'info', cuando aplica
  "neighbors": ["sec10..."], // solo en 'info' (LSR), cuando aplica
  "payload": "texto"         // solo en 'message'
}
```

**Detalles**

- `type`: tipo del mensaje.  
  - `message`: datos de usuario.  
  - `hello` / `echo`: mantenimiento y detección de vecinos.  
  - `info`: control; por ejemplo, anuncios de estado de enlaces en LSR con `seq_num` y `neighbors`.
- `from` / `to`: identificadores wire (en **Redis** usan los nombres definidos en `names.json`). `to="*"` indica broadcast.
- `hops`: TTL decreciente (los reenvíos lo reducen en 1). Si llega a 0, el mensaje se descarta.
- `headers.alg`: algoritmo que origina/guía el envío (`flooding`, `lsr`, `dvr`, `dijkstra`).
- `payload`: contenido del mensaje cuando `type="message"`. Es **texto** provisto por `send_cli`.
- `seq_num` y `neighbors`: campos de control en `info` cuando el algoritmo lo requiere (por ejemplo, LSR).

**Ejemplos**

Mensaje de usuario:
```json
{
  "type": "message",
  "from": "sec10.grupo4.cor22982",
  "to": "sec10.grupo2.rodri",
  "hops": 8,
  "headers": { "alg": "flooding" },
  "payload": "hola mundo"
}
```

Anuncio de LSR:
```json
{
  "type": "info",
  "from": "sec10.grupo4.cor22982",
  "to": "*",
  "hops": 16,
  "headers": { "alg": "lsr" },
  "seq_num": 3,
  "neighbors": ["sec10.grupo2.rodri", "sec10.grupo2.alice"]
}
```

---

## Estructura del proyecto

```
Lab_3-Redes/
├─ config/
│  ├─ names.json         # Mapa {ID lógico -> nombre wire en Redis}
│  └─ topo-*.json        # Topologías (adyacencias y costos)
├─ dijkstra.py           # Cálculo de rutas de costo mínimo
├─ dvr.py                # Distance Vector Routing
├─ flooding.py           # Reenvío simple con deduplicación
├─ lsr.py                # Link State Routing (anuncios vía 'info')
├─ messages.py           # Serialización y normalización del wire
├─ node.py               # Lógica del router (Redis/TCP, loops, ruteo)
├─ run.py                # Ejecutor interactivo multi‑nodo (menú)
├─ run_node.py           # Ejecución de un nodo individual
├─ send_cli.py           # Cliente para enviar mensajes de usuario
└─ README.md
```

---

## Requisitos e instalación

- Python **3.10+** (recomendado 3.11).
- Dependencias:
  ```bash
  pip install redis
  ```

---

## Configuración

### 1) Nombres (Redis)
Definen los canales wire y los identificadores que verás en `from`/`to` al usar Redis.

`config/names.json`:
```json
{
  "type": "names",
  "config": {
    "A": "sec10.grupopares.man22611",
    "B": "sec10.grupopares.ill22376",
    "C": "sec10.grupopares.mej22596",
    "D": "sec10.grupopares.cux22648",
    "E": "sec10.grupopares.esc22046",
    "F": "sec10.grupopares.che22153",
    "G": "sec10.grupopares.cor22982"
  }
}
```

- Las claves (`A`, `B`, …) son **IDs lógicos** de nodos usados en CLI.
- Los valores son **nombres wire** (canales en Redis).

### 2) Topología
`config/topo-*.json` modela las adyacencias (con costos opcionales):

```json
{
  "A": { "B": 1 },
  "B": { "A": 1 }
}
```

> **TCP (opcional):** si usas `--transport tcp`, define `nodes.json` con `{"A":["127.0.0.1",5001], ...}`.

---

## Ejecución de nodos

Ejemplo con **Redis + LSR**:

```bash
python run_node.py   --me A   --mode lsr   --transport redis   --names config/names.json   --topo config/topo-simple.json   --redis-host lab3.redesuvg.cloud --redis-port 6379 --redis-pwd UVGRedis2025   --log INFO
```

Parámetros relevantes:
- `--me`: ID lógico del nodo (por ejemplo, `A`).
- `--mode`: `flooding` | `lsr` | `dvr` | `dijkstra`.
- `--transport`: `redis` o `tcp`.
- `--names` (Redis) / `--nodes` (TCP): mapeos de nombres/hosts.
- `--topo`: archivo de topología.
- `--log`: `DEBUG` | `INFO` | `WARN` | `ERROR`.

---

## Envío de mensajes de usuario

```bash
python send_cli.py   --transport redis   --names config/names.json   --entry A --src A --dst B   --mode flooding   --ttl 8   --text "hola mundo"
```

- `--entry`: nodo por el que **entra** el mensaje a la red.
- `--src` / `--dst`: IDs lógicos mapeados a nombres wire cuando `--transport redis`.
- `--mode`: rellena `headers.alg` en el wire.
- `--ttl`: valor inicial de `hops`.

---

## Algoritmos de enrutamiento

- **Flooding (`flooding.py`)**  
  Reenvío a vecinos con deduplicación. Evita reenviar al vecino desde el que llegó y reduce `hops`.
- **LSR (`lsr.py`)**  
  Difunde estado de enlaces mediante `type: "info"` (con `seq_num`, `neighbors`). Construye topología dinámica y tabla de ruteo.
- **DVR (`dvr.py`)**  
  Intercambio de vectores de distancia a través de mensajes `info` con `headers.alg="dvr"`.
- **Dijkstra (`dijkstra.py`)**  
  Cálculo de rutas de costo mínimo a partir de la topología vigente.

---

## Logs y monitoreo

- `FWD(flood) → X (...)`: reenvío por flooding.
- `RECV`: entrega local (cuando `to` coincide con el nodo o es `*`).
- `WARN`: eventos de red o parsing.
