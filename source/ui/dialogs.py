from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from core.models import Finding
from core.safety import review_folder
from utils.formatting import format_bytes


def confirm_move(parent: tk.Tk, findings: list[Finding], execute: bool) -> bool:
    total = sum(item.size_bytes for item in findings)
    mode = "MOVE TO REVIEW" if execute else "DRY RUN"
    message = (
        f"{mode}\n\n"
        f"Items: {len(findings)}\n"
        f"Total size: {format_bytes(total)}\n"
        f"Destination:\n{review_folder()}\n\n"
        "StoragePilot never permanently deletes these files. "
        "Dry run previews the operation without moving anything."
    )
    return messagebox.askyesno("Move to Review", message, parent=parent)


def confirm_recycle(parent: tk.Tk, findings: list[Finding]) -> bool:
    total = sum(item.size_bytes for item in findings)
    message = (
        f"Remove {len(findings)} item(s)?\n\n"
        f"Total size: {format_bytes(total)}\n\n"
        "These files will be moved to the Windows Recycle Bin and can be restored from there."
    )
    return messagebox.askyesno("Move to Recycle Bin", message, parent=parent)


def show_error(parent: tk.Tk, title: str, message: str) -> None:
    messagebox.showerror(title, message, parent=parent)


def show_info(parent: tk.Tk, title: str, message: str) -> None:
    messagebox.showinfo(title, message, parent=parent)
