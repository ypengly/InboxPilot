@echo off
REM Builds dist\InboxPilot\InboxPilot.exe (run from a venv with requirements-dev.txt installed)
pyinstaller --noconfirm --clean --windowed --name InboxPilot ^
  --collect-submodules keyring.backends ^
  --collect-all googleapiclient --collect-data google_auth_oauthlib ^
  --hidden-import win32ctypes.pywin32.pywintypes ^
  run.py
echo.
echo Done: dist\InboxPilot\InboxPilot.exe
echo Optional installer: compile an Inno Setup script that packages the dist\InboxPilot folder.
