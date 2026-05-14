# -*- coding: utf-8 -*-
import sys
import time

from app.startup import bootstrap_startup
from performance import audit_python_sources, log_performance, perf_timer


def main():
    app_start = time.perf_counter()
    with perf_timer("startup_bootstrap"):
        bootstrap_startup()
    audit_python_sources()

    from app.application import MatadorsKasaApp

    with perf_timer("uygulama_init"):
        app = MatadorsKasaApp()
    log_performance("uygulama_acilis_suresi", (time.perf_counter() - app_start) * 1000.0)
    with perf_timer("mainloop_cikisina_kadar_calisma"):
        app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_msg = f"Program baslatilirken hata olustu: {str(e)}"
        print(error_msg)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Baslatma Hatasi", error_msg)
            root.destroy()
        except Exception:
            print(f"Kritik hata: {error_msg}")
            print("Program devam edemiyor. Lutfen sistem yoneticinize basvurun.")
        sys.exit(1)
