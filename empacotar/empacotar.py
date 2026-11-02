"""
Monta a Estante para quem não tem Python e faz o instalador. Rode na pasta do código:

    python empacotar/empacotar.py

Sai em dist/:
    Estante-<versão>.zip      app/ (o programa) e python/ (o Python portátil oficial, com os componentes).
                              É o que a atualização automática baixa.
    Instalar-Estante.exe      o instalador, com o zip dentro. Feito pelo compilador de C# que já vem no
                              Windows (nada para instalar).

O Python portátil é o "embeddable package" do python.org, da mesma versão do Python que roda este script,
e os componentes vêm do pip, já prontos para Windows de 64 bits.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from caminhos import VERSAO  # noqa: E402

SAIDA = RAIZ / "dist"
CACHE = Path(os.environ.get("TEMP") or "/tmp") / "estante-empacotar"
PY = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
PY_CURTO = f"{sys.version_info.major}{sys.version_info.minor}"
COMPONENTES = ["flask", "psutil", "pillow", "pystray", "winrt-runtime", "winrt-Windows.Media.Control", "winrt-Windows.Foundation",
               "winrt-Windows.Foundation.Collections", "winrt-Windows.Storage.Streams"]
# o que vai para app/: o programa, sem os testes, o plano de trabalho nem o instalador antigo (que pede Python)
VAI = ["*.py", "*.pyw", "estante.ico", "LEIA-ME.txt", "LICENSE", "desinstalar.ps1", "static", "extensao"]
NAO_VAI = {"icone_teste.py"}
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"


def passo(t):
    print(f"\n== {t}")


def python_portatil():
    CACHE.mkdir(parents=True, exist_ok=True)
    arq = CACHE / f"python-{PY}-embed-amd64.zip"
    if not arq.exists():
        url = f"https://www.python.org/ftp/python/{PY}/python-{PY}-embed-amd64.zip"
        print("baixando", url)
        urllib.request.urlretrieve(url, arq)
    return arq


def montar(pasta):
    app, py = pasta / "app", pasta / "python"
    passo("o programa")
    app.mkdir(parents=True)
    for padrao in VAI:
        for p in RAIZ.glob(padrao):
            if p.name in NAO_VAI:
                continue
            if p.is_dir():
                shutil.copytree(p, app / p.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(p, app / p.name)
    (app / "VERSAO.txt").write_text(VERSAO, encoding="utf-8")
    passo(f"o Python portátil {PY}")
    with zipfile.ZipFile(python_portatil()) as z:
        z.extractall(py)
    passo("os componentes")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-warn-script-location",
                    "--target", str(py / "Lib" / "site-packages"), "--platform", "win_amd64", "--python-version", PY_CURTO,
                    "--only-binary=:all:", *COMPONENTES], check=True)
    shutil.rmtree(py / "Lib" / "site-packages" / "bin", ignore_errors=True)
    # o Python portátil só enxerga o que está listado no arquivo ._pth
    pth = next(py.glob("python*._pth"))
    pth.write_text(f"python{PY_CURTO}.zip\n.\nLib\\site-packages\nimport site\n", encoding="utf-8")


def conferir(pasta):
    """Abre o programa montado com o Python portátil, sem janela e com dados de mentira, para ver se tudo importa."""
    passo("conferindo")
    env = dict(os.environ, ESTANTE_DATA=str(pasta / "dados-conferencia"), ESTANTE_SEM_BOAS_VINDAS="1",
               ESTANTE_SEM_VIGIA_MUSICA="1", ESTANTE_SEM_VIGIA_ATUALIZACAO="1", PYTHONIOENCODING="utf-8")
    teste = ("import sys; sys.path.insert(0, 'app'); import app, pystray, PIL, psutil, tocando, baixar, atualizar;"
             "print('ok', app.atualizar.VERSAO, 'winrt' if tocando.disponivel()[0] else tocando.disponivel()[1])")
    r = subprocess.run([str(pasta / "python" / "python.exe"), "-c", teste], cwd=pasta, env=env, capture_output=True, text=True)
    shutil.rmtree(pasta / "dados-conferencia", ignore_errors=True)
    print(r.stdout.strip(), r.stderr.strip()[-800:])
    if r.returncode or not r.stdout.startswith("ok"):
        raise SystemExit("o programa montado não abriu")


def zipar(pasta):
    passo("o zip")
    arq = SAIDA / f"Estante-{VERSAO}.zip"
    with zipfile.ZipFile(arq, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(pasta.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(pasta).as_posix())
    return arq


def instalador(arq_zip):
    passo("o instalador")
    if not CSC.exists():
        raise SystemExit("não achei o compilador de C# do Windows em " + str(CSC))
    exe = SAIDA / "Instalar-Estante.exe"
    subprocess.run([str(CSC), "/nologo", "/target:winexe", "/optimize+", f"/out:{exe}", f"/win32icon:{RAIZ / 'estante.ico'}",
                    f"/resource:{arq_zip},estante.zip", "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll",
                    "/r:System.Windows.Forms.dll", str(Path(__file__).with_name("instalador.cs"))], check=True)
    return exe


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def main():
    shutil.rmtree(SAIDA, ignore_errors=True)
    SAIDA.mkdir()
    pasta = SAIDA / "montagem"
    montar(pasta)
    conferir(pasta)
    arq = zipar(pasta)
    exe = instalador(arq)
    shutil.rmtree(pasta)
    passo("pronto")
    for p in (arq, exe):
        print(f"{p.name}  {p.stat().st_size / 1e6:.1f} MB  sha256 {sha256(p)}")


if __name__ == "__main__":
    main()
