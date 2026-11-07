# -*- coding: utf-8 -*-
"""Pruebas del sistema de actualizaciones: levanta un servidor HTTP local que hace de la web de
publicación y ejercita update_check / update_apply / update_rollback contra él, sin red real
ni ventana."""
import sys, os, json, hashlib, shutil, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import faster_finder as ff

WORK = tempfile.mkdtemp(prefix="ff_update_test_")
DL = os.path.join(WORK, "dl")
os.makedirs(DL)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        local = os.path.join(DL, path.split("/dl/", 1)[-1]) if "/dl/" in path else ""
        if local and os.path.isfile(local):
            data = open(local, "rb").read()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()


srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]

# Programa "instalado" (versión 1) y una versión publicada (versión 2)
APP = os.path.join(WORK, "faster_finder.py")
shutil.copyfile(os.path.join(ROOT, "faster_finder.py"), APP)
with open(APP, encoding="utf-8") as f:
    OLD = f.read()
CUR = ff.APP_PACK
NEW = OLD.replace("APP_PACK = %d" % CUR, "APP_PACK = %d" % (CUR + 1), 1) + "\n# parche de prueba\n"
assert "APP_PACK = %d" % (CUR + 1) in NEW

ff.UPDATE_BASE = "http://127.0.0.1:%d/dl/" % PORT
ff.APP_FILE = APP
ff.APP_PACK = CUR
ff.UPDATE_STATE = os.path.join(WORK, "actualizacion.json")
ff.UPDATE_BACKUPS = os.path.join(WORK, "backups_programa")
ff._UPDATE_ST = {}


def publish(content, pack, sha=None):
    data = content.encode("utf-8")
    with open(os.path.join(DL, "faster_finder.py"), "wb") as f:
        f.write(data)
    info = {"pack": pack, "version": "9999", "notes": "prueba",
            "files": {"faster_finder.py": {"sha256": sha or hashlib.sha256(data).hexdigest(), "size": len(data)}}}
    with open(os.path.join(DL, "update.json"), "w", encoding="utf-8") as f:
        json.dump(info, f)
    return info


# 1) misma versión -> "same"
publish(OLD, CUR)
assert ff.update_check()["state"] == "same", "debería estar al día"

# 2) versión nueva publicada -> "newer", se aplica y guarda copia
info = publish(NEW, CUR + 1)
res = ff.update_check()
assert res["ok"] and res["state"] == "newer", res
ff.update_apply(res["info"])
with open(APP, encoding="utf-8") as f:
    assert f.read() == NEW, "el archivo no se sustituyó"
assert ff.update_backup_available(), "no se guardó la copia"

# 3) rollback -> vuelve a la versión anterior
ff.update_rollback()
with open(APP, encoding="utf-8") as f:
    assert f.read() == OLD, "el rollback no restauró la versión anterior"

# 4) huella que no coincide -> se cancela sin tocar el archivo
publish(NEW, CUR + 1, sha="0" * 64)
res = ff.update_check()
assert res["state"] == "newer"
try:
    ff.update_apply(res["info"])
    raise AssertionError("debió rechazar la huella incorrecta")
except ValueError:
    pass
with open(APP, encoding="utf-8") as f:
    assert f.read() == OLD, "se tocó el archivo pese a la huella incorrecta"

# 5) sin servidor -> error controlado, no excepción
ff.UPDATE_BASE = "http://127.0.0.1:1/dl/"
assert ff.update_check()["ok"] is False

srv.shutdown()
shutil.rmtree(WORK, ignore_errors=True)
print("OK: pruebas de actualización correctas")
