# Animaciones Chilemorron 🐾

Aplicación en Electron con una mascota animada interactiva.

## Funciones
- Animaciones: idle, react, thinking, music, cry, dance
- Reacciones al mouse

## Instalación
crear una carpeta
npm init -y
npm install electron --save-dev

Para iniciarlo escribir el siguiente comando en consola
npm start

Ojo
verificar que package.json se encuentre de la siguiente forma.
{
  "name": "mascota-asistente",
  "version": "1.0.0",
  "main": "main.js",
  "scripts": {
    "start": "electron ."
  },
  "devDependencies": {
    "electron": "^latest"
  }
}
