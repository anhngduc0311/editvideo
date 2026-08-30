"""
Main Entry Point for AI Vocal & Instrumental Separator Tool.
Launches GUI by default or CLI if command-line arguments are provided.
"""

import sys

# Fix UTF-8 encoding on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    if len(sys.argv) > 1:
        # CLI Mode
        import cli
        cli.main()
    else:
        # GUI Mode
        import app_gui
        app_gui.main()

if __name__ == "__main__":
    main()
