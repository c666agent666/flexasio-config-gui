#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FlexASIO Config GUI
-------------------
A native GUI to generate and edit the FlexASIO.toml configuration file.

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

import os
import re
import subprocess
import sys

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:  # pragma: no cover
    sys.exit("tkinter is not available in this Python install.")


# ---------------------------------------------------------------------------
# Device scanning
# ---------------------------------------------------------------------------

def _find_portaudio_devices_exe():
    """Locate PortAudioDevices.exe shipped with FlexASIO."""
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
    """Decode PortAudioDevices output, preferring the encoding with fewest
    replacement characters so non-ASCII device names (e.g. ®) survive."""
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
    """Run PortAudioDevices.exe and return (host_apis, devices).

    host_apis: list of unique host API names (backend values).
    devices:   list of dicts with keys index, name, rate, in_ch, out_ch,
               host_api, is_default_in, is_default_out.
    Returns (None, None) on failure.
    """
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
            continue  # skip PortAudio debug noise

        if line.startswith("Device index:"):
            if cur is not None:
                devices.append(cur)
            cur = {
                "index": None, "name": "", "rate": 0,
                "in_ch": 0, "out_ch": 0, "host_api": "",
                "is_default_in": False, "is_default_out": False,
            }
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
    """Escape a string for a TOML basic (double-quoted) string."""
    if value is None:
        return '""'
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % value


def build_toml(cfg):
    """Return the FlexASIO.toml text for a config dict.

    cfg keys:
      backend, buffer_size, and 'input'/'output' sub-dicts with
      device, channels, sample_type, latency, exclusive, autoconvert,
      explicit_sample_format.
    """
    backend = cfg.get("backend", "Windows WASAPI")
    lines = []
    lines.append('backend = %s' % _toml_str(backend))

    buf = cfg.get("buffer_size")
    if buf not in (None, ""):
        lines.append("bufferSizeSamples = %s" % int(buf))
    lines.append("")

    for section in ("input", "output"):
        s = cfg.get(section, {})
        lines.append("[%s]" % section)

        device = s.get("device", "")
        lines.append("device = %s" % _toml_str(device))

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


CONFIG_PATH = os.path.join(os.path.expanduser("~"), "FlexASIO.toml")

SAMPLE_TYPES = ["Float32", "Int32", "Int24", "Int16"]


# ---------------------------------------------------------------------------
# Gradient helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _draw_gradient(canvas, x1, y1, x2, y2, c1, c2, steps=80):
    """Fill a rectangle with a horizontal c1 -> c2 gradient."""
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


