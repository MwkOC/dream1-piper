# Vivaldi MCP para el setup de Dream Labs

Integración local basada en `chrome-devtools-mcp` 1.12.0, el servidor del proyecto
Chrome DevTools. El lanzador abre Vivaldi y conecta el servidor por CDP local;
Codex se comunica con él mediante stdio. No es un servidor de control del robot.

## Instalación y registro

Requisitos: Linux, Node.js compatible con el paquete (aquí se probó Node 24.21.0),
Vivaldi instalado y una sesión gráfica activa.

```bash
cd /home/mwkoc/GITHUB/mu-robotics/dream-1
npm ci --prefix tools/vivaldi-mcp
codex mcp add vivaldi --env DISPLAY=:0 -- \
  /home/mwkoc/.nvm/versions/node/v24.21.0/bin/node \
  /home/mwkoc/GITHUB/mu-robotics/dream-1/tools/vivaldi-mcp/run.mjs
codex mcp get vivaldi
```

El servidor quedó registrado en la configuración local de Codex. En otra máquina
hay que ajustar las rutas de Node y del checkout, y usar el `DISPLAY` de esa sesión.
Para registrar cambios en el catálogo de herramientas, reiniciar la conexión MCP
desde la aplicación/cliente si todavía no aparece `vivaldi`.

Si el cliente no hereda la sesión gráfica, pasar también `XDG_RUNTIME_DIR` y
`DBUS_SESSION_BUS_ADDRESS` con los valores locales correspondientes. En este
equipo son `/run/user/1000` y `unix:path=/run/user/1000/bus`.

El lanzador busca una instalación convencional o el ejecutable Snap oficial.
`VIVALDI_BINARY` permite indicar otra ruta. Para Snap, el perfil dedicado vive en
`~/snap/vivaldi/common/dream1-piper-mcp/profile`; en una instalación convencional,
en `${XDG_CACHE_HOME:-~/.cache}/dream1-piper/vivaldi-mcp/profile`.

## Comportamiento

- Usa un perfil dedicado persistente. El inicio de sesión en Dream Labs se hace
  en esa ventana y permanece en ese perfil; no importa cookies ni credenciales
  del Vivaldi personal.
- CDP escucha en `127.0.0.1` y un puerto dinámico. No publica un servicio de
  navegador en la red ni desactiva el sandbox o la verificación TLS.
- El servidor incluye herramientas para navegar, capturar el árbol accesible,
  escribir, pulsar botones y trabajar con formularios. Se verificaron 32
  herramientas anunciadas por esta versión.
- Se desactivaron las estadísticas de uso del servidor, las consultas de CrUX y
  sus comprobaciones automáticas de actualización. El navegador conserva su
  comportamiento normal de red.
- Una sola conexión puede abrir este perfil a la vez. Una segunda instancia
  informa que el perfil ya está en uso; cerrar la conexión anterior antes de
  relanzarlo. Los locks de procesos ya terminados los recupera el propio navegador.
- Al detener el servidor, el lanzador termina su instancia dedicada de Vivaldi.
  No termina el navegador personal que ya estaba abierto.

## Verificación

Con la conexión interactiva cerrada, ejecutar:

```bash
npm test --prefix tools/vivaldi-mcp
```

La prueba abre Vivaldi real con su sandbox y una página sintética `data:`. Hace
handshake MCP, lista herramientas, abre una pestaña, toma un snapshot, pulsa un
input, escribe `Piper`, pulsa un botón y comprueba `OK Piper` en el resultado.
No entra en cuentas ni usa cámaras, CAN o Dream API. Cierra su instancia al terminar.

En esta versión de Vivaldi, `fill` informó éxito sin actualizar el campo durante
la prueba. La secuencia comprobada es `click` → `type_text` → snapshot. Usar los
IDs de página y elementos del snapshot observado, sin asumirlos por posición.

También se abrió mediante MCP la guía real
`https://platform.dreamlabs.ai/docs/drivers/#the-driver-template`. La plataforma
redirigió al login de Dream Labs; se comprobó el formulario, pero no se inició
sesión ni se registró un robot.

## Límites para el trabajo con Piper

Este MCP permite editar el setup web después del login. No mide TCP, no confirma
qué cable corresponde a cada brazo y no caracteriza la caída al quitar torque.
El registro del embodiment y las acciones de control se deben distinguir de las
pruebas de navegación. No iniciar inferencia facturable ni ejecutar los pasos
motorizados únicamente para verificar que funciona el navegador.

La compatibilidad con Vivaldi se comprobó localmente (Snap 8.3.4191.30). El
servidor upstream da soporte oficial a Chrome; otras versiones de Vivaldi deben
volver a probarse. No se modificó el entorno Python del robot.

Fuentes: [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)
y [configuración MCP de Codex](https://developers.openai.com/codex/mcp).
