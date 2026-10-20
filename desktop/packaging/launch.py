"""Entry point of the packaged client (PyInstaller): same as `python -m school_admin`."""

import sys

from school_admin.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
