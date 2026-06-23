# Creates a desktop shortcut that launches the Horror Pipeline GUI
# with no console window. Run this once from the project folder.

$ProjectDir = $PSScriptRoot

# Find pythonw.exe (runs Python without a console window) next to python.exe
$PythonExe  = (Get-Command python.exe -ErrorAction Stop).Source
$PythonW    = Join-Path (Split-Path $PythonExe) "pythonw.exe"

if (-not (Test-Path $PythonW)) {
    Write-Warning "pythonw.exe not found alongside python.exe. Falling back to python.exe (a console window may briefly appear)."
    $PythonW = $PythonExe
}

$AppScript   = Join-Path $ProjectDir "app.py"
$DesktopPath = [System.Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "Horror Pipeline.lnk"

$WShell   = New-Object -ComObject WScript.Shell
$Shortcut = $WShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath       = $PythonW
$Shortcut.Arguments        = "`"$AppScript`""
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description      = "Horror Pipeline Generator"
$Shortcut.Save()

Write-Host "Shortcut created: $ShortcutPath"
Write-Host "Target : $PythonW"
Write-Host "Working: $ProjectDir"
