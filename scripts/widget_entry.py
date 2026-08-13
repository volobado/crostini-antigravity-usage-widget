"""
Entry point for the packaged widget.

PyInstaller freezes a script, not a console command, and the executable is
windowed — so this is the widget and nothing else. The CLI (`lagrange run`,
`doctor`, `switch`) stays a console program and is installed with pip.
"""

import os
import sys

if __name__ == "__main__":
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from lagrange.ui import main

    sys.exit(main())
