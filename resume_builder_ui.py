#!/usr/bin/env python
"""Small desktop UI for regenerating resume DOCX files."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import BOTH, DISABLED, END, NORMAL, Button, Frame, Label, StringVar, Text, Tk, messagebox

from generate_resume import generate


APP_TITLE = "Resume Builder"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class ResumeBuilderApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.base_dir = app_dir()
        self.status = StringVar(value="Ready")

        root.title(APP_TITLE)
        root.geometry("560x360")
        root.minsize(500, 320)

        container = Frame(root, padx=16, pady=14)
        container.pack(fill=BOTH, expand=True)

        Label(container, text="Resume Builder", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        Label(container, text=str(self.base_dir), fg="#555555").pack(anchor="w", pady=(2, 12))

        button_row = Frame(container)
        button_row.pack(anchor="w", pady=(0, 10))

        self.buttons: list[Button] = [
            Button(button_row, text="Generate Both", width=16, command=lambda: self.run_task("both")),
            Button(button_row, text="English Only", width=14, command=lambda: self.run_task("en")),
            Button(button_row, text="Chinese Only", width=14, command=lambda: self.run_task("zh")),
            Button(button_row, text="Open Folder", width=12, command=self.open_folder),
        ]
        for button in self.buttons:
            button.pack(side="left", padx=(0, 8))

        Label(container, textvariable=self.status, fg="#333333").pack(anchor="w", pady=(0, 6))

        self.log = Text(container, height=12, wrap="word", font=("Consolas", 9))
        self.log.pack(fill=BOTH, expand=True)
        self.write_log("Ready. Edit resume_en.yaml or resume_zh.yaml, then click Generate Both.\n")

    def set_busy(self, busy: bool) -> None:
        for button in self.buttons:
            button.configure(state=DISABLED if busy else NORMAL)
        self.status.set("Generating..." if busy else "Ready")

    def write_log(self, text: str) -> None:
        self.log.configure(state=NORMAL)
        self.log.insert(END, text)
        self.log.see(END)
        self.log.configure(state=DISABLED)

    def paths_for(self, lang: str) -> tuple[Path, Path, Path, Path]:
        if lang == "en":
            return (
                self.base_dir / "resume_en.yaml",
                self.base_dir / "style_config.yaml",
                self.base_dir / "resume_en.docx",
                self.base_dir / "resume_en.log",
            )
        return (
            self.base_dir / "resume_zh.yaml",
            self.base_dir / "style_config.yaml",
            self.base_dir / "resume_zh.docx",
            self.base_dir / "resume_zh.log",
        )

    def run_task(self, target: str) -> None:
        self.set_busy(True)
        self.write_log(f"\nStarting: {target}\n")
        thread = threading.Thread(target=self.generate_target, args=(target,), daemon=True)
        thread.start()

    def generate_target(self, target: str) -> None:
        try:
            langs = ["en", "zh"] if target == "both" else [target]
            for lang in langs:
                input_path, config_path, output_path, log_path = self.paths_for(lang)
                self.root.after(0, self.write_log, f"Generating {output_path.name}...\n")
                generate(input_path, config_path, lang, output_path, export_pdf=False, log_path=log_path)
                self.root.after(0, self.write_log, f"Done: {output_path.name}\n")
            self.root.after(0, self.status.set, "Generated successfully")
        except Exception as exc:  # UI boundary: report full details in log.
            details = traceback.format_exc()
            self.root.after(0, self.write_log, f"ERROR: {exc}\n\n{details}\n")
            self.root.after(0, self.status.set, "Failed")
            self.root.after(0, messagebox.showerror, APP_TITLE, str(exc))
        finally:
            self.root.after(0, self.set_busy, False)

    def open_folder(self) -> None:
        if sys.platform.startswith("win"):
            os.startfile(self.base_dir)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(self.base_dir)])


def main() -> None:
    root = Tk()
    ResumeBuilderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
