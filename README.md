# Laboratorio 3

- Nelson Escalante
- Rodrigo Mansilla

## Dijkstra

### Como ejecutar
Para ejecutar localmente se debe hacer lo siguiente:

En 4 terminales distintas correr
```bash
python run_node.py --me A
python run_node.py --me B
python run_node.py --me C
python run_node.py --me D
```

En una terminal diferente se debe enviar el mensaje desde un nodo especifico hacia otro. Se utiliza el programa `sender.py` para esto.

Correr el programa en la terminal
```bash
python sender.py
```

En la terminal de cada nodo se vera el camino tomado por el mensaje, y en el nodo receptor se puede ver el mensaje enviado.

Para cambiar cualquier parametro del programa se pueden editar:
- `topo.json` para todo lo relacionado a la topologia del programa.
- `sender.py` para cambiar nodos de emision y recepcion, asi como el mensaje.