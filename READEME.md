## Instalação do ambiente LaTeX (Windows)

### 1. LaTeX (MiKTeX)

Se você tiver o `winget` instalado, rode no PowerShell ou Prompt:

```powershell
winget install --id MiKTeX.MiKTeX --accept-package-agreements --accept-source-agreements

Se não tiver winget, baixe e instale manualmente a partir de:
https://miktex.org/download

Instale o Visual Studio Code: https://code.visualstudio.com/
No VS Code, abra a aba de extensões e instale LaTeX Workshop (id: james-yu.latex-workshop).

Opcionalmente, crie também um script de instalação rápida para Windows, por exemplo um arquivo instalar-latex-win.cmd com:

```bat
@echo off
echo Instalando MiKTeX via winget...
winget install --id MiKTeX.MiKTeX --accept-package-agreements --accept-source-agreements

echo.
echo Ambiente LaTeX instalado. Abra o VS Code e instale a extensao "LaTeX Workshop".
pause