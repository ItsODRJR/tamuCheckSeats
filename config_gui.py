import os
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image
import sys
import requests
import pystray

import scheduler_bot

CONFIG_DIR  = os.path.join(os.environ["LOCALAPPDATA"], "TAMUClassSwap")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
COOKIE      = ""

def save_config(data: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=4)


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        save_config({})
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


cfg = load_config()
COOKIE = cfg.get("cookie", "")

class ScrollableFrame(tk.Frame):
    def __init__(self, parent, width=650, height=250):
        super().__init__(parent)

        self.canvas = tk.Canvas(self, borderwidth=0, width=width, height=height)
        self.vsb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

    def get_frame(self):
        return self._inner

class CourseGroupFrame(tk.Frame):
    """Single CRN entry in Watch Mode."""

    def __init__(self, parent, remove_cb, fetch_by_crn_cb):
        super().__init__(parent, borderwidth=1, relief="groove", padx=5, pady=5)

        self.remove_cb = remove_cb
        self.fetch_by_crn_cb = fetch_by_crn_cb

        self.crn_var = tk.StringVar()
        self.course_title_var = tk.StringVar()

        tk.Label(self, text="CRN:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        e = tk.Entry(self, textvariable=self.crn_var, width=15)
        e.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        e.bind("<FocusOut>", self.on_crn_focus_out)

        tk.Button(self, text="Remove", command=self.remove_self)\
            .grid(row=0, column=2, padx=5, pady=5)

        tk.Label(self, text="Course:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        tk.Label(self, textvariable=self.course_title_var, width=40,
                 anchor="w", relief="sunken")\
            .grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="w")

    def on_crn_focus_out(self, _event):
        crn = self.crn_var.get().strip()
        if not crn:
            self.course_title_var.set("")
            return

        self.course_title_var.set("searching…")

        def worker():
            title = self.fetch_by_crn_cb(crn)
            self.after(0, lambda: self.course_title_var.set(title or "n/a"))

        threading.Thread(target=worker, daemon=True).start()

    def remove_self(self):
        self.destroy()
        if self.remove_cb:
            self.remove_cb(self)

    def get_crn(self):
        return self.crn_var.get().strip()

class SwapPairFrame(tk.Frame):
    """Swap pair entry in Swap Mode."""

    def __init__(self, parent, remove_cb, fetch_by_crn_cb):
        super().__init__(parent, borderwidth=1, relief="groove", padx=5, pady=5)

        self.remove_cb = remove_cb
        self.fetch_by_crn_cb = fetch_by_crn_cb

        self.swap_from_var = tk.StringVar()
        self.swap_to_var = tk.StringVar()
        self.from_title_var = tk.StringVar()
        self.to_title_var = tk.StringVar()

        tk.Label(self, text="Swap From (CRN):")\
            .grid(row=0, column=0, padx=5, pady=5, sticky="e")
        e_from = tk.Entry(self, textvariable=self.swap_from_var, width=15)
        e_from.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        e_from.bind("<FocusOut>", self.on_from_focus_out)

        tk.Label(self, text="Course:").grid(row=1, column=0, padx=5, pady=2, sticky="e")
        tk.Label(self, textvariable=self.from_title_var, width=40,
                 anchor="w", relief="sunken")\
            .grid(row=1, column=1, padx=5, pady=2, sticky="w")
            
        tk.Label(self, text="Swap To (CRN):")\
            .grid(row=2, column=0, padx=5, pady=5, sticky="e")
        e_to = tk.Entry(self, textvariable=self.swap_to_var, width=15)
        e_to.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        e_to.bind("<FocusOut>", self.on_to_focus_out)

        tk.Label(self, text="Course:")\
            .grid(row=3, column=0, padx=5, pady=2, sticky="e")
        tk.Label(self, textvariable=self.to_title_var, width=40,
                 anchor="w", relief="sunken")\
            .grid(row=3, column=1, padx=5, pady=2, sticky="w")

        tk.Button(self, text="Remove Pair", command=self.remove_self)\
            .grid(row=4, column=0, columnspan=2, pady=5)

    def _do_lookup(self, var, crn):
        var.set("searching…")

        def worker():
            title = self.fetch_by_crn_cb(crn)
            self.after(0, lambda: var.set(title or "n/a"))

        threading.Thread(target=worker, daemon=True).start()

    def on_from_focus_out(self, _):
        crn = self.swap_from_var.get().strip()
        if crn:
            self._do_lookup(self.from_title_var, crn)

    def on_to_focus_out(self, _):
        crn = self.swap_to_var.get().strip()
        if crn:
            self._do_lookup(self.to_title_var, crn)

    def remove_self(self):
        self.destroy()
        if self.remove_cb:
            self.remove_cb(self)

    def get_swap_from(self):
        return self.swap_from_var.get().strip()

    def get_swap_to(self):
        return self.swap_to_var.get().strip()


class ConfigTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.cookie_var   = tk.StringVar()
        self.token_var    = tk.StringVar()
        self.channel_var  = tk.StringVar()
        self.id_var       = tk.StringVar()
        self.term_var     = tk.StringVar()
        self.type_var     = tk.StringVar(value="watch")

        self.course_groups = []
        self.swap_pairs = []
        self._term_map = {}

        self.grid_rowconfigure(10, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)

        self.build_ui()
        self.load_config_into_fields()
        self.update_type_fields()

    def fetch_terms(self):
        cookie = self.cookie_var.get() or COOKIE
        try:
            resp = requests.get(
                "https://howdy.tamu.edu/api/all-terms",
                headers={"Cookie": cookie},
                timeout=10,
            )
            resp.raise_for_status()
            terms = resp.json()
            self._term_map = {
                t["STVTERM_DESC"]: t["STVTERM_CODE"]
                for t in terms if "STVTERM_DESC" in t
            }
            return list(self._term_map.keys())
        except Exception as e:
            print("[ConfigTab] Error fetching terms:", e)
            return []

    def fetch_by_crn(self, crn):
        cookie = self.cookie_var.get() or COOKIE
        term_desc = self.term_var.get()
        term_code = self._term_map.get(term_desc)
        if not term_code:
            return None

        payload = {
            "startRow": 0,
            "endRow": 0,
            "termCode": term_code,
            "publicSearch": "Y",
            "crn": crn,
        }

        try:
            resp = requests.post(
                "https://howdy.tamu.edu/api/course-sections",
                json=payload,
                headers={"Cookie": cookie},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            sections = data if isinstance(data, list) else data.get("courseSections", [])
            for s in sections:
                if str(s.get("SWV_CLASS_SEARCH_CRN", "")) == crn:
                    sub = s["SWV_CLASS_SEARCH_SUBJECT"]
                    num = s["SWV_CLASS_SEARCH_COURSE"]
                    title = s["SWV_CLASS_SEARCH_TITLE"]
                    return f"{sub} {num} – {title}"
        except Exception as e:
            print("[ConfigTab] CRN lookup error:", e)

        return None

    def on_term_select(self, _event):
        for cg in self.course_groups:
            cg.course_title_var.set("")

        for sp in self.swap_pairs:
            sp.from_title_var.set("")
            sp.to_title_var.set("")

    def refresh_terms_and_courses(self):
        def worker():
            terms = self.fetch_terms()
            self.after(0, lambda: self.term_dropdown.config(values=terms))

        threading.Thread(target=worker, daemon=True).start()

    def build_ui(self):
        row = 0

        tk.Label(self, text="Required Settings", font=("Helvetica", 14, "bold"))\
            .grid(row=row, column=0, columnspan=3, pady=(10, 5))
        row += 1

        tk.Label(self, text="CollegeScheduler Username")\
            .grid(row=row, column=0, sticky="e", padx=5, pady=5)
        tk.Entry(self, textvariable=self.username_var, width=40)\
            .grid(row=row, column=1, sticky="w", padx=5, pady=5)
        row += 1

        tk.Label(self, text="CollegeScheduler Password")\
            .grid(row=row, column=0, sticky="e", padx=5, pady=5)
        tk.Entry(self, textvariable=self.password_var, show="*", width=40)\
            .grid(row=row, column=1, sticky="w", padx=5, pady=5)
        row += 1

        tk.Label(self, text="CollegeScheduler Cookie")\
            .grid(row=row, column=0, sticky="e", padx=5, pady=5)
        ce = tk.Entry(self, textvariable=self.cookie_var, show="*", width=40)
        ce.grid(row=row, column=1, sticky="w", padx=5, pady=5)
        ce.bind("<FocusOut>", lambda _e: self.refresh_terms_and_courses())
        row += 1

        tk.Label(self, text="Discord Token")\
            .grid(row=row, column=0, sticky="e", padx=5, pady=5)
        tk.Entry(self, textvariable=self.token_var, show="*", width=40)\
            .grid(row=row, column=1, sticky="w", padx=5, pady=5)
        row += 1

        tk.Label(self, text="Discord Channel Name")\
            .grid(row=row, column=0, sticky="e", padx=5, pady=5)
        tk.Entry(self, textvariable=self.channel_var, width=40)\
            .grid(row=row, column=1, sticky="w", padx=5, pady=5)
        row += 1

        tk.Label(self, text="Discord Account ID")\
            .grid(row=row, column=0, sticky="e", padx=5, pady=5)
        tk.Entry(self, textvariable=self.id_var, width=40)\
            .grid(row=row, column=1, sticky="w", padx=5, pady=5)
        row += 1

        tk.Label(self, text="Term Name")\
            .grid(row=row, column=0, sticky="e", padx=5, pady=5)

        self.term_dropdown = ttk.Combobox(
            self,
            textvariable=self.term_var,
            values=[],
            state="readonly",
            width=37,
        )
        self.term_dropdown.grid(row=row, column=1, sticky="w", padx=5, pady=5)
        self.term_dropdown.bind("<<ComboboxSelected>>", self.on_term_select)
        self.after(0, self.refresh_terms_and_courses)
        row += 1

        tk.Label(self, text="Select Mode", font=("Helvetica", 14, "bold"))\
            .grid(row=row, column=0, columnspan=3, pady=(10, 5))
        row += 1

        mode_frame = tk.Frame(self)
        mode_frame.grid(row=row, column=0, columnspan=3)
        tk.Label(mode_frame, text="Type:").pack(side="left", padx=10)
        tk.Radiobutton(mode_frame, text="Watch", variable=self.type_var,
                       value="watch", command=self.update_type_fields).pack(side="left")
        tk.Radiobutton(mode_frame, text="Swap", variable=self.type_var,
                       value="swap", command=self.update_type_fields).pack(side="left")
        row += 1

        self.course_groups_scroll = ScrollableFrame(self, width=650, height=250)
        self.course_groups_container = self.course_groups_scroll.get_frame()
        self.course_groups_scroll.grid(row=10, column=0, columnspan=3, sticky="nsew")

        tk.Button(self, text="Add CRN", command=self.add_course_group)\
            .grid(row=11, column=0, columnspan=3, pady=5)

        self.swap_pairs_scroll = ScrollableFrame(self, width=650, height=250)
        self.swap_pairs_container = self.swap_pairs_scroll.get_frame()
        self.swap_pairs_scroll.grid(row=10, column=0, columnspan=3, sticky="nsew")

        tk.Button(self, text="Add Swap Pair", command=self.add_swap_pair)\
            .grid(row=11, column=0, columnspan=3, pady=5)

        save_frame = tk.Frame(self)
        save_frame.grid(row=15, column=0, columnspan=3, sticky="we", pady=5)
        tk.Button(save_frame, text="Save Config", command=self.save_fields_to_config)\
            .pack(side="right")
        tk.Label(save_frame, text="Make sure to save config!", fg="gray")\
            .pack(side="left")

    def add_course_group(self):
        cg = CourseGroupFrame(
            self.course_groups_container, self.remove_course_group,
            self.fetch_by_crn
        )
        cg.pack(fill="x", pady=5, padx=5)
        self.course_groups.append(cg)

    def remove_course_group(self, cg):
        self.course_groups.remove(cg)

    def add_swap_pair(self):
        sp = SwapPairFrame(
            self.swap_pairs_container, self.remove_swap_pair,
            self.fetch_by_crn
        )
        sp.pack(fill="x", pady=5, padx=5)
        self.swap_pairs.append(sp)

    def remove_swap_pair(self, sp):
        self.swap_pairs.remove(sp)

    def update_type_fields(self):
        if self.type_var.get() == "watch":
            self.swap_pairs_scroll.grid_remove()
            self.course_groups_scroll.grid()
        else:
            self.course_groups_scroll.grid_remove()
            self.swap_pairs_scroll.grid()

    def load_config_into_fields(self):
        global COOKIE
        data = load_config()

        self.username_var.set(data.get("username", ""))
        self.password_var.set(data.get("password", ""))
        self.cookie_var.set(data.get("cookie", ""))
        COOKIE = data.get("cookie", "")
        self.token_var.set(data.get("discord_token", ""))
        self.channel_var.set(data.get("channel_name", ""))
        self.id_var.set(data.get("discord_account_id", ""))
        self.term_var.set(data.get("term_name", ""))
        self.type_var.set(data.get("type", "watch"))

        for cg in self.course_groups:
            cg.destroy()
        self.course_groups.clear()

        for sp in self.swap_pairs:
            sp.destroy()
        self.swap_pairs.clear()

        for crn in data.get("crns_to_watch", []):
            cg = CourseGroupFrame(
                self.course_groups_container,
                self.remove_course_group,
                self.fetch_by_crn,
            )
            cg.crn_var.set(crn)
            cg.pack(fill="x", pady=5)
            cg.on_crn_focus_out(None)
            self.course_groups.append(cg)

        for pair in data.get("swap_pairs", []):
            sp = SwapPairFrame(
                self.swap_pairs_container,
                self.remove_swap_pair,
                self.fetch_by_crn,
            )
            sp.swap_from_var.set(pair.get("swap_from", ""))
            sp.swap_to_var.set(pair.get("swap_to", ""))
            sp.pack(fill="x", pady=5)
            sp.on_from_focus_out(None)
            sp.on_to_focus_out(None)
            self.swap_pairs.append(sp)

    def save_fields_to_config(self):
        cfg = {
            "username": self.username_var.get(),
            "password": self.password_var.get(),
            "cookie": self.cookie_var.get(),
            "discord_token": self.token_var.get(),
            "channel_name": self.channel_var.get(),
            "discord_account_id": self.id_var.get(),
            "term_name": self.term_var.get(),
            "type": self.type_var.get(),
            "crns_to_watch": [cg.get_crn() for cg in self.course_groups],
            "swap_pairs": [
                {"swap_from": sp.get_swap_from(), "swap_to": sp.get_swap_to()}
                for sp in self.swap_pairs
            ],
        }

        save_config(cfg)
        global COOKIE
        COOKIE = self.cookie_var.get()
        messagebox.showinfo("Saved", "Configuration saved!")
        self.update_type_fields()


class MonitorTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.log_box = tk.Text(self, height=20, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=10, pady=10)

        sys.stdout = TextRedirector(self.log_box)

        btn_frame = tk.Frame(self)
        btn_frame.pack()

        tk.Button(btn_frame, text="Start Monitor", command=self.start_monitor)\
            .pack(side="left", padx=5)
        tk.Button(btn_frame, text="Stop Monitor", command=self.stop_monitor)\
            .pack(side="left", padx=5)

    def start_monitor(self):
        threading.Thread(target=scheduler_bot.start_monitoring, daemon=True).start()
        self.log("Monitoring started.")

    def stop_monitor(self):
        scheduler_bot.stop_monitoring()
        self.log("Monitoring stop requested.")

    def log(self, msg):
        self.log_box.insert(tk.END, msg + "\n")
        self.log_box.see(tk.END)


class TextRedirector:
    def __init__(self, widget):
        self.widget = widget

    def write(self, msg):
        self.widget.insert(tk.END, msg)
        self.widget.see(tk.END)

    def flush(self):
        pass


def main():
    root = tk.Tk()
    root.title("CollegeScheduler Monitor")

    icon_path = os.path.join(os.path.dirname(__file__), "scheduler_logo.ico")
    if os.path.exists(icon_path):
        root.iconbitmap(default=icon_path)
        icon_image = Image.open(icon_path)
    else:
        icon_image = Image.new("RGB", (64, 64), "white")

    notebook = ttk.Notebook(root)
    monitor = MonitorTab(notebook)
    config = ConfigTab(notebook)
    notebook.add(monitor, text="Monitor")
    notebook.add(config, text="Config")
    notebook.pack(fill="both", expand=True)

    def hide_window():
        root.withdraw()
        show_tray_icon()

    def show_window(icon, _item):
        icon.stop()
        root.after(0, root.deiconify)

    def quit_app(icon, _item):
        icon.stop()
        root.destroy()

    def show_tray_icon():
        menu = pystray.Menu(
            pystray.MenuItem("Show", show_window),
            pystray.MenuItem("Quit", quit_app),
        )

        tray = pystray.Icon("CollegeScheduler", icon_image, "CollegeScheduler", menu)
        threading.Thread(target=tray.run, daemon=True).start()

    root.protocol("WM_DELETE_WINDOW", hide_window)
    root.bind("<Unmap>", lambda e: hide_window() if root.state() == "iconic" else None)

    root.geometry("800x600")
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w // 2) - (w // 2)
    y = (screen_h // 2) - (h // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")

    root.mainloop()

if __name__ == "__main__":
    main()
