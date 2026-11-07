#!/usr/bin/env bash
# Monta la página en _site/: la carpeta site/ + los archivos descargables en dl/ (programa,
# instalador y update.json, que es lo que lee la comprobación de actualizaciones del programa).
set -euo pipefail
cd "$(dirname "$0")/.."
BASE_URL="https://enderhugin.github.io/faster-finder/dl"
VERSION="$(tr -d '[:space:]' < VERSION)"
PACK="$(sed -n 's/^APP_PACK[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' faster_finder.py | head -1)"
[ -n "$PACK" ] || { echo "faster_finder.py no define APP_PACK" >&2; exit 1; }
APPVER="$(sed -n 's/^APP_VERSION[[:space:]]*=[[:space:]]*"\([0-9.]*\)".*/\1/p' faster_finder.py | head -1)"
[ "$APPVER" = "$VERSION" ] || { echo "APP_VERSION ($APPVER) no coincide con VERSION ($VERSION)" >&2; exit 1; }
rm -rf _site
cp -r site _site
mkdir -p _site/dl
cp faster_finder.py _site/dl/faster_finder.py
echo -n "$VERSION" > _site/dl/VERSION
# el instalador se descarga como .cmd (con saltos de línea de Windows)
sed "s|__BASE_URL__|${BASE_URL}|g" installers/install-windows.cmd | sed 's/\r$//; s/$/\r/' > _site/dl/faster-finder-instalar.cmd
sed -i "s/__VERSION__/${VERSION}/g" _site/index.html
touch _site/.nojekyll
python3 - "_site" "$VERSION" <<'PYEOF'
import hashlib, json, os, re, sys
out, ver = sys.argv[1], sys.argv[2]
src = open('faster_finder.py', 'rb').read()
m = re.search(rb'^APP_PACK\s*=\s*(\d+)', src, re.M)
notes = open('NOVEDADES.md', encoding='utf-8').read()[:4000] if os.path.exists('NOVEDADES.md') else ''
with open(os.path.join(out, 'dl', 'update.json'), 'w', encoding='utf-8') as f:
    json.dump({'pack': int(m.group(1)), 'version': ver, 'notes': notes,
               'files': {'faster_finder.py': {'sha256': hashlib.sha256(src).hexdigest(), 'size': len(src)}}},
              f, ensure_ascii=False, indent=2)
PYEOF
echo "página montada en _site/ (v${VERSION}, pack ${PACK})"
