"""
Wand (o antigo WeMod): mostra quais jogos da estante têm trainer e abre o jogo pelo Wand.

Regra de ouro: este arquivo SÓ LÊ. Ele acha onde o Wand está instalado e usa a lista pública de jogos que o
próprio Wand baixa (storage-cdn.wemod.com/catalog.json, sem conta nem senha) para saber quais jogos têm trainer.
Para abrir, usa o mesmo endereço que o Wand põe nos atalhos que ele mesmo cria (wemod://play?titleId=...&gameId=...).
Nunca mexe nos arquivos do Wand e não lê nada da conta.

Um jogo só ganha o selo quando a versão que você tem (a da loja de onde ele veio) tem trainer no Wand.
Se o Wand não tem trainer para ela, o jogo é ignorado.
"""
import gzip
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import lojas
from caminhos import gravar_json, ler_json

CATALOGO_URL = "https://storage-cdn.wemod.com/catalog.json"
DESINSTALAR = lojas.HKCU + r"\Software\Microsoft\Windows\CurrentVersion\Uninstall\Wand"
PROTOCOLO = lojas.HKCU + r"\Software\Classes\wemod\shell\open\command"
UM_DIA = 24 * 3600
# loja da Estante -> como a lista do Wand chama a mesma loja
PREFIXO = {"steam": "steam", "epic": "epic", "gog": "gog", "ea": "origin", "ubisoft": "uplay", "xbox": "uwp"}
# jogos sem loja só são reconhecidos pelo executável, e só contra versões do Wand que não dependem de loja
SEM_LOJA = ("standalone", "itch", "gog")
EXE_GENERICOS = {"game.exe", "launcher.exe", "nw.exe", "start.exe", "play.exe", "run.exe", "main.exe", "app.exe",
                 "client.exe", "setup.exe", "unins000.exe", "unitycrashhandler64.exe", "unitycrashhandler32.exe"}

CTX = {}  # preenchido por iniciar(): pasta de dados e get_cfg da Estante
_lock = threading.Lock()
_indice = None        # lista do Wand já arrumada para procurar rápido (carregada do disco na primeira vez)
_por_pasta = {}       # pasta do jogo -> (versão da lista, trainer achado pelo executável ou None)
_ativo = (0.0, False)  # (quando foi visto, Wand instalado e ligado nas Configurações)
estado = {"baixando": False, "erro": ""}


def iniciar(ctx):
    CTX.update(ctx)


def _arq():
    return CTX["DATA"] / "wand.json"


# ---------------------------------------------------------------- onde o Wand está

def pasta():
    p = lojas.valor(DESINSTALAR, "InstallLocation") or os.path.join(lojas.env("LOCALAPPDATA"), "Wand")
    return p if os.path.isfile(os.path.join(p, "Wand.exe")) else ""


def exe():
    p = pasta()
    return os.path.join(p, "Wand.exe") if p else ""


def versao():
    return lojas.valor(DESINSTALAR, "DisplayVersion")


def abridor():
    """Programa usado para abrir os endereços wemod://. O Windows guarda qual versão do Wand abre esses endereços,
    e às vezes ela já foi apagada por uma atualização. Nesse caso usa o Wand.exe principal, que sempre abre a mais nova.
    Devolve "" quando o próprio Windows consegue abrir o endereço."""
    cmd = lojas.valor(PROTOCOLO, "")
    m = re.match(r'\s*"([^"]+)"', cmd) or re.match(r"\s*(\S+)", cmd)
    if m and os.path.isfile(m.group(1)):
        return ""
    return exe()


def abrir(link):
    ab = abridor()
    if ab:
        subprocess.Popen([ab, link])
    else:
        CTX["abrir_link"](link)


def link_jogar(t):
    return f"wemod://play?titleId={t['titleId']}&gameId={t['gameId']}"


def link_pagina(t):
    return f"wemod://titles/{t['titleId']}?gameId={t['gameId']}"


def ligado(cfg):
    return (cfg.get("wand") or {}).get("ligado", True)


def ativo():
    """Wand instalado e ligado nas Configurações. Guardado por alguns segundos: é perguntado para cada jogo."""
    global _ativo
    quando, sim = _ativo
    if time.time() - quando > 5:
        sim = bool(pasta()) and ligado(CTX["get_cfg"]())
        _ativo = (time.time(), sim)
    return sim


def esquecer_ativo():
    global _ativo
    _ativo = (0.0, False)


# ---------------------------------------------------------------- lista de jogos do Wand

def indexar(cat):
    """Da lista completa do Wand (uns 5 MB), guarda só o que a Estante usa: os jogos que têm trainer,
    pelo número de cada loja (steam:620, gog:1207658924...) e pelo caminho do executável dentro da pasta do jogo."""
    titulos = cat.get("titles") or {}
    por_id, por_exe = {}, {}
    for g in (cat.get("games") or {}).values():
        tr = g.get("trainer")
        if not tr or not g.get("titleId"):
            continue  # o jogo está na lista, mas sem trainer para a versão dessa loja
        item = {"titleId": str(g["titleId"]), "gameId": str(g["id"]), "loja": g.get("platformId") or "",
                "nome": (titulos.get(g["titleId"]) or {}).get("name", ""), "cheats": tr.get("cheatCount") or 0}
        for c in g.get("correlationIds") or []:
            por_id.setdefault(c.lower(), item)
        vp = (g.get("versionPath") or "").replace("/", "\\").strip("\\").lower()
        if vp.endswith(".exe") and Path(vp).name not in EXE_GENERICOS:
            por_exe.setdefault(vp, []).append(item)
    return {"por_id": por_id, "por_exe": por_exe}


