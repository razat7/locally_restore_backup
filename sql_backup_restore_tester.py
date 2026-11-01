import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
import subprocess
import threading
import queue
import tempfile
import os
import re
import csv
import json
import time
from datetime import datetime


APP_TITLE = "SQL Backup Restore"
MYSQL_DEFAULT = r"D:\xamp\mysql\bin\mysql.exe"
DEFAULT_DROP_PASSWORD = "SWa9md4E#2083"
DEFAULT_SQL_SETTINGS = {
    "mysql": MYSQL_DEFAULT,
    "host": "127.0.0.1",
    "port": "3306",
    "user": "root",
    "password": "",
    "timeout": "1800",
}


def get_app_data_folder():
    appdata = Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"))
    folder = appdata / "SQLBackupRestore"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_drop_password_file():
    return get_app_data_folder() / ".drop_password"


def get_sql_settings_file():
    return get_app_data_folder() / ".mysql_settings.json"


DROP_PASSWORD_FILE = get_drop_password_file()
DB_NAME_PATTERN = r"[A-Za-z0-9_$-]{1,64}"


class RestoreApp(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("1200x780")
        self.minsize(980, 620)
        try:
            self.state("zoomed")
        except Exception:
            pass

        self.screen_scale = 1.0
        self.error_text = None
        self.bind("<Configure>", self._apply_screen_compatibility)

        self.events = queue.Queue()
        self.files = []
        self.results = {}
        self.row_paths = {}
        self.worker = None
        self.stop_event = threading.Event()
        self.skip_event = threading.Event()
        self.current_process = None

        saved_sql_settings = self.load_sql_settings()

        self.folder_var = tk.StringVar()
        self.mysql_var = tk.StringVar(value=saved_sql_settings.get("mysql", MYSQL_DEFAULT))
        self.host_var = tk.StringVar(value=saved_sql_settings.get("host", "127.0.0.1"))
        self.port_var = tk.StringVar(value=str(saved_sql_settings.get("port", "3306")))
        self.user_var = tk.StringVar(value=saved_sql_settings.get("user", "root"))
        self.password_var = tk.StringVar(value=saved_sql_settings.get("password", ""))
        self.timeout_var = tk.StringVar(value=str(saved_sql_settings.get("timeout", "1800")))
        self.progress_var = tk.DoubleVar(value=0)
        self.status_var = tk.StringVar(value="Ready")
        self.eta_var = tk.StringVar(value="ETA --")
        self.progress_loading = False
        self.drop_password = self.load_drop_password()

        self.build_ui()

        self.after(100, self.process_events)
        self.protocol("WM_DELETE_WINDOW", self.close_app)

    # ---------------- UI ----------------

    def build_ui(self):

        self.configure(bg="#edf2f7")

        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            ".",
            background="#edf2f7",
            foreground="#162033",
            font=("Segoe UI", 10)
        )
        style.configure(
            "TLabelframe",
            background="#ffffff",
            foreground="#162033"
        )
        style.configure(
            "TLabelframe.Label",
            background="#ffffff",
            foreground="#162033",
            font=("Segoe UI", 10, "bold")
        )
        style.configure(
            "TButton",
            padding=(10, 7),
            font=("Segoe UI", 9, "bold")
        )
        style.map(
            "TButton",
            background=[
                ("active", "#dfe9f5"),
                ("pressed", "#cfe0f6")
            ],
            foreground=[("active", "#0f172a")]
        )
        style.configure("Primary.TButton", background="#2563eb", foreground="white")
        style.map("Primary.TButton", background=[("active", "#1d4ed8")], foreground=[("active", "white")])
        style.configure("Danger.TButton", background="#dc2626", foreground="white")
        style.map("Danger.TButton", background=[("active", "#b91c1c")], foreground=[("active", "white")])
        style.configure("Warning.TButton", background="#f59e0b", foreground="black")
        style.map("Warning.TButton", background=[("active", "#d97706")], foreground=[("active", "black")])
        style.configure("Success.TButton", background="#16a34a", foreground="white")
        style.map("Success.TButton", background=[("active", "#15803d")], foreground=[("active", "white")])

        style.configure(
            "Horizontal.TProgressbar",
            thickness=18,
            background="#2563eb",
            troughcolor="#dfe7f3",
            bordercolor="#c8d4ea"
        )

        canvas = tk.Canvas(self, bg="#edf2f7", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        main = ttk.Frame(canvas, padding=12)
        window = canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window, width=e.width))

        ttk.Label(
            main,
            text="SQL Backup Restore",
            font=("Segoe UI", 19, "bold")
        ).pack(anchor="w")

        ttk.Label(
            main,
            text="Local MySQL/MariaDB backup restoration and testing",
            foreground="gray"
        ).pack(anchor="w", pady=(0, 12))

        # Connection settings

        connection = ttk.LabelFrame(
            main,
            text="MySQL Connection",
            padding=10
        )
        connection.pack(fill="x", pady=5)

        action_row = tk.Frame(connection, bg="#ffffff")
        action_row.pack(fill="x")

        tk.Button(
            action_row,
            text="Config",
            command=self.open_connection_config_dialog,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="left")

        tk.Button(
            action_row,
            text="Test Connection",
            command=self.test_connection,
            bg="#0f172a",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            action_row,
            text="View Databases",
            command=self.list_databases,
            bg="#e2e8f0",
            fg="#0f172a",
            font=("Segoe UI", 10, "bold"),
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            action_row,
            text="Change Drop Password",
            command=self.change_drop_password,
            bg="#f59e0b",
            fg="#111827",
            font=("Segoe UI", 10, "bold"),
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="left", padx=(8, 0))

        tk.Label(
            action_row,
            text="Stored locally and reused on startup.",
            bg="#ffffff",
            fg="#475569",
            font=("Segoe UI", 9, "italic")
        ).pack(side="left", padx=(18, 0))

        # Backup folder

        folder = ttk.LabelFrame(
            main,
            text="Backup Folder",
            padding=10
        )
        folder.pack(fill="x", pady=5)

        ttk.Entry(
            folder,
            textvariable=self.folder_var
        ).pack(side="left", fill="x", expand=True)

        ttk.Button(
            folder,
            text="Select Folder",
            command=self.select_folder
        ).pack(side="left", padx=5)

        ttk.Button(
            folder,
            text="Refresh",
            command=self.load_files
        ).pack(side="left")

        # Backup list

        list_frame = ttk.LabelFrame(
            main,
            text="SQL Backup Files",
            padding=8
        )
        list_frame.pack(fill="both", expand=True, pady=5)

        columns = (
            "filename",
            "size",
            "database",
            "status",
            "duration"
        )

        self.tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            selectmode="extended"
        )

        headings = {
            "filename": "Backup File",
            "size": "Size",
            "database": "Detected Database",
            "status": "Status",
            "duration": "Duration"
        }

        widths = {
            "filename": 350,
            "size": 100,
            "database": 230,
            "status": 110,
            "duration": 100
        }

        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col])

        self.tree.tag_configure(
            "PASS", foreground="green"
        )

        self.tree.tag_configure(
            "FAIL", foreground="red"
        )

        self.tree.tag_configure(
            "RUNNING", foreground="blue"
        )

        scrollbar = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=self.tree.yview
        )

        self.tree.configure(
            yscrollcommand=scrollbar.set
        )

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind(
            "<<TreeviewSelect>>",
            self.show_error
        )

        # Buttons

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=8)

        ttk.Button(
            buttons,
            text="Select All",
            command=self.select_all
        ).pack(side="left", padx=5)

        ttk.Button(
            buttons,
            text="Restore All",
            command=self.restore_all,
            style="Success.TButton"
        ).pack(side="left", padx=5)

        ttk.Button(
            buttons,
            text="Restore Selected",
            command=self.restore_selected,
            style="Primary.TButton",
        ).pack(side="left", padx=5)

        ttk.Button(
            buttons,
            text="Retry Failed",
            command=self.retry_failed,
            style="Warning.TButton"
        ).pack(side="left")

        ttk.Button(
            buttons,
            text="Export Report",
            command=self.export_report
        ).pack(side="right")

        ttk.Button(
            buttons,
            text="Browse Error Logs",
            command=self.browse_error_logs
        ).pack(side="right", padx=5)

        self.stop_button = ttk.Button(
            buttons,
            text="Stop After Current",
            command=self.stop_restore,
            state="disabled"
        )
        self.stop_button.pack(side="right", padx=5)

        # Progress

        progress_frame = ttk.Frame(main)
        progress_frame.pack(fill="x", pady=5)

        self.progress = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate"
        )

        self.progress.pack(
            side="left",
            fill="x",
            expand=True
        )

        self.percent_label = ttk.Label(
            progress_frame,
            text="0%",
            width=7,
            font=("Segoe UI", 11, "bold")
        )
        self.percent_label.pack(side="left", padx=(0, 8))

        self.eta_label = ttk.Label(
            progress_frame,
            textvariable=self.eta_var,
            width=12,
            font=("Segoe UI", 10, "bold")
        )
        self.eta_label.pack(side="left", padx=(0, 8))

        ctrl = ttk.Frame(progress_frame)
        ctrl.pack(side="right")
        ttk.Button(ctrl, text="Cancel", command=self.stop_restore, style="Danger.TButton").pack(side="left", padx=2)
        ttk.Button(ctrl, text="Skip", command=self.skip_restore, style="Warning.TButton").pack(side="left", padx=2)

        ttk.Label(
            main,
            textvariable=self.status_var
        ).pack(anchor="w")

        ttk.Label(
            main,
            text="Copyright @ IT DIR SW 2026",
            foreground="gray"
        ).pack(anchor="e", pady=(4, 0))

        # Error viewer

        error_frame = ttk.LabelFrame(
            main,
            text="Exact MySQL Error / Restore Output",
            padding=8
        )

        error_frame.pack(fill="both", expand=True, pady=5)

        error_header = ttk.Frame(error_frame)
        error_header.pack(fill="x", pady=(0, 6))

        ttk.Button(
            error_header,
            text="Maximize",
            command=self.maximize_error_log
        ).pack(side="right")

        self.error_text = tk.Text(
            error_frame,
            height=8,
            wrap="word",
            font=("Consolas", 9),
            bg="#111827",
            fg="white"
        )

        error_scroll = ttk.Scrollbar(
            error_frame,
            command=self.error_text.yview
        )

        self.error_text.configure(
            yscrollcommand=error_scroll.set
        )

        self.error_text.pack(side="left", fill="both", expand=True)
        error_scroll.pack(side="right", fill="y")

    @staticmethod
    def sanitize_db_name(name):
        if name is None:
            return None
        cleaned = str(name).strip().strip("`\"'")
        if re.fullmatch(DB_NAME_PATTERN, cleaned):
            return cleaned
        return None

    def add_field(self, parent, label, variable, row, col, width):

        ttk.Label(
            parent,
            text=label
        ).grid(row=row, column=col, sticky="w", padx=4)

        ttk.Entry(
            parent,
            textvariable=variable,
            width=width
        ).grid(row=row, column=col + 1, sticky="w")

    def _apply_screen_compatibility(self, event=None):
        try:
            width = self.winfo_width()
            height = self.winfo_height()
        except Exception:
            return

        if width < 1200:
            self.screen_scale = 0.95
        elif width < 1500:
            self.screen_scale = 1.0
        else:
            self.screen_scale = 1.05

        error_text = getattr(self, "error_text", None)
        if error_text is not None:
            try:
                desired_height = max(8, min(18, int(height / 26)))
                if error_text.cget("height") != str(desired_height):
                    error_text.configure(height=desired_height)
            except Exception:
                pass

    def maximize_error_log(self):
        popup = tk.Toplevel(self)
        popup.title("MySQL Error / Restore Output")
        popup.transient(self)
        popup.grab_set()
        popup.configure(bg="#111827")

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = max(880, min(screen_w - 80, int(screen_w * 0.88)))
        height = max(540, min(screen_h - 100, int(screen_h * 0.84)))
        x = max(20, (screen_w - width) // 2)
        y = max(20, (screen_h - height) // 2)
        popup.geometry(f"{width}x{height}+{x}+{y}")

        text = tk.Text(
            popup,
            wrap="word",
            font=("Consolas", 10),
            bg="#111827",
            fg="white",
            padx=12,
            pady=12
        )
        text.insert("1.0", self.error_text.get("1.0", "end"))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=10, pady=(10, 6))

        button_bar = tk.Frame(popup, bg="#111827")
        button_bar.pack(fill="x", padx=10, pady=(0, 10))

        close_btn = tk.Button(
            button_bar,
            text="Close",
            command=popup.destroy,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        )
        close_btn.pack(anchor="e")

    # ---------------- FILE MANAGEMENT ----------------

    @staticmethod
    def load_sql_settings():
        path = get_sql_settings_file()
        defaults = DEFAULT_SQL_SETTINGS.copy()
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    defaults.update({k: str(v) for k, v in data.items() if v is not None})
        except (OSError, ValueError, TypeError):
            pass
        return defaults

    @staticmethod
    def save_sql_settings(settings):
        path = get_sql_settings_file()
        payload = {
            "mysql": str(settings.get("mysql", DEFAULT_SQL_SETTINGS["mysql"])) .strip(),
            "host": str(settings.get("host", DEFAULT_SQL_SETTINGS["host"])).strip(),
            "port": str(settings.get("port", DEFAULT_SQL_SETTINGS["port"])).strip(),
            "user": str(settings.get("user", DEFAULT_SQL_SETTINGS["user"])).strip(),
            "password": str(settings.get("password", DEFAULT_SQL_SETTINGS["password"])),
            "timeout": str(settings.get("timeout", DEFAULT_SQL_SETTINGS["timeout"])).strip(),
        }
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return True
        except OSError:
            return False

    def save_connection_settings(self):
        mysql_path = self.mysql_var.get().strip()
        if not mysql_path:
            messagebox.showerror("Settings", "MySQL client path cannot be empty.")
            return False

        try:
            port = int(self.port_var.get())
            timeout = int(self.timeout_var.get())
        except ValueError:
            messagebox.showerror("Settings", "Port and timeout must be whole numbers.")
            return False

        host = self.host_var.get().strip()
        if host.lower() not in ("127.0.0.1", "localhost", "::1"):
            messagebox.showerror("Settings", "For safety, this app only allows local MySQL hosts.")
            return False

        settings = {
            "mysql": mysql_path,
            "host": host,
            "port": str(port),
            "user": self.user_var.get().strip(),
            "password": self.password_var.get(),
            "timeout": str(timeout),
        }

        if not self.save_sql_settings(settings):
            messagebox.showwarning("Settings", "The connection settings were updated in memory but could not be saved to disk.")
            self.status_var.set("Connection settings not saved.")
            return False

        self.status_var.set("MySQL connection settings saved.")
        messagebox.showinfo("Settings", "MySQL connection settings saved successfully.")
        return True

    def open_connection_config_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("MySQL Connection Settings")
        dialog.geometry("620x490")
        dialog.minsize(560, 420)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg="#eef2f7")

        body = tk.Frame(dialog, bg="#eef2f7", padx=20, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Connection settings",
            bg="#eef2f7",
            fg="#0f172a",
            font=("Segoe UI", 15, "bold")
        ).pack(anchor="w", pady=(0, 14))

        form = tk.Frame(body, bg="#eef2f7")
        form.pack(fill="both", expand=True)

        row = 0

        tk.Label(form, text="MySQL client", bg="#eef2f7", fg="#1f2937", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=8
        )
        tk.Entry(form, textvariable=self.mysql_var, width=44, font=("Segoe UI", 10), bg="white", fg="#111827").grid(
            row=row, column=1, sticky="ew", pady=8
        )
        form.grid_columnconfigure(1, weight=1)

        def browse_in_dialog():
            path = filedialog.askopenfilename(filetypes=[("MySQL client", "mysql.exe")])
            if path:
                self.mysql_var.set(path)

        tk.Button(
            form,
            text="Browse",
            command=browse_in_dialog,
            bg="#e2e8f0",
            fg="#0f172a",
            font=("Segoe UI", 9, "bold"),
            relief="raised",
            bd=1,
            padx=10,
            pady=4
        ).grid(row=0, column=2, padx=(8, 0), pady=8)

        row += 1
        tk.Label(form, text="Host", bg="#eef2f7", fg="#1f2937", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=8
        )
        tk.Entry(form, textvariable=self.host_var, width=22, font=("Segoe UI", 10), bg="white", fg="#111827").grid(
            row=row, column=1, sticky="w", pady=8
        )

        tk.Label(form, text="Port", bg="#eef2f7", fg="#1f2937", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=2, sticky="w", padx=(18, 10), pady=8
        )
        tk.Entry(form, textvariable=self.port_var, width=10, font=("Segoe UI", 10), bg="white", fg="#111827").grid(
            row=row, column=3, sticky="w", pady=8
        )

        row += 1
        tk.Label(form, text="Username", bg="#eef2f7", fg="#1f2937", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=8
        )
        tk.Entry(form, textvariable=self.user_var, width=22, font=("Segoe UI", 10), bg="white", fg="#111827").grid(
            row=row, column=1, sticky="w", pady=8
        )

        tk.Label(form, text="Timeout (sec)", bg="#eef2f7", fg="#1f2937", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=2, sticky="w", padx=(18, 10), pady=8
        )
        tk.Entry(form, textvariable=self.timeout_var, width=10, font=("Segoe UI", 10), bg="white", fg="#111827").grid(
            row=row, column=3, sticky="w", pady=8
        )

        row += 1
        tk.Label(form, text="Password", bg="#eef2f7", fg="#1f2937", font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=8
        )
        password_frame = tk.Frame(form, bg="#eef2f7")
        password_frame.grid(row=row, column=1, sticky="w", pady=8)
        password_entry = tk.Entry(password_frame, textvariable=self.password_var, show="*", width=24, font=("Segoe UI", 10), bg="white", fg="#111827")
        password_entry.pack(side="left")

        show_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            password_frame,
            text="Show",
            variable=show_var,
            bg="#eef2f7",
            fg="#0f172a",
            activebackground="#eef2f7",
            activeforeground="#0f172a",
            selectcolor="#dbeafe",
            command=lambda: password_entry.configure(show="" if show_var.get() else "*"),
            font=("Segoe UI", 9)
        ).pack(side="left", padx=(8, 0))

        tk.Label(
            body,
            text="Local-only safety: this tool only accepts 127.0.0.1, localhost, or ::1.",
            bg="#eef2f7",
            fg="#b45309",
            font=("Segoe UI", 9, "italic"),
            justify="left",
            wraplength=500
        ).pack(anchor="w", pady=(12, 0))

        button_row = tk.Frame(body, bg="#eef2f7")
        button_row.pack(fill="x", pady=(18, 0))

        tk.Button(
            button_row,
            text="Cancel",
            command=dialog.destroy,
            bg="#e5e7eb",
            fg="#111827",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right")

        def save_and_close():
            if self.save_connection_settings():
                dialog.destroy()

        tk.Button(
            button_row,
            text="Save",
            command=save_and_close,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right", padx=(0, 10))

    def browse_mysql(self):

        path = filedialog.askopenfilename(
            filetypes=[("MySQL client", "mysql.exe")]
        )

        if path:
            self.mysql_var.set(path)

    def test_connection(self):
        try:
            mysql = Path(self.mysql_var.get())
            port = int(self.port_var.get())
            timeout = int(self.timeout_var.get())
        except ValueError:
            messagebox.showerror("Settings", "Invalid port or timeout.")
            return
        if not mysql.is_file():
            messagebox.showerror("Settings", "mysql.exe not found.")
            return
        cfg = {
            "mysql": str(mysql),
            "host": self.host_var.get().strip(),
            "port": port,
            "user": self.user_var.get().strip(),
            "password": self.password_var.get(),
            "timeout": timeout
        }
        option = self.create_option_file(cfg)
        try:
            res = self._run_hidden_command(
                self.mysql_command(cfg, option, sql="SELECT 1;"),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30
            )
        finally:
            if os.path.exists(option):
                os.remove(option)
        if res.returncode != 0:
            messagebox.showerror("Connection", res.stderr or "Connection failed.")
        else:
            messagebox.showinfo("Connection", "Connection successful.")

    def browse_error_logs(self):

        path = filedialog.askopenfilename(
            title="Browse Error Logs",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")]
        )

        if not path:
            return

        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messagebox.showerror("Error Logs", str(exc))
            return

        self.error_text.delete("1.0", "end")
        self.error_text.insert("1.0", content)

    def select_folder(self):

        folder = filedialog.askdirectory()

        if folder:
            self.folder_var.set(folder)
            self.load_files()

    def load_files(self):

        folder = Path(self.folder_var.get())

        if not folder.is_dir():
            messagebox.showerror(
                "Error",
                "Select a valid backup folder."
            )
            return

        self.files = sorted(
            folder.glob("*.sql"),
            key=lambda p: p.name.lower()
        )

        self.results.clear()
        self.tree.delete(*self.tree.get_children())
        self.row_paths.clear()

        for path in self.files:

            iid = self.tree.insert(
                "",
                "end",
                values=(
                    path.name,
                    self.human_size(path.stat().st_size),
                    "Detecting...",
                    "Pending",
                    "-"
                )
            )

            self.row_paths[iid] = path

        self.status_var.set(
            f"{len(self.files)} SQL backup files loaded."
        )

    @staticmethod
    def human_size(size):

        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024

        return f"{size:.1f} TB"

    def select_all(self):
 
        self.tree.selection_set(
            self.tree.get_children()
        )

    def list_databases(self):
        try:
            mysql = Path(self.mysql_var.get())
            port = int(self.port_var.get())
            timeout = int(self.timeout_var.get())
        except ValueError:
            messagebox.showerror("Settings", "Invalid port or timeout.")
            return
        if not mysql.is_file():
            messagebox.showerror("Settings", "mysql.exe not found.")
            return
        cfg = {
            "mysql": str(mysql),
            "host": self.host_var.get().strip(),
            "port": port,
            "user": self.user_var.get().strip(),
            "password": self.password_var.get(),
            "timeout": timeout
        }
        option = self.create_option_file(cfg)
        try:
            res = self._run_hidden_command(
                self.mysql_command(cfg, option, sql="SHOW DATABASES;"),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30
            )
        finally:
            if os.path.exists(option):
                os.remove(option)
        if res.returncode != 0:
            messagebox.showerror("Databases", res.stderr)
            return

        dbs = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        if not dbs:
            messagebox.showinfo("Databases", "(none)")
            return

        win = tk.Toplevel(self)
        win.title("Available Databases")
        win.geometry("500x470")
        win.transient(self)
        win.grab_set()
        win.configure(bg="#edf2f7")

        body = tk.Frame(win, bg="#edf2f7", padx=16, pady=16)
        body.pack(fill="both", expand=True)

        title = tk.Label(
            body,
            text="Available databases",
            bg="#edf2f7",
            fg="#0f172a",
            font=("Segoe UI", 12, "bold")
        )
        title.pack(anchor="w", pady=(0, 12))

        actions_row = tk.Frame(body, bg="#edf2f7")
        actions_row.pack(fill="x", pady=(0, 10))
        tk.Button(
            actions_row,
            text="Add Database",
            command=lambda: self._prompt_drop_password_then_create_database(cfg, win),
            bg="#16a34a",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            width=14,
            relief="raised",
            bd=1,
            padx=10,
            pady=5
        ).pack(side="right")

        search_var = tk.StringVar()
        search_frame = tk.Frame(body, bg="#edf2f7")
        search_frame.pack(fill="x", pady=(0, 8))
        tk.Label(search_frame, text="Search:", bg="#edf2f7", fg="#1f2937", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Entry(search_frame, textvariable=search_var, width=40, font=("Segoe UI", 10), bd=1, relief="solid").pack(fill="x", ipady=6)

        list_panel = tk.Frame(body, bg="#ffffff", bd=1, relief="solid")
        list_panel.pack(fill="both", expand=True, pady=(8, 12))

        canvas = tk.Canvas(list_panel, bg="#ffffff", highlightthickness=0, height=280)
        canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_panel, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)

        list_container = tk.Frame(canvas, bg="#ffffff", padx=8, pady=8)
        canvas.create_window((0, 0), window=list_container, anchor="nw")

        def refresh_rows(values):
            for child in list_container.winfo_children():
                child.destroy()
            for db in values:
                row = tk.Frame(list_container, bg="#f8fafc", bd=1, relief="solid", padx=10, pady=8)
                row.pack(fill="x", pady=4)
                tk.Label(row, text=db, bg="#f8fafc", fg="#111827", font=("Segoe UI", 10), anchor="w").pack(side="left", fill="x", expand=True)

                action_frame = tk.Frame(row, bg="#f8fafc")
                action_frame.pack(side="right")

                tk.Button(
                    action_frame,
                    text="Export",
                    command=lambda name=db: self._prompt_drop_password_then_export(cfg, name, win),
                    bg="#2563eb",
                    fg="white",
                    font=("Segoe UI", 9, "bold"),
                    width=8,
                    relief="raised",
                    bd=1,
                    padx=8,
                    pady=4
                ).pack(side="left", padx=(0, 8))

                tk.Button(
                    action_frame,
                    text="Drop",
                    command=lambda name=db: self._prompt_drop_password_then_drop(cfg, name, win),
                    bg="#dc2626",
                    fg="white",
                    font=("Segoe UI", 9, "bold"),
                    width=8,
                    relief="raised",
                    bd=1,
                    padx=8,
                    pady=4
                ).pack(side="left")
            list_container.update_idletasks()
            canvas.config(scrollregion=canvas.bbox("all"))

        def filter_dbs(*_):
            query = search_var.get().lower()
            if not query:
                refresh_rows(dbs)
                return
            refresh_rows([db for db in dbs if query in db.lower()])

        refresh_rows(dbs)
        search_var.trace_add("write", filter_dbs)

        note = tk.Label(
            body,
            text="Note: large database drops or exports may take time. Please be patient and wait after confirming.",
            bg="#edf2f7",
            fg="#374151",
            font=("Segoe UI", 9, "italic"),
            justify="left",
            wraplength=430
        )
        note.pack(anchor="w", pady=(0, 10))

        close_btn = tk.Button(
            body,
            text="Close",
            command=win.destroy,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        )
        close_btn.pack(anchor="e")

    @staticmethod
    def load_drop_password():
        path = get_drop_password_file()
        legacy_path = Path(__file__).with_name(".drop_password")
        try:
            if path.exists():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
            if legacy_path.exists() and not path.exists():
                value = legacy_path.read_text(encoding="utf-8").strip()
                if value:
                    path.write_text(value, encoding="utf-8")
                    return value
        except OSError:
            pass
        return DEFAULT_DROP_PASSWORD

    @staticmethod
    def save_drop_password(password):
        path = get_drop_password_file()
        try:
            path.write_text(str(password).strip(), encoding="utf-8")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except OSError:
            return False
        return True

    def change_drop_password(self):
        dialog = tk.Toplevel(self)
        dialog.title("Change Drop Password")
        dialog.geometry("490x360")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg="#eef2f7")

        main = tk.Frame(dialog, bg="#eef2f7", padx=18, pady=18)
        main.pack(fill="both", expand=True)

        title = tk.Label(
            main,
            text="Change Drop Password",
            bg="#eef2f7",
            fg="#0f172a",
            font=("Segoe UI", 13, "bold")
        )
        title.pack(anchor="w", pady=(0, 14))

        current_var = tk.StringVar()
        new_var = tk.StringVar()
        confirm_var = tk.StringVar()

        field_data = [
            ("Current password", current_var),
            ("New password", new_var),
            ("Confirm password", confirm_var),
        ]

        entries = {}
        show_flags = {}

        for label_text, var in field_data:
            label = tk.Label(
                main,
                text=label_text,
                bg="#eef2f7",
                fg="#1f2937",
                font=("Segoe UI", 10, "bold")
            )
            label.pack(anchor="w", pady=(10, 4))

            show_flag = tk.BooleanVar(value=False)
            show_flags[label_text] = show_flag

            frame = tk.Frame(main, bg="#eef2f7")
            frame.pack(fill="x", pady=(0, 8))

            entry = tk.Entry(
                frame,
                textvariable=var,
                show="*",
                width=42,
                font=("Segoe UI", 10),
                bg="white",
                fg="#111827",
                bd=1,
                relief="solid",
                insertbackground="#111827",
                highlightthickness=1,
                highlightbackground="#cbd5e1",
                highlightcolor="#2563eb",
            )
            entry.pack(side="left", fill="x", expand=True, ipady=6)
            entries[label_text] = entry

            def toggle_password_visibility(flag_var, entry_widget, field_name):
                if flag_var.get():
                    entry_widget.configure(show="")
                else:
                    entry_widget.configure(show="*")

            toggle_btn = tk.Checkbutton(
                frame,
                text="View",
                variable=show_flag,
                bg="#eef2f7",
                fg="#0f172a",
                activebackground="#eef2f7",
                activeforeground="#0f172a",
                selectcolor="#dbeafe",
                command=lambda v=show_flag, e=entry: toggle_password_visibility(v, e, label_text),
                font=("Segoe UI", 9)
            )
            toggle_btn.pack(side="left", padx=(8, 0))

        def save_password():
            current = current_var.get()
            new_password = new_var.get()
            confirm_password = confirm_var.get()

            if current != self.drop_password:
                messagebox.showerror("Password", "Incorrect current password.")
                return
            if not new_password.strip():
                messagebox.showerror("Password", "Password cannot be empty.")
                return
            if new_password != confirm_password:
                messagebox.showerror("Password", "New passwords do not match.")
                return

            self.drop_password = new_password
            if not self.save_drop_password(new_password):
                messagebox.showwarning("Password", "Password was changed in memory but could not be saved to disk.")
            else:
                messagebox.showinfo("Password", "Drop password updated successfully.")
            dialog.destroy()

        def reset_to_default_password():
            secret_code = simpledialog.askstring(
                "Reset Drop Password",
                "What is the Secret DB Code ?"
            )
            if secret_code is None:
                return
            if secret_code.strip() != "1015#CWING_db#687":
                messagebox.showerror("Secret DB Code", "Incorrect secret DB code. The password was not reset.")
                return

            self.drop_password = DEFAULT_DROP_PASSWORD
            if not self.save_drop_password(DEFAULT_DROP_PASSWORD):
                messagebox.showwarning("Password", "The default password was restored in memory but could not be saved to disk.")
            else:
                messagebox.showinfo("Password", "Drop password was reset to the default hardcoded value.")
            dialog.destroy()

        button_row = tk.Frame(main, bg="#eef2f7")
        button_row.pack(fill="x", pady=(18, 0))

        reset_btn = tk.Button(
            button_row,
            text="Reset",
            command=reset_to_default_password,
            bg="#dc2626",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        )
        reset_btn.pack(side="left")

        cancel_btn = tk.Button(
            button_row,
            text="Cancel",
            command=dialog.destroy,
            bg="#e5e7eb",
            fg="#111827",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        )
        cancel_btn.pack(side="right")

        save_btn = tk.Button(
            button_row,
            text="Save",
            command=save_password,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        )
        save_btn.pack(side="right", padx=(0, 10))

        dialog.wait_window()

    def drop_database(self):
        password_dialog = tk.Toplevel(self)
        password_dialog.title("Verify Drop Access")
        password_dialog.geometry("420x180")
        password_dialog.transient(self)
        password_dialog.grab_set()
        password_dialog.configure(bg="#eef2f7")

        body = tk.Frame(password_dialog, bg="#eef2f7", padx=18, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Verification key",
            bg="#eef2f7",
            fg="#0f172a",
            font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", pady=(0, 8))

        password_var = tk.StringVar()
        password_frame = tk.Frame(body, bg="#eef2f7")
        password_frame.pack(fill="x")

        entry = tk.Entry(
            password_frame,
            textvariable=password_var,
            show="*",
            width=34,
            font=("Segoe UI", 10),
            bg="white",
            fg="#111827",
            bd=1,
            relief="solid",
            insertbackground="#111827"
        )
        entry.pack(side="left", fill="x", expand=True, ipady=6)

        show_var = tk.BooleanVar(value=False)

        def toggle_visibility():
            entry.configure(show="" if show_var.get() else "*")

        tk.Checkbutton(
            password_frame,
            text="View",
            variable=show_var,
            bg="#eef2f7",
            fg="#0f172a",
            activebackground="#eef2f7",
            activeforeground="#0f172a",
            selectcolor="#dbeafe",
            command=toggle_visibility,
            font=("Segoe UI", 9)
        ).pack(side="left", padx=(8, 0))

        def confirm_password():
            password = password_var.get()
            if password != self.drop_password:
                messagebox.showerror("Password", "Incorrect password.")
                return
            password_dialog.destroy()
            self._open_drop_database_selector()

        button_row = tk.Frame(body, bg="#eef2f7")
        button_row.pack(fill="x", pady=(18, 0))
        tk.Button(
            button_row,
            text="Cancel",
            command=password_dialog.destroy,
            bg="#e5e7eb",
            fg="#111827",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right")
        tk.Button(
            button_row,
            text="Continue",
            command=confirm_password,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right", padx=(0, 10))

    def _drop_database_by_name(self, cfg, db_name, owner_window=None):
        if not messagebox.askyesno("Confirm", f"Drop database '{db_name}'?"):
            return
        option = self.create_option_file(cfg)
        try:
            result = self._run_hidden_command(
                self.mysql_command(cfg, option, sql=f"DROP DATABASE `{db_name}`;"),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30
            )
        finally:
            if os.path.exists(option):
                os.remove(option)
        if result.returncode != 0:
            messagebox.showerror("Drop Database", result.stderr)
            return
        messagebox.showinfo("Drop Database", f"Dropped '{db_name}'.")
        if owner_window is not None:
            owner_window.destroy()

    def _export_database_sql(self, cfg, db_name, owner_window=None):
        save_path = filedialog.asksaveasfilename(
            title=f"Export {db_name} SQL",
            defaultextension=".sql",
            initialfile=f"{db_name}_export.sql",
            filetypes=[("SQL dump", "*.sql"), ("All files", "*.*")]
        )

        if not save_path:
            return

        mysql_path = Path(cfg["mysql"])
        dump_exe = mysql_path.with_name("mysqldump.exe")
        if not dump_exe.exists():
            dump_exe = mysql_path.parent / "mysqldump.exe"

        if not dump_exe.exists():
            messagebox.showerror("Export", "mysqldump.exe was not found next to mysql.exe.")
            return

        option = self.create_option_file(cfg)
        cmd = [
            str(dump_exe),
            f"--defaults-extra-file={option}",
            "--default-character-set=utf8mb4",
            "--databases",
            db_name,
            "--add-drop-database",
            "--add-drop-table",
            "--skip-comments",
            "--single-transaction",
            "--quick",
            "--result-file",
            save_path,
        ]

        try:
            result = self._run_hidden_command(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600
            )
        finally:
            if os.path.exists(option):
                os.remove(option)

        if result.returncode != 0:
            messagebox.showerror("Export Database", result.stderr or "Export failed.")
            return

        messagebox.showinfo("Export Database", f"Database '{db_name}' exported to:\n{save_path}")
        if owner_window is not None:
            owner_window.destroy()

    def _create_database(self, cfg, db_name, owner_window=None):
        db_name = db_name.strip()
        if not db_name:
            messagebox.showerror("Create Database", "Database name is required.")
            return
        if not re.fullmatch(r"[A-Za-z0-9_$-]+", db_name):
            messagebox.showerror("Create Database", "Database name may only contain letters, numbers, underscore, dollar, or dash.")
            return

        option = self.create_option_file(cfg)
        try:
            result = self._run_hidden_command(
                self.mysql_command(
                    cfg,
                    option,
                    sql=f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30
            )
        finally:
            if os.path.exists(option):
                os.remove(option)

        if result.returncode != 0:
            messagebox.showerror("Create Database", result.stderr or "Failed to create database.")
            return

        messagebox.showinfo("Create Database", f"Database '{db_name}' created with collation utf8mb4_general_ci.")
        if owner_window is not None:
            owner_window.destroy()
            self.list_databases()

    def _prompt_drop_password_then_create_database(self, cfg, owner_window=None):
        password_dialog = tk.Toplevel(self)
        password_dialog.title("Verify Create Access")
        password_dialog.geometry("460x230")
        password_dialog.transient(self)
        password_dialog.grab_set()
        password_dialog.configure(bg="#eef2f7")

        body = tk.Frame(password_dialog, bg="#eef2f7", padx=18, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Database name",
            bg="#eef2f7",
            fg="#0f172a",
            font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", pady=(0, 6))

        name_var = tk.StringVar()
        tk.Entry(
            body,
            textvariable=name_var,
            width=34,
            font=("Segoe UI", 10),
            bg="white",
            fg="#111827",
            bd=1,
            relief="solid",
            insertbackground="#111827"
        ).pack(fill="x", ipady=6)

        tk.Label(
            body,
            text="Verification key",
            bg="#eef2f7",
            fg="#0f172a",
            font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", pady=(12, 6))

        password_var = tk.StringVar()
        password_frame = tk.Frame(body, bg="#eef2f7")
        password_frame.pack(fill="x")

        entry = tk.Entry(
            password_frame,
            textvariable=password_var,
            show="*",
            width=34,
            font=("Segoe UI", 10),
            bg="white",
            fg="#111827",
            bd=1,
            relief="solid",
            insertbackground="#111827"
        )
        entry.pack(side="left", fill="x", expand=True, ipady=6)

        show_var = tk.BooleanVar(value=False)

        def toggle_visibility():
            entry.configure(show="" if show_var.get() else "*")

        tk.Checkbutton(
            password_frame,
            text="View",
            variable=show_var,
            bg="#eef2f7",
            fg="#0f172a",
            activebackground="#eef2f7",
            activeforeground="#0f172a",
            selectcolor="#dbeafe",
            command=toggle_visibility,
            font=("Segoe UI", 9)
        ).pack(side="left", padx=(8, 0))

        def confirm():
            if password_var.get() != self.drop_password:
                messagebox.showerror("Password", "Incorrect password.")
                return
            db_name = name_var.get().strip()
            if not db_name:
                messagebox.showerror("Create Database", "Database name is required.")
                return
            password_dialog.destroy()
            self._create_database(cfg, db_name, owner_window)

        button_row = tk.Frame(body, bg="#eef2f7")
        button_row.pack(fill="x", pady=(18, 0))
        tk.Button(
            button_row,
            text="Cancel",
            command=password_dialog.destroy,
            bg="#e5e7eb",
            fg="#111827",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right")
        tk.Button(
            button_row,
            text="Create",
            command=confirm,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right", padx=(0, 10))

    def _prompt_drop_password_then_export(self, cfg, db_name, owner_window=None):
        password_dialog = tk.Toplevel(self)
        password_dialog.title("Verify Export Access")
        password_dialog.geometry("420x170")
        password_dialog.transient(self)
        password_dialog.grab_set()
        password_dialog.configure(bg="#eef2f7")

        body = tk.Frame(password_dialog, bg="#eef2f7", padx=18, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Verification key",
            bg="#eef2f7",
            fg="#0f172a",
            font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", pady=(0, 8))

        password_var = tk.StringVar()
        password_frame = tk.Frame(body, bg="#eef2f7")
        password_frame.pack(fill="x")

        entry = tk.Entry(
            password_frame,
            textvariable=password_var,
            show="*",
            width=34,
            font=("Segoe UI", 10),
            bg="white",
            fg="#111827",
            bd=1,
            relief="solid",
            insertbackground="#111827"
        )
        entry.pack(side="left", fill="x", expand=True, ipady=6)

        show_var = tk.BooleanVar(value=False)

        def toggle_visibility():
            entry.configure(show="" if show_var.get() else "*")

        tk.Checkbutton(
            password_frame,
            text="View",
            variable=show_var,
            bg="#eef2f7",
            fg="#0f172a",
            activebackground="#eef2f7",
            activeforeground="#0f172a",
            selectcolor="#dbeafe",
            command=toggle_visibility,
            font=("Segoe UI", 9)
        ).pack(side="left", padx=(8, 0))

        def confirm_password():
            if password_var.get() != self.drop_password:
                messagebox.showerror("Password", "Incorrect password.")
                return
            password_dialog.destroy()
            self._export_database_sql(cfg, db_name, owner_window)

        button_row = tk.Frame(body, bg="#eef2f7")
        button_row.pack(fill="x", pady=(18, 0))
        tk.Button(
            button_row,
            text="Cancel",
            command=password_dialog.destroy,
            bg="#e5e7eb",
            fg="#111827",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right")
        tk.Button(
            button_row,
            text="Continue",
            command=confirm_password,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right", padx=(0, 10))

    def _prompt_drop_password_then_drop(self, cfg, db_name, owner_window=None):
        password_dialog = tk.Toplevel(self)
        password_dialog.title("Verify Drop Access")
        password_dialog.geometry("420x170")
        password_dialog.transient(self)
        password_dialog.grab_set()
        password_dialog.configure(bg="#eef2f7")

        body = tk.Frame(password_dialog, bg="#eef2f7", padx=18, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Verification key",
            bg="#eef2f7",
            fg="#0f172a",
            font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", pady=(0, 8))

        password_var = tk.StringVar()
        password_frame = tk.Frame(body, bg="#eef2f7")
        password_frame.pack(fill="x")

        entry = tk.Entry(
            password_frame,
            textvariable=password_var,
            show="*",
            width=34,
            font=("Segoe UI", 10),
            bg="white",
            fg="#111827",
            bd=1,
            relief="solid",
            insertbackground="#111827"
        )
        entry.pack(side="left", fill="x", expand=True, ipady=6)

        show_var = tk.BooleanVar(value=False)

        def toggle_visibility():
            entry.configure(show="" if show_var.get() else "*")

        tk.Checkbutton(
            password_frame,
            text="View",
            variable=show_var,
            bg="#eef2f7",
            fg="#0f172a",
            activebackground="#eef2f7",
            activeforeground="#0f172a",
            selectcolor="#dbeafe",
            command=toggle_visibility,
            font=("Segoe UI", 9)
        ).pack(side="left", padx=(8, 0))

        def confirm_password():
            if password_var.get() != self.drop_password:
                messagebox.showerror("Password", "Incorrect password.")
                return
            password_dialog.destroy()
            self._drop_database_by_name(cfg, db_name, owner_window)

        button_row = tk.Frame(body, bg="#eef2f7")
        button_row.pack(fill="x", pady=(18, 0))
        tk.Button(
            button_row,
            text="Cancel",
            command=password_dialog.destroy,
            bg="#e5e7eb",
            fg="#111827",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right")
        tk.Button(
            button_row,
            text="Continue",
            command=confirm_password,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right", padx=(0, 10))

    def _open_drop_database_selector(self):
        try:
            mysql = Path(self.mysql_var.get())
            port = int(self.port_var.get())
            timeout = int(self.timeout_var.get())
        except ValueError:
            messagebox.showerror("Settings", "Invalid port or timeout.")
            return
        if not mysql.is_file():
            messagebox.showerror("Settings", "mysql.exe not found.")
            return
        cfg = {
            "mysql": str(mysql),
            "host": self.host_var.get().strip(),
            "port": port,
            "user": self.user_var.get().strip(),
            "password": self.password_var.get(),
            "timeout": timeout
        }
        option = self.create_option_file(cfg)
        try:
            res = self._run_hidden_command(
                self.mysql_command(cfg, option, sql="SHOW DATABASES;"),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30
            )
        finally:
            if os.path.exists(option):
                os.remove(option)
        if res.returncode != 0:
            messagebox.showerror("Databases", res.stderr)
            return
        dbs = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        if not dbs:
            messagebox.showinfo("Databases", "(none)")
            return

        win = tk.Toplevel(self)
        win.title("Drop Database")
        win.geometry("500x470")
        win.transient(self)
        win.grab_set()
        win.configure(bg="#edf2f7")

        frame = tk.Frame(win, bg="#edf2f7", padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="Select a database to drop",
            bg="#edf2f7",
            fg="#0f172a",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=(0, 10))

        search_var = tk.StringVar()
        search_frame = tk.Frame(frame, bg="#edf2f7")
        search_frame.pack(fill="x", pady=(0, 8))
        tk.Label(search_frame, text="Search:", bg="#edf2f7", fg="#1f2937", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Entry(search_frame, textvariable=search_var, width=36, font=("Segoe UI", 10), bd=1, relief="solid").pack(fill="x", ipady=6)

        list_panel = tk.Frame(frame, bg="#ffffff", bd=1, relief="solid")
        list_panel.pack(fill="both", expand=True, pady=(8, 12))

        canvas = tk.Canvas(list_panel, bg="#ffffff", highlightthickness=0, height=260)
        canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_panel, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)

        list_container = tk.Frame(canvas, bg="#ffffff", padx=8, pady=8)
        canvas.create_window((0, 0), window=list_container, anchor="nw")

        def refresh_rows(filtered=None):
            for child in list_container.winfo_children():
                child.destroy()
            values = filtered if filtered is not None else dbs
            for db in values:
                row = tk.Frame(list_container, bg="#f8fafc", bd=1, relief="solid", padx=10, pady=8)
                row.pack(fill="x", pady=4)
                tk.Label(row, text=db, bg="#f8fafc", fg="#111827", font=("Segoe UI", 10), anchor="w").pack(side="left", fill="x", expand=True)
                tk.Button(
                    row,
                    text="Drop",
                    command=lambda name=db: self._drop_database_by_name(cfg, name, win),
                    bg="#dc2626",
                    fg="white",
                    font=("Segoe UI", 9, "bold"),
                    width=8,
                    relief="raised",
                    bd=1,
                    padx=8,
                    pady=4
                ).pack(side="right")
            list_container.update_idletasks()
            canvas.config(scrollregion=canvas.bbox("all"))

        def filter_rows(*_):
            query = search_var.get().lower()
            if not query:
                refresh_rows(dbs)
                return
            refresh_rows([db for db in dbs if query in db.lower()])

        refresh_rows(dbs)
        search_var.trace_add("write", filter_rows)

        actions = tk.Frame(frame, bg="#edf2f7")
        actions.pack(fill="x")
        tk.Button(
            actions,
            text="Close",
            command=win.destroy,
            bg="#2563eb",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            width=12,
            relief="raised",
            bd=1,
            padx=12,
            pady=6
        ).pack(side="right")

    # ---------------- DATABASE NAME DETECTION ----------------

    def detect_database(self, sql_file):

        primary_patterns = [
            r'CREATE\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
            r'[`"]?([A-Za-z0-9_$-]+)[`"]?',

            r'CREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?'
            r'[`"]?([A-Za-z0-9_$-]+)[`"]?',

            r'USE\s+[`"]?([A-Za-z0-9_$-]+)[`"]?\s*;',

            r'DROP\s+DATABASE\s+(?:IF\s+EXISTS\s+)?'
            r'[`"]?([A-Za-z0-9_$-]+)[`"]?',

            r'ALTER\s+DATABASE\s+[`"]?([A-Za-z0-9_$-]+)[`"]?',

            r"Dump(?:ing)?\s+(?:routines\s+for\s+)?(?:database|schema)\s+['\"]?([A-Za-z0-9_$-]+)['\"]?",
        ]

        fallback_patterns = [
            r'\bFROM\s+[`"]?([A-Za-z0-9_$-]+)[`"]?\.[`"]?([A-Za-z0-9_$-]+)[`"]?\b',
            r'`?([A-Za-z0-9_$-]+)`?\.[`"]?([A-Za-z0-9_$-]+)[`"]?\s+INSERT\s+INTO',
            r'INSERT\s+INTO\s+[`"]?([A-Za-z0-9_$-]+)[`"]?\.',
            r'UPDATE\s+[`"]?([A-Za-z0-9_$-]+)[`"]?\.',
        ]

        with open(
            sql_file,
            "r",
            encoding="utf-8-sig",
            errors="replace"
        ) as f:

            prefix = ""
            tail = ""
            total_read = 0
            scan_limit = 2 * 1024 * 1024
            tail_limit = 64 * 1024

            while True:
                chunk = f.read(65536)
                if not chunk:
                    break

                total_read += len(chunk)

                if len(prefix) < scan_limit:
                    prefix += chunk
                else:
                    tail += chunk[-tail_limit:]

                if total_read > scan_limit and len(tail) > tail_limit:
                    tail = tail[-tail_limit:]

                content = prefix if total_read <= scan_limit else prefix + tail

                for pattern in primary_patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        for group_index in range(1, match.lastindex + 1 if match.lastindex else 1):
                            value = match.group(group_index)
                            if value and re.fullmatch(r"[A-Za-z0-9_$-]+", value):
                                return value

                for pattern in fallback_patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        first_value = match.group(1)
                        if first_value and re.fullmatch(r"[A-Za-z0-9_$-]+", first_value):
                            if first_value.lower() in {"select", "insert", "update", "delete", "from"}:
                                continue
                            if len(first_value) <= 2 and not re.search(r"[_-]", first_value):
                                continue
                            return first_value

                if total_read >= scan_limit * 2:
                    break

        return None

    # ---------------- MYSQL CONNECTION ----------------

    def settings(self):

        mysql = Path(self.mysql_var.get())

        if not mysql.is_file():
            raise ValueError("mysql.exe not found.")

        if not self.files:
            raise ValueError("No SQL files loaded.")

        try:
            port = int(self.port_var.get())
            timeout = int(self.timeout_var.get())
        except ValueError:
            raise ValueError("Invalid port or timeout.")

        if not (1 <= port <= 65535) or timeout < 1:
            raise ValueError("Invalid port or timeout value.")

        return {
            "mysql": str(mysql),
            "host": self.host_var.get().strip(),
            "port": port,
            "user": self.user_var.get().strip(),
            "password": self.password_var.get(),
            "timeout": timeout
        }

    def create_option_file(self, cfg):

        fd, path = tempfile.mkstemp(suffix=".cnf")
        os.close(fd)

        def quote(value):
            return '"' + value.replace(
                "\\", "\\\\"
            ).replace('"', '\\"').replace(
                "\n", "\\n"
            ) + '"'

        Path(path).write_text(
            "[client]\n"
            f"user={quote(cfg['user'])}\n"
            f"password={quote(cfg['password'])}\n"
            f"host={quote(cfg['host'])}\n"
            f"port={cfg['port']}\n",
            encoding="utf-8"
        )

        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

        return path

    def mysql_command(self, cfg, option, sql=None, database=None):

        cmd = [
            cfg["mysql"],
            f"--defaults-extra-file={option}",
            "--default-character-set=utf8mb4",
            "--binary-mode",
            "--force",
            "--max_allowed_packet=1073741824",
            "--batch",
            "--show-warnings"
        ]

        if sql:
            cmd.extend(["-e", sql])

        if database:
            cmd.extend(["--database", database])

        return cmd

    def _hidden_subprocess_kwargs(self):
        kwargs = {}
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return kwargs

    def _run_hidden_command(self, cmd, **kwargs):
        merged = self._hidden_subprocess_kwargs()
        merged.update(kwargs)
        return subprocess.run(cmd, **merged)

    def _popen_hidden_command(self, cmd, **kwargs):
        merged = self._hidden_subprocess_kwargs()
        merged.update(kwargs)
        return subprocess.Popen(cmd, **merged)

    def _clean_error(self, exc):

        msg = str(exc).strip()

        if not msg:
            msg = type(exc).__name__

        return msg

    def _friendly_sql_error(self, message, db_name=None):
        text = (message or "").lower()

        if "duplicate entry" in text or "duplicate key" in text or "1062" in text:
            return (
                "This usually means the SQL script is re-creating data or tables that already exist. "
                "When the dump is CREATE-only without DROP/TRUNCATE/RECREATE cleanup, MySQL can raise duplicate-key errors."
            )

        if "database exists" in text or "can't create database" in text or "database already exists" in text or "already exists" in text and "database" in text:
            return (
                f"The target database '{db_name or 'selected database'}' already exists. This is a common sign that the dump is meant for a fresh database and does not include a DROP/cleanup step before CREATE statements."
            )

        if "table exists" in text or "already exists" in text and "table" in text:
            return (
                "The script is trying to create a table that already exists. This usually happens when the dump contains CREATE statements without first dropping the existing table structure."
            )

        if "unknown database" in text or "no database selected" in text:
            return (
                "The database name could not be resolved or the dump did not declare a valid target database. Check the detected database name and the SQL header for CREATE DATABASE / USE statements."
            )

        if "access denied" in text or "authentication" in text:
            return (
                "The connection credentials or MySQL permissions do not allow the restore operation. Check the MySQL user, password, and granted privileges."
            )

        return "This usually means the restore script is not safe for an already-populated database or the dump is missing cleanup statements before CREATE/INSERT statements."

    def _write_error_log(self, backup, db_name, output):

        log_path = getattr(self, "error_log_path", None)

        if not log_path:
            return

        try:

            with log_path.open("a", encoding="utf-8") as f:

                f.write(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"File: {backup.name}\n"
                    f"Database: {db_name or '-'}\n"
                    f"{output}\n"
                    f"{'-' * 60}\n"
                )

        except OSError:

            pass

    # ---------------- RESTORE CONTROL ----------------

    @staticmethod
    def format_eta(seconds):
        if seconds is None or seconds < 0:
            return "ETA --"
        total = max(0, int(seconds))
        mins, secs = divmod(total, 60)
        hours, mins = divmod(mins, 60)
        if hours:
            return f"ETA {hours:02d}:{mins:02d}:{secs:02d}"
        return f"ETA {mins:02d}:{secs:02d}"

    def set_progress_loader(self, active, percent=None, text=None, eta=None):

        if active:
            self.progress.config(mode="indeterminate")
            if not self.progress_loading:
                self.progress.start(18)
                self.progress_loading = True
            if text is not None:
                self.status_var.set(text)
            if eta is not None:
                self.eta_var.set(eta)
            return

        if self.progress_loading:
            self.progress.stop()

        self.progress_loading = False
        self.progress.config(mode="determinate")

        if percent is not None:
            self.progress_var.set(percent)
            self.percent_label.config(text=f"{int(percent)}%")

        if eta is not None:
            self.eta_var.set(eta)
        elif percent is None:
            self.eta_var.set("ETA --")

        if text is not None:
            self.status_var.set(text)

    def restore_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Selection", "Select a backup row first.")
            return
        paths = [self.row_paths[i] for i in sel if i in self.row_paths]
        if paths:
            self.start_restore(paths)

    def retry_row(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Selection", "Select a backup row first.")
            return
        paths = [
            self.row_paths[i] for i in sel
            if i in self.row_paths and self.results.get(str(self.row_paths[i]), {}).get("status") == "FAIL"
        ]
        if not paths:
            messagebox.showinfo("Retry", "Selected row is not failed.")
            return
        self.start_restore(paths)

    def restore_all(self):

        if not self.files:
            return

        paths = [
            p for p in self.files
            if self.results.get(str(p), {}).get("status") not in ("PASS", "MANUAL")
        ]

        if not paths:
            messagebox.showinfo("Restore All", "All backups already restored.")
            return

        self.start_restore(paths)

    def retry_failed(self):

        paths = [
            path for path in self.files
            if self.results.get(str(path), {}).get("status") == "FAIL"
        ]

        if not paths:
            messagebox.showinfo(
                "Retry",
                "No failed backups found."
            )
            return

        self.start_restore(paths)

    def start_restore(self, paths):

        if self.worker and self.worker.is_alive():
            return

        try:
            cfg = self.settings()
        except Exception as exc:
            messagebox.showerror("Settings", str(exc))
            return

        if not messagebox.askyesno(
            "Confirm Restore",
            "SQL files may contain destructive commands.\n\n"
            "Use only a disposable LOCAL MySQL server.\n\n"
            "Existing databases will NOT be overwritten.\n\n"
            "Continue?"
        ):
            return

        self.stop_event.clear()
        self.skip_event.clear()
        self.progress_var.set(0)
        self.percent_label.config(text="0%")
        self.eta_var.set("ETA --")
        self.set_progress_loader(True, text="Preparing restore queue...")
        self.stop_button.config(state="normal")

        self.worker = threading.Thread(
            target=self.restore_worker,
            args=(paths, cfg),
            daemon=True
        )

        self.worker.start()

    # ---------------- RESTORE ENGINE ----------------

    def restore_worker(self, paths, cfg):

        option = None
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        report_rows = []

        folder = Path(self.folder_var.get())

        if folder.exists():
            self.error_log_path = folder / f"restore_errors_{run_id}.log"
        else:
            self.error_log_path = None

        try:

            option = self.create_option_file(cfg)

            for index, backup in enumerate(paths, 1):

                if self.stop_event.is_set():
                    break

                self.events.put((
                    "progress",
                    0,
                    f"Preparing {index}/{len(paths)}: {backup.name}"
                ))

                self.events.put((
                    "row",
                    str(backup),
                    "RUNNING",
                    "Detecting...",
                    "-"
                ))

                started = time.monotonic()
                status = "FAIL"
                db_name = None
                output = ""

                stdout_path = None
                stderr_path = None

                try:

                    db_name = self.detect_database(backup)
                    if not db_name:
                        db_name = backup.stem

                    cleaned = self.sanitize_db_name(db_name)
                    if not cleaned:
                        raise RuntimeError(
                            f"Unsafe or unsupported database name: {db_name}"
                        )
                    db_name = cleaned

                    check_sql = (
                        "SELECT COUNT(*) FROM information_schema.schemata "
                        f"WHERE schema_name = '{db_name}'"
                    )

                    check = self._run_hidden_command(
                        self.mysql_command(
                            cfg, option, sql=check_sql
                        ),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30
                    )

                    if check.returncode != 0:
                        raise RuntimeError(
                            "DATABASE CHECK FAILED:\n" + check.stderr
                        )

                    count = int(
                        check.stdout.strip().splitlines()[-1]
                    )

                    has_drop = False
                    with backup.open("r", encoding="utf-8-sig", errors="replace") as sf:
                        for line in sf:
                            if re.search(r"\bDROP\s+(DATABASE|TABLE|SCHEMA)\b", line, re.IGNORECASE):
                                has_drop = True
                                break

                    if count > 0 and not has_drop:
                        status = "ALREADY EXISTS"
                        output = (
                            f"Database '{db_name}' already exists and "
                            "script contains no DROP statement. Skipped."
                        )
                        raise RuntimeError(output)

                    if count == 0:
                        create = self._run_hidden_command(
                            self.mysql_command(
                                cfg, option,
                                sql=f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4;"
                            ),
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30
                        )
                        if create.returncode != 0:
                            raise RuntimeError(
                                "DATABASE CREATE FAILED:\n" + create.stderr
                            )

                    self.events.put((
                        "row",
                        str(backup),
                        "RUNNING",
                        db_name,
                        "-"
                    ))

                    self.events.put((
                        "progress",
                        0,
                        f"Restoring {backup.name}: preparing import"
                    ))

                    self.current_process = process = None
                    total_size = max(backup.stat().st_size, 1)
                    restore_start = time.monotonic()

                    # Use temporary files for stdout and stderr to prevent pipe deadlocks
                    stdout_fd, stdout_path = tempfile.mkstemp(suffix=".out")
                    stderr_fd, stderr_path = tempfile.mkstemp(suffix=".err")
                    os.close(stdout_fd)
                    os.close(stderr_fd)

                    try:
                        with open(backup, "rb") as sql_file, open(stdout_path, "wb") as out_f, open(stderr_path, "wb") as err_f:
                            self.current_process = process = self._popen_hidden_command(
                                self.mysql_command(
                                    cfg,
                                    option,
                                    database=db_name
                                ),
                                stdin=sql_file,
                                stdout=out_f,
                                stderr=err_f
                            )

                            while process.poll() is None:
                                if self.stop_event.is_set() or self.skip_event.is_set():
                                    try:
                                        process.kill()
                                    except Exception:
                                        pass
                                    break

                                try:
                                    current_pos = sql_file.tell()
                                except Exception:
                                    current_pos = 0

                                percent = min(99, int(current_pos / total_size * 100))
                                elapsed = max(time.monotonic() - restore_start, 0.1)
                                eta_seconds = (elapsed / max(percent, 1)) * (100 - percent) if percent > 0 else 0
                                eta_text = self.format_eta(eta_seconds)

                                self.events.put((
                                    "progress",
                                    percent,
                                    f"Restoring {backup.name}: {percent}% • {eta_text}"
                                ))
                                time.sleep(0.2)

                            process.wait()
                        self.current_process = None

                        stdout = Path(stdout_path).read_text(encoding="utf-8", errors="replace") if os.path.exists(stdout_path) else ""
                        stderr = Path(stderr_path).read_text(encoding="utf-8", errors="replace") if os.path.exists(stderr_path) else ""
                        output = stderr + "\n" + stdout

                        if process.returncode != 0 and not self.skip_event.is_set():
                            raise RuntimeError(
                                f"MySQL exit code: {process.returncode}\n{output}"
                            )

                    except subprocess.TimeoutExpired:
                        if process:
                            process.kill()
                            process.wait()
                        raise RuntimeError(
                            f"Restore exceeded {cfg['timeout']} seconds."
                        )
                    finally:
                        if stdout_path and os.path.exists(stdout_path):
                            try:
                                os.remove(stdout_path)
                            except Exception:
                                pass
                        if stderr_path and os.path.exists(stderr_path):
                            try:
                                os.remove(stderr_path)
                            except Exception:
                                pass

                    verify = self._run_hidden_command(
                        self.mysql_command(
                            cfg,
                            option,
                            sql=(
                                "SELECT COUNT(*) FROM information_schema.tables "
                                f"WHERE table_schema = '{db_name}'"
                            )
                        ),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30
                    )

                    if verify.returncode != 0:
                        raise RuntimeError(
                            "VERIFICATION FAILED:\n" + verify.stderr
                        )

                    table_count = int(
                        verify.stdout.strip().splitlines()[-1]
                    )

                    if table_count == 0:
                        raise RuntimeError(
                            "Restore completed but no tables were found."
                        )

                    status = "PASS"
                    output += (
                        f"\n\nVerification successful."
                        f"\nTables found: {table_count}"
                    )

                except Exception as exc:

                    clean = self._clean_error(exc)
                    friendly = self._friendly_sql_error(clean, db_name)

                    technical = output.strip()

                    if technical:
                        output = (
                            f"Restore failed: {clean}\n\n"
                            f"Likely reason: {friendly}\n\n"
                            f"Technical details:\n{technical}"
                        )
                    else:
                        output = (
                            f"Restore failed: {clean}\n\n"
                            f"Likely reason: {friendly}"
                        )

                    self._write_error_log(backup, db_name, output)

                duration = round(
                    time.monotonic() - started, 2
                )

                self.skip_event.clear()

                self.results[str(backup)] = {
                    "status": status,
                    "database": db_name or "-",
                    "duration": duration,
                    "details": output
                }

                report_rows.append({
                    "file": backup.name,
                    "database": db_name or "-",
                    "status": status,
                    "duration": duration,
                    "details": output
                })

                self.events.put((
                    "row",
                    str(backup),
                    status,
                    db_name or "-",
                    f"{duration}s"
                ))

                self.events.put((
                    "details",
                    str(backup),
                    output
                ))

                if status == "FAIL":
                    self.events.put((
                        "file_failed",
                        str(backup),
                        output
                    ))

                self.events.put((
                    "progress",
                    100,
                    f"{status}: {backup.name}"
                ))

            report = (
                Path(self.folder_var.get())
                / f"restore_report_{run_id}.csv"
            )

            with report.open(
                "w",
                newline="",
                encoding="utf-8-sig"
            ) as f:

                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "file",
                        "database",
                        "status",
                        "duration",
                        "details"
                    ]
                )

                writer.writeheader()
                writer.writerows(report_rows)

            self.events.put((
                "finished",
                len(report_rows),
                str(report)
            ))

        except Exception as exc:

            self.events.put((
                "fatal",
                str(exc)
            ))

        finally:

            if option and os.path.exists(option):
                os.remove(option)

    # ---------------- PROGRESS AND EVENTS ----------------

    def process_events(self):

        try:

            while True:

                event = self.events.get_nowait()
                kind = event[0]

                if kind == "progress":

                    percent = event[1]
                    status_text = event[2]
                    text_lower = status_text.lower()

                    eta = None
                    if "• ETA " in status_text:
                        eta = status_text.split("• ETA ", 1)[1].strip()

                    if (
                        self.worker is not None
                        and self.worker.is_alive()
                        and percent <= 0
                        and "failed" not in text_lower
                        and "completed" not in text_lower
                        and "passed" not in text_lower
                    ):
                        self.set_progress_loader(True, text=status_text)
                        continue

                    if self.worker is not None and self.worker.is_alive() and percent < 100:
                        self.set_progress_loader(False, percent=percent, text=status_text, eta=eta)
                    else:
                        self.set_progress_loader(False, percent=percent, text=status_text, eta=eta)

                elif kind == "row":

                    _, path, status, database, duration = event

                    iid = next(
                        (
                            key for key, value in self.row_paths.items()
                            if str(value) == path
                        ),
                        None
                    )

                    if iid:

                        backup = self.row_paths[iid]

                        self.tree.item(
                            iid,
                            values=(
                                backup.name,
                                self.human_size(backup.stat().st_size),
                                database,
                                status,
                                duration
                            ),
                            tags=(status,)
                        )

                elif kind == "details":

                    _, path, output = event

                    self.results.setdefault(path, {
                        "status": "FAIL",
                        "database": "-",
                        "duration": 0,
                        "details": ""
                    })
                    self.results[path]["details"] = output

                    self.show_error()

                elif kind == "file_failed":

                    _, path, output = event

                    popup = tk.Toplevel(self)
                    popup.title("Restore Failed")
                    ttk.Label(popup, text=f"File: {Path(path).name}\n\n{output[:500]}", padding=12, wraplength=400).pack()
                    popup.after(4000, popup.destroy)

                elif kind == "finished":

                    count, report = event[1:]

                    self.stop_button.config(state="disabled")
                    self.worker = None

                    passed = sum(
                        1 for r in self.results.values()
                        if r["status"] == "PASS"
                    )

                    failed = sum(
                        1 for r in self.results.values()
                        if r["status"] == "FAIL"
                    )

                    self.set_progress_loader(False, percent=100, text=f"Completed: {count} | Passed: {passed} | Failed: {failed}", eta="ETA 00:00")

                    popup = tk.Toplevel(self)
                    popup.title("Restore Completed")
                    ttk.Label(popup, text=f"Processed: {count}\nPassed: {passed}\nFailed: {failed}\nReport: {report}", padding=12).pack()
                    popup.after(4000, popup.destroy)

                elif kind == "fatal":

                    self.stop_button.config(state="disabled")
                    self.worker = None
                    self.set_progress_loader(False, percent=100, text="Restore failed.", eta="ETA --")

                    messagebox.showerror(
                        "Restore Error",
                        event[1]
                    )

        except queue.Empty:
            pass

        self.after(100, self.process_events)

    # ---------------- ERROR VIEWER ----------------

    def show_error(self, event=None):

        selection = self.tree.selection()

        if not selection:
            return

        backup = self.row_paths.get(selection[0])

        if not backup:
            return

        result = self.results.get(str(backup))

        self.error_text.delete("1.0", "end")

        if result:

            self.error_text.insert(
                "1.0",
                f"File: {backup.name}\n"
                f"Database: {result['database']}\n"
                f"Status: {result['status']}\n"
                f"Duration: {result['duration']} seconds\n\n"
                f"{result['details']}"
            )

        else:

            self.error_text.insert(
                "1.0",
                f"File: {backup.name}\nPending..."
            )

    # ---------------- REPORT ----------------

    def export_report(self):

        if not self.results:
            messagebox.showinfo(
                "Report",
                "No restore results available."
            )
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")]
        )

        if not path:
            return

        with open(
            path,
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "file",
                    "database",
                    "status",
                    "duration",
                    "details"
                ]
            )

            writer.writeheader()

            for filename, result in self.results.items():

                writer.writerow({
                    "file": Path(filename).name,
                    **result
                })

        messagebox.showinfo(
            "Export",
            "Report exported successfully."
        )

    # ---------------- STOP ----------------

    def stop_restore(self):

        self.stop_event.set()
        if getattr(self, "current_process", None):
            try:
                self.current_process.kill()
            except Exception:
                pass

        self.set_progress_loader(False, percent=max(0, int(self.progress_var.get())), text="Stop requested. Current backup will finish first.")

    def skip_restore(self):
        self.skip_event.set()
        if getattr(self, "current_process", None):
            try:
                self.current_process.kill()
            except Exception:
                pass
        self.set_progress_loader(False, percent=max(0, int(self.progress_var.get())), text="Skip requested.")

    def close_app(self):

        if self.worker and self.worker.is_alive():

            if not messagebox.askyesno(
                "Restore Running",
                "A restore is running. Close the application?"
            ):
                return

            self.stop_event.set()
            if getattr(self, "current_process", None):
                try:
                    self.current_process.kill()
                except Exception:
                    pass

        self.destroy()


if __name__ == "__main__":

    app = RestoreApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        try:
            app.stop_event.set()
            if app.worker and app.worker.is_alive():
                app.current_process = getattr(app, "current_process", None)
                if app.current_process:
                    try:
                        app.current_process.kill()
                    except Exception:
                        pass
            app.destroy()
        except Exception:
            pass