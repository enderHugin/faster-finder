"""Faster Finder: buscador recursivo de carpetas multimedia (DCIM, Cámara, Videos...).

Busca carpetas con esos nombres en los discos locales (o en una carpeta elegida), muestra sus
fechas, permite ordenar por ellas y filtrar por fecha de creación o modificación de su contenido.

Un único archivo. Se actualiza solo desde la web del proyecto (ver UPDATE_BASE).
"""
import os
import re
import sys
import ssl
import json
import time
import queue
import ctypes
import bisect
import shutil
import hashlib
import threading
import subprocess
import urllib.request
import datetime as dt
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------------------------------------------------------------------------
# Versión y actualizaciones. APP_VERSION debe coincidir con el archivo VERSION.
# APP_PACK sube en cada versión que cambie el programa: es lo que compara la actualización.
# ---------------------------------------------------------------------------
APP_NAME = "Faster Finder"
APP_VERSION = "2026.11.07"
APP_PACK = 2
UPDATE_BASE = "https://enderhugin.github.io/faster-finder/dl/"
APP_FILE = os.path.abspath(__file__)
HERE = os.path.dirname(APP_FILE)
UPDATE_STATE = os.path.join(HERE, "actualizacion.json")
UPDATE_BACKUPS = os.path.join(HERE, "backups_programa")
UPDATE_FILE = "faster_finder.py"

NAMES = {
    "dcim", "camara", "cámara", "camera",
    "video", "videos", "vídeo"
}

# Campo de fecha por el que se filtra (fecha del contenido) y su etiqueta en pantalla
FIELD_NONE = "Sin filtro"
FIELD_CREATED = "Creación del contenido"
FIELD_MODIFIED = "Modificación del contenido"
FIELD_CODES = {FIELD_NONE: None, FIELD_CREATED: "c", FIELD_MODIFIED: "m"}

# (id, cabecera, anchura, alineación, es_fecha)
COLUMNS = [
    ("carpeta", "Carpeta", 380, "w", False),
    ("creada", "Creada", 135, "w", True),
    ("modificada", "Modificada", 135, "w", True),
    ("archivos", "Archivos", 70, "e", False),
    ("tamano", "Tamaño", 85, "e", False),
    ("c_contenido", "Contenido: creado (desde → hasta)", 265, "w", True),
    ("m_contenido", "Contenido: modificado (desde → hasta)", 265, "w", True),
]
PRESET_DAYS = {"Últimos 7 días": 7, "Últimos 30 días": 30, "Últimos 365 días": 365}

events = queue.Queue()      # hacia la interfaz: found / stats / done / update_*
tasks = queue.Queue()       # trabajo del escáner
stats_q = queue.Queue()     # carpetas pendientes de calcular fechas de contenido
stop_event = threading.Event()
workers = []
running = False


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------

def local_drives():
    drives = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()

    for i in range(26):
        if mask & (1 << i):
            drive = chr(65 + i) + ":\\"
            if ctypes.windll.kernel32.GetDriveTypeW(
                drive
            ) == 3:
                drives.append(drive)

    return drives


def _is_link(stat):
    """Junctions y enlaces de Windows (atributo de punto de reanálisis)."""
    return bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def worker():
    while True:
        folder = tasks.get()

        try:
            if folder is None:
                return

            if stop_event.is_set():
                continue

            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if stop_event.is_set():
                            break

                        try:
                            if not entry.is_dir(
                                follow_symlinks=False
                            ):
                                continue

                            if _is_link(entry.stat(follow_symlinks=False)):
                                continue

                            path = entry.path

                            if entry.name.casefold() in NAMES:
                                events.put(("found", path))
                                stats_q.put(path)

                            tasks.put(path)

                        except (OSError, PermissionError):
                            continue

            except (OSError, PermissionError):
                pass

        finally:
            tasks.task_done()


