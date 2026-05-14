# -*- coding: utf-8 -*-
import os
import sys
import locale


def configure_process_environment():
    os.environ["TK_SCALE"] = "1.0"
    os.environ["TK_DPI_AWARENESS"] = "1"

    if sys.platform == 'win32':
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    ctypes.windll.shcore.SetProcessDpiAwareness(1)
                except Exception:
                    pass
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        except Exception:
            pass


def configure_tk_scaling():
    import tkinter as tk
    root_temp = tk.Tk()
    root_temp.withdraw()
    root_temp.tk.call('tk', 'scaling', 1.0)
    return root_temp


def configure_customtkinter_scaling(ctk):
    ctk.deactivate_automatic_dpi_awareness()
    ctk.set_widget_scaling(1)
    ctk.set_window_scaling(1)


def safe_startup():
    """Safe startup with comprehensive error handling."""
    locale_set = False

    try:
        try:
            locale.setlocale(locale.LC_ALL, 'Turkish_Turkey.1254')
            locale_set = True
        except locale.Error:
            try:
                locale.setlocale(locale.LC_ALL, 'tr_TR.UTF-8')
                locale_set = True
            except locale.Error:
                pass
        except Exception as e:
            print(f"Startup warning: Error setting locale: {e}")
    except Exception as e:
        print(f"Startup warning: Locale setup failed: {e}")

    try:
        try:
            import tkinter.font as tkfont
            default_font = tkfont.nametofont("TkDefaultFont")
            default_font.configure(family="Segoe UI", size=14, weight="normal")
            tkfont.nametofont("TkTextFont").configure(family="Segoe UI", size=14, weight="normal")
            tkfont.nametofont("TkFixedFont").configure(family="Consolas", size=14, weight="normal")
            tkfont.nametofont("TkMenuFont").configure(family="Segoe UI", size=12, weight="normal")
            tkfont.nametofont("TkCaptionFont").configure(family="Segoe UI", size=11, weight="normal")
            tkfont.nametofont("TkSmallCaptionFont").configure(family="Segoe UI", size=10, weight="normal")
            tkfont.nametofont("TkIconFont").configure(family="Segoe UI", size=12, weight="normal")
            tkfont.nametofont("TkTooltipFont").configure(family="Segoe UI", size=11, weight="normal")
        except Exception as e:
            print(f"Startup warning: Font configuration failed, using defaults. Error: {e}")
            try:
                import tkinter.font as tkfont
                default_font = tkfont.nametofont("TkDefaultFont")
                default_font.configure(family="Arial", size=12)
                tkfont.nametofont("TkTextFont").configure(family="Arial", size=12)
                tkfont.nametofont("TkFixedFont").configure(family="Courier New", size=12)
            except Exception:
                pass
    except Exception as e:
        print(f"Startup warning: Font setup failed: {e}")

    return True, locale_set


def bootstrap_startup():
    configure_process_environment()
    root_temp = configure_tk_scaling()

    import customtkinter as ctk
    configure_customtkinter_scaling(ctk)

    try:
        startup_success, locale_success = safe_startup()
    finally:
        try:
            root_temp.destroy()
        except Exception:
            pass
    print(f"Startup completed - Locale success: {locale_success}")
    return ctk, startup_success, locale_success
