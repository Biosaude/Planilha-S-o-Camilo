Option Explicit
Dim sh, fs, folder, command
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & folder & "\scripts\Encerrar-SegundoPlano.ps1"""
sh.Run command, 0, False