def scan_coordinator(roots, count):
    global workers

    for root in roots:
        if os.path.isdir(root):
            if os.path.basename(os.path.normpath(
                root
            )).casefold() in NAMES:
                events.put(("found", root))
                stats_q.put(root)

            tasks.put(root)

    workers = [
        threading.Thread(target=worker, daemon=True)
        for _ in range(count)
    ]

    for thread in workers:
        thread.start()

    tasks.join()

    for _ in workers:
        tasks.put(None)

    tasks.join()

    for thread in workers:
        thread.join()

    events.put(("done", None))


def folder_stats(path):
    """Fechas y tamaño de una carpeta y de todo su contenido. Creación = st_ctime (en Windows es
    la fecha de creación), modificación = st_mtime. Las listas van ordenadas para poder buscar
    en ellas por rango."""
    st = os.stat(path)
    cts, mts, size = [], [], 0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not _is_link(entry.stat(follow_symlinks=False)):
                                pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            s = entry.stat(follow_symlinks=False)
                            cts.append(s.st_ctime)
                            mts.append(s.st_mtime)
                            size += s.st_size
                    except OSError:
                        continue
        except OSError:
            continue
    cts.sort()
    mts.sort()
    return {"created": st.st_ctime, "modified": st.st_mtime,
            "cts": cts, "mts": mts, "size": size}


def stats_worker():
    while True:
        path = stats_q.get()
        try:
            try:
                data = folder_stats(path)
            except OSError:
                data = None
            events.put(("stats", (path, data)))
        finally:
            stats_q.task_done()


def parse_range(desde, hasta):
    """(lo, hi) en marcas de tiempo, con hi excluido. Fechas en formato AAAA-MM-DD; vacío = sin
    límite. Lanza ValueError si el formato no es válido o el rango está al revés."""
    lo, hi = float("-inf"), float("inf")
    if desde.strip():
        lo = dt.datetime.strptime(desde.strip(), "%Y-%m-%d").timestamp()
    if hasta.strip():
        hi = (dt.datetime.strptime(hasta.strip(), "%Y-%m-%d") + dt.timedelta(days=1)).timestamp()
    if lo >= hi:
        raise ValueError("la fecha «desde» es posterior a «hasta»")
    return lo, hi


def any_in_range(sorted_values, lo, hi):
    """¿Hay algún valor en [lo, hi)? Con la lista ordenada, búsqueda binaria."""
    i = bisect.bisect_left(sorted_values, lo)
    return i < len(sorted_values) and sorted_values[i] < hi


def new_record(path):
    return {"path": path, "created": None, "modified": None,
            "cts": [], "mts": [], "size": 0, "ready": False}


def open_path(path):
    if hasattr(os, "startfile"):
        os.startfile(path)
    else:  # solo para pruebas fuera de Windows
        subprocess.Popen(["xdg-open", path])


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------

