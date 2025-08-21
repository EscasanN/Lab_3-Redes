# Laboratorio 3

- Nelson Escalante
- Rodrigo Mansilla

## Ejecución con `run.py`

### Requisitos
- Python 3.10+ (usa el mismo intérprete que ejecuta `run.py`).

### Cómo ejecutar
1) Abrir una terminal en el directorio del proyecto y correr:
```bash
python run.py
```
2) Elegir el algoritmo cuando se te pregunte:
   - 1) dijkstra
   - 2) flooding
   - 3) lsr
   - 4) dvr
3) Se levantarán los 4 nodos (A, B, C, D). Cuando estén listos verás el mensaje "[RUN] Listo. Menú habilitado.".
4) Usa el menú interactivo para pruebas rápidas:
   - 1) Enviar DATA A→D (mensaje de prueba)
   - 2) Enviar PING lógico A→D (10 intentos)
   - 3) Pedir INFO genérica (A→*)
   - 4) Reiniciar un nodo (A/B/C/D)
   - 5) Ver tail de log de un nodo
   - 0) Salir (mata todos los nodos)

### Logs
- La salida de cada nodo se guarda en `logs/` con el patrón `A_<modo>.log`, `B_<modo>.log`, etc.
- Opción 5 del menú muestra el final del log del nodo seleccionado.

### Configuración
- `config/nodes.json`: mapea cada nodo a (host, puerto). Ej.: `{"A": ["127.0.0.1", 5001], ...}`
- `config/topo.json`: define los vecinos y costos de la topología inicial.
- Ajusta estos archivos para cambiar puertos, enlaces o costos.

### Envío manual (opcional) con `send_cli.py`
- Interactivo:
```bash
python send_cli.py --nodes config/nodes.json --topo config/topo.json
```
- Envío directo de un mensaje de texto (ejemplo en modo DVR):
```bash
python send_cli.py --nodes config/nodes.json --topo config/topo.json \
  --mode dvr --src A --dst D --text "hola"
```
- PING lógico:
```bash
python send_cli.py --nodes config/nodes.json --topo config/topo.json \
  --mode dvr --src A --dst D --ping
```
- INFO genérico:
```bash
python send_cli.py --nodes config/nodes.json --topo config/topo.json \
  --mode dvr --src A --dst * --info prueba
```

### Notas
- Para detener todo, usa la opción 0 del menú de `run.py`.
- En Windows, los procesos se gestionan con `taskkill` automáticamente al salir.