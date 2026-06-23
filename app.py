"""GUI launcher for the horror/history video pipeline."""

import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

APP_DIR = Path(__file__).resolve().parent
PIPELINE = APP_DIR / "pipeline.py"
DEFAULT_VOICE_ID = "Uh6UEmMIUnnL0GOOUghh"


class PipelineApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Horror Pipeline")
        self.resizable(False, False)
        self._running = False
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        P = 12  # standard padding

        # ── Options frame ─────────────────────────────────────────────────────
        opt = ttk.LabelFrame(self, text=" Options ", padding=P)
        opt.grid(row=0, column=0, padx=P, pady=(P, 0), sticky="ew")
        opt.columnconfigure(1, weight=1)

        # Mode
        ttk.Label(opt, text="Mode").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 16))
        self.mode_var = tk.StringVar(value="both")
        mode_row = ttk.Frame(opt)
        mode_row.grid(row=0, column=1, sticky="w")
        for val, label in [("horror", "Horror"), ("history", "Dark History"), ("both", "Both")]:
            ttk.Radiobutton(mode_row, text=label, variable=self.mode_var, value=val).pack(
                side="left", padx=(0, 12)
            )

        # Count
        ttk.Label(opt, text="Count").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 16))
        self.count_var = tk.IntVar(value=1)
        ttk.Spinbox(opt, from_=1, to=20, textvariable=self.count_var, width=6).grid(
            row=1, column=1, sticky="w"
        )

        # Voice ID
        ttk.Label(opt, text="Voice ID").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 16))
        self.voice_var = tk.StringVar(value=DEFAULT_VOICE_ID)
        ttk.Entry(opt, textvariable=self.voice_var, width=36).grid(row=2, column=1, sticky="w")

        # Checkboxes
        checks = ttk.Frame(opt)
        checks.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.dry_run_var = tk.BooleanVar()
        self.keep_temp_var = tk.BooleanVar()
        self.verbose_var = tk.BooleanVar()
        ttk.Checkbutton(checks, text="Dry Run", variable=self.dry_run_var).pack(
            side="left", padx=(0, 16)
        )
        ttk.Checkbutton(checks, text="Keep Temp Files", variable=self.keep_temp_var).pack(
            side="left", padx=(0, 16)
        )
        ttk.Checkbutton(checks, text="Verbose Logging", variable=self.verbose_var).pack(side="left")

        # Optional script file
        ttk.Label(opt, text="Script File").grid(
            row=4, column=0, sticky="w", pady=(10, 0), padx=(0, 16)
        )
        sf = ttk.Frame(opt)
        sf.grid(row=4, column=1, sticky="ew", pady=(10, 0))
        self.script_var = tk.StringVar()
        ttk.Entry(sf, textvariable=self.script_var, width=30).pack(side="left")
        ttk.Button(sf, text="Browse…", command=self._browse_script, width=9).pack(
            side="left", padx=(6, 0)
        )

        # ── Generate button ───────────────────────────────────────────────────
        self.gen_btn = ttk.Button(self, text="Generate", command=self._on_generate, width=22)
        self.gen_btn.grid(row=1, column=0, pady=P)

        # ── Output log ────────────────────────────────────────────────────────
        log_frame = ttk.LabelFrame(self, text=" Output ", padding=(P, 4))
        log_frame.grid(row=2, column=0, padx=P, pady=(0, P), sticky="nsew")

        self.log_area = scrolledtext.ScrolledText(
            log_frame,
            width=76,
            height=22,
            state="disabled",
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
            relief="flat",
        )
        self.log_area.pack(fill="both", expand=True)
        self.log_area.tag_config("error", foreground="#f48771")
        self.log_area.tag_config("success", foreground="#89d185")
        self.log_area.tag_config("dim", foreground="#808080")

        ttk.Button(log_frame, text="Clear", command=self._clear_log, width=8).pack(
            anchor="e", pady=(6, 0)
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _browse_script(self):
        path = filedialog.askopenfilename(
            title="Select script file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=str(APP_DIR),
        )
        if path:
            self.script_var.set(path)

    def _clear_log(self):
        self.log_area.configure(state="normal")
        self.log_area.delete("1.0", tk.END)
        self.log_area.configure(state="disabled")

    def _append(self, text: str, tag: str = "") -> None:
        """Thread-safe write to the log area."""
        def _do():
            self.log_area.configure(state="normal")
            self.log_area.insert(tk.END, text, tag)
            self.log_area.configure(state="disabled")
            self.log_area.see(tk.END)
        self.after(0, _do)

    # ── Pipeline execution ────────────────────────────────────────────────────

    def _on_generate(self):
        if self._running:
            return

        script_path = self.script_var.get().strip()
        if script_path and not Path(script_path).exists():
            messagebox.showerror("File not found", f"Script file not found:\n{script_path}")
            return

        cmd = [sys.executable, str(PIPELINE)]
        cmd += ["--mode", self.mode_var.get()]
        cmd += ["--count", str(self.count_var.get())]
        voice = self.voice_var.get().strip()
        if voice:
            cmd += ["--voice", voice]
        if self.dry_run_var.get():
            cmd.append("--dry-run")
        if self.keep_temp_var.get():
            cmd.append("--keep-temp")
        if self.verbose_var.get():
            cmd.append("--verbose")
        if script_path:
            cmd += ["--script", script_path]

        self._clear_log()
        self._append(" ".join(cmd) + "\n\n", "dim")

        self._running = True
        self.gen_btn.configure(state="disabled", text="Running…")
        threading.Thread(target=self._stream, args=(cmd,), daemon=True).start()

    def _stream(self, cmd: list[str]) -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(APP_DIR),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                tag = "error" if "[ERROR]" in line else ""
                self._append(line, tag)
            proc.wait()
            if proc.returncode == 0:
                self._append("\nFinished successfully.\n", "success")
            else:
                self._append(f"\nExited with code {proc.returncode}.\n", "error")
        except Exception as exc:
            self._append(f"\nCould not start pipeline: {exc}\n", "error")
        finally:
            self.after(0, self._on_done)

    def _on_done(self):
        self._running = False
        self.gen_btn.configure(state="normal", text="Generate")


if __name__ == "__main__":
    app = PipelineApp()
    app.mainloop()
