"""
Lê os jogos instalados pelas outras lojas e launchers do PC (Steam, Epic, GOG, EA, Ubisoft,
Battle.net e Xbox), usando só os arquivos e registros que eles mesmos guardam.

Regra de ouro: este arquivo SÓ LÊ. Nunca altera, move ou apaga nada das lojas ou dos jogos,
e não usa senha, login nem token de conta.

Cada leitor devolve {"encontrada": bool, "jogos": [entrada, ...]}, onde cada entrada tem:
  loja, loja_id, nome, pasta (pasta do jogo), abrir (link do launcher, ex.: steam://...),
  exe e args (quando o jogo abre por um programa em vez de um link),
  capas_locais (imagens já guardadas no PC pela loja), capa_url (imagem da loja na internet),
  capas_reserva (imagens locais menos boas, usadas só se nada melhor aparecer) e meta (descrição etc.).
"""
import base64
import glob
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET

LOJAS = {
    "steam": "Steam",
    "epic": "Epic Games",
    "gog": "GOG",
    "ea": "EA app",
    "ubisoft": "Ubisoft Connect",
    "battlenet": "Battle.net",
    "xbox": "Xbox",
}
ORDEM = list(LOJAS)

HKLM, HKCU = "HKLM", "HKCU"
UNINSTALL = [
    HKLM + r"\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    HKLM + r"\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    HKCU + r"\Software\Microsoft\Windows\CurrentVersion\Uninstall",
]


# ---------------------------------------------------------------- registro do Windows (só leitura)

class RegistroWindows:
    def _abrir(self, caminho):
        import winreg
        raiz, _, sub = caminho.partition("\\")
        h = {HKLM: winreg.HKEY_LOCAL_MACHINE, HKCU: winreg.HKEY_CURRENT_USER}[raiz]
        return winreg.OpenKey(h, sub, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)

    def valores(self, caminho):
        import winreg
        out = {}
        try:
            with self._abrir(caminho) as k:
                i = 0
                while True:
                    try:
                        nome, valor, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    out[nome] = valor
                    i += 1
        except OSError:
            pass
        return out

    def subchaves(self, caminho):
        import winreg
        out = []
        try:
            with self._abrir(caminho) as k:
                i = 0
                while True:
                    try:
                        out.append(winreg.EnumKey(k, i))
                    except OSError:
                        break
                    i += 1
        except OSError:
            pass
        return out


class SemRegistro:
    """Fora do Windows não há registro: tudo vem vazio."""
    def valores(self, caminho):
        return {}

    def subchaves(self, caminho):
        return []


REG = RegistroWindows() if os.name == "nt" else SemRegistro()


def valor(caminho, nome):
    v = REG.valores(caminho).get(nome)
    return v if isinstance(v, str) else (str(v) if v is not None else "")


def env(nome, padrao=""):
    return os.environ.get(nome) or padrao


