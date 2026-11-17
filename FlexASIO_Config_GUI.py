#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FlexASIO Config GUI
-------------------
A native Windows GUI to generate and edit the FlexASIO.toml configuration
file. DPI-aware, with detent sliders, segmented buttons, a device list and a
syntax-highlighted TOML preview.

What it does:
  1. Runs PortAudioDevices.exe (shipped with FlexASIO) to enumerate every
     audio device and host API (backend) on this machine.
  2. Lets you pick a backend, input device, output device, buffer size,
     sample type, latency hint and WASAPI flags.
  3. Writes the result to %USERPROFILE%\\FlexASIO.toml as UTF-8.

No external packages required — stdlib only (tkinter).

Run:
  python FlexASIO_Config_GUI.py
"""

import ctypes
import os
import re
import subprocess
import sys

# High-DPI: make Windows stop bitmap-scaling the window (fixes blur).
def _enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:  # pragma: no cover
    sys.exit("tkinter is not available in this Python install.")


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

BG = "#263158"          # medium indigo window background
BG_GRAD_1 = "#2e3d6e"   # header gradient start
BG_GRAD_2 = "#4a5da6"   # header gradient mid (vivid indigo)
BG_GRAD_3 = "#6a4fb0"   # header gradient end (violet)
PANEL = "#33437a"       # section panel surface
PANEL_EDGE = "#6678c0"  # visible panel edge
FIELD = "#232d52"       # input well / listbox / preview bg
FG = "#ffffff"          # pure white text
MUTED = "#c3cdec"       # light slate secondary text
CYAN = "#2ad4f0"        # input accent
GREEN = "#3ed9a0"       # output / save accent
PURPLE = "#b794f6"      # brand accent
AMBER = "#fbbf24"       # numbers / booleans in preview
DANGER = "#ff8a8a"

FONT = "Segoe UI"
MONO = "Consolas"

# Detent presets for the sliders.
BUFFER_DETENTS = [64, 96, 128, 160, 192, 256, 384, 480, 512, 768, 960, 1024,
                  1536, 2048]
LATENCY_DETENTS = [0.0, 0.02, 0.05, 0.1, 0.2]
LATENCY_LABELS = ["0 ms", "20 ms", "50 ms", "100 ms", "200 ms"]
CHANNEL_DETENTS = [None, 2, 4, 6, 8, 16, 32]

SAMPLE_TYPES = ["Float32", "Int32", "Int24", "Int16"]

CONFIG_PATH = os.path.join(os.path.expanduser("~"), "FlexASIO.toml")


# ---------------------------------------------------------------------------
# Device scanning
# ---------------------------------------------------------------------------

def _find_portaudio_devices_exe():
    candidates = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for base in (pf, pf86):
        candidates += [
            os.path.join(base, "FlexASIO", "x64", "PortAudioDevices.exe"),
            os.path.join(base, "FlexASIO", "x86", "PortAudioDevices.exe"),
        ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _decode(raw_bytes):
    best = ("", 10 ** 9)
    for enc in ("utf-8", "cp1252", "cp850", "cp437", "latin-1"):
        try:
            s = raw_bytes.decode(enc)
            repl = s.count("\ufffd")
            if repl < best[1]:
                best = (s, repl)
            if repl == 0:
                break
        except UnicodeDecodeError:
            continue
    return best[0]


def scan_devices():
    """Return (host_apis, devices). Each device dict has index, name, rate,
    in_ch, out_ch, host_api, is_default_in, is_default_out."""
    exe = _find_portaudio_devices_exe()
    if exe is None:
        return None, None
    try:
        proc = subprocess.run([exe], capture_output=True, timeout=30)
    except Exception:
        return None, None
    text = _decode(proc.stdout if proc.stdout else proc.stderr)

    devices = []
    host_apis = []
    cur = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("["):
            continue
        if line.startswith("Device index:"):
            if cur is not None:
                devices.append(cur)
            cur = {"index": None, "name": "", "rate": 0, "in_ch": 0,
                   "out_ch": 0, "host_api": "", "is_default_in": False,
                   "is_default_out": False}
            m = re.search(r"Device index:\s*(\d+)", line)
            if m:
                cur["index"] = int(m.group(1))
            continue
        if cur is None:
            continue
        if line.startswith("Device name:"):
            m = re.search(r'Device name:\s*"(.*)"', line)
            if m:
                cur["name"] = m.group(1)
        elif line.startswith("Default sample rate:"):
            m = re.search(r"(\d+)", line)
            if m:
                cur["rate"] = int(m.group(1))
        elif line.startswith("Input:"):
            m = re.search(r"max channel count\s*(\d+)", line)
            if m:
                cur["in_ch"] = int(m.group(1))
        elif line.startswith("Output:"):
            m = re.search(r"max channel count\s*(\d+)", line)
            if m:
                cur["out_ch"] = int(m.group(1))
        elif line.startswith("Host API name:"):
            cur["host_api"] = line.split(":", 1)[1].strip()
        elif "DEFAULT INPUT DEVICE" in line:
            cur["is_default_in"] = True
        elif "DEFAULT OUTPUT DEVICE" in line:
            cur["is_default_out"] = True

    if cur is not None:
        devices.append(cur)

    if not devices:
        return None, None

    for d in devices:
        if d["host_api"] and d["host_api"] not in host_apis:
            host_apis.append(d["host_api"])
    return host_apis, devices


# ---------------------------------------------------------------------------
# TOML generation
# ---------------------------------------------------------------------------

def _toml_str(value):
    if value is None:
        return '""'
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % value


def build_toml(cfg):
    backend = cfg.get("backend", "Windows WASAPI")
    lines = ['backend = %s' % _toml_str(backend)]
    buf = cfg.get("buffer_size")
    if buf not in (None, ""):
        lines.append("bufferSizeSamples = %s" % int(buf))
    lines.append("")

    for section in ("input", "output"):
        s = cfg.get(section, {})
        lines.append("[%s]" % section)
        lines.append("device = %s" % _toml_str(s.get("device", "")))

        ch = s.get("channels")
        if ch not in (None, ""):
            lines.append("channels = %s" % int(ch))

        st = s.get("sample_type")
        if st not in (None, ""):
            lines.append("sampleType = %s" % _toml_str(st))

        lat = s.get("latency")
        if lat not in (None, ""):
            lines.append("suggestedLatencySeconds = %s" % lat)

        if s.get("exclusive"):
            lines.append("wasapiExclusiveMode = true")
        if s.get("autoconvert") is False:
            lines.append("wasapiAutoConvert = false")
        if s.get("explicit_sample_format"):
            lines.append("wasapiExplicitSampleFormat = true")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Gradient helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _draw_gradient(canvas, x1, y1, x2, y2, c1, c2, steps=80):
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    width = max(1, x2 - x1)
    for i in range(steps):
        t = i / (steps - 1)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        color = "#%02x%02x%02x" % (r, g, b)
        x = x1 + int(width * i / steps)
        w = int(width / steps) + 1
        canvas.create_rectangle(x, y1, x + w, y2, fill=color, outline="")


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------

class Segmented(ttk.Frame):
    """A row of toggle buttons; exactly one is active. Backs a StringVar."""

    def __init__(self, parent, values, var, on_change=None, accent=CYAN,
                 style="panel"):
        super().__init__(parent)
        self.var = var
        self.on_change = on_change
        self.accent = accent
        self.buttons = {}
        for v in values:
            b = tk.Button(
                self, text=v, relief="flat", bd=0, padx=10, pady=4,
                font=(FONT, 9), cursor="hand2", highlightthickness=0,
                command=lambda v=v: self.select(v),
            )
            b.pack(side="left", padx=(0, 4), pady=2)
            self.buttons[v] = b
        self.var.trace_add("write", lambda *a: self._refresh())
        self._refresh()

    def select(self, v):
        self.var.set(v)
        if self.on_change:
            self.on_change()

    def _refresh(self):
        cur = self.var.get()
        for v, b in self.buttons.items():
            if v == cur:
                b.config(bg=self.accent, fg="#081018",
                         activebackground=self.accent,
                         activeforeground="#081018")
            else:
                b.config(bg=PANEL, fg=FG, activebackground=PANEL_EDGE,
                         activeforeground=FG)


class DetentSlider(ttk.Frame):
    """A slider with discrete detent positions and a generous click target.

    You don't have to hit the thumb precisely: clicking anywhere on the
    track line (or a few pixels above/below it) jumps the handle to the
    nearest detent. The end detents also have a widened zone so landing on
    min/max (e.g. 0 ms latency) is easy."""

    def __init__(self, parent, detents, labels, initial_index=0,
                 on_change=None):
        super().__init__(parent)
        self.detents = detents
        self.labels = labels
        self.on_change = on_change
        self.n = len(detents)
        self.value = detents[initial_index]
        self._syncing = False

        self.scale = ttk.Scale(
            self, from_=0, to=self.n - 1,
            value=initial_index, command=self._drag,
        )
        # Extra vertical padding widens the click target above/below the
        # track so you don't need to hit the handle exactly.
        self.scale.pack(side="left", fill="x", expand=True, pady=8)
        self.label = ttk.Label(
            self, text=labels[initial_index], width=16, anchor="e",
            font=(FONT, 9, "bold"),
        )
        self.label.pack(side="right", padx=(8, 0))

        # Bigger hit area: clicks/drags on the padding (this frame) and on
        # the track itself both jump the handle to the nearest detent.
        self.bind("<ButtonPress-1>", self._jump)
        self.bind("<B1-Motion>", self._jump)
        self.scale.bind("<ButtonPress-1>", self._jump)
        self.scale.bind("<B1-Motion>", self._jump)

    def _snap(self, f):
        n = self.n
        # Widened zone at the ends for easy handling.
        if f < 0.75:
            return 0
        if f > n - 1.75:
            return n - 1
        return max(0, min(n - 1, int(round(f))))

    def _set_index(self, idx):
        idx = max(0, min(self.n - 1, idx))
        self.value = self.detents[idx]
        self.label.config(text=self.labels[idx])
        # Snap the thumb visually. scale.set() re-fires the -command
        # callback, so guard against re-entrancy.
        if self._syncing:
            return
        self._syncing = True
        try:
            self.scale.set(idx)
        finally:
            self._syncing = False

    def _jump(self, event):
        w = self.scale.winfo_width()
        if w <= 1:
            return "break"
        # Map the horizontal click position to a detent index. The scale is
        # packed flush-left, so event.x is the position along the track.
        f = (event.x / w) * (self.n - 1)
        self._set_index(self._snap(f))
        if self.on_change:
            self.on_change()
        return "break"

    def _drag(self, raw):
        if self._syncing:
            return
        self._set_index(self._snap(float(raw)))
        if self.on_change:
            self.on_change()

    def set_by_value(self, v):
        try:
            idx = self.detents.index(v)
        except ValueError:
            # snap to nearest
            idx = min(range(len(self.detents)),
                      key=lambda i: abs(self.detents[i] - v)) \
                if self.detents[0] is not None else 0
        self._set_index(idx)


class FlexASIOGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FlexASIO Config")
        self.root.configure(bg=BG)
        self.root.geometry("1000x1120")
        self.root.minsize(900, 980)

        self.host_apis = []
        self.devices = []

        self._build_style()
        self._build_ui()
        self.rescan()

    # -- styling ------------------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG,
                        font=(FONT, 10))
        style.configure("Panel.TLabel", background=PANEL, foreground=FG,
                        font=(FONT, 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED,
                        font=(FONT, 9))
        style.configure("PanelMuted.TLabel", background=PANEL,
                        foreground=MUTED, font=(FONT, 9))
        style.configure(
            "TScale", background=PANEL, troughcolor=FIELD,
            bordercolor=PANEL_EDGE, lightcolor=PANEL, darkcolor=PANEL,
        )
        style.configure(
            "TCheckbutton", background=PANEL, foreground=FG,
            font=(FONT, 9),
        )
        style.map("TCheckbutton",
                  background=[("active", PANEL)],
                  foreground=[("active", FG)])
        style.configure(
            "Save.TButton", background=GREEN, foreground="#06231a",
            font=(FONT, 10, "bold"), borderwidth=0, focuscolor=GREEN,
            padding=(16, 7),
        )
        style.map("Save.TButton", background=[("active", "#4ce0a7")])
        style.configure(
            "Ghost.TButton", background=PANEL, foreground=FG, borderwidth=0,
            focuscolor=PANEL, padding=(12, 6),
        )
        style.map("Ghost.TButton", background=[("active", PANEL_EDGE)])

    # -- UI construction ----------------------------------------------------
    def _build_ui(self):
        # Status bar packed first so it reserves its strip at the bottom
        # before the expanding content frames above it.
        self.status = tk.Label(
            self.root, text="", bg=BG, fg=MUTED, anchor="w",
            font=(FONT, 9), padx=16, pady=5,
        )
        self.status.pack(fill="x", side="bottom")

        # Header
        self.header = tk.Canvas(self.root, height=78, bg=BG_GRAD_1,
                                highlightthickness=0)
        self.header.pack(fill="x")
        self.header.bind("<Configure>", lambda e: self._paint_header(e.width))

        # Backend segmented control
        backend_row = ttk.Frame(self.root, style="TFrame")
        backend_row.pack(fill="x", padx=16, pady=(14, 2))
        ttk.Label(backend_row, text="Backend", style="TLabel").pack(
            anchor="w"
        )
        self.backend_var = tk.StringVar(value="Windows WASAPI")
        self.backend_seg = Segmented(
            backend_row, [], self.backend_var,
            on_change=self.on_backend_change, accent=PURPLE,
        )
        self.backend_seg.pack(anchor="w", pady=(4, 0))

        # Buffer size slider (global)
        buffer_row = ttk.Frame(self.root, style="TFrame")
        buffer_row.pack(fill="x", padx=16, pady=6)
        ttk.Label(buffer_row, text="Buffer", style="TLabel").pack(
            side="left"
        )
        self.buffer_slider = DetentSlider(
            buffer_row, BUFFER_DETENTS,
            ["%d samples" % v for v in BUFFER_DETENTS],
            initial_index=BUFFER_DETENTS.index(480),
            on_change=self.update_preview,
        )
        self.buffer_slider.pack(side="left", fill="x", expand=True,
                                padx=(14, 0))

        # Action buttons
        btns = ttk.Frame(self.root, style="TFrame")
        btns.pack(fill="x", padx=16, pady=(6, 10))
        ttk.Button(btns, text="Rescan devices", style="Ghost.TButton",
                   command=self.rescan).pack(side="left")
        ttk.Button(btns, text="Load existing", style="Ghost.TButton",
                   command=self.load_existing).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Save config", style="Save.TButton",
                   command=self.save_config).pack(side="right")

        # Input / output columns (equal-width via uniform grid columns)
        cols = ttk.Frame(self.root, style="TFrame")
        cols.pack(fill="both", expand=True, padx=16, pady=4)
        cols.columnconfigure(0, weight=1, uniform="col")
        cols.columnconfigure(1, weight=1, uniform="col")
        self.input_section = self._build_section(cols, "INPUT", CYAN, 0)
        self.output_section = self._build_section(cols, "OUTPUT", GREEN, 1)

        # Preview
        prev_frame = ttk.Frame(self.root, style="Panel.TFrame")
        prev_frame.pack(fill="both", expand=True, padx=16, pady=(8, 8))
        self._paint_section_strip(prev_frame, "PREVIEW  ·  FlexASIO.toml",
                                  PURPLE, MONO, 10)

        prev_body = ttk.Frame(prev_frame, style="Panel.TFrame")
        prev_body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.preview = tk.Text(
            prev_body, height=12, bg=FIELD, fg="#dbe4f5", relief="flat",
            bd=0, font=(MONO, 10), wrap="none", padx=14, pady=10,
            insertbackground=FG, highlightthickness=0,
        )
        prev_sb = ttk.Scrollbar(prev_body, orient="vertical",
                                command=self.preview.yview)
        self.preview.config(yscrollcommand=prev_sb.set)
        self.preview.pack(side="left", fill="both", expand=True)
        prev_sb.pack(side="right", fill="y")
        self._configure_preview_tags()

    def _paint_header(self, width):
        self.header.delete("all")
        mid = int(width * 0.55)
        _draw_gradient(self.header, 0, 0, mid, 78, BG_GRAD_1, BG_GRAD_2)
        _draw_gradient(self.header, mid, 0, width, 78, BG_GRAD_2, BG_GRAD_3)
        self.header.create_line(0, 76, width, 76, fill=CYAN, width=2)
        self.header.create_text(26, 30, anchor="w", text="FLEXASIO  CONFIG",
                                fill=FG, font=(FONT, 21, "bold"))
        self.header.create_text(26, 58, anchor="w",
                                text="ASIO driver configuration  ·  writes "
                                     + CONFIG_PATH,
                                fill=MUTED, font=(FONT, 9))

    def _paint_section_strip(self, parent, title, accent, font_fam, font_sz):
        strip = tk.Canvas(parent, height=30, highlightthickness=0)
        strip.pack(fill="x", padx=8, pady=(8, 0))
        strip.bind(
            "<Configure>",
            lambda e, c=strip, t=title, a=accent, f=font_fam, s=font_sz:
            self._fill_strip(c, e.width, t, a, f, s),
        )

    def _fill_strip(self, canvas, width, title, accent, font_fam, font_sz):
        canvas.delete("all")
        _draw_gradient(canvas, 0, 0, width, 30, accent, PANEL, steps=60)
        canvas.create_text(14, 15, anchor="w", text=title, fill=FG,
                           font=(font_fam, font_sz, "bold"))

    def _configure_preview_tags(self):
        self.preview.tag_configure("section", foreground=PURPLE,
                                   font=(MONO, 10, "bold"))
        self.preview.tag_configure("key", foreground=CYAN)
        self.preview.tag_configure("eq", foreground=MUTED)
        self.preview.tag_configure("string", foreground=GREEN)
        self.preview.tag_configure("number", foreground=AMBER)

    def _build_section(self, parent, title, accent, column):
        panel = ttk.Frame(parent, style="Panel.TFrame")
        panel.grid(row=0, column=column, sticky="nsew",
                   padx=(0, 6) if column == 0 else 0)

        self._paint_section_strip(panel, title, accent, FONT, 12)

        body = ttk.Frame(panel, style="Panel.TFrame")
        body.pack(fill="x", padx=12, pady=8)

        # Device listbox
        ttk.Label(body, text="Device", style="Panel.TLabel").pack(
            anchor="w"
        )
        lb_frame = ttk.Frame(body, style="Panel.TFrame")
        lb_frame.pack(fill="x", pady=(2, 8))
        listbox = tk.Listbox(
            lb_frame, bg=FIELD, fg=FG, selectbackground=accent,
            selectforeground="#081018", highlightthickness=0, relief="flat",
            font=(FONT, 9), height=3, activestyle="none",
        )
        vsb = ttk.Scrollbar(lb_frame, orient="vertical", command=listbox.yview)
        listbox.config(yscrollcommand=vsb.set)
        listbox.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Channels slider
        ttk.Label(body, text="Channels", style="Panel.TLabel").pack(
            anchor="w"
        )
        ch_slider = DetentSlider(
            body, CHANNEL_DETENTS,
            ["auto"] + [str(v) for v in CHANNEL_DETENTS[1:]],
            initial_index=0, on_change=self.update_preview,
        )
        ch_slider.pack(fill="x")

        # Sample type segmented buttons
        ttk.Label(body, text="Sample type", style="Panel.TLabel").pack(
            anchor="w", pady=(8, 0)
        )
        st_var = tk.StringVar(value="Float32")
        st_seg = Segmented(body, SAMPLE_TYPES, st_var,
                           on_change=self.update_preview, accent=accent)
        st_seg.pack(anchor="w", pady=(2, 0))

        # Latency slider
        ttk.Label(body, text="Latency", style="Panel.TLabel").pack(
            anchor="w", pady=(8, 0)
        )
        lat_slider = DetentSlider(
            body, LATENCY_DETENTS, LATENCY_LABELS,
            initial_index=0, on_change=self.update_preview,
        )
        lat_slider.pack(fill="x")

        # WASAPI flags (single row to keep the panel compact)
        excl_var = tk.BooleanVar(value=False)
        conv_var = tk.BooleanVar(value=True)
        expl_var = tk.BooleanVar(value=False)
        chk = ttk.Frame(body, style="Panel.TFrame")
        chk.pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(chk, text="Exclusive", variable=excl_var).pack(
            side="left"
        )
        ttk.Checkbutton(chk, text="Auto-convert", variable=conv_var).pack(
            side="left", padx=(12, 0)
        )
        ttk.Checkbutton(chk, text="Explicit sample format",
                        variable=expl_var).pack(side="left", padx=(12, 0))

        # Wire live preview updates.
        listbox.bind("<<ListboxSelect>>", self.update_preview)
        for var in (st_var, excl_var, conv_var, expl_var):
            var.trace_add("write", self.update_preview)

        return {
            "listbox": listbox,
            "ch_slider": ch_slider,
            "st_var": st_var,
            "st_seg": st_seg,
            "lat_slider": lat_slider,
            "excl_var": excl_var,
            "conv_var": conv_var,
            "expl_var": expl_var,
            "kind": title.lower(),
            "accent": accent,
        }

    # -- device population --------------------------------------------------
    def rescan(self):
        host_apis, devices = scan_devices()
        if not host_apis or not devices:
            self.host_apis = ["Windows WASAPI", "Windows DirectSound",
                              "MME", "Windows WDM-KS"]
            self.devices = []
            self.status.config(
                text="Could not run PortAudioDevices.exe — is FlexASIO "
                     "installed? Device lists are empty.", fg=DANGER,
            )
        else:
            self.host_apis = host_apis
            self.devices = devices
            self.status.config(
                text="Found %d devices across %d backends."
                     % (len(devices), len(host_apis)), fg=MUTED,
            )

        # Rebuild backend segmented buttons with the discovered host APIs.
        for b in list(self.backend_seg.buttons.values()):
            b.destroy()
        self.backend_seg.buttons = {}
        for v in self.host_apis:
            b = tk.Button(
                self.backend_seg, text=v, relief="flat", bd=0, padx=10,
                pady=4, font=(FONT, 9), cursor="hand2", highlightthickness=0,
                command=lambda v=v: self.backend_seg.select(v),
            )
            b.pack(side="left", padx=(0, 4), pady=2)
            self.backend_seg.buttons[v] = b
        self.backend_seg._refresh()

        if self.backend_var.get() not in self.host_apis:
            self.backend_var.set(
                "Windows WASAPI" if "Windows WASAPI" in self.host_apis
                else self.host_apis[0]
            )
        self._populate_device_boxes()
        self.update_preview()

    def _populate_device_boxes(self):
        backend = self.backend_var.get()
        in_devs = [d for d in self.devices
                   if d["host_api"] == backend and d["in_ch"] > 0]
        out_devs = [d for d in self.devices
                    if d["host_api"] == backend and d["out_ch"] > 0]

        self._fill_listbox(self.input_section["listbox"],
                           in_devs, default_key=None)
        self._fill_listbox(self.output_section["listbox"],
                           out_devs, default_key="is_default_out")

    def _fill_listbox(self, lb, devs, default_key=None):
        current = self._selected_name(lb)
        lb.delete(0, "end")
        lb.insert("end", "(disabled)")
        for d in devs:
            lb.insert("end", d["name"])
        # Restore previous selection if still present.
        if current:
            items = lb.get(0, "end")
            if current in items:
                self._select_device(lb, current)
                return
        # Otherwise pick the default device, or fall back to "(disabled)".
        if default_key:
            default = next((d["name"] for d in devs if d[default_key]), None)
            if default:
                self._select_device(lb, default)
                return
        lb.selection_clear(0, "end")
        lb.selection_set(0)

    def _selected_name(self, lb):
        sel = lb.curselection()
        if not sel:
            return None
        return lb.get(sel[0])

    def _select_device(self, lb, name):
        if not name:
            lb.selection_clear(0, "end")
            lb.selection_set(0)
            lb.see(0)
            return
        items = lb.get(0, "end")
        for i, it in enumerate(items):
            if it == name:
                lb.selection_clear(0, "end")
                lb.selection_set(i)
                lb.see(i)
                return
        lb.selection_clear(0, "end")
        lb.selection_set(0)

    def on_backend_change(self, *_):
        self._populate_device_boxes()
        self.update_preview()

    # -- config read/write --------------------------------------------------
    def _read_section(self, s):
        name = self._selected_name(s["listbox"])
        if name == "(disabled)":
            name = ""
        return {
            "device": name or "",
            "channels": s["ch_slider"].value,
            "sample_type": s["st_var"].get(),
            "latency": s["lat_slider"].value,
            "exclusive": s["excl_var"].get(),
            "autoconvert": s["conv_var"].get(),
            "explicit_sample_format": s["expl_var"].get(),
        }

    def _collect(self):
        return {
            "backend": self.backend_var.get(),
            "buffer_size": self.buffer_slider.value,
            "input": self._read_section(self.input_section),
            "output": self._read_section(self.output_section),
        }

    def _insert_highlighted(self, text):
        self.preview.delete("1.0", "end")
        for line in text.splitlines():
            m = re.match(r'^(\[.*\])$', line)
            if m:
                self.preview.insert("end", line + "\n", "section")
                continue
            m = re.match(r'^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*)$', line)
            if m:
                self.preview.insert("end", m.group(1))
                self.preview.insert("end", m.group(2), "key")
                self.preview.insert("end", m.group(3), "eq")
                val = m.group(4)
                if val.startswith('"') and val.endswith('"'):
                    self.preview.insert("end", val, "string")
                elif val in ("true", "false"):
                    self.preview.insert("end", val, "number")
                else:
                    self.preview.insert("end", val, "number")
                self.preview.insert("end", "\n")
                continue
            self.preview.insert("end", line + "\n")

    def update_preview(self, *_):
        cfg = self._collect()
        self._insert_highlighted(build_toml(cfg))

    def save_config(self):
        cfg = self._collect()
        text = build_toml(cfg)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except OSError as e:
            messagebox.showerror("Save failed", str(e))
            return
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                written = f.read()
        except OSError:
            written = ""
        if written == text:
            self.status.config(
                text="Saved and verified: " + CONFIG_PATH, fg=GREEN,
            )
        else:
            self.status.config(
                text="Saved, but read-back mismatch — check the file.",
                fg=DANGER,
            )

    def load_existing(self):
        if not os.path.isfile(CONFIG_PATH):
            self.status.config(
                text="No existing config at " + CONFIG_PATH, fg=MUTED,
            )
            return
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            messagebox.showerror("Load failed", str(e))
            return

        section = None
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^\[(\w+)\]$", line)
            if m:
                section = m.group(1)
                continue
            m = re.match(r'^(\w+)\s*=\s*(.+)$', line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip()
            val = val.strip('"').strip("'")

            if section is None:
                if key == "backend":
                    self.backend_var.set(val)
                elif key == "bufferSizeSamples":
                    try:
                        self.buffer_slider.set_by_value(int(val))
                    except ValueError:
                        pass
                continue

            s = (self.input_section if section == "input"
                 else self.output_section if section == "output" else None)
            if s is None:
                continue
            if key == "device":
                self._select_device(s["listbox"], val)
            elif key == "channels":
                try:
                    s["ch_slider"].set_by_value(int(val))
                except ValueError:
                    pass
            elif key == "sampleType":
                s["st_var"].set(val)
            elif key == "suggestedLatencySeconds":
                try:
                    fv = float(val)
                    nearest = min(LATENCY_DETENTS,
                                  key=lambda d: abs(d - fv))
                    s["lat_slider"].set_by_value(nearest)
                except ValueError:
                    pass
            elif key == "wasapiExclusiveMode":
                s["excl_var"].set(val == "true")
            elif key == "wasapiAutoConvert":
                s["conv_var"].set(val == "true")
            elif key == "wasapiExplicitSampleFormat":
                s["expl_var"].set(val == "true")

        self._populate_device_boxes()
        self.update_preview()
        self.status.config(text="Loaded " + CONFIG_PATH, fg=MUTED)


def main():
    root = tk.Tk()
    FlexASIOGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
