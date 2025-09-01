# Laboratorio 3

- Nelson Escalante  
- Rodrigo Mansilla

## Requisitos
- Python 3.10+  
- Dependencias:  
  ```bash
  pip install redis
  ```

---

## Ejecución con `run.py` (fase 1 — TCP local)
1. Abre una terminal en el directorio del proyecto y corre:
   ```bash
   python run.py
   ```
2. Elige el algoritmo:
   - 1) dijkstra (estático, tabla fija por topología)
   - 2) flooding
   - 3) lsr (link state routing con flooding de LSP)
   - 4) dvr (distance vector routing)
3. Se levantarán los 4 nodos (A, B, C, D) en TCP local.
4. Usa el menú interactivo para pruebas rápidas:
   - 1) Enviar DATA A→D (mensaje de prueba)
   - 2) Enviar PING lógico A→D (10 intentos)
   - 3) Pedir INFO genérica (A→*)
   - 4) Reiniciar un nodo
   - 5) Ver tail de log de un nodo
   - 0) Salir (mata todos los nodos)

**Logs**  
- Guardados en `logs/` como `A_<modo>.log`, `B_<modo>.log`, etc.  
- La opción 5 muestra el final del log en consola.

**Archivos de configuración (fase 1)**  
- `config/nodes.json`: mapa `{"A": ["127.0.0.1", 5001], ...}`  
- `config/topo.json`: vecinos y costos.

---

## Ejecución con `run_node.py` (fase 2 — Redis)
Cada nodo se levanta individualmente, usando **Redis pub/sub** para comunicarse.

### Ejemplo: iniciar nodo A en DVR
```bash
python run_node.py --me A --mode flooding --transport redis --names config/names.json --topo config/topo.json
```

### Archivos de configuración (fase 2)
- `config/names.json`: mapea nodos a **canales Redis** (ej. `"A": "sec10.grupo3.nelson"`)  
- `config/topojson`: define vecinos y costos (igual que en fase 1)

El nuevo `run_node.py` selecciona:
- `--nodes` si usas `--transport tcp`
- `--names` si usas `--transport redis`

---

## Envío de mensajes con `send_cli.py`
Funciona tanto en TCP como en Redis.

### Directo
```bash
python send_cli.py --transport redis --names config/names.json --entry A --src A --dst B --mode flooding --ttl 8 --text "hola"
```