class FlexASIOGUI:
    # Rich navy/indigo palette — no flat black.
    BG = "#0a1128"          # deep navy window background
    BG_GRAD_1 = "#0c1533"   # header gradient start
    BG_GRAD_2 = "#1a2a55"   # header gradient end
    PANEL = "#141d38"       # section panel surface
    PANEL_EDGE = "#223058"
    FIELD = "#0a1325"       # input well
    FG = "#ffffff"          # pure white text
    MUTED = "#8ea0c0"       # slate secondary text
    CYAN = "#22d3ee"        # input accent
    GREEN = "#34d399"       # output / save accent
    PURPLE = "#a78bfa"      # brand accent
    DANGER = "#f87171"

    def __init__(self, root):
        self.root = root
        self.root.title("FlexASIO Config")
        self.root.configure(bg=self.BG)
        self.root.geometry("900x760")
        self.root.minsize(780, 620)

        self.host_apis = []
        self.devices = []

        self._build_style()
        self._build_ui()
        self.rescan()

    # -- styling ------------------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure(
            "TLabel", background=self.BG, foreground=self.FG,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Panel.TLabel", background=self.PANEL, foreground=self.FG,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel", background=self.BG, foreground=self.MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "TCombobox",
            fieldbackground=self.FIELD, background=self.FIELD,
            foreground=self.FG, arrowcolor=self.FG,
            bordercolor=self.PANEL_EDGE, lightcolor=self.FIELD,
            darkcolor=self.FIELD, insertcolor=self.FG,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.FIELD)],
            foreground=[("readonly", self.FG)],
            selectbackground=[("readonly", "#1c2a4a")],
            selectforeground=[("readonly", self.FG)],
        )
        style.configure(
            "TEntry",
            fieldbackground=self.FIELD, foreground=self.FG,
            insertcolor=self.FG, bordercolor=self.PANEL_EDGE,
            lightcolor=self.FIELD, darkcolor=self.FIELD,
        )
        style.configure(
            "TCheckbutton", background=self.PANEL, foreground=self.FG,
            font=("Segoe UI", 9),
        )
        style.map(
            "TCheckbutton",
            background=[("active", self.PANEL)],
            foreground=[("active", self.FG)],
        )
        style.configure(
            "Save.TButton", background=self.GREEN, foreground="#06231a",
            font=("Segoe UI", 10, "bold"), borderwidth=0,
            focuscolor=self.GREEN, padding=(14, 6),
        )
        style.map(
            "Save.TButton",
            background=[("active", "#4ce0a7")],
        )
        style.configure(
            "Ghost.TButton", background=self.PANEL, foreground=self.FG,
            borderwidth=0, focuscolor=self.PANEL, padding=(12, 6),
        )
        style.map(
            "Ghost.TButton",
            background=[("active", "#223058")],
        )

    # -- UI construction ----------------------------------------------------
    def _build_ui(self):
        # ---- gradient header ----
        self.header = tk.Canvas(
            self.root, height=76, bg=self.BG_GRAD_1,
            highlightthickness=0,
        )
        self.header.pack(fill="x")
        self.header.bind(
            "<Configure>",
            lambda e: self._paint_header(e.width),
        )

        # ---- stats + backend / buffer row ----
        controls = ttk.Frame(self.root, style="TFrame")
        controls.pack(fill="x", padx=16, pady=(14, 4))

        ttk.Label(controls, text="Backend", style="TLabel").pack(side="left")
        self.backend_var = tk.StringVar()
        self.backend_box = ttk.Combobox(
            controls, textvariable=self.backend_var, state="readonly", width=28
        )
        self.backend_box.pack(side="left", padx=(6, 20))

        ttk.Label(controls, text="Buffer (samples)", style="TLabel").pack(
            side="left"
        )
        self.buffer_var = tk.StringVar(value="480")
        ttk.Entry(controls, textvariable=self.buffer_var, width=8).pack(
            side="left", padx=(6, 0)
        )

        # ---- action buttons ----
        btns = ttk.Frame(self.root, style="TFrame")
        btns.pack(fill="x", padx=16, pady=(6, 10))
        ttk.Button(
            btns, text="Rescan devices", style="Ghost.TButton",
            command=self.rescan,
        ).pack(side="left")
        ttk.Button(
            btns, text="Load existing", style="Ghost.TButton",
            command=self.load_existing,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            btns, text="Save config", style="Save.TButton",
            command=self.save_config,
        ).pack(side="right")

        # ---- input / output columns ----
        cols = ttk.Frame(self.root, style="TFrame")
        cols.pack(fill="both", expand=True, padx=16, pady=4)

        self.input_section = self._build_section(cols, "INPUT", self.CYAN)
        self.output_section = self._build_section(cols, "OUTPUT", self.GREEN)

        # Wire live updates.
        self.backend_var.trace_add("write", self.on_backend_change)
        self.buffer_var.trace_add("write", self.update_preview)
        for sec in (self.input_section, self.output_section):
            sec["dev_var"].trace_add("write", self.update_preview)
            sec["ch_var"].trace_add("write", self.update_preview)
            sec["st_var"].trace_add("write", self.update_preview)
            sec["lat_var"].trace_add("write", self.update_preview)
            sec["excl_var"].trace_add("write", self.update_preview)
            sec["conv_var"].trace_add("write", self.update_preview)
            sec["expl_var"].trace_add("write", self.update_preview)

        # ---- TOML preview ----
        prev_frame = ttk.Frame(self.root, style="Panel.TFrame")
        prev_frame.pack(fill="both", expand=True, padx=16, pady=(8, 8))
        self._paint_section_strip(
            prev_frame, "PREVIEW", self.PURPLE, "Consolas", 10
        )

        self.preview = tk.Text(
            prev_frame, height=9, bg=self.FIELD, fg="#c8d6f0",
            insertbackground=self.FG, relief="flat", bd=0,
            font=("Consolas", 10), wrap="none", padx=12, pady=8,
        )
        self.preview.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # ---- status bar ----
        self.status = tk.Label(
            self.root, text="", bg=self.BG, fg=self.MUTED,
            anchor="w", font=("Segoe UI", 9), padx=16, pady=5,
        )
        self.status.pack(fill="x", side="bottom")

    def _paint_header(self, width):
        self.header.delete("all")
        _draw_gradient(
            self.header, 0, 0, width, 76, self.BG_GRAD_1, self.BG_GRAD_2
        )
        # Neon accent hairline at the bottom edge.
        self.header.create_line(
            0, 74, width, 74, fill=self.CYAN, width=2
        )
        self.header.create_text(
            24, 30, anchor="w", text="FLEXASIO  CONFIG",
            fill=self.FG, font=("Segoe UI", 20, "bold"),
        )
        self.header.create_text(
            24, 56, anchor="w",
            text="ASIO driver configuration  ·  writes " + CONFIG_PATH,
            fill=self.MUTED, font=("Segoe UI", 9),
        )

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
        _draw_gradient(canvas, 0, 0, width, 30, accent, self.PANEL, steps=60)
        canvas.create_text(
            14, 15, anchor="w", text=title, fill=self.FG,
            font=(font_fam, font_sz, "bold"),
        )

    def _build_section(self, parent, title, accent):
        panel = ttk.Frame(parent, style="Panel.TFrame")
        panel.pack(side="left", fill="both", expand=True, padx=(0, 6))

        self._paint_section_strip(panel, title, accent, "Segoe UI", 11)

        body = ttk.Frame(panel, style="Panel.TFrame")
        body.pack(fill="x", padx=14, pady=10)

        # Device
        ttk.Label(body, text="Device", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", pady=4
        )
        dev_var = tk.StringVar()
        dev_box = ttk.Combobox(
            body, textvariable=dev_var, state="readonly", width=34
        )
        dev_box.grid(row=0, column=1, sticky="ew", pady=4)

        # Channels
        ttk.Label(body, text="Channels", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", pady=4
        )
        ch_var = tk.StringVar(value="")
        ttk.Entry(body, textvariable=ch_var, width=8).grid(
            row=1, column=1, sticky="w", pady=4
        )

        # Sample type
        ttk.Label(body, text="Sample type", style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=4
        )
        st_var = tk.StringVar(value="Float32")
        st_box = ttk.Combobox(
            body, textvariable=st_var, state="readonly", width=12,
            values=SAMPLE_TYPES,
        )
        st_box.grid(row=2, column=1, sticky="w", pady=4)

        # Latency
        ttk.Label(body, text="Latency (s)", style="Panel.TLabel").grid(
            row=3, column=0, sticky="w", pady=4
        )
        lat_var = tk.StringVar(value="0.0")
        ttk.Entry(body, textvariable=lat_var, width=8).grid(
            row=3, column=1, sticky="w", pady=4
        )

        # Checkboxes
        excl_var = tk.BooleanVar(value=False)
        conv_var = tk.BooleanVar(value=True)
        expl_var = tk.BooleanVar(value=False)
        chk = ttk.Frame(body, style="Panel.TFrame")
        chk.grid(row=4, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Checkbutton(chk, text="Exclusive", variable=excl_var).pack(
            anchor="w"
        )
        ttk.Checkbutton(chk, text="Auto-convert", variable=conv_var).pack(
            anchor="w"
        )
        ttk.Checkbutton(
            chk, text="Explicit sample format", variable=expl_var
        ).pack(anchor="w")

        body.columnconfigure(1, weight=1)

        return {
            "dev_var": dev_var,
            "dev_box": dev_box,
            "ch_var": ch_var,
            "st_var": st_var,
            "lat_var": lat_var,
            "excl_var": excl_var,
            "conv_var": conv_var,
            "expl_var": expl_var,
            "kind": title.lower(),
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
                     "installed? Device lists are empty.", fg=self.DANGER
            )
        else:
            self.host_apis = host_apis
            self.devices = devices
            self.status.config(
                text="Found %d devices across %d backends."
                     % (len(devices), len(host_apis)), fg=self.MUTED
            )

        self.backend_box["values"] = self.host_apis
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

        in_choices = ["(disabled)"] + [d["name"] for d in in_devs]
        out_choices = ["(disabled)"] + [d["name"] for d in out_devs]

        self.input_section["dev_box"]["values"] = in_choices
        self.output_section["dev_box"]["values"] = out_choices

        if not self.output_section["dev_var"].get():
            default_out = next(
                (d["name"] for d in out_devs if d["is_default_out"]), None
            )
            if default_out:
                self.output_section["dev_var"].set(default_out)
            elif out_choices:
                self.output_section["dev_var"].set(out_choices[0])

    def on_backend_change(self, *_):
        self._populate_device_boxes()
        self.update_preview()

    # -- config read/write --------------------------------------------------
    def _read_section(self, s):
        dev = s["dev_var"].get()
        if dev == "(disabled)":
            dev = ""
        return {
            "device": dev,
            "channels": s["ch_var"].get().strip() or None,
            "sample_type": s["st_var"].get(),
            "latency": s["lat_var"].get().strip() or None,
            "exclusive": s["excl_var"].get(),
            "autoconvert": s["conv_var"].get(),
            "explicit_sample_format": s["expl_var"].get(),
        }

    def _collect(self):
        return {
            "backend": self.backend_var.get(),
            "buffer_size": self.buffer_var.get().strip() or None,
            "input": self._read_section(self.input_section),
            "output": self._read_section(self.output_section),
        }

    def update_preview(self, *_):
        cfg = self._collect()
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", build_toml(cfg))

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
                text="Saved and verified: " + CONFIG_PATH, fg=self.GREEN
            )
        else:
            self.status.config(
                text="Saved, but read-back mismatch — check the file.",
                fg=self.DANGER,
            )

    def load_existing(self):
        if not os.path.isfile(CONFIG_PATH):
            self.status.config(
                text="No existing config at " + CONFIG_PATH, fg=self.MUTED
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
                    self.buffer_var.set(val)
                continue

            s = (self.input_section if section == "input"
                 else self.output_section if section == "output" else None)
            if s is None:
                continue
            if key == "device":
                s["dev_var"].set(val if val else "(disabled)")
            elif key == "channels":
                s["ch_var"].set(val)
            elif key == "sampleType":
                s["st_var"].set(val)
            elif key == "suggestedLatencySeconds":
                s["lat_var"].set(val)
            elif key == "wasapiExclusiveMode":
                s["excl_var"].set(val == "true")
            elif key == "wasapiAutoConvert":
                s["conv_var"].set(val == "true")
            elif key == "wasapiExplicitSampleFormat":
                s["expl_var"].set(val == "true")

        self._populate_device_boxes()
        self.update_preview()
        self.status.config(text="Loaded " + CONFIG_PATH, fg=self.MUTED)


def main():
    root = tk.Tk()
    FlexASIOGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
