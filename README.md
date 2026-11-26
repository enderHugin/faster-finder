# Faster Finder

Buscador recursivo de carpetas multimedia (DCIM, Cámara, Videos y variantes) en los discos locales de Windows o en una carpeta concreta.

Página del proyecto: <https://enderhugin.github.io/faster-finder/>

## Instalación rápida (Windows)
Descarga el instalador desde la página del proyecto y ábrelo; la página te da el de tu idioma (`faster-finder-instalar.cmd` en español, `-en` o `-ca`). No necesitas Python ni permisos de administrador: el instalador prepara su propio Python con `uv` y crea accesos directos. Lo monta [py-installer](https://github.com/enderHugin/py-installer) a partir de [`py-installer.toml`](py-installer.toml).

## Idiomas
Español, inglés y catalán, con [lang-kit](https://github.com/enderHugin/lang-kit). Los textos del programa están en `lang/<idioma>.json` y los de la página, en `site/lang/`. El idioma se cambia con el botón **Idioma / Language**. Al instalar se elige el del instalador descargado.

## Uso
- Escribe una carpeta (o déjalo vacío para todos los discos) y pulsa **Iniciar**.
- Haz clic en una cabecera para ordenar; otra vez para invertir el orden.
- En **Filtrar por fecha del contenido** elige creación o modificación, un rango y pulsa Enter (o usa un atajo). Una carpeta aparece si al menos un archivo suyo cae en el rango.

## Uso a mano
Requiere Windows con Python 3.10+ y tkinter (no hay dependencias externas). Los textos salen de `lang/`, con la copia de lang-kit de `vendor/`.

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
4. Haz push a `main`: el workflow `Probar y publicar` prueba, instala de verdad en Windows y, con py-installer, monta `_site/` (página, instaladores en cada idioma y `update.json`) y lo despliega en GitHub Pages.

Para probar el montaje en local: `python3 ../py-installer/pyi.py build --app . --base http://127.0.0.1:8765 --out _site`.

## Pruebas
    python tests/unit_update.py
    python tests/unit_scan.py      # fechas, filtros, orden y arranque de la interfaz (necesita display fuera de Windows)

## Licencia
MIT.
