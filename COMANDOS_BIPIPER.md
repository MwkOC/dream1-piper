## 2. Preparar el computador del robot

1. Conecta `can0` al brazo izquierdo y `can1` al derecho.
2. Comprueba el identificador USB (`bus-info`) de cada adaptador CAN:

   ```bash
   sudo ethtool -i can0 | grep bus-info
   sudo ethtool -i can1 | grep bus-info
   ```

   En esta configuración, el adaptador del brazo izquierdo usa `1-3.1.1:1.0` y el del brazo derecho usa `1-3.1.2:1.0`. Si los comandos muestran identificadores distintos, reemplázalos en los comandos de activación siguientes.

3. Activa ambas interfaces CAN a 1 Mbps con el script incluido en `piper_sdk`:

   ```bash
   sudo bash .venv/lib/python3.13/site-packages/piper_sdk/can_activate.sh \
     can0 1000000 1-3.1.1:1.0
   sudo bash .venv/lib/python3.13/site-packages/piper_sdk/can_activate.sh \
     can1 1000000 1-3.1.2:1.0
   ```

4. Verifica que ambas interfaces estén activas:

   ```bash
   ip link show can0 | grep state
   ip link show can1 | grep state
   ```
