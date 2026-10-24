# Adds a "Skillboard" shortcut with an icon to the Windows Start Menu.
# Then right-click it in Start and choose "Pin to taskbar".
# Run:  powershell -ExecutionPolicy Bypass -File install-shortcut.ps1
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { Write-Error "pythonw.exe not found. Install Python 3.9 or newer and add it to PATH."; exit 1 }
$menu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $menu "Skillboard.lnk"))
$link.TargetPath = $pythonw
$link.Arguments = "`"$(Join-Path $here 'skillboard.py')`""
$link.WorkingDirectory = $here
$link.IconLocation = (Join-Path $here "assets\skillboard.ico") + ",0"
$link.Description = "Open my Claude Skillboard (always fresh)"
$link.Save()
Write-Host "Added Skillboard to the Start Menu. Right-click it and choose Pin to taskbar."
