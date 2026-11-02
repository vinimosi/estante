"""Cria o ícone e os atalhos da Estante (área de trabalho e menu Iniciar) e abre o programa."""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from icone import salvar_ico  # noqa: E402
from caminhos import migrar, pasta_dados  # noqa: E402

dados = pasta_dados()  # já traz sozinha os dados de %APPDATA%\EstanteDeJogos, se existirem

# se havia uma versão bem antiga instalada em outra pasta (que guardava tudo em "data"), traz a biblioteca dela
LER = r"""
$w = New-Object -ComObject WScript.Shell
foreach ($n in @('Estante.lnk', 'Estante de Jogos.lnk')) {
  $l = Join-Path ([Environment]::GetFolderPath('Desktop')) $n
  if (Test-Path $l) { $w.CreateShortcut($l).Arguments }
}
"""
try:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", LER],
                       capture_output=True, text=True, timeout=30)
    for linha in r.stdout.splitlines():
        antigo = linha.strip().strip('"')
        if not antigo:
            continue
        pasta_antiga = Path(antigo).parent / "data"
        if pasta_antiga.resolve() != (BASE / "data").resolve() and migrar(pasta_antiga, dados):
            print("  Trouxe sua biblioteca da versão anterior da Estante.")
            break
except Exception as e:
    print("  (Não deu para procurar a versão anterior:", e, ")")
ico = BASE / "estante.ico"
salvar_ico(ico)

pythonw = Path(sys.executable).with_name("pythonw.exe")
if not pythonw.exists():
    pythonw = Path(sys.executable)
alvo = BASE / "Estante.pyw"

# cria os atalhos novos ("Estante") e apaga os atalhos antigos ("Estante de Jogos"), que foram criados por este mesmo instalador
PS = r"""
$w = New-Object -ComObject WScript.Shell
foreach ($pasta in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
  $s = $w.CreateShortcut((Join-Path $pasta 'Estante.lnk'))
  $s.TargetPath = $env:E_PYW
  $s.Arguments = '"' + $env:E_ALVO + '"'
  $s.WorkingDirectory = $env:E_BASE
  $s.IconLocation = $env:E_ICO
  $s.Description = 'Estante'
  $s.Save()
  $velho = Join-Path $pasta 'Estante de Jogos.lnk'
  if (Test-Path $velho) { Remove-Item $velho -ErrorAction SilentlyContinue }
}
"""
env = dict(os.environ, E_PYW=str(pythonw), E_ALVO=str(alvo), E_BASE=str(BASE), E_ICO=str(ico))
subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS], env=env, check=True)

print("\n  Pronto! Criei o atalho \"Estante\" na sua área de trabalho e no menu Iniciar.")
print("  Sua biblioteca fica guardada em", dados)
print("  Daqui pra frente é só abrir por ele. Abrindo a Estante agora...\n")
subprocess.Popen([str(pythonw), str(alvo)], cwd=str(BASE), creationflags=0x00000008 | 0x00000200)
