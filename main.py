"""Entry point for AIRTS."""
from app import App

if __name__ == "__main__":
    try:
        App().run()
    except Exception as exc:
        from systems.crash_handler import log_crash
        path = log_crash(exc, context="fatal")
        print(f"[AIRTS] Fatal crash — log saved to {path}")
