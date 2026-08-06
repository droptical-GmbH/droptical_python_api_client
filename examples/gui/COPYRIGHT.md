Copyright (c) 2025 droptical GmbH

This folder’s original code is licensed under: SPDX-License-Identifier: MIT

Rationale: This folder uses PySide6 (the Qt for Python bindings), which is LGPL-3.0.
Unlike GPL, LGPL does not require this folder’s own code to be copyleft, so it stays
MIT like the rest of the repository. The LGPL obligations apply only to the Qt
libraries themselves (see the Distribution Notes below).

Third-Party Components:

- PySide6 — LGPL-3.0 — https://www.qt.io/qt-for-python

- shiboken6 — LGPL-3.0 — https://www.qt.io/qt-for-python

- PyInstaller — GPL-2.0 WITH Bootloader Exception — https://github.com/pyinstaller/pyinstaller

- Plus all “base” dependencies — see ../../COPYRIGHT

Distribution Notes:

- LGPL-3.0 (Qt/PySide6): keep the Qt libraries replaceable by the end user. A PyInstaller
  one-folder build satisfies this (the Qt shared libraries ship as separate files that can
  be swapped); avoid a one-file build for distributed binaries. Provide the corresponding
  source of PySide6/Qt (or a written offer) and preserve their licence notices.

- If distributing binaries, comply with PyInstaller’s bootloader exception and include its license.

- Preserve all third-party notices; your own code here remains under MIT.
