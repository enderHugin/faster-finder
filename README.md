# Faster Finder

Buscador recursivo de carpetas multimedia (DCIM, Cámara, Videos y variantes) en los discos locales de Windows o en una carpeta concreta.

Página del proyecto: <https://enderhugin.github.io/faster-finder/>

## Instalación rápida (Windows)
Descarga `faster-finder-instalar.cmd` desde la página del proyecto y ábrelo. No necesitas Python ni permisos de administrador: el instalador prepara su propio Python con `uv` y crea accesos directos. Fuente: [`installers/install-windows.cmd`](installers/install-windows.cmd).

## Uso
- Escribe una carpeta (o déjalo vacío para todos los discos) y pulsa **Iniciar**.
- Haz clic en una cabecera para ordenar; otra vez para invertir el orden.
- En **Filtrar por fecha del contenido** elige creación o modificación, un rango y pulsa Enter (o usa un atajo). Una carpeta aparece si al menos un archivo suyo cae en el rango.

## Uso a mano
Requiere Windows con Python 3.10+ y tkinter (no hay dependencias externas).

    python faster_finder.py

## Actualizaciones
- Al abrir comprueba en silencio si hay una versión nueva en la página del proyecto.
- Si la hay, pregunta si quieres instalarla. Guarda una copia de la versión anterior.
- La casilla «Actualizar automáticamente al abrir, sin preguntar» evita la pregunta.
- «BUSCAR ACTUALIZACIONES» comprueba en cualquier momento; «REVERTIR ACTUALIZACIÓN» vuelve a la copia anterior.
- Las actualizaciones solo se descargan de `https://enderhugin.github.io/faster-finder/dl/` y se comprueba su huella SHA-256 antes de instalarlas.

## Publicar una versión
1. Cambia el código en `faster_finder.py`.
2. Sube `APP_PACK` (un número mayor que el anterior) y pon la nueva fecha en `APP_VERSION` y en `VERSION`.
3. Añade la entrada en `NOVEDADES.md`.
4. Haz push a `main`: el workflow `Publicar la página` monta `_site/` y lo despliega en GitHub Pages (Settings → Pages → Source: GitHub Actions).

Para probar el montaje en local: `bash tools/build_site.sh`.

## Pruebas
    python tests/unit_update.py
    python tests/unit_scan.py      # fechas, filtros, orden y arranque de la interfaz (necesita display fuera de Windows)

## Licencia
MIT.
