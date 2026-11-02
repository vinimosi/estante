# Desinstala a Estante instalada pelo Instalar-Estante.exe (chamado por Configurações > Aplicativos).
# Apaga o programa e os atalhos. Os seus dados (%APPDATA%\Estante) ficam, para o caso de instalar de novo.
Add-Type -AssemblyName System.Windows.Forms
$base = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$aberta = $false
try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', 8765); $aberta = $c.Connected; $c.Close() } catch {}
if ($aberta) {
  [Windows.Forms.MessageBox]::Show('A Estante está aberta. Feche ela antes (ícone perto do relógio > Fechar a Estante) e desinstale de novo.', 'Estante') | Out-Null
  exit 1
}
$r = [Windows.Forms.MessageBox]::Show("Desinstalar a Estante?`n`nO programa sai deste computador. Seus jogos, séries e configurações continuam guardados em $env:APPDATA\Estante, caso você instale de novo; se quiser, apague essa pasta depois.", 'Desinstalar a Estante', 'OKCancel', 'Question')
if ($r -ne 'OK') { exit 0 }
foreach ($pasta in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
  Remove-Item (Join-Path $pasta 'Estante.lnk') -ErrorAction SilentlyContinue
}
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Estante' -Recurse -ErrorAction SilentlyContinue
Set-Location $env:TEMP
Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
[Windows.Forms.MessageBox]::Show('A Estante foi desinstalada.', 'Estante') | Out-Null