def fmt_date(ts):
    if ts is None:
        return "—"
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def fmt_day(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def fmt_span(values, ready):
    if not ready:
        return "calculando…"
    if not values:
        return "—"
    first, last = fmt_day(values[0]), fmt_day(values[-1])
    return first if first == last else "%s → %s" % (first, last)


def row_values(rec):
    ready = rec["ready"]
    return (
        rec["path"],
        fmt_date(rec["created"]),
        fmt_date(rec["modified"]),
        len(rec["cts"]) if ready else "…",
        fmt_size(rec["size"]) if ready else "…",
        fmt_span(rec["cts"], ready),
        fmt_span(rec["mts"], ready),
    )


def sort_value(rec, col):
    if col == "carpeta":
        return rec["path"].casefold()
    if col == "creada":
        return rec["created"]
    if col == "modificada":
        return rec["modified"]
    if not rec["ready"]:
        return None
    if col == "archivos":
        return len(rec["cts"])
    if col == "tamano":
        return rec["size"]
    if col == "c_contenido":
        return rec["cts"][0] if rec["cts"] else None
    if col == "m_contenido":
        return rec["mts"][0] if rec["mts"] else None
    return None


def passes_filter(rec, code, lo, hi):
    if code is None:
        return True
    if not rec["ready"]:
        return False
    return any_in_range(rec["cts"] if code == "c" else rec["mts"], lo, hi)


# ---------------------------------------------------------------------------
# Actualizaciones (comprobación con huella SHA-256, copia de la versión anterior y rollback;
# solo se descarga de UPDATE_BASE)
# ---------------------------------------------------------------------------

_UPDATE_ST = {}


def update_state():
    global _UPDATE_ST
    if not _UPDATE_ST:
        try:
            with open(UPDATE_STATE, "r", encoding="utf-8") as f:
                d = json.load(f)
            _UPDATE_ST = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            _UPDATE_ST = {}
    return _UPDATE_ST


def update_state_save():
    try:
        os.makedirs(os.path.dirname(UPDATE_STATE), exist_ok=True)
        tmp = UPDATE_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(update_state(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, UPDATE_STATE)
    except OSError:
        pass


def update_local_info():
    with open(APP_FILE, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    return {"pack": APP_PACK, "sha256": sha, "label": APP_VERSION}


def _update_get(url, limit, timeout=20):
    """Descarga una dirección de la web del proyecto (y nada más: ni siquiera si hay una
    redirección a otro sitio)."""
    if not url.startswith(UPDATE_BASE):
        raise ValueError("dirección no permitida")

    class _Same(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not newurl.startswith(UPDATE_BASE):
                raise ValueError("redirección a otro sitio rechazada")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    op = urllib.request.build_opener(
        _Same(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req = urllib.request.Request(
        url, headers={"User-Agent": "faster-finder", "Cache-Control": "no-cache"})
    with op.open(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("la respuesta es demasiado grande")
    return data


def update_check():
    """Mira la versión publicada. Devuelve {ok, state: newer|same|older|diverged, info, local}
    o {ok: False, error}."""
    try:
        info = json.loads(_update_get(UPDATE_BASE + "update.json?t=%d" % int(time.time()),
                                      262144).decode("utf-8"))
        meta = info["files"][UPDATE_FILE]
        pack, sha, size = int(info["pack"]), str(meta["sha256"]).lower(), int(meta["size"])
        if not re.fullmatch(r"[0-9a-f]{64}", sha) or size <= 0 or size > 1048576:
            raise ValueError("update.json no es válido")
    except Exception as e:  # noqa: BLE001 - cualquier fallo de red o de formato se muestra tal cual
        return {"ok": False, "error": str(e) or e.__class__.__name__}
    loc = update_local_info()
    if pack > loc["pack"]:
        st = "newer"
    elif pack < loc["pack"]:
        st = "older"
    else:
        st = "same" if sha == loc["sha256"] else "diverged"
    update_state()["last_check"] = time.time()
    update_state_save()
    return {"ok": True, "state": st, "info": info, "local": loc}


def _update_file(info):
    meta = info["files"][UPDATE_FILE]
    # con la huella en la dirección no se sirve una copia vieja de la caché
    data = _update_get(UPDATE_BASE + UPDATE_FILE + "?v=" + str(meta["sha256"])[:12], int(meta["size"]))
    if len(data) != int(meta["size"]) or hashlib.sha256(data).hexdigest() != str(meta["sha256"]).lower():
        raise ValueError("lo descargado no coincide con la huella publicada (se cancela; si "
                         "acaban de publicar, inténtalo de nuevo en unos minutos)")
    compile(data, UPDATE_FILE, "exec")  # que al menos sea Python válido antes de tocar nada
    return data


def _update_put(path, data):
    tmp = path + ".nuevo"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _update_bkname():
    """Nombre libre para una copia (nunca pisa otra, aunque se hagan dos en el mismo segundo)."""
    base = os.path.join(UPDATE_BACKUPS, "faster_finder.pack%d.%s" % (APP_PACK, time.strftime("%Y%m%d-%H%M%S")))
    p, i = base + ".py", 2
    while os.path.exists(p):
        p = "%s-%d.py" % (base, i)
        i += 1
    return p


def update_apply(info):
    """Descarga y comprueba la versión publicada, guarda una copia de la actual y la sustituye."""
    d = os.path.dirname(APP_FILE)
    if not os.access(d, os.W_OK) or not os.access(APP_FILE, os.W_OK):
        raise ValueError("No hay permiso para escribir en la carpeta del programa (%s)." % d)
    data = _update_file(info)
    m = re.search(rb"^APP_PACK\s*=\s*(\d+)", data, re.M)
    if not m or int(m.group(1)) != int(info["pack"]):
        raise ValueError("El archivo publicado no es el de la versión anunciada (se cancela).")
    os.makedirs(UPDATE_BACKUPS, exist_ok=True)
    bk = _update_bkname()
    shutil.copyfile(APP_FILE, bk)
    _update_put(APP_FILE, data)
    st = update_state()
    st.update({"last_backup": bk, "from_pack": APP_PACK, "to_pack": int(info["pack"]), "applied": time.time()})
    update_state_save()
    try:  # se conservan las 5 últimas copias
        olds = sorted((os.path.join(UPDATE_BACKUPS, f) for f in os.listdir(UPDATE_BACKUPS)
                       if f.startswith("faster_finder.pack")), key=os.path.getmtime)
        for f in olds[:-5]:
            os.remove(f)
    except OSError:
        pass
    return {"backup": bk}


def update_backup_available():
    bk = update_state().get("last_backup")
    return bool(bk) and os.path.exists(bk) and os.path.abspath(os.path.dirname(bk)) == os.path.abspath(UPDATE_BACKUPS)


def update_rollback():
    """Vuelve a la copia guardada en la última actualización (y deja la actual como copia)."""
    if not update_backup_available():
        raise ValueError("No hay una copia anterior a la que volver.")
    st = update_state()
    with open(st["last_backup"], "rb") as f:
        data = f.read()
    compile(data, UPDATE_FILE, "exec")
    cur = _update_bkname()
    shutil.copyfile(APP_FILE, cur)
    _update_put(APP_FILE, data)
    st.update({"last_backup": cur, "applied": time.time()})
    update_state_save()
    return {"backup": cur}


def _pythonw():
    """El intérprete sin consola en Windows (pythonw.exe) si existe junto al actual."""
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    return exe


def update_spawn_restart(delay=3):
    """Lanza, aparte, una orden que vuelve a abrir el programa pasados unos segundos (da
    tiempo a que este termine de cerrarse)."""
    cmd = [_pythonw(), APP_FILE] + sys.argv[1:]
    code = ("import subprocess, sys, time\ntime.sleep({0})\n"
            "subprocess.Popen(sys.argv[1:], close_fds=True{1})").format(
        int(delay), ", creationflags=0x08000008" if os.name == "nt" else ", start_new_session=True")
    kw = {"creationflags": 0x08000008} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, "-c", code] + cmd, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **kw)
    return cmd


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------

class App:
    DATE_COLS = {"creada", "modificada", "c_contenido", "m_contenido"}

    def __init__(self, root):
        self.root = root
        self.records = {}
        self.sort_col = "carpeta"
        self.sort_desc = False
        self.dirty = False
        self.last_refresh = 0.0
        self.auto_update = tk.BooleanVar(value=bool(update_state().get("auto", False)))
        self._styles()
        self._build()
        for _ in range(2):
            threading.Thread(target=stats_worker, daemon=True).start()
        root.after(100, self.poll)
        root.after(2000, lambda: self.check_updates(False))  # comprobación silenciosa al abrir

    # --- estilo y disposición -------------------------------------------------------------------

    def _styles(self):
        bg = "#f4f6fa"
        self.root.configure(background=bg)
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=bg, font=("Segoe UI", 10))
        st.configure("TFrame", background=bg)
        st.configure("TLabel", background=bg)
        st.configure("TCheckbutton", background=bg)
        st.configure("TLabelframe", background=bg)
        st.configure("TLabelframe.Label", background=bg, foreground="#374151",
                     font=("Segoe UI", 9, "bold"))
        st.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#1d2433")
        st.configure("Muted.TLabel", foreground="#6b7280")
        st.configure("Error.TLabel", foreground="#b42318")
        st.configure("TButton", padding=(10, 5))
        st.configure("Accent.TButton", background="#2d6cdf", foreground="white",
                     padding=(16, 6), font=("Segoe UI", 10, "bold"))
        st.map("Accent.TButton",
               background=[("active", "#2459b8"), ("disabled", "#a9c2ef")],
               foreground=[("disabled", "white")])
        st.configure("Treeview", rowheight=26, background="white",
                     fieldbackground="white", borderwidth=0)
        st.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=(6, 6))
        st.map("Treeview", background=[("selected", "#2d6cdf")],
               foreground=[("selected", "white")])

    def _build(self):
        r = self.root
        r.title(APP_NAME)
        r.geometry("1080x700")
        r.minsize(820, 520)

        outer = ttk.Frame(r, padding=(18, 14, 18, 10))
        outer.pack(fill="both", expand=True)

        # Cabecera
        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="Faster Finder", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="v" + APP_VERSION, style="Muted.TLabel").pack(side="right", pady=(8, 0))
        ttk.Label(outer, style="Muted.TLabel",
                  text="Busca carpetas de fotos y vídeos (DCIM, Cámara, Videos…), ordénalas y filtra por fecha."
                  ).pack(anchor="w", pady=(0, 10))

        # Origen + búsqueda
        top = ttk.Frame(outer)
        top.pack(fill="x")

        src = ttk.LabelFrame(top, text=" Origen ", padding=10)
        src.pack(side="left", fill="x", expand=True)
        self.location = tk.StringVar()
        entry = ttk.Entry(src, textvariable=self.location)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.start_search())
        ttk.Button(src, text="Examinar…", command=self.browse).pack(side="left", padx=(8, 0))
        ttk.Label(src, text="vacío = todos los discos locales", style="Muted.TLabel").pack(side="left", padx=(10, 0))

        srch = ttk.LabelFrame(top, text=" Búsqueda ", padding=10)
        srch.pack(side="left", padx=(12, 0))
        ttk.Label(srch, text="Hilos").grid(row=0, column=0, sticky="w")
        self.thread_count = tk.StringVar(value="8")
        ttk.Spinbox(srch, from_=1, to=32, width=5, textvariable=self.thread_count
                    ).grid(row=0, column=1, padx=6)
        self.btn_start = ttk.Button(srch, text="Iniciar", style="Accent.TButton", command=self.start_search)
        self.btn_start.grid(row=0, column=2, padx=(6, 4))
        self.btn_stop = ttk.Button(srch, text="Detener", command=self.stop_search)
        self.btn_stop.grid(row=0, column=3)

        # Filtro de fechas
        dates = ttk.LabelFrame(outer, text=" Filtrar por fecha del contenido ", padding=10)
        dates.pack(fill="x", pady=(12, 0))
        ttk.Label(dates, text="Campo").grid(row=0, column=0, sticky="w")
        self.field = tk.StringVar(value=FIELD_NONE)
        cb = ttk.Combobox(dates, textvariable=self.field, state="readonly", width=26,
                          values=list(FIELD_CODES))
        cb.grid(row=0, column=1, padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Label(dates, text="Desde (AAAA-MM-DD)").grid(row=0, column=2, padx=(14, 0))
        self.d_from = tk.StringVar()
        self._date_entry(dates, self.d_from).grid(row=0, column=3, padx=6)
        ttk.Label(dates, text="Hasta").grid(row=0, column=4, padx=(14, 0))
        self.d_to = tk.StringVar()
        self._date_entry(dates, self.d_to).grid(row=0, column=5, padx=6)

        ttk.Label(dates, text="Atajos").grid(row=0, column=6, padx=(14, 0))
        self.preset = ttk.Combobox(dates, state="readonly", width=17, values=list(PRESET_DAYS))
        self.preset.grid(row=0, column=7, padx=6)
        self.preset.bind("<<ComboboxSelected>>", self.apply_preset)
        ttk.Button(dates, text="Quitar filtro", command=self.clear_dates).grid(row=0, column=8, padx=(14, 0))
        self.date_msg = ttk.Label(dates, text="", style="Error.TLabel")
        self.date_msg.grid(row=1, column=0, columnspan=9, sticky="w", pady=(6, 0))

        # Resultados
        res = ttk.Frame(outer)
        res.pack(fill="both", expand=True, pady=(10, 0))
        ids = [c[0] for c in COLUMNS]
        self.tree = ttk.Treeview(res, columns=ids, show="headings", selectmode="extended")
        for cid, label, width, anchor, _is_date in COLUMNS:
            self.tree.heading(cid, text=label, command=lambda c=cid: self.sort_by(c))
            self.tree.column(cid, width=width, anchor=anchor, stretch=cid == "carpeta")
        vsb = ttk.Scrollbar(res, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(res, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        res.rowconfigure(0, weight=1)
        res.columnconfigure(0, weight=1)
        self.tree.tag_configure("odd", background="#f7f9fc")
        self.tree.tag_configure("pending", foreground="#9ca3af")
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Return>", lambda e: self.open_selected())
        self.tree.bind("<Button-3>", self.popup)
        self.menu = tk.Menu(r, tearoff=0)
        self.menu.add_command(label="Abrir", command=self.open_selected)
        self.menu.add_command(label="Copiar ruta", command=self.copy_paths)

        # Barra de acciones sobre la selección
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Abrir selección", command=self.open_selected).pack(side="left")
        ttk.Button(actions, text="Copiar ruta", command=self.copy_paths).pack(side="left", padx=6)
        self.count_lbl = ttk.Label(actions, text="", style="Muted.TLabel")
        self.count_lbl.pack(side="right")

        # Pie: estado y actualizaciones
        foot = ttk.Frame(outer)
        foot.pack(fill="x", pady=(10, 0))
        self.status = tk.StringVar(value="Preparado")
        ttk.Label(foot, textvariable=self.status).pack(side="left")
        self.progress = ttk.Progressbar(foot, mode="indeterminate", length=160)
        self.progress.pack(side="left", padx=10)
        ttk.Button(foot, text="Revertir actualización", command=self.rollback).pack(side="right", padx=(6, 0))
        ttk.Button(foot, text="Buscar actualizaciones", command=lambda: self.check_updates(True)).pack(side="right", padx=(6, 0))
        ttk.Checkbutton(foot, text="Actualizar automáticamente sin preguntar",
                        variable=self.auto_update, command=self.save_auto_update).pack(side="right")

        self._update_headings()
        self._set_busy(False)

    def _date_entry(self, parent, var):
        e = ttk.Entry(parent, textvariable=var, width=12)
        e.bind("<Return>", lambda ev: self.refresh())
        e.bind("<FocusOut>", lambda ev: self.refresh())
        return e

    def _set_busy(self, busy):
        self.btn_start.state(["disabled"] if busy else ["!disabled"])
        self.btn_stop.state(["!disabled"] if busy else ["disabled"])
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    # --- estado visible --------------------------------------------------------------------------

    def set_status(self, text):
        self.status.set(text)

    def _update_counts(self, shown):
        total = len(self.records)
        ready = sum(1 for r in self.records.values() if r["ready"])
        pending = stats_q.unfinished_tasks
        text = "%d de %d carpetas · %d con fechas" % (shown, total, ready)
        if pending:
            text += " · calculando %d más…" % pending
        self.count_lbl.configure(text=text)

    def _update_headings(self):
        for cid, label, *_ in COLUMNS:
            arrow = ""
            if cid == self.sort_col:
                arrow = "  ▼" if self.sort_desc else "  ▲"
            self.tree.heading(cid, text=label + arrow)

    # --- búsqueda --------------------------------------------------------------------------------

    def browse(self):
        path = filedialog.askdirectory()
        if path:
            self.location.set(path)

    def start_search(self):
        global running
        if running:
            return
        path = self.location.get().strip()
        if path:
            if not os.path.isdir(path):
                messagebox.showerror(APP_NAME, "Directorio no válido")
                return
            roots = [os.path.abspath(path)]
        else:
            roots = local_drives()
        if not roots:
            messagebox.showerror(APP_NAME, "No se encontraron discos locales")
            return
        try:
            count = max(1, min(32, int(self.thread_count.get())))
        except ValueError:
            count = 8

        self.records.clear()
        self.tree.delete(*self.tree.get_children())
        stop_event.clear()
        running = True
        self._set_busy(True)
        self.set_status("Buscando…")
        self.dirty = True
        threading.Thread(target=scan_coordinator, args=(roots, count), daemon=True).start()

    def stop_search(self):
        if running:
            stop_event.set()
            self.set_status("Deteniendo búsqueda…")

    # --- orden y filtro ------------------------------------------------------------------------

    def sort_by(self, col):
        if self.sort_col == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col = col
            self.sort_desc = col in self.DATE_COLS  # las fechas, la más reciente primero
        self.refresh()

    def apply_preset(self, _event=None):
        days = PRESET_DAYS.get(self.preset.get())
        if not days:
            return
        if self.field.get() == FIELD_NONE:
            self.field.set(FIELD_MODIFIED)
        self.d_from.set((dt.date.today() - dt.timedelta(days=days)).isoformat())
        self.d_to.set("")
        self.preset.set("")
        self.refresh()

    def clear_dates(self):
        self.d_from.set("")
        self.d_to.set("")
        self.field.set(FIELD_NONE)
        self.refresh()

    def refresh(self):
        """Vuelve a construir la lista según el orden y el filtro actuales."""
        self.dirty = False
        self.last_refresh = time.monotonic()

        code = FIELD_CODES[self.field.get()]
        lo, hi = float("-inf"), float("inf")
        try:
            lo, hi = parse_range(self.d_from.get(), self.d_to.get())
            self.date_msg.configure(text="")
        except ValueError as e:
            self.date_msg.configure(text="Fecha no válida: %s. Se muestran todas." % e)
            code = None

        rows, without = [], []
        for rec in self.records.values():
            if not passes_filter(rec, code, lo, hi):
                continue
            value = sort_value(rec, self.sort_col)
            (without if value is None else rows).append((value, rec))
        rows.sort(key=lambda t: t[0], reverse=self.sort_desc)
        ordered = [rec for _v, rec in rows] + [rec for _v, rec in without]

        self.tree.delete(*self.tree.get_children())
        for i, rec in enumerate(ordered):
            tags = []
            if i % 2:
                tags.append("odd")
            if not rec["ready"]:
                tags.append("pending")
            self.tree.insert("", "end", iid=rec["path"], values=row_values(rec), tags=tuple(tags))

        self._update_headings()
        self._update_counts(len(ordered))

    # --- acciones sobre la selección -----------------------------------------------------------

    def selected_paths(self):
        return list(self.tree.selection())

    def open_selected(self):
        for path in self.selected_paths()[:10]:
            try:
                open_path(path)
            except OSError as e:
                messagebox.showerror(APP_NAME, "No se pudo abrir:\n%s\n\n%s" % (path, e))

    def copy_paths(self):
        paths = self.selected_paths()
        if paths:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(paths))
            self.set_status("Copiado: %d ruta(s) al portapapeles" % len(paths))

    def popup(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            try:
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()

    # --- eventos que llegan de los hilos -------------------------------------------------------

    def poll(self):
        global running
        try:
            while True:
                kind, value = events.get_nowait()

                if kind == "found":
                    self.records.setdefault(value, new_record(value))
                    self.dirty = True

                elif kind == "stats":
                    path, data = value
                    rec = self.records.get(path)
                    if rec is not None:  # descartar cálculos de una búsqueda anterior
                        if data:
                            rec.update(data)
                        rec["ready"] = True
                        self.dirty = True

                elif kind == "done":
                    running = False
                    self._set_busy(False)
                    self.set_status("Búsqueda finalizada")
                    self.dirty = True

                elif kind == "update_check":
                    manual, res = value
                    self.handle_update(manual, res)

                elif kind == "update_applied":
                    messagebox.showinfo(APP_NAME, "Actualizado. El programa se reiniciará ahora.")
                    update_spawn_restart()
                    self.root.destroy()
                    return

                elif kind == "update_error":
                    self.set_status("Error al actualizar")
                    messagebox.showerror(APP_NAME, "No se pudo actualizar:\n\n" + value)

        except queue.Empty:
            pass

        if self.dirty and time.monotonic() - self.last_refresh > 0.3:
            self.refresh()
        elif not running and stats_q.unfinished_tasks == 0 and self.count_lbl.cget("text").count("calculando"):
            self._update_counts(len(self.tree.get_children()))

        self.root.after(100, self.poll)

    # --- actualizaciones -----------------------------------------------------------------------

    def check_updates(self, manual):
        def run():
            events.put(("update_check", (manual, update_check())))
        threading.Thread(target=run, daemon=True).start()

    def _apply_async(self, info):
        def run():
            try:
                update_apply(info)
                events.put(("update_applied", None))
            except Exception as e:  # noqa: BLE001
                events.put(("update_error", str(e) or e.__class__.__name__))
        self.set_status("Descargando actualización…")
        threading.Thread(target=run, daemon=True).start()

    def handle_update(self, manual, res):
        if not res.get("ok"):
            if manual:
                messagebox.showerror(APP_NAME, "No se pudieron buscar actualizaciones:\n\n" + res.get("error", ""))
            return
        state = res["state"]
        if state in ("same", "older"):
            if manual and state == "same":
                messagebox.showinfo(APP_NAME, "Ya tienes la última versión (v%s)." % APP_VERSION)
            return
        info = res["info"]
        ver = info.get("version", "?")
        if running:
            if manual:
                messagebox.showinfo(APP_NAME, "Hay una búsqueda en curso. Espera a que termine o pulsa Detener para actualizar.")
            self.set_status("Hay una versión nueva (v%s): se puede instalar al terminar la búsqueda" % ver)
            return
        if self.auto_update.get():
            self._apply_async(info)
            return
        notes = (info.get("notes") or "").strip()[:600]
        question = ("Hay una versión nueva: v%s (tienes v%s).\n\n%s\n\n¿Actualizar ahora?\n"
                    "Se guardará una copia de la versión actual." % (ver, APP_VERSION, notes))
        if messagebox.askyesno(APP_NAME, question):
            self._apply_async(info)
        else:
            self.set_status("Actualización v%s disponible" % ver)

    def save_auto_update(self):
        update_state()["auto"] = bool(self.auto_update.get())
        update_state_save()

    def rollback(self):
        if running:
            messagebox.showinfo(APP_NAME, "Espera a que termine la búsqueda antes de revertir.")
            return
        if not messagebox.askyesno(APP_NAME, "¿Volver a la versión anterior guardada?"):
            return
        try:
            update_rollback()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, "No se pudo revertir:\n\n%s" % e)
            return
        messagebox.showinfo(APP_NAME, "Versión anterior restaurada. El programa se reiniciará.")
        update_spawn_restart()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
