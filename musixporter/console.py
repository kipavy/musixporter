try:
    from rich.console import Console
    from rich.theme import Theme
    console = Console(theme=Theme({"info": "cyan", "success": "green", "error": "bold red", "warn": "yellow"}))
except Exception:
    class _Fallback:
        def print(self, *args, **kwargs):
            print(*args)
        def print_exception(self, *args, **kwargs):
            import traceback
            traceback.print_exc()
    console = _Fallback()

def info(msg, **kwargs):
    try:
        console.print(msg, style="info", **kwargs)
    except Exception:
        console.print(msg)

def success(msg, **kwargs):
    try:
        console.print(msg, style="success", **kwargs)
    except Exception:
        console.print(msg)

def warn(msg, **kwargs):
    try:
        console.print(msg, style="warn", **kwargs)
    except Exception:
        console.print(msg)

def error(msg, **kwargs):
    try:
        console.print(msg, style="error", **kwargs)
    except Exception:
        console.print(msg)
