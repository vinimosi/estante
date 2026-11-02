"""
Atualização automática pelo GitHub. Uma vez por dia a Estante olha a versão mais nova publicada no repositório
(caminhos.REPOSITORIO). Quando você clica em "Atualizar", ela espera os jogos abertos fecharem, baixa a versão
nova, fecha, troca o programa e abre de novo. Os seus dados ficam onde estão (%APPDATA%\\Estante), e a versão
anterior do programa fica guardada em "app-anterior", para dar para voltar.

A Estante instalada fica assim (o Instalar-Estante.exe monta):
    %LOCALAPPDATA%\\Programs\\Estante\\app      o programa (esta pasta)
    %LOCALAPPDATA%\\Programs\\Estante\\python   o Python portátil, com os componentes
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from caminhos import REPOSITORIO, VERSAO

BASE = Path(__file__).resolve().parent          # a pasta do programa (app)
INSTALACAO = BASE.parent                         # onde ficam app e python, na Estante instalada
UM_DIA = 86400
AGENTE = f"Estante/{VERSAO} (atualizacao)"
CTX = {}  # preenchido por iniciar(): pasta de dados, lock, configurações, jogos abertos e como fechar
estado = {"verificando": False, "baixando": False, "esperando_jogo": False, "progresso": 0, "erro": ""}


def versao_tupla(v):
    """"v2.10.1" -> (2, 10, 1). Pedaços que não são número contam como 0."""
    return tuple(int(x) if x.isdigit() else 0 for x in re.sub(r"^[vV]", "", str(v or "")).split(".")[:4])


def instalada():
    """A atualização só troca o programa na Estante instalada pelo Instalar-Estante.exe (com o Python portátil).
    Rodando pelo código-fonte (com o Python do computador), ela só avisa que há versão nova."""
    return (INSTALACAO / "python" / "pythonw.exe").exists() and BASE.name == "app"


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read(2_000_000).decode("utf-8"))


def _baixar(url, destino, progresso=None):
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=60) as r, open(destino, "wb") as f:
        total, feito = int(r.headers.get("Content-Length") or 0), 0
        while True:
            bloco = r.read(256 * 1024)
            if not bloco:
                break
            f.write(bloco)
            feito += len(bloco)
            if progresso and total:
                progresso(feito / total)


def _cfg():
    return CTX["get_cfg"]().get("atualizacao") or {}


def _guardar(**campos):
    with CTX["lock"]:
        cfg = CTX["get_cfg"]()
        cfg.setdefault("atualizacao", {}).update(campos)
        CTX["save_cfg"](cfg)


def verificar():
    """Pergunta ao GitHub qual é a versão mais nova. Guarda o que achou em cfg["atualizacao"]["nova"]."""
    if not REPOSITORIO:
        return None
    estado["verificando"] = True
    try:
        r = _get_json(f"https://api.github.com/repos/{REPOSITORIO}/releases/latest")
        v = str(r.get("tag_name") or "").lstrip("vV")
        zipe = next((a for a in r.get("assets") or [] if re.fullmatch(r"Estante-[\d.]+\.zip", a.get("name") or "")), None)
        nova = None
        if v and zipe and versao_tupla(v) > versao_tupla(VERSAO):
            nova = {"versao": v, "url": zipe["browser_download_url"], "tamanho": zipe.get("size") or 0,
                    "sha256": str(zipe.get("digest") or "").removeprefix("sha256:"), "notas": str(r.get("body") or "")[:3000],
                    "pagina": r.get("html_url") or ""}
        _guardar(ultima=time.time(), nova=nova)
        estado["erro"] = ""
        return nova
    except Exception as e:
        print("[atualizacao] não consegui ver se há versão nova:", e)
        _guardar(ultima=time.time())
        return None
    finally:
        estado["verificando"] = False


def vigiar():
    """Uma vez por dia, olha se saiu versão nova (a primeira vez um minuto depois de abrir)."""
    def loop():
        time.sleep(60)
        while True:
            try:
                if time.time() - (_cfg().get("ultima") or 0) > UM_DIA:
                    verificar()
            except Exception as e:
                print("[atualizacao]", e)
            time.sleep(3600)
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------- trocar o programa

TROCAR = r"""
# Troca o programa da Estante pela versão nova, depois que ela fechar. Feito pela própria Estante (atualizar.py).
param([int]$Pid_, [string]$Base, [switch]$SemAbrir)
$ErrorActionPreference = 'Stop'
$log = Join-Path $Base 'atualizacao.log'
function Anota($t) { Add-Content -Path $log -Value ((Get-Date -Format 'dd/MM/yyyy HH:mm:ss') + '  ' + $t) -Encoding UTF8 }
try {
  for ($i = 0; $i -lt 120 -and (Get-Process -Id $Pid_ -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 500 }
  Start-Sleep -Seconds 1
  $nova = Join-Path $Base 'nova'
  foreach ($parte in @('app', 'python')) {
    $de = Join-Path $nova $parte
    if (-not (Test-Path $de)) { continue }
    $atual = Join-Path $Base $parte
    $velha = Join-Path $Base ($parte + '-anterior')
    if (Test-Path $velha) { Remove-Item $velha -Recurse -Force }
    if (Test-Path $atual) { Rename-Item $atual ($parte + '-anterior') }
    Move-Item $de $atual
  }
  Remove-Item $nova -Recurse -Force -ErrorAction SilentlyContinue
  $v = Join-Path $Base 'app\VERSAO.txt'
  $reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Estante'
  if ((Test-Path $v) -and (Test-Path $reg)) { Set-ItemProperty $reg DisplayVersion ((Get-Content $v -Raw).Trim()) }
  Anota 'Estante atualizada.'
} catch {
  Anota ('Não deu para atualizar: ' + $_)
  # volta o que já tinha sido trocado
  foreach ($parte in @('app', 'python')) {
    $atual = Join-Path $Base $parte; $velha = Join-Path $Base ($parte + '-anterior')
    if (-not (Test-Path $atual) -and (Test-Path $velha)) { Rename-Item $velha $parte }
  }
}
if (-not $SemAbrir) {
  Start-Process -FilePath (Join-Path $Base 'python\pythonw.exe') -ArgumentList ('"' + (Join-Path $Base 'app\Estante.pyw') + '"') -WorkingDirectory (Join-Path $Base 'app')
}
"""


def preparar(nova, progresso=None):
    """Baixa a versão nova e deixa pronta em INSTALACAO\\nova (app e, se veio, python). Confere o tamanho e,
    quando o GitHub informa, a impressão digital (sha256) do arquivo."""
    pasta = CTX["DATA"] / "atualizacao"
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True)
    arq = pasta / f"Estante-{nova['versao']}.zip"
    _baixar(nova["url"], arq, progresso)
    if nova.get("tamanho") and arq.stat().st_size != nova["tamanho"]:
        raise ValueError("o arquivo baixado veio incompleto")
    if nova.get("sha256"):
        h = hashlib.sha256()
        with open(arq, "rb") as f:
            for bloco in iter(lambda: f.read(1 << 20), b""):
                h.update(bloco)
        if h.hexdigest() != nova["sha256"].lower():
            raise ValueError("o arquivo baixado não confere com o publicado")
    destino = INSTALACAO / "nova"
    shutil.rmtree(destino, ignore_errors=True)
    with zipfile.ZipFile(arq) as z:
        for nome in z.namelist():  # só app/ e python/, sem caminhos que saiam da pasta
            p = Path(nome)
            if p.is_absolute() or ".." in p.parts or p.parts[0] not in ("app", "python"):
                raise ValueError("o arquivo da versão nova tem algo fora do lugar")
        z.extractall(destino)
    if not (destino / "app" / "Estante.pyw").exists():
        raise ValueError("a versão nova veio sem o programa")
    shutil.rmtree(pasta, ignore_errors=True)
    return destino


def _abrir_troca(sem_abrir=False):
    script = INSTALACAO / "atualizar.ps1"
    script.write_text(TROCAR, encoding="utf-8-sig")  # com BOM: o PowerShell do Windows lê os acentos certo
    args = ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-Pid_", str(os.getpid()), "-Base", str(INSTALACAO)] + (["-SemAbrir"] if sem_abrir else [])
    flags = 0x00000008 | 0x00000200 | 0x08000000 if os.name == "nt" else 0  # separado da Estante e sem janela
    subprocess.Popen(args, creationflags=flags, close_fds=True)


def atualizar():
    """Em segundo plano: espera os jogos fecharem, baixa, prepara e fecha a Estante para o script trocar."""
    nova = _cfg().get("nova")
    if not nova or estado["baixando"]:
        return
    estado.update(baixando=True, progresso=0, erro="")
    try:
        while CTX["jogos_abertos"]():  # fechar a Estante com um jogo aberto perderia o tempo jogado
            estado["esperando_jogo"] = True
            time.sleep(10)
        estado["esperando_jogo"] = False
        preparar(nova, lambda p: estado.update(progresso=round(p * 100)))
        print(f"[atualizacao] versão {nova['versao']} baixada; fechando para trocar")
        _abrir_troca()
        time.sleep(1)
        CTX["sair"]()
    except Exception as e:
        print("[atualizacao] não deu para atualizar:", e)
        estado["erro"] = f"Não deu para atualizar agora ({e}). Tente de novo mais tarde."
        shutil.rmtree(INSTALACAO / "nova", ignore_errors=True) if instalada() else None
    finally:
        estado.update(baixando=False, esperando_jogo=False)


def situacao():
    c = _cfg()
    nova = c.get("nova")
    if nova and versao_tupla(nova.get("versao")) <= versao_tupla(VERSAO):
        nova = None  # já atualizou
    return {"versao": VERSAO, "nova": nova, "instalada": instalada(), "ultima": c.get("ultima"), "repositorio": REPOSITORIO,
            **estado}


def rotas(app):
    from flask import jsonify

    @app.get("/api/atualizacao")
    def api_atualizacao():
        return jsonify(situacao())

    @app.post("/api/atualizacao/verificar")
    def api_atualizacao_verificar():
        verificar()
        return jsonify(situacao())

    @app.post("/api/atualizacao/instalar")
    def api_atualizacao_instalar():
        if not instalada():
            return jsonify({"error": "Esta Estante roda pelo código-fonte. Baixe a versão nova na página do GitHub."}), 400
        if not situacao()["nova"]:
            return jsonify({"error": "Você já tem a versão mais nova."}), 400
        threading.Thread(target=atualizar, daemon=True).start()
        time.sleep(0.2)
        return jsonify(situacao())


def iniciar(app, ctx):
    CTX.update(ctx)
    rotas(app)
    if not os.environ.get("ESTANTE_SEM_VIGIA_ATUALIZACAO"):
        vigiar()
