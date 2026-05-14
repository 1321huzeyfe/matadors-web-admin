# -*- coding: utf-8 -*-
"""Small keyboard shortcut helpers shared by Tk/CustomTkinter forms."""

from __future__ import annotations

from tkinter import messagebox


def _is_multiline_text_widget(widget) -> bool:
    """Return True when Enter should keep its native newline behavior."""
    try:
        if widget.winfo_class() == "Text":
            return True
    except Exception:
        pass

    current = widget
    while current is not None:
        if "CTkTextbox" in type(current).__name__:
            return True
        try:
            parent_name = current.winfo_parent()
            current = current.nametowidget(parent_name) if parent_name else None
        except Exception:
            current = None
    return False


def bind_enter_action(widget, action, error_title: str = "Hata") -> None:
    """Run action on Enter, except inside multiline text inputs."""
    def handler(event):
        if _is_multiline_text_widget(event.widget):
            return None
        try:
            action()
        except Exception as exc:
            messagebox.showerror(error_title, f"İşlem yapılırken hata oluştu:\n{exc}")
        return "break"

    for target in _walk_widgets(widget):
        target.bind("<Return>", handler, add="+")
        target.bind("<KP_Enter>", handler, add="+")


def bind_ctrl_shortcut(widget, sequence: str, action, error_title: str = "Hata") -> None:
    """Bind a Ctrl shortcut to an existing command without duplicating UI."""
    def handler(_event):
        try:
            action()
        except Exception as exc:
            messagebox.showerror(error_title, f"Kısayol çalıştırılırken hata oluştu:\n{exc}")
        return "break"

    for target in _walk_widgets(widget):
        target.bind(sequence, handler, add="+")


def _walk_widgets(widget):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _walk_widgets(child)
