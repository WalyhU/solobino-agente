# Cliente Solobino

Aplicación Electron para Windows y macOS. Captura el micrófono, muestra la mascota
y ejecuta las acciones locales solicitadas por el backend. El usuario instala un
solo paquete; Python y las herramientas van incluidos en el instalador.

Consulta [INSTALACION.md](../INSTALACION.md) para configurar el backend y descargar
los paquetes `.exe` y `.dmg` creados por GitHub Actions.

## Desarrollo

```sh
# Desde la raíz del repositorio: crea voice-backend/venv e instala
# desktop-ui/client-requirements.txt en ese entorno.
cd desktop-ui
npm ci
npm start
```

Al primer inicio, introduce la URL WebSocket del servicio y su token. La app
guarda el token cifrado con el almacén seguro del sistema. El menú de Solobino o
el clic derecho sobre la mascota abren la configuración después.
