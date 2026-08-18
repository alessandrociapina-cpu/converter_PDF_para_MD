@echo off
rem Cria um atalho do aplicativo na Area de Trabalho.
setlocal
cd /d "%~dp0"
set "ALVO=%~dp0iniciar_app.bat"
set "ICONE=%~dp0frontend\icones\icone-512.png"

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$atalho = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Conversor PDF para Markdown.lnk');" ^
  "$atalho.TargetPath = '%ALVO%';" ^
  "$atalho.WorkingDirectory = '%~dp0';" ^
  "$atalho.Description = 'Converte PDFs grandes em Markdown com o Docling';" ^
  "$atalho.Save()"

echo Atalho criado na Area de Trabalho.
pause
