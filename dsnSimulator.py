"""Tkinter desktop simulator. No hardware driver or OMS implementation."""
import argparse
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dsnSimulatorCore import DEMO_INTERVAL_MS, Simulator


class SimulatorWindow:
    def __init__(self, root):
        self.root = root
        self.model = Simulator()
        self.next_sample = 0
        self.root.title("Jack Marino — ADC Simulator")
        self.root.geometry("940x740")
        self.root.minsize(820, 670)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.mode = tk.StringVar(value="Simulator")
        self.value = tk.DoubleVar(value=150)
        self.pause = tk.BooleanVar(value=False)
        self.info = tk.StringVar(value="Ready. Choose Start to generate simulated readings.")
        outer = ttk.Frame(root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="ADC Acquisition Simulator", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(outer, text="SIMULATED DATA ONLY  •  Hardware: TBD  •  OMS: Proposed  •  Human review: Pending").pack(anchor="w", pady=(3, 14))
        modes = ttk.LabelFrame(outer, text="1. Choose a mode (stop before switching)", padding=10)
        modes.pack(fill="x")
        self.mode_buttons = []
        for label in ("Simulator", "Replay", "Live Hardware"):
            b = ttk.Radiobutton(modes, text=label + (" — unavailable" if label == "Live Hardware" else ""),
                                value=label, variable=self.mode, command=self.change_mode)
            b.pack(side="left", padx=(0, 22))
            if label == "Live Hardware":
                b.state(["disabled"])
            else:
                self.mode_buttons.append(b)
        simulation = ttk.LabelFrame(outer, text="2. Simulator controls", padding=10)
        simulation.pack(fill="x", pady=10)
        row = ttk.Frame(simulation)
        row.pack(fill="x")
        self.start_button = ttk.Button(row, text="Start", command=self.start)
        self.start_button.pack(side="left")
        ttk.Button(row, text="Stop", command=self.stop).pack(side="left", padx=8)
        self.pause_button = ttk.Checkbutton(row, text="Pause simulated input (status keeps running)", variable=self.pause, command=self.pause_input)
        self.pause_button.pack(side="left", padx=12)
        self.slider_label = ttk.Label(simulation, text="Synthetic ADC code: 150 (not a voltage)")
        self.slider_label.pack(anchor="w", pady=(10, 0))
        self.slider = ttk.Scale(simulation, from_=0, to=255, variable=self.value, command=self.slider_changed)
        self.slider.pack(fill="x", pady=6)
        ttk.Label(simulation, text="Demo: 20 samples/s • 128-record buffer, drop oldest visibly • stale after 100 ms without publication",
                  wraplength=850).pack(anchor="w")
        files = ttk.LabelFrame(outer, text="3. Recording and replay", padding=10)
        files.pack(fill="x")
        actions = [("Start Recording…", self.record), ("Stop Recording", self.stop_recording),
                   ("Open Recording…", self.open_recording), ("Play", self.play),
                   ("Pause Replay", self.pause_replay), ("Stop Replay", self.stop)]
        self.file_buttons = {}
        for i, (label, action) in enumerate(actions):
            b = ttk.Button(files, text=label, command=action)
            b.grid(row=0, column=i, padx=3, pady=3)
            self.file_buttons[label] = b
        self.file_label = ttk.Label(files, text="No recording loaded. Replay uses 20 records/s demo pacing; original times remain unchanged.", wraplength=850)
        self.file_label.grid(row=1, column=0, columnspan=6, sticky="w", pady=(7, 0))
        status = ttk.LabelFrame(outer, text="Current output", padding=10)
        status.pack(fill="both", expand=True, pady=10)
        self.fields = {}
        for i, name in enumerate(("Mode / source", "Status / validity", "ADC code / sequence", "Timestamp / timing quality",
                                  "Sample age", "Session", "Connection / recording", "Loss / error")):
            ttk.Label(status, text=name + ":", width=27).grid(row=i, column=0, sticky="nw", pady=3)
            variable = tk.StringVar(value="—")
            ttk.Label(status, textvariable=variable, wraplength=610).grid(row=i, column=1, sticky="nw", pady=3)
            self.fields[name] = variable
        status.columnconfigure(1, weight=1)
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Settings…", command=self.settings).pack(side="left")
        ttk.Label(bottom, textvariable=self.info, wraplength=710).pack(side="left", padx=12)
        self.tick()

    def guard(self, action):
        try:
            action()
        except (OSError, ValueError, PermissionError) as exc:
            self.info.set(str(exc))
            messagebox.showerror("ADC Simulator", str(exc), parent=self.root)
        self.refresh()

    def change_mode(self):
        self.guard(lambda: self.model.set_mode(self.mode.get()))
        self.mode.set(self.model.mode)

    def slider_changed(self, _=None):
        self.slider_label.configure(text=f"Synthetic ADC code: {round(self.value.get())} (not a voltage)")

    def start(self):
        def action():
            self.model.start()
            self.pause.set(False)
            self.next_sample = 0
            self.info.set("Simulator running. Move the slider or pause input to observe stale status.")
        self.guard(action)

    def stop(self):
        self.model.stop()
        self.pause.set(False)
        self.info.set("Stopped. Recording closed; modes can now be changed.")
        self.refresh()

    def pause_input(self):
        self.model.input_paused = self.pause.get()

    def record(self):
        if not self.model.running or self.model.mode != "Simulator":
            self.guard(lambda: self.model.begin_recording(""))
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Save a NEW simulator recording (existing files are protected)",
                                          defaultextension=".jsonl", filetypes=[("JSON Lines", "*.jsonl")], initialfile="adc-simulator.jsonl")
        if path:
            self.guard(lambda: self.model.begin_recording(path))
            if self.model.writer:
                self.file_label.configure(text=f"Recording: {path}")
                self.info.set("Recording simulated source data; use a new filename for each recording.")

    def stop_recording(self):
        self.model.end_recording()
        self.info.set("Recording stopped and file closed.")
        self.refresh()

    def open_recording(self):
        if self.model.running:
            self.info.set("Stop the current activity before opening a recording.")
            return
        path = filedialog.askopenfilename(parent=self.root, title="Open simulator recording", filetypes=[("JSON Lines", "*.jsonl"), ("All files", "*.*")])
        if path:
            self.guard(lambda: self.model.open_recording(path))
            self.mode.set(self.model.mode)
            if self.model.replay_path == Path(path):
                self.file_label.configure(text=f"Loaded for REPLAY: {path}")
                self.info.set("Recording loaded. Choose Play; original source is simulated, output mode is Replay.")

    def play(self):
        self.guard(self.model.play)
        self.next_sample = 0

    def pause_replay(self):
        self.model.pause_replay()
        self.refresh()

    def settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings — simulator profile / hardware TBD")
        dialog.transient(self.root)
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Software demonstration profile", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(body, text="20 simulated samples/s; 128 records; drop-oldest with visible loss.\nReplay: 20 records/s, original metadata unchanged.\n100 ms stale target is exercised by software only.\nThese are demonstration defaults, not hardware allocations.\n\nProtected acquisition changes: unavailable.\nIdentity/access policy, real device settings and timing capture: TBD.\nOMS: Proposed. Human review: Pending.", wraplength=520).pack(anchor="w", pady=12)
        ttk.Button(body, text="Close", command=dialog.destroy).pack(anchor="e")

    def refresh(self):
        m = self.model
        sample = m.current
        self.fields["Mode / source"].set(f"{m.mode.upper()} / " + ("recorded SIMULATOR data" if m.mode == "Replay" else "SIMULATOR ONLY"))
        self.fields["Status / validity"].set(m.status + (f"; recorded validity: {sample.validity}" if sample else ""))
        self.fields["ADC code / sequence"].set(f"{sample.code} / {sample.sequence}" if sample else "No sample")
        self.fields["Timestamp / timing quality"].set(f"{sample.timestamp_ns} ns / {sample.timing_quality} (not ADC timing)" if sample else "Unknown / unavailable")
        age = "N/A in Replay — original timestamp preserved" if m.mode == "Replay" else (f"{max(0, (m.clock()-sample.timestamp_ns)/1e6):.0f} ms (simulated event)" if sample else "Unknown")
        self.fields["Sample age"].set(age)
        self.fields["Session"].set(sample.session_id if sample else (m.session_id or "Not started"))
        self.fields["Connection / recording"].set("No hardware connection; " + ("RECORDING" if m.writer else "not recording"))
        self.fields["Loss / error"].set(f"Demo buffer loss: {m.loss}; replay gap count: {m.replay_gaps}. {m.error or 'No reported error.'}")
        for b in self.mode_buttons:
            b.state(["disabled"] if m.running else ["!disabled"])
        sim = m.mode == "Simulator"
        self.start_button.state(["!disabled"] if sim and not m.running else ["disabled"])
        self.slider.state(["!disabled"] if sim else ["disabled"])
        self.pause_button.state(["!disabled"] if sim and m.running else ["disabled"])
        for name in ("Play", "Pause Replay", "Stop Replay"):
            self.file_buttons[name].state(["!disabled"] if not sim else ["disabled"])
        self.file_buttons["Start Recording…"].state(["!disabled"] if sim and m.running and not m.writer else ["disabled"])
        self.file_buttons["Stop Recording"].state(["!disabled"] if m.writer else ["disabled"])
        self.file_buttons["Open Recording…"].state(["disabled"] if m.running else ["!disabled"])

    def tick(self):
        now = time.monotonic_ns()
        if self.model.running and now >= self.next_sample:
            if self.model.mode == "Simulator":
                self.model.generate(round(self.value.get()))
                self.model.publish()
            else:
                self.model.replay_next()
            self.next_sample = now + DEMO_INTERVAL_MS * 1_000_000
        self.refresh()
        self.root.after(20, self.tick)

    def close(self):
        self.model.stop()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true", help="Create window, exercise controls and exit without hardware.")
    args = parser.parse_args()
    root = tk.Tk()
    window = SimulatorWindow(root)
    if args.smoke_test:
        window.start()
        root.after(180, lambda: (window.pause.set(True), window.pause_input()))
        root.after(400, lambda: print("GUI smoke:", window.model.status, flush=True))
        root.after(450, window.close)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except tk.TclError as exc:
        print(f"Tkinter could not start: {exc}\nUse a Python 3 installation with working Tcl/Tk. No hardware is required.", file=sys.stderr)
        raise SystemExit(1)
