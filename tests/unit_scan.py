# -*- coding: utf-8 -*-
"""Pruebas de la lógica de fechas, filtros y orden (sin ventana ni unidades de Windows) y un
arranque real de la interfaz bajo un display virtual, si lo hay."""
import os, sys, time, tempfile, shutil, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import faster_finder as ff

# parse_range
lo, hi = ff.parse_range("2026-01-01", "2026-01-31")
assert lo < hi
assert ff.parse_range("", "")  == (float("-inf"), float("inf"))
for bad in [("2026-02-01", "2026-01-01"), ("31/01/2026", ""), ("", "2026-13-01")]:
    try:
        ff.parse_range(*bad)
        raise AssertionError("debió rechazar %r" % (bad,))
    except ValueError:
        pass

# any_in_range: basta con que UN contenido caiga en el rango
vals = [10.0, 20.0, 30.0]
assert ff.any_in_range(vals, 15, 25)
assert not ff.any_in_range(vals, 31, 40)
assert not ff.any_in_range(vals, 0, 10)      # hi es exclusivo
assert ff.any_in_range(vals, 10, 11)         # lo es inclusivo
assert not ff.any_in_range([], 0, 100)

# passes_filter y sort_value sobre un registro
rec = ff.new_record("C:\\x\\DCIM")
assert ff.passes_filter(rec, None, 0, 1)           # sin filtro: siempre
assert not ff.passes_filter(rec, "c", 0, 1)        # sin datos aún: fuera del filtro
rec.update({"cts": [5.0, 50.0], "mts": [7.0], "size": 3, "ready": True})
assert ff.passes_filter(rec, "c", 40, 60)
assert not ff.passes_filter(rec, "m", 40, 60)
assert ff.sort_value(rec, "archivos") == 2
assert ff.sort_value(rec, "c_contenido") == 5.0
assert ff.sort_value(ff.new_record("x"), "tamano") is None

# folder_stats sobre un árbol real: fechas de contenido y tamaño
tmp = tempfile.mkdtemp(prefix="ff_scan_")
try:
    dcim = os.path.join(tmp, "DCIM", "100CAM")
    os.makedirs(dcim)
    a = os.path.join(dcim, "a.jpg"); b = os.path.join(tmp, "DCIM", "b.mp4")
    open(a, "wb").write(b"x" * 100); open(b, "wb").write(b"y" * 50)
    old = time.mktime((2020, 3, 1, 12, 0, 0, 0, 0, -1))
    os.utime(a, (old, old))
    st = ff.folder_stats(os.path.join(tmp, "DCIM"))
    assert len(st["mts"]) == 2 and st["size"] == 150
    assert st["mts"][0] == old, "la fecha más antigua de modificación debe ser la de a.jpg"
    assert ff.any_in_range(st["mts"], dt.datetime(2020, 1, 1).timestamp(), dt.datetime(2020, 12, 31).timestamp())
    assert not ff.any_in_range(st["mts"], dt.datetime(2030, 1, 1).timestamp(), dt.datetime(2031, 1, 1).timestamp())
    assert ff.fmt_span(st["mts"], True).startswith("2020-03-01")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# Arranque real de la interfaz si hay display (en Windows siempre lo hay)
display_ok = os.name == "nt" or bool(os.environ.get("DISPLAY"))
if display_ok:
    import tkinter as tk
    root = tk.Tk()
    app = ff.App(root)
    app.records["C:\\DCIM"] = ff.new_record("C:\\DCIM")
    app.records["C:\\DCIM"].update({"cts": [1.0], "mts": [2.0], "size": 10, "ready": True})
    app.refresh()
    assert len(app.tree.get_children()) == 1
    app.sort_by("archivos")
    app.field.set(ff.FIELD_MODIFIED)
    app.d_from.set("2099-01-01")
    app.refresh()
    assert len(app.tree.get_children()) == 0, "el filtro de fecha futura debe ocultarlo"
    root.after(300, root.destroy)
    root.mainloop()
    print("interfaz: arranque y filtro OK")
else:
    print("interfaz: sin display, se omite")

print("OK: pruebas de fechas, filtros y orden correctas")