def unidades():
    """Letras de disco que existem (C:\\, D:\\...)."""
    if os.name != "nt":
        return []
    return [f"{l}:\\" for l in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{l}:\\")]


def _np(p):
    return os.path.normpath(p) if p else ""


def _isdir(p):
    try:
        return bool(p) and os.path.isdir(p)
    except (OSError, ValueError):
        return False


def _isfile(p):
    try:
        return bool(p) and os.path.isfile(p)
    except (OSError, ValueError):
        return False


def _ler_texto(p, limite=5_000_000):
    with open(p, "rb") as f:
        raw = f.read(limite)
    for cod in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return raw.decode(cod)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def programas_instalados():
    """Entradas de 'Adicionar ou remover programas' (só leitura)."""
    vistos = set()
    for raiz in UNINSTALL:
        for sub in REG.subchaves(raiz):
            if (raiz.split("\\")[0], sub.lower()) in vistos:
                continue
            vistos.add((raiz.split("\\")[0], sub.lower()))
            yield sub, REG.valores(raiz + "\\" + sub)


def entrada(loja, loja_id, nome, pasta, abrir="", exe="", args="", **extra):
    e = {"loja": loja, "loja_id": str(loja_id), "nome": (nome or "").strip(), "pasta": _np(pasta),
         "abrir": abrir, "exe": _np(exe), "args": args, "capas_locais": [], "capa_url": "",
         "capas_reserva": [], "meta": {}}
    e.update(extra)
    if not e["nome"]:
        e["nome"] = os.path.basename(e["pasta"].rstrip("\\/")) or e["loja_id"]
    return e


# ---------------------------------------------------------------- Steam

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|([^\s{}"]+)')


def vdf(texto):
    """Lê o formato de texto da Steam (VDF/ACF) e devolve um dicionário."""
    texto = re.sub(r"(?m)^\s*//.*$", "", texto)
    tokens = []
    for m in _TOKEN.finditer(texto):
        if m.group(2):
            tokens.append(m.group(2))
        else:
            s = m.group(1) if m.group(1) is not None else m.group(3)
            tokens.append(("s", s.replace('\\"', '"').replace("\\\\", "\\")))
    pos = 0

    def bloco():
        nonlocal pos
        d = {}
        while pos < len(tokens):
            t = tokens[pos]
            if t == "}":
                pos += 1
                return d
            if t == "{":  # chave faltando: ignora
                pos += 1
                continue
            chave = t[1]
            pos += 1
            if pos >= len(tokens):
                break
            v = tokens[pos]
            if v == "{":
                pos += 1
                d[chave] = bloco()
            elif v == "}":
                d[chave] = ""
                continue
            else:
                d[chave] = v[1]
                pos += 1
        return d

    return bloco()


def _sem_caixa(d, chave):
    """Busca uma chave sem ligar para maiúsculas (a Steam mistura 'AppState' e 'appstate')."""
    if not isinstance(d, dict):
        return None
    for k, v in d.items():
        if k.lower() == chave.lower():
            return v
    return None


STEAM_NAO_JOGO = re.compile(r"^(steamworks common redistributables|steam linux runtime|proton\b|steamvr\b|steam audio|"
                            r"spacewar$)|soundtrack|\bost$|dedicated server|\bsdk$", re.I)
STEAM_IDS_FERRAMENTA = {"228980", "1070560", "1391110", "1628350", "1493710", "1826330", "250820", "480"}


def steam_pasta():
    for chave, nome in [(HKCU + r"\Software\Valve\Steam", "SteamPath"),
                        (HKLM + r"\SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                        (HKLM + r"\SOFTWARE\Valve\Steam", "InstallPath")]:
        p = _np(valor(chave, nome))
        if _isdir(p):
            return p
    for p in [os.path.join(env("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Steam"),
              os.path.join(env("ProgramFiles", r"C:\Program Files"), "Steam")]:
        if _isdir(p):
            return _np(p)
    return ""


def steam_bibliotecas(raiz):
    libs = [raiz]
    arq = os.path.join(raiz, "steamapps", "libraryfolders.vdf")
    if not _isfile(arq):
        arq = os.path.join(raiz, "config", "libraryfolders.vdf")
    if _isfile(arq):
        d = _sem_caixa(vdf(_ler_texto(arq)), "libraryfolders") or {}
        for k, v in d.items():
            if isinstance(v, dict):
                p = _sem_caixa(v, "path")
            elif k.isdigit():
                p = v  # formato antigo: "1" "D:\\SteamLibrary"
            else:
                p = None
            if p and _isdir(p):
                libs.append(_np(p))
    unicas, vistas = [], set()
    for p in libs:
        if os.path.normcase(p) not in vistas:
            vistas.add(os.path.normcase(p))
            unicas.append(p)
    return unicas


def _steam_capas_locais(raiz, appid):
    cache = os.path.join(raiz, "appcache", "librarycache")
    out = []
    for padrao in (f"{appid}_library_600x900*.jpg", os.path.join(str(appid), "library_600x900*.jpg"),
                   os.path.join(str(appid), "*", "library_600x900*.jpg")):
        out += sorted(glob.glob(os.path.join(glob.escape(cache), padrao)), key=lambda p: ("2x" not in p, p))
    return out


def ler_steam():
    raiz = steam_pasta()
    if not raiz:
        return {"encontrada": False, "jogos": []}
    jogos, vistos = [], set()
    for lib in steam_bibliotecas(raiz):
        apps = os.path.join(lib, "steamapps")
        for acf in sorted(glob.glob(os.path.join(glob.escape(apps), "appmanifest_*.acf"))):
            try:
                st = _sem_caixa(vdf(_ler_texto(acf)), "AppState") or {}
            except OSError:
                continue
            appid = str(_sem_caixa(st, "appid") or "")
            nome = _sem_caixa(st, "name") or ""
            pasta = os.path.join(apps, "common", _sem_caixa(st, "installdir") or "\0")
            if not appid or appid in vistos or appid in STEAM_IDS_FERRAMENTA or STEAM_NAO_JOGO.search(nome):
                continue
            if not _isdir(pasta):
                continue
            vistos.add(appid)
            cdn = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}"
            e = entrada("steam", appid, nome, pasta, abrir=f"steam://rungameid/{appid}",
                        capa_url=f"{cdn}/library_600x900_2x.jpg")
            e["capas_locais"] = _steam_capas_locais(raiz, appid)
            jogos.append(e)
    return {"encontrada": True, "jogos": jogos}


# ---------------------------------------------------------------- Epic Games

def epic_dados():
    p = valor(HKLM + r"\SOFTWARE\WOW6432Node\Epic Games\EpicGamesLauncher", "AppDataPath")
    if _isdir(p):
        return _np(p)
    return os.path.join(env("ProgramData", r"C:\ProgramData"), "Epic", "EpicGamesLauncher", "Data")


def _epic_catalogo(dados):
    """O launcher guarda uma cópia do catálogo (com capas e descrições) em catcache.bin."""
    arq = os.path.join(dados, "Catalog", "catcache.bin")
    out = {}
    if not _isfile(arq):
        return out
    try:
        with open(arq, "rb") as f:
            itens = json.loads(base64.b64decode(f.read()))
        for it in itens if isinstance(itens, list) else []:
            if isinstance(it, dict) and it.get("id"):
                out[it["id"]] = it
    except Exception as e:
        print("[epic] não consegui ler o catálogo guardado:", e)
    return out


def ler_epic():
    dados = epic_dados()
    manif = os.path.join(dados, "Manifests")
    encontrada = _isdir(manif)
    jogos = []
    if not encontrada:
        return {"encontrada": False, "jogos": []}
    cat = _epic_catalogo(dados)
    for arq in sorted(glob.glob(os.path.join(glob.escape(manif), "*.item"))):
        try:
            m = json.loads(_ler_texto(arq))
        except Exception as e:
            print(f"[lojas] Epic: não entendi o arquivo {os.path.basename(arq)}: {e}")
            continue
        app = m.get("AppName") or ""
        if not app or m.get("bIsIncompleteInstall"):
            continue
        if m.get("MainGameAppName") and m["MainGameAppName"] != app:
            continue  # DLC
        cats = m.get("AppCategories")
        if isinstance(cats, list) and cats and "games" not in cats:
            continue  # Unreal Engine, ferramentas
        pasta = m.get("InstallLocation") or ""
        if not _isdir(pasta):
            continue
        ns, item = m.get("CatalogNamespace") or "", m.get("CatalogItemId") or ""
        abrir = f"com.epicgames.launcher://apps/{ns}%3A{item}%3A{app}?action=launch&silent=true"
        e = entrada("epic", app, m.get("DisplayName") or app, pasta, abrir=abrir)
        c = cat.get(item) or {}
        imgs = {k.get("type"): k.get("url") for k in c.get("keyImages") or [] if isinstance(k, dict)}
        e["capa_url"] = imgs.get("DieselGameBoxTall") or imgs.get("OfferImageTall") or ""
        if c:
            e["meta"] = {"description": (c.get("description") or "").strip(), "developer": c.get("developer") or ""}
        jogos.append(e)
    return {"encontrada": True, "jogos": jogos}


# ---------------------------------------------------------------- GOG

GOG_JOGOS = HKLM + r"\SOFTWARE\WOW6432Node\GOG.com\Games"


def gog_galaxy():
    p = valor(HKLM + r"\SOFTWARE\WOW6432Node\GOG.com\GalaxyClient\paths", "client")
    cands = [os.path.join(p, "GalaxyClient.exe")] if p else []
    cands.append(os.path.join(env("ProgramFiles(x86)", r"C:\Program Files (x86)"), "GOG Galaxy", "GalaxyClient.exe"))
    return next((_np(c) for c in cands if _isfile(c)), "")


def _gog_info(pasta, gid):
    arq = os.path.join(pasta, f"goggame-{gid}.info")
    if not _isfile(arq):
        achados = glob.glob(os.path.join(glob.escape(pasta), "goggame-*.info"))
        arq = achados[0] if achados else ""
    if not arq:
        return {}
    try:
        return json.loads(_ler_texto(arq))
    except Exception as e:
        print(f"[lojas] GOG: não entendi o arquivo {os.path.basename(arq)}: {e}")
        return {}


def ler_gog():
    galaxy = gog_galaxy()
    ids = REG.subchaves(GOG_JOGOS)
    if not ids and not galaxy:
        return {"encontrada": False, "jogos": []}
    jogos = []
    for gid in ids:
        r = REG.valores(GOG_JOGOS + "\\" + gid)
        pasta = r.get("path") or ""
        if not _isdir(pasta):
            continue
        info = _gog_info(pasta, gid)
        if info.get("rootGameId") and str(info.get("rootGameId")) != str(info.get("gameId", gid)):
            continue  # DLC
        nome = r.get("gameName") or info.get("name") or ""
        if galaxy:
            exe, args = galaxy, f'/command=runGame /gameId={gid} /path="{_np(pasta)}"'
        else:
            tarefa = next((t for t in info.get("playTasks") or [] if t.get("isPrimary")), None)
            if tarefa and tarefa.get("path"):
                exe, args = os.path.join(pasta, tarefa["path"]), tarefa.get("arguments") or ""
            else:
                exe, args = r.get("exe") or "", r.get("launchParam") or ""
        if not exe:
            continue
        jogos.append(entrada("gog", gid, nome, pasta, exe=exe, args=args))
    return {"encontrada": True, "jogos": jogos}


# ---------------------------------------------------------------- EA app

def _tag(el):
    return el.tag.rsplit("}", 1)[-1].lower()


def _ea_dados(pasta):
    arq = os.path.join(pasta, "__Installer", "installerdata.xml")
    if not _isfile(arq):
        return None
    try:
        raiz = ET.fromstring(_ler_texto(arq).encode("utf-8"))
    except ET.ParseError:
        return None
    ids, titulos = [], {}
    for el in raiz.iter():
        t = _tag(el)
        if t == "contentid" and (el.text or "").strip():
            ids.append(el.text.strip())
        elif t in ("gametitle", "title") and (el.text or "").strip():
            loc = el.get("locale") or ""
            if not loc:  # formato antigo: <localeInfo locale="en_US"><title>
                loc = "?"
            titulos.setdefault(loc, el.text.strip())
    if not ids:
        return None
    nome = titulos.get("pt_BR") or titulos.get("en_US") or next(iter(titulos.values()), "")
    return {"ids": list(dict.fromkeys(ids)), "nome": nome}


def ea_app_instalado():
    p = valor(HKLM + r"\SOFTWARE\Electronic Arts\EA Desktop", "InstallLocation")
    return _isdir(p) or _isdir(os.path.join(env("ProgramFiles", r"C:\Program Files"), "Electronic Arts", "EA Desktop"))


def ler_ea():
    pastas = {}
    for _, v in programas_instalados():
        p = v.get("InstallLocation") or ""
        if p and _isfile(os.path.join(p, "__Installer", "installerdata.xml")):
            pastas.setdefault(os.path.normcase(_np(p)), (_np(p), v.get("DisplayName") or ""))
    for base in (HKLM + r"\SOFTWARE\WOW6432Node\EA Games", HKLM + r"\SOFTWARE\WOW6432Node\Electronic Arts",
                 HKLM + r"\SOFTWARE\WOW6432Node\Origin Games"):
        for sub in REG.subchaves(base):
            p = valor(base + "\\" + sub, "Install Dir")
            if _isdir(p):
                pastas.setdefault(os.path.normcase(_np(p)), (_np(p), sub))
    for base in (os.path.join(env("ProgramFiles", r"C:\Program Files"), "EA Games"),
                 os.path.join(env("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Origin Games")):
        if _isdir(base):
            for nome in sorted(os.listdir(base)):
                p = os.path.join(base, nome)
                if _isdir(p):
                    pastas.setdefault(os.path.normcase(_np(p)), (_np(p), nome))
    jogos = []
    for p, nome_reg in pastas.values():
        d = _ea_dados(p)
        if not d:
            continue
        abrir = "origin2://game/launch?offerIds=" + ",".join(d["ids"]) + "&autoDownload=1"
        jogos.append(entrada("ea", d["ids"][0], d["nome"] or nome_reg, p, abrir=abrir))
    return {"encontrada": bool(jogos) or ea_app_instalado(), "jogos": jogos}


# ---------------------------------------------------------------- Ubisoft Connect

UBI = HKLM + r"\SOFTWARE\WOW6432Node\Ubisoft\Launcher"


def ler_ubisoft():
    launcher = valor(UBI, "InstallDir")
    ids = REG.subchaves(UBI + r"\Installs")
    if not ids and not _isdir(launcher):
        return {"encontrada": False, "jogos": []}
    nomes = {}
    for sub, v in programas_instalados():
        m = re.match(r"Uplay Install (\d+)$", sub, re.I)
        if m and v.get("DisplayName"):
            nomes[m.group(1)] = v["DisplayName"]
    jogos = []
    for uid in ids:
        pasta = valor(UBI + r"\Installs" + "\\" + uid, "InstallDir")
        if not _isdir(pasta):
            continue
        jogos.append(entrada("ubisoft", uid, nomes.get(uid, ""), pasta, abrir=f"uplay://launch/{uid}/0"))
    return {"encontrada": True, "jogos": jogos}


# ---------------------------------------------------------------- Battle.net

# Códigos que o próprio Battle.net usa para abrir cada jogo ("Battle.net.exe --exec=\"launch CÓDIGO\"").
# Só estão aqui os que são bem conhecidos. Os outros abrem pelo abridor que vem na pasta do jogo.
# Conferidos com a lista do Playnite (github.com/JosefNemec/PlayniteExtensions, BattleNetGames.cs).
BNET_CODIGOS = {"wow": "WoW", "prometheus": "Pro", "diablo3": "D3", "fenris": "Fen", "fen": "Fen", "hs_beta": "WTCG",
                "heroes": "Hero", "s2": "S2", "s1": "S1", "w3": "W3", "osi": "OSI", "d1": "D1", "anbs": "ANBS",
                "w1r": "W1R", "w2r": "W2R", "rtro": "RTRO", "wlby": "WLBY",
                # Call of Duty
                "viper": "VIPR", "odin": "ODIN", "lazarus": "LAZR", "zeus": "ZEUS", "fore": "FORE", "auks": "AUKS"}


def bnet_exe():
    cands = []
    icone = valor(HKLM + r"\SOFTWARE\WOW6432Node\Blizzard Entertainment\Battle.net\Capabilities", "ApplicationIcon")
    if icone:
        cands.append(icone.split(",")[0].strip('"'))
    pf86 = env("ProgramFiles(x86)", r"C:\Program Files (x86)")
    cands += [os.path.join(pf86, "Battle.net", "Battle.net.exe"), os.path.join(pf86, "Battle.net", "Battle.net Launcher.exe")]
    return next((_np(c) for c in cands if _isfile(c)), "")


def _abridor_na_pasta(pasta):
    for padrao in ("*Launcher.exe", os.path.join("*", "*Launcher.exe")):
        achados = sorted(glob.glob(os.path.join(glob.escape(pasta), padrao)))
        if achados:
            return achados[0]
    return ""


def ler_battlenet():
    cliente = bnet_exe()
    jogos, vistos = [], set()
    for _, v in programas_instalados():
        un = v.get("UninstallString") or ""
        m = re.search(r"--uid=([^\s\"]+)", un)
        if not m or not re.search(r"blizzard|battle\.net", un + " " + (v.get("Publisher") or ""), re.I):
            continue
        uid = m.group(1).lower()
        pasta = v.get("InstallLocation") or ""
        if uid in vistos or uid.startswith("battle.net") or not _isdir(pasta):
            continue
        vistos.add(uid)
        nome = v.get("DisplayName") or ""
        codigo = BNET_CODIGOS.get(uid)
        if codigo and cliente:
            e = entrada("battlenet", uid, nome, pasta, exe=cliente, args=f'--exec="launch {codigo}"')
        else:
            exe = _abridor_na_pasta(pasta)
            if not exe and cliente:
                exe = cliente  # pelo menos abre o Battle.net, e você clica em Jogar lá
            if not exe:
                continue
            e = entrada("battlenet", uid, nome, pasta, exe=exe)
            e["so_abre_launcher"] = exe == cliente
        jogos.append(e)
    return {"encontrada": bool(jogos) or bool(cliente), "jogos": jogos}


# ---------------------------------------------------------------- Xbox / Microsoft Store (jogos na pasta XboxGames)

_ALFABETO_PFN = "0123456789abcdefghjkmnpqrstvwxyz"


def id_editor(publisher):
    """Calcula o 'publisher id' que o Windows usa no nome da família do pacote (ex.: 8wekyb3d8bbwe)."""
    h = hashlib.sha256(publisher.encode("utf-16-le")).digest()[:8]
    bits = int.from_bytes(h, "big") << 1  # 65 bits, em 13 grupos de 5
    return "".join(_ALFABETO_PFN[(bits >> (60 - 5 * i)) & 31] for i in range(13))


def _raizes_gaming():
    """Cada disco com jogos do app Xbox tem um arquivo .GamingRoot dizendo qual é a pasta (normalmente XboxGames)."""
    out = []
    for u in unidades():
        arq = os.path.join(u, ".GamingRoot")
        if _isfile(arq):
            try:
                with open(arq, "rb") as f:
                    raw = f.read(4096)
                if raw[:4] == b"RGBX":
                    for parte in raw[8:].decode("utf-16-le", "ignore").split("\x00"):
                        parte = parte.strip()
                        if parte:
                            out.append(os.path.join(u, parte.lstrip("\\/")))
            except OSError:
                pass
        padrao = os.path.join(u, "XboxGames")
        if _isdir(padrao):
            out.append(padrao)
    unicas = []
    for p in out:
        if _isdir(p) and os.path.normcase(_np(p)) not in {os.path.normcase(_np(x)) for x in unicas}:
            unicas.append(_np(p))
    return unicas


def _xml(arq):
    try:
        return ET.fromstring(_ler_texto(arq).encode("utf-8"))
    except (ET.ParseError, OSError):
        return None


def _bom_nome(s):
    return s if s and not s.lower().startswith("ms-resource:") else ""


def ler_xbox():
    raizes = _raizes_gaming()
    if not raizes:
        return {"encontrada": False, "jogos": []}
    jogos = []
    for raiz in raizes:
        for nome_pasta in sorted(os.listdir(raiz)):
            conteudo = os.path.join(raiz, nome_pasta, "Content")
            cfg = _xml(os.path.join(conteudo, "MicrosoftGame.config"))
            manif = _xml(os.path.join(conteudo, "appxmanifest.xml"))
            if cfg is None or manif is None:
                continue
            ident = next((el for el in manif.iter() if _tag(el) == "identity"), None)
            app = next((el for el in manif.iter() if _tag(el) == "application" and el.get("Id")), None)
            if ident is None or app is None or not ident.get("Name") or not ident.get("Publisher"):
                continue
            pfn = ident.get("Name") + "_" + id_editor(ident.get("Publisher"))
            visuais = next((el for el in cfg.iter() if _tag(el) == "shellvisuals"), None)
            disp_manif = next((el.text for el in manif.iter() if _tag(el) == "displayname" and el.text), "")
            nome = _bom_nome(visuais.get("DefaultDisplayName") if visuais is not None else "") or _bom_nome(disp_manif) or nome_pasta
            e = entrada("xbox", pfn, nome, conteudo, abrir=f"shell:AppsFolder\\{pfn}!{app.get('Id')}")
            if visuais is not None:
                for k in ("SplashScreenImage", "Square480x480Logo", "Square150x150Logo"):
                    if visuais.get(k):
                        img = os.path.join(conteudo, visuais.get(k).replace("\\", os.sep))
                        if _isfile(img):
                            e["capas_reserva"].append(img)
            jogos.append(e)
    return {"encontrada": True, "jogos": jogos}


LEITORES = {"steam": ler_steam, "epic": ler_epic, "gog": ler_gog, "ea": ler_ea,
            "ubisoft": ler_ubisoft, "battlenet": ler_battlenet, "xbox": ler_xbox}


def ler(loja):
    return LEITORES[loja]()