def _carregar():
    global _indice
    if _indice is None:
        try:
            _indice = ler_json(_arq(), {})
        except OSError as e:
            print("[wand] não consegui ler a lista guardada do Wand:", e)
            _indice = {}
    return _indice


def info():
    d = _carregar()
    return {"baixado": d.get("baixado"), "jogos": len({(x["titleId"], x["gameId"]) for x in (d.get("por_id") or {}).values()})}


def baixar(forcar=False):
    """Baixa a lista do Wand, no máximo uma vez por dia (ou agora, com forcar). Devolve True se deu certo."""
    global _indice
    d = _carregar()
    if not forcar and d.get("baixado") and time.time() - d["baixado"] < UM_DIA:
        return True
    if not _lock.acquire(blocking=False):
        with _lock:  # já tem um download rodando: espera ele terminar
            return not estado["erro"]
    estado.update(baixando=True, erro="")
    try:
        h = {"User-Agent": "Estante", "Accept": "application/json", "Accept-Encoding": "gzip"}
        if d.get("etag") and d.get("por_id"):
            h["If-None-Match"] = d["etag"]
        req = urllib.request.Request(CATALOGO_URL, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read(40_000_000)
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                novo = indexar(json.loads(raw.decode("utf-8")))
                novo["etag"] = r.headers.get("ETag") or ""
        except urllib.error.HTTPError as e:
            if e.code != 304:
                raise
            novo = dict(d)  # nada mudou desde a última vez
        novo["baixado"] = time.time()
        gravar_json(_arq(), novo, indent=None)
        _indice = novo
        return True
    except Exception as e:
        print("[wand] não consegui baixar a lista de jogos do Wand:", e)
        estado["erro"] = "Não consegui baixar a lista de jogos do Wand agora. Confira a internet e tente de novo."
        return False
    finally:
        estado["baixando"] = False
        _lock.release()


# ---------------------------------------------------------------- qual jogo da estante tem trainer

def _pasta_de(f):
    if f.get("pasta_jogo"):
        return f["pasta_jogo"]
    return str(Path(f["exe"]).parent) if f.get("exe") else ""


def _exes(pasta_jogo, fundo=5, limite=20000):
    """Caminhos dos .exe dentro da pasta do jogo, relativos a ela (ex.: binaries\\win64\\jogo.exe)."""
    raiz = Path(pasta_jogo)
    n = 0
    for atual, dirs, arqs in os.walk(raiz):
        rel = Path(atual).relative_to(raiz)
        if len(rel.parts) >= fundo:
            dirs[:] = []
        n += len(arqs) + len(dirs)
        if n > limite:
            break
        for a in arqs:
            if a.lower().endswith(".exe"):
                yield str(rel / a).lower()


def _pelo_exe(pasta_jogo, lojas_ok):
    d = _carregar()
    por_exe = d.get("por_exe") or {}
    if not por_exe or not pasta_jogo or not os.path.isdir(pasta_jogo):
        return None
    for rel in _exes(pasta_jogo):
        for item in por_exe.get(rel, []):
            if item["loja"] in lojas_ok:
                return item
    return None


def trainer(g):
    """O trainer do Wand para este jogo, ou None. Procura pelo número da loja (rápido); o executável só é olhado
    em segundo plano (preencher), porque é preciso abrir a pasta do jogo."""
    if not ativo():
        return None
    d = _carregar()
    por_id = d.get("por_id") or {}
    for f in [g] + list(g.get("outras_fontes") or []):
        loja = f.get("loja") or ""
        if loja in PREFIXO and f.get("loja_id"):
            item = por_id.get(f"{PREFIXO[loja]}:{f['loja_id']}".lower())
            if item:
                return item
    for f in [g] + list(g.get("outras_fontes") or []):
        if (f.get("loja") or "") == "battlenet":
            continue  # o Wand não tem jogos da Battle.net
        cache = _por_pasta.get(_pasta_de(f))
        if cache and cache[0] == d.get("baixado") and cache[1]:
            return cache[1]
    return None


def preencher(jogos):
    """Em segundo plano: olha a pasta dos jogos que não foram achados pelo número da loja."""
    d = _carregar()
    if not d.get("por_exe"):
        return
    for g in jogos:
        for f in [g] + list(g.get("outras_fontes") or []):
            loja = f.get("loja") or ""
            if loja == "battlenet" or (loja in PREFIXO and f.get("loja_id")
                                       and (d.get("por_id") or {}).get(f"{PREFIXO[loja]}:{f['loja_id']}".lower())):
                continue
            p = _pasta_de(f)
            if not p or (_por_pasta.get(p) or (None,))[0] == d.get("baixado"):
                continue
            try:
                achado = _pelo_exe(p, (PREFIXO[loja],) if loja in PREFIXO else SEM_LOJA)
            except OSError as e:
                print(f"[wand] não consegui olhar a pasta {p}: {e}")
                achado = None
            _por_pasta[p] = (d.get("baixado"), achado)


def vigiar_passo(jogos):
    """Chamado a cada 5 minutos pela Estante: atualiza a lista do Wand (uma vez por dia) e olha os jogos novos."""
    if not ativo():
        return
    if baixar():
        preencher(jogos)
