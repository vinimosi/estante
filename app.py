"""
Estante - organizador local dos seus jogos de PC (e, em breve, leitura e música).
Roda só no seu computador (127.0.0.1) e abre no navegador.
"""
import gzip
import html as htmlmod
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from html.parser import HTMLParser
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

try:
    import psutil
except ImportError:  # o app funciona sem, só fica menos esperto pra contar tempo de jogos com launcher
    psutil = None

PORTA = 8765
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from caminhos import VERSAO, apagar_arquivo, gravar_json, ler_json, navegador_app, pasta_dados  # noqa: E402
import lojas  # noqa: E402
import leitura  # noqa: E402
import wand  # noqa: E402
import tocando  # noqa: E402
import atualizar  # noqa: E402
import copias  # noqa: E402
import estatisticas  # noqa: E402

DATA = pasta_dados()  # %APPDATA%\Estante no Windows
COVERS = DATA / "covers"
LIB = DATA / "library.json"
CFG = DATA / "config.json"
COVERS.mkdir(exist_ok=True)

WINDOWS = os.name == "nt"
lock = threading.RLock()
running = {}  # id do jogo -> horário em que começou
AO_SAIR = []  # o Estante.pyw põe aqui como fechar o programa (a atualização usa para fechar e trocar)

app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")


@app.before_request
def _so_deste_computador():
    """Só a janela da Estante e a extensão dela podem mudar alguma coisa.
    Assim, nenhum site aberto no navegador consegue mandar ordens para a Estante."""
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        origem = request.headers.get("Origin")
        local = request.host.split(":")[0] in ("127.0.0.1", "localhost")
        if origem and not (local and origem == "http://" + request.host) \
                and not origem.startswith(("chrome-extension://", "extension://")):
            abort(403)


# ---------------------------------------------------------------- armazenamento

def _load(path, default):
    return ler_json(path, default)


def _save(path, obj):
    gravar_json(path, obj)


VERSAO_DADOS = 3  # 2 = jogos de lojas (loja, loja_id, abrir, outras_fontes) e jogos guardados; 3 = subcoleções (RPG/Ação)


def _completar_jogo(g):
    """Acrescenta os campos novos em jogos salvos por versões antigas, sem mexer no que já existe."""
    for k, v in new_game("", "").items():
        if k not in g:
            g[k] = v if not isinstance(v, (list, dict)) else type(v)()
    return g


def get_lib():
    lib = _load(LIB, None)
    if not isinstance(lib, dict):
        lib = {"games": []}
    lib.setdefault("games", [])
    lib.setdefault("guardados", [])  # jogos de loja desinstalados: voltam com tudo se você instalar de novo
    if lib.get("versao", 1) < VERSAO_DADOS:
        copia = LIB.with_name(f"library-antes-v{VERSAO_DADOS}.json")
        try:  # cópia de segurança antes da conversão
            if LIB.exists() and not copia.exists():
                copia.write_bytes(LIB.read_bytes())
        except OSError as e:
            print("[dados] não consegui guardar a cópia de antes da conversão:", e)
        if lib.get("versao", 1) < 3:  # 3: a barra (/) separa coleção de subcoleção; nas coleções antigas ela vira " - "
            for g in lib["games"] + lib["guardados"]:
                g["tags"] = [t.replace("/", " - ") for t in g.get("tags") or []]
        lib["versao"] = VERSAO_DADOS
    for g in lib["games"]:
        _completar_jogo(g)
    return lib


def save_lib(lib):
    _save(LIB, lib)


def get_cfg():
    cfg = _load(CFG, {})
    cfg.setdefault("sgdb_key", "")
    cfg.setdefault("pastas", [])
    cfg.setdefault("ignorados", [])
    cfg.setdefault("lojas", {})            # loja -> ligada (True/False); se faltar, está ligada
    cfg.setdefault("ignorados_lojas", [])  # "steam:620" de jogos que você tirou da estante de propósito
    cfg.setdefault("nao_juntar", [])       # grupos de jogos que você disse que não são o mesmo
    return cfg


def loja_ligada(cfg, loja):
    return cfg["lojas"].get(loja, True)


def save_cfg(cfg):
    with lock:
        _save(CFG, cfg)


def find_game(lib, gid):
    for g in lib["games"]:
        if g["id"] == gid:
            return g
    return None


def norm_path(p):
    return os.path.normcase(os.path.normpath(p)) if p else ""


def new_game(name, exe, args=""):
    return {
        "id": uuid.uuid4().hex[:12],
        "name": name.strip() or (Path(exe).stem if exe else ""),
        "exe": os.path.normpath(exe) if exe else "",
        "args": args or "",
        "workdir": "",
        "tags": [],
        "favorite": False,
        "hidden": False,
        "playtime": 0,
        "last_played": None,
        "sessoes": [],  # cada vez que você jogou: [começo, segundos]. Antes disso só existia o total
        "added": time.time(),
        "cover": None,
        "year": None,
        "description": "",
        "developer": "",
        "url": "",
        "version": "",
        "latest_version": "",
        "status": "",
        "engine": "",
        "genres": [],
        "update_checked": None,
        "pasta_jogo": "",
        # de onde o jogo vem e como abre. "" = jogo do seu PC, aberto pelo executável
        "loja": "",
        "loja_id": "",
        "abrir": "",          # link do launcher (steam://, com.epicgames.launcher://, uplay://...)
        "outras_fontes": [],  # quando você junta o mesmo jogo de lojas diferentes
        "pelo_wand": False,   # o Jogar abre pelo Wand (com o trainer), quando o jogo tem trainer lá
        "situacao": "",       # a sua: quero, jogando, zerei, larguei ("" = nenhuma)
        "nota": "",           # o que você quiser anotar sobre o jogo
    }


SITUACOES = ("quero", "jogando", "zerei", "larguei")


# ---------------------------------------------------------------- de onde cada jogo vem (fontes)

CAMPOS_FONTE = ("loja", "loja_id", "abrir", "exe", "args", "workdir", "pasta_jogo")


def fonte_principal(g):
    f = {k: g.get(k) or "" for k in CAMPOS_FONTE}
    f["nome"] = g.get("name", "")
    return f


def fontes(g):
    """Todas as formas de abrir o jogo: a principal primeiro, depois as que foram juntadas."""
    return [fonte_principal(g)] + [dict(f) for f in g.get("outras_fontes") or []]


def usar_fonte(g, f):
    """Coloca uma fonte como principal do jogo."""
    for k in CAMPOS_FONTE:
        g[k] = f.get(k) or ""


def nome_loja(loja):
    return lojas.LOJAS.get(loja, "Arquivo do jogo")


def pela(loja):
    return ("pela " if loja in ("steam", "epic") else "pelo ") + nome_loja(loja)


def _unidade_ausente(caminho):
    """True quando o disco do caminho não está ligado (ex.: HD externo desconectado)."""
    anchor = Path(caminho).anchor if caminho else ""
    return bool(anchor) and not os.path.exists(anchor)


# ---------------------------------------------------------------- capas (SteamGridDB)

def sgdb(path):
    key = get_cfg().get("sgdb_key", "").strip()
    if not key:
        raise RuntimeError("Falta a chave do SteamGridDB nas Configurações.")
    req = urllib.request.Request(
        "https://www.steamgriddb.com/api/v2" + path,
        headers={"Authorization": "Bearer " + key, "User-Agent": "Estante/2.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def sgdb_search(term):
    data = sgdb("/search/autocomplete/" + urllib.parse.quote(term)).get("data") or []
    out = []
    for d in data[:12]:
        year = None
        if d.get("release_date"):
            try:
                year = time.gmtime(int(d["release_date"])).tm_year
            except (TypeError, ValueError, OverflowError, OSError):  # data que não é data: fica sem ano
                pass
        out.append({"id": d["id"], "name": d.get("name", ""), "year": year})
    return out


def sgdb_grids(sgdb_id):
    q = "?dimensions=600x900,342x482,660x930&types=static&nsfw=false"
    data = sgdb(f"/grids/game/{sgdb_id}{q}").get("data") or []
    if not data:
        data = sgdb(f"/grids/game/{sgdb_id}?types=static&nsfw=false").get("data") or []
        data = [d for d in data if d.get("height", 0) > d.get("width", 1)] or data
    return [{"url": d["url"], "thumb": d.get("thumb") or d["url"]} for d in data[:30]]


IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def store_cover_bytes(gid, raw, ext):
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            return None
        old = g.get("cover")
        fname = f"{gid}_{int(time.time() * 1000)}{ext}"
        (COVERS / fname).write_bytes(raw)
        g["cover"] = fname
        save_lib(lib)
    if old:
        apagar_arquivo(COVERS / old)
    return fname


def _img_headers(referer=None):
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
         "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    if referer:
        h["Referer"] = referer
    return h


def download_cover(gid, url, referer=None):
    req = urllib.request.Request(url, headers=_img_headers(referer))
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read(15_000_000)
        ctype = (r.headers.get_content_type() or "").lower()
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext not in IMG_EXT:
        ext = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(ctype, ".jpg")
    return store_cover_bytes(gid, raw, ext)


def auto_cover(gid):
    """Busca a capa sozinha: pega o primeiro resultado da busca e a capa mais votada."""
    try:
        g = find_game(get_lib(), gid)
        if not g or g.get("cover"):
            return False
        results = sgdb_search(g["name"])
        alvo = _clean(g["name"])
        results = [r for r in results if _clean(r["name"]) == alvo
                   or (len(alvo) > 3 and (alvo in _clean(r["name"]) or _clean(r["name"]) in alvo))]
        if not results:
            return False
        grids = sgdb_grids(results[0]["id"])
        if not grids:
            return False
        download_cover(gid, grids[0]["url"])
        if results[0].get("year"):
            with lock:
                lib = get_lib()
                gg = find_game(lib, gid)
                if gg and not gg.get("year"):
                    gg["year"] = results[0]["year"]
                    save_lib(lib)
        return True
    except Exception as e:
        print(f"[capa] não deu pra buscar a capa de {gid}: {e}")
        return False


def auto_cover_many(ids):
    def worker():
        for gid in ids:
            auto_cover(gid)
            time.sleep(0.3)
    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------- dados pela página do jogo

IMG_RE = re.compile(r"\.(jpe?g|png|webp|gif)(\?|$)", re.I)
RUIM_RE = re.compile(r"(logo|icon|favicon|avatar|emoji|smilie|sprite|spacer|pixel|badge|button|banner_ad|placeholder|default|steam_share|share_image|og-image|blank)", re.I)
LOGIN_RE = re.compile(r"^(iniciar sess|sign in|log ?in|entrar|login)", re.I)


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.title, self._in_title = {}, "", False
        self.imgs, self.links = [], []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            k = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if k and a.get("content") and k not in self.meta:
                self.meta[k] = a["content"].strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "img":
            src = a.get("data-src") or a.get("data-url") or a.get("data-lazy-src") or a.get("src") or ""
            if src and not src.startswith("data:"):
                self.imgs.append(src)
        elif tag == "a" and IMG_RE.search(a.get("href", "")):
            self.links.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, d):
        if self._in_title:
            self.title += d


class _PrimeiroPost(HTMLParser):
    """Pega o texto e as imagens do primeiro post de um tópico de fórum (XenForo, usado pelo F95zone)."""
    BLOCO = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ativo = self.fim = False
        self.nivel = 0
        self.partes, self.imgs, self.links = [], [], []

    def handle_starttag(self, tag, attrs):
        if self.fim:
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        if not self.ativo:
            if tag == "div" and "bbWrapper" in a.get("class", ""):
                self.ativo, self.nivel = True, 1
            return
        if tag == "div":
            self.nivel += 1
        if tag in self.BLOCO:
            self.partes.append("\n")
        if tag == "img":
            src = a.get("data-src") or a.get("data-url") or a.get("src") or ""
            if src and not src.startswith("data:"):
                self.imgs.append(src)
        elif tag == "a" and IMG_RE.search(a.get("href", "")):
            self.links.append(a["href"])

    def handle_endtag(self, tag):
        if self.ativo and not self.fim and tag == "div":
            self.nivel -= 1
            if self.nivel <= 0:
                self.fim, self.ativo = True, False

    def handle_data(self, d):
        if self.ativo and not self.fim:
            self.partes.append(re.sub(r"\s*\n\s*", " ", d))  # quebras do código HTML não contam

    def texto(self):
        linhas = [re.sub(r"[ \t\u00a0]+", " ", l).strip() for l in "".join(self.partes).split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()


ROTULOS_F95 = ["Overview", "Thread Updated", "Updated", "Release Date", "Developer", "Developer/Publisher", "Publisher",
               "Censored", "Censorship", "Version", "OS", "Platform", "Language", "Languages", "Genre", "Genres",
               "Installation", "Changelog", "Developer Notes", "Download", "Downloads", "Store", "Translations",
               "Voiced", "Length", "Other Games", "Prequel", "Sequel", "Note", "Notes"]
_ROTULO_RE = re.compile(r"(?:^|\n)[ \t]*(" + "|".join(re.escape(r) for r in sorted(ROTULOS_F95, key=len, reverse=True)) + r")[ \t]*:", re.I)
STATUS_F95 = {"completed": "Completo", "abandoned": "Abandonado", "onhold": "Pausado", "on hold": "Pausado"}
ENGINES_F95 = ["Ren'Py", "RenPy", "Unity", "RPGM", "Unreal Engine", "HTML", "Flash", "QSP", "RAGS", "Tads", "Java",
               "WebGL", "Wolf RPG", "Godot", "ADRIFT", "Others"]


def _f95_post(page):
    pp = _PrimeiroPost()
    pp.feed(page)
    texto = pp.texto()
    pedacos = _ROTULO_RE.split(texto)
    blocos = {}
    for rot, val in zip(pedacos[1::2], pedacos[2::2]):
        blocos.setdefault(rot.lower(), val.strip())

    def limpo(t):
        linhas = [l for l in t.split("\n") if not re.match(r"^\s*spoiler\b", l, re.I)]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()

    out = {"description": limpo(blocos.get("overview", ""))[:4000]}
    v = limpo(blocos.get("version", "")).split("\n")[0].strip()
    if v:
        out["version"] = v
    dev = limpo(blocos.get("developer", "") or blocos.get("developer/publisher", "")).split("\n")[0]
    dev = re.split(r"\s+[-|–]\s+|\s{2,}|\s+(?:Patreon|Itch\.io|Subscribestar|Steam|Discord|Twitter|Website)\b", dev, flags=re.I)[0].strip()
    if dev:
        out["developer"] = dev
    m = re.search(r"(19|20)\d\d", blocos.get("release date", ""))
    if m:
        out["year"] = int(m.group(0))
    g = limpo(blocos.get("genre", "") or blocos.get("genres", ""))
    if g:
        out["genres"] = [x.strip(" .") for x in re.split(r"[,\n]", g) if 1 < len(x.strip(" .")) < 30][:30]
    grandes = [u for u in pp.links if "/thumb/" not in u]
    out["images"] = grandes or pp.imgs
    return out


def _get_text(url, limit=4_000_000, headers=None):
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read(limit)
        charset = r.headers.get_content_charset() or "utf-8"
        final = r.geturl()
    return raw.decode(charset, "replace"), final


def _existe(url):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Estante/2.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def _unicos(lista, limite=24):
    vistos, out = set(), []
    for u in lista:
        if u and u not in vistos and not u.lower().endswith(".svg"):
            vistos.add(u)
            out.append(u)
    return out[:limite]


def _steam_meta(appid):
    """Steam: usa os dados públicos da loja, que não pedem login nem verificação de idade."""
    txt, _ = _get_text(f"https://store.steampowered.com/api/appdetails?appids={appid}&l=brazilian&cc=br")
    d = (json.loads(txt).get(str(appid)) or {}).get("data") or {}
    if not d:
        raise ValueError("A Steam não devolveu dados desse jogo.")
    cdn = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}"
    vertical = [f"{cdn}/library_600x900_2x.jpg", f"{cdn}/library_600x900.jpg"]
    imgs = [u for u in vertical if _existe(u)][:1]
    imgs += [d.get("header_image"), d.get("capsule_imagev5"), d.get("capsule_image")]
    imgs += [sc.get("path_full") for sc in (d.get("screenshots") or [])[:8]]
    imgs = _unicos(imgs)
    ano = None
    m = re.search(r"(19|20)\d\d", (d.get("release_date") or {}).get("date", ""))
    if m:
        ano = int(m.group(0))
    return {
        "title": d.get("name", ""),
        "description": htmlmod.unescape(re.sub(r"<[^>]+>", "", d.get("short_description", ""))).strip(),
        "developer": ", ".join(d.get("developers") or []),
        "image": imgs[0] if imgs else "",
        "images": imgs,
        "url": f"https://store.steampowered.com/app/{appid}/",
        "site": "Steam",
        "year": ano,
        "genres": [x.get("description") for x in d.get("genres") or [] if x.get("description")][:12],
    }


def _gog_meta(gid):
    """GOG: dados públicos do catálogo da GOG (não pedem login)."""
    txt, _ = _get_text(f"https://gamesdb.gog.com/platforms/gog/external_releases/{gid}")
    d = json.loads(txt)
    jogo = d.get("game") or {}

    def txt_de(x):
        return (x or {}).get("*") or (x or {}).get("en-US") or "" if isinstance(x, dict) else (x or "")

    capa = ((jogo.get("vertical_cover") or {}).get("url_format") or "").replace("{formatter}", "").replace("{ext}", "jpg")
    ano = None
    m = re.match(r"(19|20)\d\d", d.get("first_release_date") or jogo.get("first_release_date") or "")
    if m:
        ano = int(m.group(0))
    return {
        "description": txt_de(d.get("summary") or jogo.get("summary")).strip()[:4000],
        "developer": ", ".join(txt_de(x.get("name")) if isinstance(x.get("name"), dict) else (x.get("name") or "")
                               for x in jogo.get("developers") or [] if isinstance(x, dict)),
        "genres": [txt_de(x.get("name")) for x in jogo.get("genres") or [] if isinstance(x, dict)][:12],
        "year": ano,
        "image": capa,
    }


_steam_busca_cache = {}


def steam_por_nome(nome):
    """Procura o jogo na loja pública da Steam pelo nome (sem chave nem login).
    Só aceita quando o nome bate certinho, para não pegar um jogo errado."""
    alvo = _clean(nome or "")
    if len(alvo) < 2:
        return None
    if alvo in _steam_busca_cache:
        return _steam_busca_cache[alvo]
    txt, _ = _get_text("https://store.steampowered.com/api/storesearch/?term="
                       + urllib.parse.quote(nome) + "&l=brazilian&cc=BR")
    achado = None
    for it in json.loads(txt).get("items") or []:
        if it.get("type", "app") == "app" and _clean(it.get("name", "")) == alvo:
            achado = str(it.get("id"))
            break
    _steam_busca_cache[alvo] = achado
    return achado


def _vertical_steam(meta):
    return next((u for u in meta.get("images") or [] if "library_600x900" in u), "")


def _appid_da_pasta(g):
    """Jogos com arquivos da Steam na pasta dizem o número deles em steam_appid.txt: aí não há como errar o jogo."""
    try:
        pasta = Path(g.get("pasta_jogo") or Path(g.get("exe") or "").parent)
        for arq in list(pasta.glob("steam_appid.txt")) + list(pasta.glob("*/steam_appid.txt"))[:3]:
            t = arq.read_text("utf-8", "ignore").strip()
            if t.isdigit():
                return t
    except OSError:
        pass
    return None


def _marcar_jogo(gid, **campos):
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if g:
            g.update(campos)
            save_lib(lib)


def completar_avulso(gid):
    """Jogo sem loja: tenta achar o mesmo jogo na Steam pelo nome e trazer capa e dados.
    Se não achar e houver chave do SteamGridDB, busca a capa lá."""
    g = find_game(get_lib(), gid)
    if not g:
        return False
    meta = {}
    if not (g.get("description") and g.get("cover")) and not g.get("nunca_steam"):
        try:
            appid = _appid_da_pasta(g) or steam_por_nome(g["name"])
            meta = _steam_meta(appid) if appid else {}
        except Exception as e:
            print(f"[dados] busca na Steam para {g['name']}: {e}")
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            return False
        for k in ("description", "developer", "year", "genres"):
            if meta.get(k) and not g.get(k):
                g[k] = meta[k]
        if meta.get("description") and not g.get("dados_de"):
            g["dados_de"] = "steam"
        save_lib(lib)
        tem_capa = bool(g.get("cover"))
    if not tem_capa and _vertical_steam(meta):
        try:
            if download_cover(gid, _vertical_steam(meta)):
                _marcar_jogo(gid, capa_de="steam")
                return True
        except Exception as e:
            print(f"[capas] não consegui baixar a capa da Steam de {gid}: {e}")
    if not tem_capa and get_cfg().get("sgdb_key"):
        return auto_cover(gid)
    return bool(meta)


def page_meta(url):
    """Lê nome, descrição, criador e imagens da página de um jogo."""
    url = (url or "").strip()
    if not url:
        raise ValueError("Cole o link da página do jogo.")
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url

    m_steam = re.search(r"store\.steampowered\.com/(?:agecheck/)?app/(\d+)", url, re.I)
    if m_steam:
        return _steam_meta(m_steam.group(1))

    # cookies de "já confirmei minha idade" que vários sites usam
    page, final = _get_text(url, headers={"Cookie": "birthtime=0; mature_content=1; wants_mature_content=1; lastagecheckage=1-0-1990"})
    p = _MetaParser()
    p.feed(page)
    m = p.meta
    host = (urllib.parse.urlparse(final).hostname or "").lower()
    tag_title = re.sub(r"\s+", " ", p.title).strip()
    title = htmlmod.unescape(m.get("og:title") or m.get("twitter:title") or tag_title).strip()
    desc = htmlmod.unescape(m.get("og:description") or m.get("description") or m.get("twitter:description") or "").strip()
    og_img = m.get("og:image") or m.get("og:image:url") or m.get("twitter:image") or m.get("twitter:image:src") or ""
    dev = htmlmod.unescape(m.get("author") or m.get("article:author") or "").strip()
    aviso = ""
    extra = {}
    conteudo = [u for u in p.links + p.imgs if not RUIM_RE.search(u)]

    if host.endswith(".itch.io") and host != "itch.io":
        try:
            data = json.loads(_get_text(final.split("?")[0].rstrip("/") + "/data.json")[0])
            title = data.get("title") or title
            og_img = data.get("cover_image") or og_img
            if (data.get("authors") or [{}])[0].get("name"):
                dev = data["authors"][0]["name"]
        except Exception as e:
            print(f"[dados] não entendi os dados do itch.io em {url}: {e}")
        if not dev:
            mm = re.match(r"(.+?) by (.+?)(?: - itch\.io)?$", tag_title)
            dev = mm.group(2) if mm else host.split(".")[0]

    elif host.endswith("f95zone.to"):
        # títulos do tipo "VN - Ren'Py - Nome do Jogo [v0.1] [Criador]"
        t = re.sub(r"\s*\|\s*F95zone.*$", "", title, flags=re.I)
        colchetes = re.findall(r"\[([^\]]+)\]", t)
        nome = re.sub(r"\[[^\]]*\]", "", t)
        nome = re.sub(r"^\s*(?:[A-Za-z'’\. ]{1,14}\s+-\s+)+", "", nome).strip(" -")
        prefixos = [x.strip() for x in re.findall(r"([A-Za-z'’\. ]{1,14})\s+-\s+", t.split(nome)[0])] if nome and nome in t else []
        title = nome or title
        if colchetes and not re.match(r"v?\d", colchetes[-1], re.I):
            dev = colchetes[-1]
        extra["version"] = next((c for c in colchetes if re.match(r"(v|ver\.?|ep|ch|chapter|episode|season|build|r)?\s*\d", c, re.I)
                                 or re.search(r"\b(final|completed?)\b", c, re.I)), "")
        for pf in prefixos:
            if pf.lower() in STATUS_F95:
                extra["status"] = STATUS_F95[pf.lower()]
            for eng in ENGINES_F95:
                if pf.lower().replace("'", "") == eng.lower().replace("'", ""):
                    extra["engine"] = "Ren'Py" if eng == "RenPy" else eng
        if "status" not in extra:
            extra["status"] = "Em desenvolvimento"
        try:
            post = _f95_post(page)
            if len(post.get("description", "")) > len(desc.rstrip(". …")) - 5:
                desc = post["description"]
            extra["version"] = extra["version"] or post.get("version", "")
            dev = dev or post.get("developer", "")
            if post.get("year"):
                extra["year"] = post["year"]
            if post.get("genres"):
                extra["genres"] = post["genres"]
            if post["images"]:
                p.links, p.imgs = post["images"], []
        except Exception as e:
            print("[f95] não consegui ler o primeiro post:", e)
        desc = re.sub(r"^\s*overview:?\s*", "", desc, flags=re.I)
        anexos = [u for u in p.links + p.imgs if "attachments.f95zone.to" in u and "/thumb/" not in u]
        if not anexos:
            anexos = [u for u in p.imgs if "attachments.f95zone.to" in u]
        conteudo = anexos + conteudo
        og_img = ""  # a imagem de prévia do F95zone é sempre a logo do fórum

    if LOGIN_RE.match(title or ""):
        aviso = "Essa página pediu login, então não deu para ver os dados do jogo. Tente outro link, como a página do criador ou do itch.io."
        title, desc, og_img = "", "", ""

    title = re.sub(r"\s*[|\-–]\s*(itch\.io|Game Jolt|Steam|F95zone).*$", "", title).strip()
    desc = re.sub(r"^\s*overview:?\s*", "", desc, flags=re.I)

    og_ruim = (not og_img) or bool(RUIM_RE.search(og_img))
    imgs = [urllib.parse.urljoin(final, u) for u in ([] if og_ruim else [og_img]) + conteudo + ([og_img] if og_ruim and og_img else [])]
    imgs = _unicos(imgs)
    return {
        "title": title,
        "description": desc[:4000],
        "developer": dev,
        "image": imgs[0] if imgs else "",
        "images": imgs,
        "url": final,
        "site": m.get("og:site_name") or host,
        "warning": aviso,
        **extra,
    }


def apply_meta(gid, meta, use_name=True, use_cover=True, use_info=True):
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            return None
        if use_name and meta.get("title"):
            g["name"] = meta["title"]
        if use_info:
            for k in ("description", "developer", "url"):
                if meta.get(k):
                    g[k] = meta[k]
            if meta.get("year") and not g.get("year"):
                g["year"] = meta["year"]
            for k in ("status", "engine"):
                if meta.get(k):
                    g[k] = meta[k]
            if meta.get("genres"):
                g["genres"] = meta["genres"]
            if meta.get("version"):
                if not g.get("version"):
                    g["version"] = meta["version"]  # primeira vez: considera que você tem essa versão
                g["latest_version"] = meta["version"]
                g["update_checked"] = time.time()
        save_lib(lib)
    if use_info and meta.get("description"):
        _marcar_jogo(gid, dados_de="pagina")  # dados que você escolheu pelo link: a busca automática não troca
    if use_cover and meta.get("image"):
        download_cover(gid, meta["image"], referer=meta.get("url"))
        _marcar_jogo(gid, capa_de="pagina")
    return find_game(get_lib(), gid)


def read_itch_receipt(folder):
    """Jogos instalados pelo app do itch.io guardam os dados do jogo na pasta .itch."""
    base = Path(folder) / ".itch"
    try:
        if (base / "receipt.json.gz").exists():
            with gzip.open(base / "receipt.json.gz", "rt", encoding="utf-8") as f:
                d = json.load(f)
        elif (base / "receipt.json").exists():
            d = json.loads((base / "receipt.json").read_text("utf-8"))
        else:
            return None
        g = d.get("game") or {}
        if not g.get("title"):
            return None
        user = g.get("user") or {}
        return {
            "title": g["title"],
            "description": g.get("shortText") or "",
            "developer": user.get("displayName") or user.get("username") or "",
            "url": g.get("url") or "",
            "image": g.get("coverUrl") or g.get("stillCoverUrl") or "",
        }
    except Exception as e:
        print(f"[itch] não consegui ler os dados em {folder}: {e}")
        return None


# ---------------------------------------------------------------- escanear pastas

SKIP_EXE = re.compile(
    r"(unins|setup|install|redist|vcredist|vc_redist|dxsetup|directx|dxwebsetup|crash|report|"
    r"updater|patch|dotnet|prereq|ue4prereq|helper|cleanup|touchup|activation|register|"
    r"benchmark|uploader|notification|errorhandler|cefsharp|subprocess|quicksfv|7z|unrar)",
    re.I,
)
SKIP_DIR = re.compile(r"(^\.itch$|redist|directx|_commonredist|__installer|support|prereq|dotnet|vcredist|tools|extras|bonus)", re.I)


def _clean(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def nice_name(folder_name):
    n = re.sub(r"\s*[\[\(].*?[\]\)]\s*", " ", folder_name)  # tira [GOG], (v1.2) etc.
    # tira a versão e o que vem depois: "Jogo-0.01-pc" -> "Jogo", "Saga 21.0.0 wip" -> "Saga" ("Half-Life 2" fica)
    n = re.sub(r"[\s_\-]+(?:(?:v|ver|ep|ch|episode|chapter|build)\.?\s*\d+(?:[._]\d+)*|\d+(?:\.\d+)+)[a-z]?(?:[\s_\-].*)?$", "", n, flags=re.I)
    n = re.sub(r"[\s_\-]+(pc|win|win64|windows|linux|mac|market|final|repack)$", "", n, flags=re.I)
    n = re.sub(r"[_\.]+", " ", n)
    return re.sub(r"\s+", " ", n).strip() or folder_name


def iter_exes(folder, max_depth=3, limit=400):
    found = []
    base_depth = str(folder).rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(folder):
        depth = root.rstrip(os.sep).count(os.sep) - base_depth
        dirs[:] = [d for d in dirs if not SKIP_DIR.search(d)] if depth < max_depth else []
        for f in files:
            if f.lower().endswith(".exe") and not SKIP_EXE.search(f):
                p = Path(root) / f
                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0
                found.append((p, depth, size))
                if len(found) >= limit:
                    return found
    return found


def rank_exes(folder_name, exes):
    target = _clean(folder_name)

    def score(item):
        p, depth, size = item
        stem = _clean(p.stem)
        if stem and stem == target:
            match = 3
        elif stem and target and (stem in target or target in stem):
            match = 2
        elif stem[:4] and stem[:4] == target[:4]:
            match = 1
        else:
            match = 0
        return (-match, depth, -size)

    return [str(p) for p, _, _ in sorted(exes, key=score)]


# Pastas que fazem parte de um jogo (o executável pode estar dentro delas): não são categorias de jogos.
PASTA_INTERNA = re.compile(r"^(bin|binaries|x64|x86|win64|win32|windows|game|data|engine|lib|libs|www|resources|content|"
                           r"system|runtime|renpy|jre|java|mono|monobleedingedge|plugins|nwjs|locales|swiftshader|.+_data)$", re.I)
PROFUNDIDADE_CATEGORIAS = 5  # quantas pastas de categoria dentro de categoria a busca desce (RPG\Ação\...)


def _exes_na_raiz(pasta):
    try:
        return [p for p in Path(pasta).iterdir() if p.suffix.lower() == ".exe" and p.is_file() and not SKIP_EXE.search(p.name)]
    except OSError:
        return []


def _subpastas(pasta):
    try:
        return sorted([p for p in Path(pasta).iterdir() if p.is_dir() and not SKIP_DIR.search(p.name)], key=lambda p: p.name.lower())
    except OSError:
        return []


def so_versao(nome):
    """Pasta que é só a versão de um jogo: "versão 0.5", "v1.2", "0.13.0", "Build 12"."""
    n = re.sub(r"(?<![a-z])(vers[aã]o|version|versi[oó]n|update|atualiza[cç][aã]o|release|patch|full)(?![a-z])", " ", (nome or "").lower())
    return bool(re.search(r"\d", nome or "")) and not chave_pasta(n)


def pasta_do_titulo(pasta):
    """A pasta que dá nome ao jogo: a do próprio jogo, ou a de cima quando a pasta é só a versão (Outro Jogo\\versão 0.5)."""
    p = Path(pasta)
    return p.parent if so_versao(p.name) else p


def chave_do_jogo(pasta):
    """Chave para reconhecer versões novas do mesmo jogo, mesmo quando as versões ficam em subpastas."""
    return chave_pasta(pasta_do_titulo(pasta).name)


def numero_versao(pasta):
    """Os números do nome da pasta, para comparar versões: "Jogo-0.10-pc" (0, 10) é mais nova que "Jogo-0.9-pc" (0, 9)."""
    return tuple(int(x) for x in re.findall(r"\d+", Path(pasta).name))


def achar_pastas_de_jogo(raiz, de_onde=1):
    """Desce pelas pastas de categoria (RPG, Visual Novel\\Romance...) até achar as pastas dos jogos.
    Uma pasta é de um jogo quando tem um executável nela mesma, ou só dentro das pastas do próprio jogo (bin\\x64).
    Devolve (pasta do jogo, categorias até ela). Dentro de uma pasta de jogo a busca para."""
    out = []

    def eh_jogo(pasta, subs):
        if _exes_na_raiz(pasta):
            return True
        internas = [s for s in subs if PASTA_INTERNA.match(s.name)]
        return bool(internas) and any(iter_exes(s, max_depth=3, limit=1) for s in internas) \
            and not any(_exes_na_raiz(s) for s in subs if s not in internas)

    def visitar(pasta, cats, prof):
        subs = _subpastas(pasta)
        if eh_jogo(pasta, subs):
            out.append((pasta, cats))
            return
        if prof >= PROFUNDIDADE_CATEGORIAS:
            return
        for s in subs:
            visitar(s, cats + [pasta.name], prof + 1)

    for s in _subpastas(raiz):
        visitar(s, [], de_onde)
    return out


def scan_folder(folder):
    root = Path(folder)
    if not root.is_dir():
        raise ValueError("Essa pasta não existe.")
    jogos = get_lib()["games"]
    known = {norm_path(f["exe"]) for g in jogos for f in fontes(g) if f["exe"]}
    pastas_loja = [norm_path(f["pasta_jogo"]) for g in jogos for f in fontes(g) if f["loja"] and f["pasta_jogo"]]

    def de_loja(caminho):
        c = norm_path(caminho)
        if os.sep + "steamapps" + os.sep in c + os.sep:  # tudo dentro da Steam é da Steam (inclusive ferramentas dela)
            return True
        return any(c == p or c.startswith(p + os.sep) or p.startswith(c + os.sep) for p in pastas_loja)

    out = []

    def add(name_src, exes, folder=None, cats=()):
        if not exes:
            return
        ranked = rank_exes(name_src, exes)
        meta = read_itch_receipt(folder) if folder else None
        loja = bool(folder) and de_loja(folder)
        out.append({
            "pasta": str(folder) if folder else "",
            "meta": meta,
            "name": meta["title"] if meta else nice_name(name_src),
            "exe": ranked[0],
            "alternatives": ranked[:15],
            "already": loja or any(norm_path(e) in known for e in ranked),
            "de_loja": loja,
            "colecao": "/".join(cats),  # as pastas de categoria até o jogo (RPG/Ação)
        })

    # exes soltos direto na pasta escolhida (caso ela já seja a pasta de um jogo)
    direct = [(p, 0, p.stat().st_size) for p in _exes_na_raiz(root)]
    achados = achar_pastas_de_jogo(root)
    if direct:  # a pasta escolhida já é um jogo: as pastas internas dele (lib, game, bin...) não são outros jogos
        achados = [(p, cats) for p, cats in achados if not PASTA_INTERNA.match(cats[0] if cats else p.name)]
    if direct and not achados:
        add(root.name, direct + iter_exes(root), root)
        return out
    if direct:
        add(root.name, direct)
    for pasta, cats in achados:
        titulo = pasta_do_titulo(pasta)
        if titulo != pasta:  # Outro Jogo\versão 0.5: o nome e a coleção vêm da pasta de cima
            cats = cats[:-1]
        try:
            add(titulo.name, iter_exes(pasta), pasta, cats)
        except PermissionError:
            continue
    # o mesmo jogo em várias versões lado a lado (versão 0.5 e versão 0.6): fica só a mais nova
    melhor = {}
    for c in out:
        k = chave_do_jogo(c["pasta"]) if c["pasta"] else ""
        if len(k) >= 3 and (k not in melhor or numero_versao(c["pasta"]) > numero_versao(melhor[k]["pasta"])):
            melhor[k] = c
    for c in out:
        k = chave_do_jogo(c["pasta"]) if c["pasta"] else ""
        if len(k) >= 3 and melhor[k] is not c:
            c["antiga"] = True  # versão mais antiga de um jogo que também está numa pasta mais nova
    return out


# ---------------------------------------------------------------- acompanhar pastas

PALAVRAS_VERSAO = r"(pc|win|windows|win64|win32|x64|x86|linux|mac|osx|android|market|final|public|release|beta|alpha|ea|early ?access|demo|patreon|steam|itch|gog|elite|premium|compressed|repack)"
EXE_GENERICOS = {"game.exe", "launcher.exe", "nw.exe", "start.exe", "play.exe", "run.exe", "main.exe", "app.exe", "client.exe", "unitycrashhandler64.exe"}


def chave_pasta(nome):
    """Nome da pasta sem versão: "College-0.02-pc" e "College-0.01-pc" dão a mesma chave."""
    n = (nome or "").lower()
    n = re.sub(r"[\[\(].*?[\]\)]", " ", n)
    n = re.sub(r"(?<![a-z])(v|ver|version|ep|episode|ch|chapter|season|s|build|b|r)?[ ._-]*\d+([._]\d+)*[a-z]?(?![a-z])", " ", n)
    n = re.sub(r"(?<![a-z])" + PALAVRAS_VERSAO + r"(?![a-z])", " ", n)
    return re.sub(r"[^a-z0-9]", "", n)


def _pasta_do_jogo(g):
    return g.get("pasta_jogo") or str(Path(g["exe"]).parent)


def _dentro_de_pasta_acompanhada(caminho, pastas):
    c = norm_path(caminho)
    return any(c.startswith(norm_path(p) + os.sep) for p in pastas)


eventos = {"added": [], "relinked": []}


def _colecao_da_pasta(pasta, raizes):
    """As pastas de categoria entre a pasta acompanhada e o jogo: D:\\Jogos\\RPG\\Ação\\Nome -> "RPG/Ação"."""
    titulo = pasta_do_titulo(pasta)
    for r in sorted(raizes, key=lambda x: -len(norm_path(x))):
        base = norm_path(r)
        if norm_path(str(titulo)).startswith(base + os.sep):
            partes = Path(os.path.relpath(str(titulo.parent), r)).parts
            return "/".join(p for p in partes if p not in (".", ""))
    return None


def _atualizar_colecoes_pasta(lib, raizes):
    """Guarda em cada jogo das pastas acompanhadas a coleção que vem das pastas (colecao_pasta).
    Ela é separada das coleções que você criou à mão, que nunca são mexidas. Devolve True se algo mudou."""
    mudou = False
    for g in lib["games"]:
        if g.get("loja") or not g.get("exe"):
            continue
        c = _colecao_da_pasta(_pasta_do_jogo(g), raizes)
        if c is not None and g.get("colecao_pasta", "") != c:
            g["colecao_pasta"] = c
            mudou = True
    return mudou


_col_pastas = {"valor": False, "quando": 0.0}


def colecoes_pastas_ligado():
    """Opção das Configurações: mostrar as coleções que seguem as pastas. Guardada por alguns segundos."""
    if time.time() - _col_pastas["quando"] > 3:
        _col_pastas["valor"] = bool(get_cfg().get("colecoes_pastas"))
        _col_pastas["quando"] = time.time()
    return _col_pastas["valor"]


def tags_do_jogo(g):
    """As coleções do jogo: as suas e, com a opção ligada, a que segue a pasta (a menos que você tenha tirado)."""
    tags = list(g.get("tags") or [])
    c = g.get("colecao_pasta")
    if c and colecoes_pastas_ligado() and not g.get("sem_colecao_pasta") and c not in tags:
        tags.append(c)
    return sorted(tags, key=str.lower)


def limpar_colecao(t):
    """ "RPG / Ação " -> "RPG/Ação": a barra separa a coleção da subcoleção."""
    return "/".join(p.strip() for p in str(t).split("/") if p.strip())


def sync_folders():
    """Procura jogos novos e versões novas nas pastas acompanhadas.
    Jogo atualizado (pasta com outro nome) continua sendo o mesmo jogo, com histórico, capa e coleções."""
    cfg = get_cfg()
    pastas = [p for p in cfg["pastas"] if os.path.isdir(p)]
    if not pastas:
        return
    ignorados = set(cfg["ignorados"])
    candidatos = []
    for p in pastas:
        try:
            candidatos += scan_folder(p)
        except Exception as e:
            print(f"[pastas] não consegui olhar {p}: {e}")
    novos, religados = [], []
    with lock:
        lib = get_lib()
        conhecidos = {norm_path(f["exe"]) for g in lib["games"] for f in fontes(g) if f["exe"]}
        livres = [c for c in candidatos if not c.get("de_loja")
                  and not any(norm_path(e) in conhecidos for e in c["alternatives"])]
        sumidos = [g for g in lib["games"] if not g.get("loja") and g.get("exe")
                   and not os.path.exists(g["exe"]) and g["id"] not in running]
        def religar(g, c, mesmo_exe=()):
            g["exe"] = mesmo_exe[0] if mesmo_exe else c["exe"]
            g["pasta_jogo"] = c["pasta"]
            # se a pasta nova tem o número da versão mais recente, considera atualizado
            num = re.sub(r"[^0-9.]", "", g.get("latest_version") or "").strip(".")
            if num and num in Path(c["pasta"]).name:
                g["version"] = g["latest_version"]
            religados.append(g["name"])
            livres.remove(c)

        livres = [c for c in livres if not c.get("antiga")]
        for g in sumidos:
            gk = chave_do_jogo(_pasta_do_jogo(g))
            gexe = Path(g["exe"]).name.lower()
            for c in livres:
                ck = chave_do_jogo(c["pasta"])
                mesmo_exe = [e for e in c["alternatives"] if Path(e).name.lower() == gexe]
                if (gk and ck == gk) or (mesmo_exe and gexe not in EXE_GENERICOS):
                    religar(g, c, mesmo_exe)
                    break
        # versão nova ao lado da antiga (Jogo\versão 0.5 e Jogo\versão 0.6): o jogo passa a abrir pela mais nova;
        # uma versão mais velha que aparecer não vira outro jogo
        vivos = {}
        for g in lib["games"]:
            if not g.get("loja") and g.get("exe") and g["id"] not in running and _dentro_de_pasta_acompanhada(_pasta_do_jogo(g), pastas):
                k = chave_do_jogo(_pasta_do_jogo(g))
                if len(k) >= 3:
                    vivos.setdefault(k, g)
        for c in list(livres):
            g = vivos.get(chave_do_jogo(c["pasta"]))
            if not g:
                continue
            if numero_versao(c["pasta"]) > numero_versao(_pasta_do_jogo(g)):
                religar(g, c)
            else:
                livres.remove(c)
        for c in livres:
            if c["already"] or chave_do_jogo(c["pasta"]) in ignorados:
                continue
            meta = c.get("meta") or {}
            g = new_game(c["name"], c["exe"])
            g["pasta_jogo"] = c["pasta"]
            for k in ("description", "developer", "url"):
                if meta.get(k):
                    g[k] = meta[k]
            lib["games"].append(g)
            novos.append((g["id"], meta.get("image")))
            eventos["added"].append(g["name"])
        eventos["relinked"] += religados
        mudou_colecao = _atualizar_colecoes_pasta(lib, pastas)
        if novos or religados or mudou_colecao:
            save_lib(lib)
    if religados:
        print("[pastas] versões novas reconhecidas:", ", ".join(religados))
    if novos:
        def capas():
            for gid, img in novos:
                try:
                    if img:
                        download_cover(gid, img)
                    else:
                        completar_avulso(gid)
                except Exception as e:
                    print("[pastas] capa:", e)
        threading.Thread(target=capas, daemon=True).start()


def vigiar_pastas(intervalo=300):
    """Ao abrir e a cada 5 minutos: importa os jogos das lojas e olha as pastas acompanhadas.
    Também começa a procurar capítulos novos das séries da Leitura (a cada 6 horas)."""
    leitura.vigiar()
    copias.vigiar()  # cópia de segurança automática, uma por dia

    def loop():
        while True:
            try:
                sync_lojas()
            except Exception as e:
                print("[lojas]", e)
            try:
                sync_folders()
            except Exception as e:
                print("[pastas]", e)
            try:
                wand.vigiar_passo(get_lib()["games"])
            except Exception as e:
                print("[wand]", e)
            try:
                limpar_minis()
            except Exception as e:
                print("[capas]", e)
            time.sleep(intervalo)
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------- jogos das outras lojas (Steam, Epic, GOG...)

lojas_status = {}  # loja -> o que foi visto na última leitura
_sync_lojas_lock = threading.Lock()
eventos.update({"voltaram": [], "sairam": [], "convertidos": []})


def chave_fonte(f):
    return f"{f.get('loja')}:{f.get('loja_id')}"


def _fonte_de_entrada(e):
    return {"loja": e["loja"], "loja_id": e["loja_id"], "abrir": e.get("abrir") or "", "exe": e.get("exe") or "",
            "args": e.get("args") or "", "workdir": "", "pasta_jogo": e.get("pasta") or "", "nome": e.get("nome") or ""}


def sync_lojas(so=None):
    """Lê as lojas ligadas e coloca na estante os jogos instalados nelas. Só lê os arquivos das lojas."""
    if not _sync_lojas_lock.acquire(blocking=False):
        with _sync_lojas_lock:  # já tem uma leitura rodando: espera ela terminar
            return
    try:
        cfg = get_cfg()
        for loja in lojas.ORDEM:
            if so and loja != so:
                continue
            if not loja_ligada(cfg, loja):
                lojas_status[loja] = {"ligada": False}
                continue
            try:
                r = lojas.ler(loja)
            except Exception as e:
                print(f"[lojas] não consegui ler {lojas.LOJAS[loja]}: {e}")
                lojas_status[loja] = {"ligada": True, "encontrada": True, "instalados": 0,
                                      "erro": "Não consegui ler os dados dessa loja agora."}
                continue
            lojas_status[loja] = {"ligada": True, "encontrada": r["encontrada"], "instalados": len(r["jogos"]), "erro": ""}
            if r["encontrada"]:
                _aplicar_loja(loja, r["jogos"], cfg)
    finally:
        _sync_lojas_lock.release()


def _aplicar_loja(loja, entradas, cfg):
    novos, voltaram, sairam, convertidos, pendentes = [], [], [], [], []
    with lock:
        lib = get_lib()
        ignorados = set(cfg["ignorados_lojas"])
        mapa = {}  # "steam:620" -> (jogo, índice da fonte; -1 = principal)
        for g in lib["games"]:
            for i, f in enumerate(fontes(g)):
                if f["loja"]:
                    mapa[chave_fonte(f)] = (g, i - 1)
        vistos, mudou = set(), False
        for e in entradas:
            k = chave_fonte(e)
            vistos.add(k)
            nova = _fonte_de_entrada(e)
            if k in mapa:  # já está na estante: só acompanha se mudou de pasta
                g, i = mapa[k]
                alvo = g if i < 0 else g["outras_fontes"][i]
                for c in ("abrir", "exe", "args", "pasta_jogo"):
                    if (alvo.get(c) or "") != nova[c]:
                        alvo[c] = nova[c]
                        mudou = True
                continue
            if k in ignorados:
                continue
            guardado = next((x for x in lib["guardados"] if chave_fonte(fonte_principal(x)) == k), None)
            if guardado:  # foi desinstalado antes e voltou: volta com tempo jogado, capa e coleções
                lib["guardados"].remove(guardado)
                guardado.pop("guardado_em", None)
                _completar_jogo(guardado)
                usar_fonte(guardado, nova)
                lib["games"].append(guardado)
                mapa[k] = (guardado, -1)
                voltaram.append(guardado["name"])
                mudou = True
                continue
            pasta = norm_path(e.get("pasta"))
            manual = next((g for g in lib["games"] if not g.get("loja") and g.get("exe") and pasta
                           and norm_path(g["exe"]).startswith(pasta + os.sep)), None)
            if manual:  # você já tinha adicionado esse jogo à mão: passa a abrir pela loja, mantendo tudo
                antiga = fonte_principal(manual)
                antiga["nome"] = "Arquivo do jogo"
                usar_fonte(manual, nova)
                manual["outras_fontes"] = [antiga] + list(manual.get("outras_fontes") or [])
                mapa[k] = (manual, -1)
                convertidos.append(manual["name"])
                pendentes.append((manual["id"], e))
                mudou = True
                continue
            g = new_game(e["nome"], "")
            usar_fonte(g, nova)
            lib["games"].append(g)
            mapa[k] = (g, -1)
            novos.append(g["name"])
            pendentes.append((g["id"], e))
            mudou = True
        # o que a loja não mostra mais foi desinstalado (a não ser que o disco esteja desligado)
        for g in list(lib["games"]):
            if g["id"] in running:
                continue
            fs = fontes(g)
            ficam = [f for f in fs if not (f["loja"] == loja and chave_fonte(f) not in vistos
                                           and not _unidade_ausente(f["pasta_jogo"]))]
            if len(ficam) == len(fs):
                continue
            mudou = True
            if not ficam:
                lib["games"].remove(g)
                g["guardado_em"] = time.time()
                lib["guardados"].append(g)
                sairam.append(g["name"])
            else:
                usar_fonte(g, ficam[0])
                g["outras_fontes"] = ficam[1:]
        if len(lib["guardados"]) > 500:
            lib["guardados"] = sorted(lib["guardados"], key=lambda x: x.get("guardado_em") or 0)[-500:]
        if mudou:
            save_lib(lib)
        eventos["added"] += novos
        eventos["voltaram"] += voltaram
        eventos["sairam"] += sairam
        eventos["convertidos"] += convertidos
    if novos or voltaram or sairam or convertidos:
        print(f"[lojas] {lojas.LOJAS[loja]}: {len(novos)} novo(s), {len(voltaram)} voltaram, "
              f"{len(sairam)} desinstalado(s), {len(convertidos)} passaram a abrir pela loja")
    if pendentes:
        def completar():
            for gid, e in pendentes:
                try:
                    _completar_loja(gid, e)
                except Exception as ex:
                    print(f"[lojas] capa/dados de {e.get('nome')}: {ex}")
                time.sleep(1.2)  # devagar, pra não sobrecarregar os sites
        threading.Thread(target=completar, daemon=True).start()


def _entrada_de_fonte(f):
    """Monta o mínimo para buscar capa e dados de uma fonte que já está na estante."""
    e = {"loja": f["loja"], "loja_id": f["loja_id"], "capas_locais": [], "capa_url": "", "capas_reserva": [], "meta": {}}
    if f["loja"] == "steam":
        raiz = lojas.steam_pasta()
        e["capas_locais"] = lojas._steam_capas_locais(raiz, f["loja_id"]) if raiz else []
        e["capa_url"] = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{f['loja_id']}/library_600x900_2x.jpg"
    return e


def _guardar_capa_local(gid, caminho):
    ext = Path(caminho).suffix.lower()
    return store_cover_bytes(gid, Path(caminho).read_bytes(), ext if ext in IMG_EXT else ".jpg")


def _completar_loja(gid, e):
    """Busca capa, descrição, criador, ano e gêneros de um jogo de loja.
    A Steam vem sempre primeiro (pelo número do jogo, ou pelo nome quando ele é de outra loja);
    depois os dados da própria loja (GOG, Epic) e, para a capa, o SteamGridDB. Só preenche o que estiver vazio,
    a não ser quando os dados vieram de outra loja e a Steam tem os dela."""
    g0 = find_game(get_lib(), gid)
    if not g0:
        return
    nome = e.get("nome") or g0["name"]
    steam = {}
    try:
        appid = e["loja_id"] if e["loja"] == "steam" else (None if g0.get("nunca_steam") else steam_por_nome(nome))
        if appid:
            steam = _steam_meta(appid)
    except Exception as ex:
        print(f"[lojas] Steam para {nome}: {ex}")
    outra = {k: v for k, v in (e.get("meta") or {}).items() if v}
    if e["loja"] == "gog" and not steam.get("description"):
        try:
            outra = {**{k: v for k, v in _gog_meta(e["loja_id"]).items() if v}, **outra}
        except Exception as ex:
            print(f"[lojas] GOG para {nome}: {ex}")
    meta = {**outra, **{k: v for k, v in steam.items() if v and k not in ("image", "images")}}
    fonte = "steam" if steam.get("description") else (e["loja"] if outra.get("description") else "")
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            return
        trocar = fonte == "steam" and g.get("dados_de") in lojas.LOJAS and g.get("dados_de") != "steam"  # dados de outra loja: a Steam tem prioridade
        for k in ("description", "developer", "url", "year", "genres"):
            if meta.get(k) and (not g.get(k) or trocar):
                g[k] = meta[k]
        if fonte and (trocar or not g.get("dados_de")):
            g["dados_de"] = fonte
        save_lib(lib)
        if g.get("cover"):
            return
    vertical_steam = _vertical_steam(steam) if e["loja"] != "steam" else ""
    for caminho in e.get("capas_locais") or []:  # capa que a própria Steam já guardou no PC
        try:
            if _guardar_capa_local(gid, caminho):
                return
        except OSError:
            continue
    urls = ([e.get("capa_url")] if e["loja"] == "steam" else [vertical_steam, e.get("capa_url"), outra.get("image")])
    for u in urls:
        if u:
            try:
                if download_cover(gid, u):
                    if u == vertical_steam:
                        _marcar_jogo(gid, capa_de="steam")
                    return
            except Exception as e:
                print(f"[capas] não consegui baixar a capa {u}: {e}")
                continue
    if get_cfg().get("sgdb_key") and auto_cover(gid):
        return
    for caminho in e.get("capas_reserva") or []:
        try:
            if _guardar_capa_local(gid, caminho):
                return
        except OSError:
            continue
    if steam.get("image"):  # imagem deitada da Steam, melhor que nada
        try:
            download_cover(gid, steam["image"])
        except Exception as e:
            print(f"[capas] não consegui baixar a imagem da Steam de {gid}: {e}")


def repetidos(jogos, cfg):
    """Grupos de jogos com o mesmo nome vindos de lojas diferentes (provavelmente o mesmo jogo)."""
    grupos = {}
    for g in jogos:
        if not g.get("hidden"):
            grupos.setdefault(_clean(g["name"]), []).append(g)
    nao = set(cfg["nao_juntar"])
    out = []
    for k, gs in grupos.items():
        if k and len(gs) > 1 and len({g.get("loja") for g in gs}) > 1:
            ids = sorted(g["id"] for g in gs)
            if "|".join(ids) not in nao:
                out.append(ids)
    return out


# ---------------------------------------------------------------- abrir jogo e contar tempo

def _procs_in_folder(folder):
    if not psutil:
        return False
    folder = norm_path(folder) + os.sep
    me = os.getpid()
    for p in psutil.process_iter(["pid", "exe"]):
        try:
            exe = p.info.get("exe")
            if exe and p.info["pid"] != me and norm_path(exe).startswith(folder):
                return True
        except Exception:
            continue
    return False


def _track(gid, proc, folder, espera=45, so_se_visto=False):
    """Conta o tempo jogado. so_se_visto: para jogos abertos por uma loja, só conta a partir do momento
    em que o jogo aparece rodando da pasta dele (o tempo da loja abrindo ou atualizando não entra)."""
    start = running.get(gid, time.time())
    seen = None
    try:
        if proc is not None:
            proc.wait()
        # Jogos com launcher fecham o primeiro processo rápido e abrem outro.
        # Nesses casos, fica de olho em qualquer programa rodando da pasta do jogo.
        if psutil and folder and (proc is None or time.time() - start < 20):
            deadline = time.time() + espera
            while True:
                time.sleep(4)
                alive = _procs_in_folder(folder)
                if alive:
                    seen = seen or time.time() - 4
                elif seen or time.time() > deadline:
                    break
    finally:
        end = time.time()
        if so_se_visto and seen:
            start = max(start, seen)
        with lock:
            lib = get_lib()
            g = find_game(lib, gid)
            if g and (seen or not so_se_visto):
                g["playtime"] = int(g.get("playtime", 0) + (end - start))
                g["last_played"] = end
                if end - start >= 30:  # abrir e fechar na hora não conta como uma vez jogada
                    g.setdefault("sessoes", []).append([int(start), int(end - start)])
                save_lib(lib)
            running.pop(gid, None)


def _abrir_link(link):
    if not WINDOWS:
        webbrowser.open(link)
    elif link.lower().startswith("shell:"):
        subprocess.Popen(["explorer.exe", link])  # jogos do app Xbox
    else:
        os.startfile(link)  # steam://, com.epicgames.launcher://, uplay://, origin2://


def launch_game(g, f=None):
    f = f or fonte_principal(g)
    pasta = f.get("pasta_jogo") or ""
    if f.get("abrir"):  # abre pela própria loja
        _abrir_link(f["abrir"])
        running[g["id"]] = time.time()
        threading.Thread(target=_track, args=(g["id"], None, pasta, 180, True), daemon=True).start()
        return
    exe = f.get("exe") or ""
    if not exe or not os.path.exists(exe):
        if f.get("loja"):
            raise FileNotFoundError(f"Não achei o programa da loja ({nome_loja(f['loja'])}) para abrir esse jogo. Ele ainda está instalado?")
        raise FileNotFoundError("Não achei o arquivo do jogo. Ele foi movido? Corrija o caminho em Editar.")
    folder = f.get("workdir") or str(Path(exe).parent)
    args = f.get("args") or ""
    proc = None
    ext = Path(exe).suffix.lower()
    if WINDOWS and ext != ".exe":
        os.startfile(exe)  # atalhos .lnk, .url, .bat
    elif WINDOWS:
        proc = subprocess.Popen(f'"{exe}" {args}'.strip(), cwd=folder)
    else:
        proc = subprocess.Popen([exe] + shlex.split(args), cwd=folder)
    running[g["id"]] = time.time()
    if f.get("loja") and pasta and not norm_path(exe).startswith(norm_path(pasta) + os.sep):
        # abriu pelo programa da loja (GOG Galaxy, Battle.net): acompanha a pasta do jogo, não o programa da loja
        threading.Thread(target=_track, args=(g["id"], None, pasta, 180, True), daemon=True).start()
    else:
        threading.Thread(target=_track, args=(g["id"], proc, pasta if f.get("loja") and pasta else folder),
                         daemon=True).start()


def launch_wand(g, t):
    """Abre o jogo pelo Wand, com o trainer. O Wand abre o jogo pela loja, então o tempo só conta
    a partir do momento em que o jogo aparece rodando da pasta dele, como nos jogos de loja."""
    if not wand.pasta():
        raise FileNotFoundError("Não achei o Wand neste computador. Ele ainda está instalado?")
    f = fonte_principal(g)
    pasta = f.get("pasta_jogo") or (str(Path(f["exe"]).parent) if f.get("exe") else "")
    wand.abrir(wand.link_jogar(t))
    running[g["id"]] = time.time()
    threading.Thread(target=_track, args=(g["id"], None, pasta, 180, True), daemon=True).start()


# ---------------------------------------------------------------- janela de escolher arquivo/pasta

# a janela do próprio Windows, pelo PowerShell (a Estante instalada leva um Python portátil, que não tem o tkinter)
PICKER = r"""
Add-Type -AssemblyName System.Windows.Forms
$dono = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false; WindowState = 'Minimized'}
$p = ''
if ($env:E_TIPO -eq 'folder') {
  $d = New-Object System.Windows.Forms.FolderBrowserDialog
  $d.Description = 'Escolha a pasta'
  if ($d.ShowDialog($dono) -eq 'OK') { $p = $d.SelectedPath }
} else {
  $d = New-Object System.Windows.Forms.OpenFileDialog
  if ($env:E_TIPO -eq 'image') { $d.Title = 'Escolha a imagem da capa'; $d.Filter = 'Imagens|*.jpg;*.jpeg;*.png;*.webp|Todos|*.*' }
  else { $d.Title = 'Escolha o executável do jogo'; $d.Filter = 'Jogos|*.exe;*.lnk;*.bat;*.url|Todos|*.*' }
  if ($d.ShowDialog($dono) -eq 'OK') { $p = $d.FileName }
}
[IO.File]::WriteAllText($env:E_SAIDA, $p, [Text.Encoding]::UTF8)
"""


# ---------------------------------------------------------------- rotas

def _ver(v):
    """Normaliza versões: "v0.1", "Ver 0.1" e "0.1" contam como a mesma."""
    return _clean(re.sub(r"^\s*(version|ver\.?|v)\s*", "", v or "", flags=re.I))


SEMANA = 7 * 86400


def game_out(g):
    d = dict(g)
    # a lista inteira de vezes jogadas fica fora da lista da estante (ela é pedida a cada poucos segundos)
    sess = d.pop("sessoes", None) or []
    d["sessoes_n"] = len(sess)
    d["sessoes_recentes"] = sorted(sess)[-5:][::-1]
    d["semana"] = sum(s for t, s in sess if t >= time.time() - SEMANA)
    d["running"] = g["id"] in running
    d["cover_url"] = f"/covers/{g['cover']}" if g.get("cover") else None
    if g.get("loja"):
        d["missing"] = bool(g.get("pasta_jogo")) and not os.path.isdir(g["pasta_jogo"]) and not _unidade_ausente(g["pasta_jogo"])
    else:
        d["missing"] = not os.path.exists(g.get("exe") or "")
    d["fontes"] = [{"loja": f["loja"], "nome_loja": nome_loja(f["loja"]), "nome": f.get("nome") or g["name"]} for f in fontes(g)]
    d["lojas"] = [f["loja"] for f in fontes(g)]
    d["has_update"] = bool(g.get("latest_version") and g.get("version")
                           and _ver(g["latest_version"]) != _ver(g["version"]))
    d["tags"] = tags_do_jogo(g)
    d["colecao_pasta"] = g.get("colecao_pasta", "") if colecoes_pastas_ligado() else ""
    d["wand"] = wand.trainer(g)  # None quando o Wand não tem trainer para a versão que você tem
    return d


@app.get("/")
def index():
    return send_from_directory(BASE / "static", "index.html")


MINI = COVERS / "mini"   # cópias pequenas das capas, só para os cartões (a original fica para o painel)
MINI_LARGURA = 340       # o dobro do cartão, para continuar nítida em tela de alta resolução


@app.get("/covers/mini/<fname>")
def covers_mini(fname):
    """A capa reduzida, feita na primeira vez que é pedida. Algumas capas têm 700 KB e 600 pixels para aparecer
    num cartão de 170; com mais de mil séries, a tela carregava mais de 100 MB."""
    orig = COVERS / fname
    if "/" in fname or "\\" in fname or fname.startswith(".") or not orig.is_file():
        abort(404)
    mini = MINI / (fname + ".webp")
    if not mini.exists():
        try:
            from PIL import Image
            with Image.open(orig) as im:
                if im.width <= MINI_LARGURA * 1.1:
                    return send_from_directory(COVERS, fname, max_age=31536000)
                im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
                im.thumbnail((MINI_LARGURA, MINI_LARGURA * 4))
                MINI.mkdir(exist_ok=True)
                tmp = mini.with_name(f"{mini.name}.{threading.get_ident()}.tmp")
                im.save(tmp, "WEBP", quality=82)
                os.replace(tmp, mini)
        except Exception as e:  # imagem que o Pillow não entende: vai a original
            print(f"[capas] não consegui reduzir {fname}: {e}")
            return send_from_directory(COVERS, fname, max_age=31536000)
    return send_from_directory(MINI, mini.name, max_age=31536000, mimetype="image/webp")


def limpar_minis():
    """Tira as capas pequenas cuja original já foi apagada (capa trocada, jogo ou série que saiu)."""
    if MINI.is_dir():
        for p in MINI.glob("*.webp"):
            if not (COVERS / p.name[:-5]).exists():
                apagar_arquivo(p)


@app.get("/covers/<path:fname>")
def covers(fname):
    return send_from_directory(COVERS, fname, max_age=31536000)


def prune_missing():
    """Tira da estante os jogos cujo arquivo não existe mais.
    Se o disco inteiro não estiver conectado (ex.: HD externo), o jogo fica,
    para não sumir com a biblioteca só porque o HD está desligado."""
    removed = []
    if any(not g.get("loja") and g.get("exe") and not os.path.exists(g["exe"]) for g in get_lib()["games"]):
        try:
            sync_folders()  # talvez seja só uma versão nova numa pasta com outro nome
        except Exception as e:
            print("[pastas]", e)
    with lock:
        lib = get_lib()
        keep, mudou = [], False
        for g in lib["games"]:
            # arquivo de jogo juntado a outro que sumiu: só essa forma de abrir sai
            outras = [f for f in g.get("outras_fontes") or [] if f.get("loja") or not f.get("exe")
                      or os.path.exists(f["exe"]) or _unidade_ausente(f["exe"])]
            if len(outras) != len(g.get("outras_fontes") or []):
                g["outras_fontes"] = outras
                mudou = True
            exe = g.get("exe") or ""
            # jogos de loja saem pela leitura da loja (sync_lojas), não por aqui
            if g.get("loja") or not exe or os.path.exists(exe) or g["id"] in running or _unidade_ausente(exe):
                keep.append(g)
            elif g["outras_fontes"]:  # o arquivo sumiu, mas o jogo ainda abre por outra loja
                usar_fonte(g, g["outras_fontes"].pop(0))
                keep.append(g)
                mudou = True
            else:
                removed.append(g)
        if removed or mudou:
            lib["games"] = keep
            save_lib(lib)
    for g in removed:
        if g.get("cover"):
            apagar_arquivo(COVERS / g["cover"])
        print(f"[estante] {g['name']} saiu da estante: o arquivo não está mais em {g['exe']}")
    return [g["name"] for g in removed]


@app.get("/api/games")
def api_games():
    removed = prune_missing()
    with lock:
        ev = {k: v[:] for k, v in eventos.items()}
        for v in eventos.values():
            v.clear()
    cfg = get_cfg()
    # jogos de lojas desligadas nas Configurações não aparecem (mas continuam guardados)
    jogos = [g for g in get_lib()["games"] if any(not f["loja"] or loja_ligada(cfg, f["loja"]) for f in fontes(g))]
    return jsonify({"games": [game_out(g) for g in jogos], "removed": removed, "sairam": ev["sairam"],
                    "added": ev["added"], "relinked": ev["relinked"], "voltaram": ev["voltaram"],
                    "convertidos": ev["convertidos"], "repetidos": repetidos(jogos, cfg)})


LIMITE_OCIOSO = 120  # segundos sem a janela aberta antes de fechar
last_ping = time.time()


@app.post("/api/ping")
def api_ping():
    global last_ping
    last_ping = time.time()
    return jsonify({"ok": True})


@app.post("/api/bye")
def api_bye():
    # a janela foi fechada: fecha em alguns segundos, a menos que ela volte (ex.: recarregar a página)
    global last_ping
    last_ping = min(last_ping, time.time() - LIMITE_OCIOSO + 8)
    return ("", 204)


def ocioso():
    """True quando ninguém está com a janela aberta e nenhum jogo está rodando."""
    return not running and time.time() - last_ping > LIMITE_OCIOSO


@app.get("/api/running")
def api_running():
    return jsonify(sorted(running.keys()))


@app.post("/api/games")
def api_add():
    body = request.get_json(force=True) or {}
    items = body.get("games") or [body]
    added, pares = [], []
    with lock:
        lib = get_lib()
        known = {norm_path(g["exe"]) for g in lib["games"]}
        for it in items:
            exe = (it.get("exe") or "").strip().strip('"')
            if not exe or norm_path(exe) in known:
                continue
            g = new_game(it.get("name") or "", exe, it.get("args") or "")
            g["tags"] = [t for t in it.get("tags", []) if t]
            for k in ("description", "developer", "url"):
                if it.get(k):
                    g[k] = str(it[k])
            g["pasta_jogo"] = it.get("pasta") or ""
            lib["games"].append(g)
            pares.append((g["id"], it))
            known.add(norm_path(exe))
            added.append(g)
        save_lib(lib)
    with lock:  # ler, mudar e gravar de uma vez só: senão uma gravação da extensão no meio se perde
        cfg = get_cfg()
        mudou = False
        pasta = (body.get("watch_folder") or "").strip()
        if pasta and os.path.isdir(pasta) and norm_path(pasta) not in {norm_path(x) for x in cfg["pastas"]}:
            cfg["pastas"].append(os.path.normpath(pasta))
            mudou = True
        for g in added:  # se tinha sido tirado antes e voltou de propósito, para de ignorar
            k = chave_do_jogo(_pasta_do_jogo(g))
            if k in cfg["ignorados"]:
                cfg["ignorados"].remove(k)
                mudou = True
        if mudou:
            save_cfg(cfg)
        lib = get_lib()  # coleções que seguem as pastas, para os jogos que acabaram de entrar
        if _atualizar_colecoes_pasta(lib, [p for p in cfg["pastas"] if os.path.isdir(p)]):
            save_lib(lib)
    tem_chave = bool(cfg.get("sgdb_key"))

    def completar():
        for gid, it in pares:
            try:
                if it.get("image"):
                    download_cover(gid, it["image"])
                elif it.get("page_url"):
                    apply_meta(gid, page_meta(it["page_url"]), use_name=not (it.get("name") or "").strip())
                else:
                    completar_avulso(gid)
            except Exception as e:
                print(f"[dados] não consegui completar {gid}: {e}")
                if tem_chave:
                    auto_cover(gid)
            time.sleep(0.3)

    if pares:
        threading.Thread(target=completar, daemon=True).start()
    return jsonify({"added": len(added), "games": [game_out(g) for g in added]})


EDITABLE = {"name", "exe", "args", "workdir", "tags", "favorite", "hidden", "year", "description", "developer", "url",
            "version", "latest_version", "status", "engine", "genres", "pelo_wand", "situacao", "nota"}


@app.patch("/api/games/<gid>")
def api_edit(gid):
    body = request.get_json(force=True) or {}
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            abort(404)
        for k, v in body.items():
            if k in EDITABLE:
                if k == "tags":
                    v = sorted({limpar_colecao(t) for t in v if limpar_colecao(t)}, key=str.lower)
                    c = g.get("colecao_pasta")
                    if c and colecoes_pastas_ligado():  # a coleção da pasta não é guardada junto com as suas
                        mostrava = c in tags_do_jogo(g)
                        if c in v:
                            if c not in (g.get("tags") or []):
                                v.remove(c)
                            g["sem_colecao_pasta"] = False
                        elif mostrava:
                            g["sem_colecao_pasta"] = True  # você tirou o jogo da coleção da pasta
                if k == "situacao" and v not in SITUACOES + ("",):
                    continue
                if k == "nota":
                    v = str(v or "")[:5000]
                if k == "exe":
                    v = os.path.normpath(str(v).strip().strip('"'))
                if k == "description" and v != g.get(k):
                    g["dados_de"] = "voce"  # você editou: a busca automática não troca mais
                g[k] = v
        save_lib(lib)
        return jsonify(game_out(g))


@app.delete("/api/games/<gid>")
def api_delete(gid):
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            abort(404)
        lib["games"] = [x for x in lib["games"] if x["id"] != gid]
        save_lib(lib)
    with lock:
        cfg = get_cfg()
        for f in fontes(g):
            if f["loja"]:  # tirou de propósito: a loja não traz de volta sozinha
                if chave_fonte(f) not in cfg["ignorados_lojas"]:
                    cfg["ignorados_lojas"].append(chave_fonte(f))
            elif f["exe"] and _dentro_de_pasta_acompanhada(f.get("pasta_jogo") or str(Path(f["exe"]).parent), cfg["pastas"]):
                k = chave_do_jogo(f.get("pasta_jogo") or str(Path(f["exe"]).parent))
                if k and k not in cfg["ignorados"]:
                    cfg["ignorados"].append(k)
        save_cfg(cfg)
    if g.get("cover"):
        apagar_arquivo(COVERS / g["cover"])
    return jsonify({"ok": True})


@app.post("/api/games/<gid>/launch")
def api_launch(gid):
    g = find_game(get_lib(), gid)
    if not g:
        abort(404)
    if gid in running:
        return jsonify({"error": "Esse jogo já está aberto."}), 409
    body = request.get_json(silent=True) or {}
    i = body.get("fonte")
    fs = fontes(g)
    f = fs[i + 1] if isinstance(i, int) and 0 <= i + 1 < len(fs) else fs[0]
    # pelo Wand: quando pedido, ou no Jogar normal de um jogo marcado "Jogar sempre pelo Wand"
    t = wand.trainer(g) if body.get("wand") or (g.get("pelo_wand") and not (isinstance(i, int) and i >= 0)) else None
    if body.get("wand") and not t:
        return jsonify({"error": "O Wand não tem trainer para este jogo."}), 400
    try:
        if t:
            launch_wand(g, t)
            return jsonify({"ok": True, "wand": True})
        launch_game(g, f)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        running.pop(gid, None)
        if t:
            return jsonify({"error": f"Não consegui abrir o Wand. Confira se ele está instalado e funcionando. ({e})"}), 400
        if f.get("loja"):
            return jsonify({"error": f"Não consegui abrir {pela(f['loja'])}. Confira se a loja está instalada e funcionando. ({e})"}), 400
        return jsonify({"error": f"Não consegui abrir o jogo. Confira o executável em Editar. ({e})"}), 400
    return jsonify({"ok": True})


@app.post("/api/games/<gid>/open-folder")
def api_open_folder(gid):
    g = find_game(get_lib(), gid)
    if not g:
        abort(404)
    folder = g.get("pasta_jogo") if g.get("loja") else str(Path(g.get("exe") or "").parent)
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "A pasta do jogo não existe mais."}), 400
    if WINDOWS:
        os.startfile(folder)
    return jsonify({"ok": True})


@app.post("/api/games/<gid>/nao-e-este")
def api_nao_e_este(gid):
    """A Steam trouxe os dados de outro jogo com o mesmo nome (comum em jogos pequenos): desfaz e não tenta mais."""
    capa = None
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            abort(404)
        if g.get("dados_de") == "steam":
            for k in ("description", "developer"):
                g[k] = ""
            g["year"], g["genres"] = None, []
            if "store.steampowered.com" in (g.get("url") or ""):
                g["url"] = ""
        if g.get("capa_de") == "steam" and g.get("cover"):
            capa, g["cover"] = g["cover"], None
        g["dados_de"], g["capa_de"], g["nunca_steam"] = "voce", "", True
        save_lib(lib)
    if capa:
        apagar_arquivo(COVERS / capa)
    if get_cfg().get("sgdb_key"):
        threading.Thread(target=auto_cover, args=(gid,), daemon=True).start()
    return jsonify(game_out(find_game(get_lib(), gid)))


@app.post("/api/games/<gid>/reset-playtime")
def api_reset_time(gid):
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            abort(404)
        g["playtime"] = 0
        g["sessoes"] = []
        save_lib(lib)
        return jsonify(game_out(g))


@app.post("/api/scan")
def api_scan():
    folder = (request.get_json(force=True) or {}).get("folder", "").strip().strip('"')
    try:
        return jsonify(scan_folder(folder))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/pick")
def api_pick():
    kind = (request.get_json(force=True) or {}).get("kind", "file")
    out = DATA / f"pick_{uuid.uuid4().hex[:8]}.txt"
    try:
        flags = 0x08000000 if WINDOWS else 0  # CREATE_NO_WINDOW
        env = dict(os.environ, E_TIPO=str(kind), E_SAIDA=str(out))
        subprocess.run(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", PICKER],
                       timeout=600, creationflags=flags, env=env)
        p = out.read_text("utf-8-sig").strip() if out.exists() else ""
        return jsonify({"path": os.path.normpath(p) if p else ""})
    except Exception as e:
        return jsonify({"error": f"Não consegui abrir a janela de escolha: {e}"}), 400
    finally:
        apagar_arquivo(out)


@app.post("/api/page-preview")
def api_page_preview():
    try:
        return jsonify(page_meta((request.get_json(force=True) or {}).get("url")))
    except Exception as e:
        return jsonify({"error": f"Não consegui ler essa página: {e}"}), 400


@app.get("/api/img")
def api_img():
    """Mostra imagens de sites que bloqueiam abrir a imagem fora da página deles."""
    u = request.args.get("u", "")
    if not re.match(r"https?://", u, re.I):
        abort(400)
    try:
        req = urllib.request.Request(u, headers=_img_headers(request.args.get("r") or None))
        with urllib.request.urlopen(req, timeout=20) as r:
            ctype = r.headers.get_content_type() or ""
            if not ctype.startswith("image/"):
                abort(415)
            raw = r.read(15_000_000)
    except Exception:
        abort(404)
    return app.response_class(raw, mimetype=ctype, headers={"Cache-Control": "max-age=3600"})


@app.post("/api/games/<gid>/from-page")
def api_from_page(gid):
    b = request.get_json(force=True) or {}
    try:
        meta = b.get("meta") or page_meta(b.get("url"))
        g = apply_meta(gid, meta, b.get("use_name", True), b.get("use_cover", True), b.get("use_info", True))
    except Exception as e:
        return jsonify({"error": f"Não consegui usar os dados dessa página: {e}"}), 400
    if not g:
        abort(404)
    return jsonify(game_out(g))


def check_update(gid):
    g = find_game(get_lib(), gid)
    if not g or not g.get("url"):
        return None
    meta = page_meta(g["url"])
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            return None
        if meta.get("version"):
            if not g.get("version"):
                g["version"] = meta["version"]
            g["latest_version"] = meta["version"]
        for k in ("status", "engine"):
            if meta.get(k):
                g[k] = meta[k]
        g["update_checked"] = time.time()
        save_lib(lib)
        return g


checando = {"ativo": False, "feitos": 0, "total": 0}


@app.post("/api/games/<gid>/check-update")
def api_check_update(gid):
    try:
        g = check_update(gid)
    except Exception as e:
        return jsonify({"error": f"Não consegui verificar: {e}"}), 400
    if not g:
        return jsonify({"error": "Esse jogo não tem link da página salvo."}), 400
    return jsonify(game_out(g))


@app.post("/api/check-updates")
def api_check_updates():
    if checando["ativo"]:
        return jsonify(checando)
    ids = [g["id"] for g in get_lib()["games"] if g.get("url") and (g.get("version") or g.get("latest_version"))]
    checando.update(ativo=True, feitos=0, total=len(ids))

    def worker():
        for gid in ids:
            try:
                check_update(gid)
            except Exception as e:
                print(f"[atualização] {gid}: {e}")
            checando["feitos"] += 1
            time.sleep(1.5)  # devagar, pra não sobrecarregar os sites
        checando["ativo"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify(checando)


@app.get("/api/check-updates")
def api_check_updates_status():
    return jsonify(checando)


@app.get("/api/config")
def api_cfg_get():
    cfg = get_cfg()
    k = cfg.get("sgdb_key", "")
    return jsonify({"has_key": bool(k), "key_hint": ("•••• " + k[-4:]) if k else "",
                    "pastas": [{"path": p, "ok": os.path.isdir(p)} for p in cfg["pastas"]],
                    "ignorados": len(cfg["ignorados"]) + len(cfg["ignorados_lojas"]), "data_dir": str(DATA),
                    "extensao_dir": str(BASE / "extensao"), "colecoes_pastas": bool(cfg.get("colecoes_pastas")),
                    "anilist_usuario": (cfg.get("leitura") or {}).get("anilist_usuario", ""),
                    "versao": VERSAO, "preferencias": cfg.get("preferencias") or {},
                    "boas_vindas": cfg.get("boas_vindas") == "mostrar"})


PREF_OK = re.compile(r"^[A-Za-z_]{1,40}$")


@app.post("/api/preferencias")
def api_preferencias():
    """Escolhas da tela (onde abrir os capítulos, modo do leitor...). Ficam no config.json, e não só na janela,
    para entrarem na cópia de segurança e valerem em qualquer janela."""
    body = request.get_json(force=True) or {}
    with lock:
        cfg = get_cfg()
        pref = cfg.setdefault("preferencias", {})
        for k, v in body.items():
            if PREF_OK.match(k) and (v is None or isinstance(v, (str, bool, int, float))) and len(str(v)) <= 200:
                if v is None:
                    pref.pop(k, None)
                elif k in pref or len(pref) < 200:
                    pref[k] = v
        save_cfg(cfg)
    return jsonify({"ok": True, "preferencias": pref})


@app.post("/api/pastas/remover")
def api_pasta_remover():
    p = (request.get_json(force=True) or {}).get("pasta", "")
    with lock:
        cfg = get_cfg()
        cfg["pastas"] = [x for x in cfg["pastas"] if norm_path(x) != norm_path(p)]
        save_cfg(cfg)
    return jsonify({"ok": True})


@app.post("/api/pastas/acrescentar")
def api_pasta_acrescentar():
    """Passa a acompanhar mais uma pasta de jogos (nas Configurações). Já procura os jogos dela."""
    p = str((request.get_json(force=True) or {}).get("pasta", "")).strip().strip('"')
    if not p or not os.path.isdir(p):
        return jsonify({"error": "Essa pasta não existe. Confira o caminho."}), 400
    p = os.path.normpath(p)
    with lock:
        cfg = get_cfg()
        for x in cfg["pastas"]:
            if norm_path(x) == norm_path(p):
                return jsonify({"error": "Essa pasta já é acompanhada."}), 400
            if norm_path(p).startswith(norm_path(x) + os.sep):
                return jsonify({"error": f"Essa pasta já fica dentro de uma pasta acompanhada ({x})."}), 400
        cfg["pastas"].append(p)
        save_cfg(cfg)

    def procurar():
        try:
            sync_folders()
        except Exception as e:
            print("[pastas]", e)
    threading.Thread(target=procurar, daemon=True).start()
    return jsonify({"ok": True, "pastas": cfg["pastas"]})


@app.post("/api/pastas/esquecer-ignorados")
def api_esquecer_ignorados():
    with lock:
        cfg = get_cfg()
        cfg["ignorados"] = []
        cfg["ignorados_lojas"] = []
        save_cfg(cfg)
    return jsonify({"ok": True})


@app.post("/api/sync")
def api_sync():
    try:
        sync_lojas()
        sync_folders()
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.post("/api/abrir-leitor")
def api_abrir_leitor():
    """Abre o capítulo na janela de leitura da Estante: uma janela só do site, sem barra de endereço.
    É o mesmo navegador de sempre, então a extensão continua marcando o que você lê."""
    url = ((request.get_json(force=True) or {}).get("url") or "").strip()
    if not re.match(r"https?://", url, re.I):
        return jsonify({"error": "Link inválido."}), 400
    nav = navegador_app((get_cfg().get("leitura") or {}).get("navegador", "")) if WINDOWS else ""
    try:
        if nav:
            subprocess.Popen([nav, f"--app={url}", "--window-size=1100,1000"])
        else:
            webbrowser.open(url)
    except Exception as e:
        return jsonify({"error": f"Não consegui abrir a janela de leitura: {e}"}), 400
    return jsonify({"ok": True})


@app.post("/api/abrir-extensao")
def api_abrir_extensao():
    if WINDOWS:
        os.startfile(str(BASE / "extensao"))
    return jsonify({"ok": True})


@app.post("/api/abrir-dados")
def api_abrir_dados():
    if WINDOWS:
        os.startfile(str(DATA))
    return jsonify({"ok": True})


@app.post("/api/config")
def api_cfg_set():
    body = request.get_json(force=True) or {}
    with lock:
        cfg = get_cfg()
        if "sgdb_key" in body:
            cfg["sgdb_key"] = str(body["sgdb_key"]).strip()
        if "colecoes_pastas" in body:
            cfg["colecoes_pastas"] = bool(body["colecoes_pastas"])
            _col_pastas["quando"] = 0.0
            lib = get_lib()
            if _atualizar_colecoes_pasta(lib, [p for p in cfg["pastas"] if os.path.isdir(p)]):
                save_lib(lib)
        save_cfg(cfg)
    if "sgdb_key" in body and cfg.get("sgdb_key"):
        try:
            sgdb("/search/autocomplete/doom")
        except Exception as e:
            return jsonify({"ok": False, "error": f"A chave não funcionou: {e}"}), 400
    return jsonify({"ok": True})


@app.post("/api/covers/fetch-missing")
def api_fetch_missing():
    """Busca capa e dados de todos os jogos que ainda não têm (Steam pelo nome e, com chave, SteamGridDB)."""
    jogos = [g for g in get_lib()["games"] if not g.get("cover") or not g.get("description")
             or (g.get("loja") and g.get("dados_de") in lojas.LOJAS and g.get("dados_de") != "steam")]

    def worker():
        for g in jogos:
            try:
                if g.get("loja"):
                    f = fonte_principal(g)
                    e = _entrada_de_fonte(f)
                    e["nome"] = g["name"]
                    _completar_loja(g["id"], e)
                else:
                    completar_avulso(g["id"])
            except Exception as ex:
                print(f"[dados] {g['name']}: {ex}")
            time.sleep(1.2)
    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"queued": len(jogos)})


@app.get("/api/cover-search")
def api_cover_search():
    try:
        return jsonify(sgdb_search(request.args.get("q", "")))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/cover-options/<int:sgdb_id>")
def api_cover_options(sgdb_id):
    try:
        return jsonify(sgdb_grids(sgdb_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/games/<gid>/cover")
def api_set_cover(gid):
    if "file" in request.files:
        f = request.files["file"]
        ext = os.path.splitext(f.filename or "")[1].lower() or ".jpg"
        if ext not in IMG_EXT:
            return jsonify({"error": "Use uma imagem JPG, PNG, WEBP ou GIF."}), 400
        fname = store_cover_bytes(gid, f.read(), ext)
    else:
        body = request.get_json(force=True) or {}
        try:
            if body.get("path"):
                p = Path(body["path"])
                fname = store_cover_bytes(gid, p.read_bytes(), p.suffix.lower() or ".jpg")
            else:
                fname = download_cover(gid, body["url"])
        except Exception as e:
            return jsonify({"error": f"Não deu pra salvar a capa: {e}"}), 400
    if not fname:
        abort(404)
    return jsonify(game_out(find_game(get_lib(), gid)))


# ---------------------------------------------------------------- rotas das lojas e de juntar jogos

def _lojas_out():
    cfg = get_cfg()
    jogos = get_lib()["games"]
    out = []
    for loja in lojas.ORDEM:
        st = lojas_status.get(loja, {})
        out.append({
            "loja": loja,
            "nome": lojas.LOJAS[loja],
            "ligada": loja_ligada(cfg, loja),
            "encontrada": st.get("encontrada"),
            "instalados": st.get("instalados", 0),
            "na_estante": sum(1 for g in jogos if loja in [f["loja"] for f in fontes(g)]),
            "erro": st.get("erro", ""),
        })
    return out


@app.get("/api/lojas")
def api_lojas():
    return jsonify(_lojas_out())


@app.post("/api/lojas")
def api_lojas_set():
    b = request.get_json(force=True) or {}
    loja = b.get("loja")
    if loja not in lojas.LOJAS:
        abort(400)
    with lock:
        cfg = get_cfg()
        cfg["lojas"][loja] = bool(b.get("ligada"))
        save_cfg(cfg)
    if cfg["lojas"][loja]:
        sync_lojas(so=loja)
    else:
        lojas_status[loja] = {"ligada": False}
    return jsonify(_lojas_out())


@app.post("/api/lojas/importar")
def api_lojas_importar():
    sync_lojas()
    return jsonify(_lojas_out())


# ---------------------------------------------------------------- Wand (trainers)

def _wand_out():
    cfg = get_cfg()
    p = wand.pasta()
    jogos = [g for g in get_lib()["games"] if not g.get("hidden")]
    return {"encontrado": bool(p), "pasta": p, "versao": wand.versao() if p else "", "ligado": wand.ligado(cfg),
            "lista": wand.info(), "baixando": wand.estado["baixando"], "erro": wand.estado["erro"],
            "com_trainer": sum(1 for g in jogos if wand.trainer(g))}


@app.get("/api/wand")
def api_wand():
    return jsonify(_wand_out())


@app.post("/api/wand")
def api_wand_set():
    b = request.get_json(force=True) or {}
    with lock:
        cfg = get_cfg()
        cfg.setdefault("wand", {})["ligado"] = bool(b.get("ligado"))
        save_cfg(cfg)
    wand.esquecer_ativo()
    if cfg["wand"]["ligado"] and wand.pasta():
        threading.Thread(target=wand.vigiar_passo, args=(get_lib()["games"],), daemon=True).start()
    return jsonify(_wand_out())


@app.post("/api/wand/atualizar")
def api_wand_atualizar():
    """Baixa agora a lista de jogos do Wand e olha de novo as pastas dos jogos."""
    if not wand.baixar(forcar=True):
        return jsonify({"error": wand.estado["erro"]}), 400
    wand.preencher(get_lib()["games"])
    return jsonify(_wand_out())


@app.post("/api/games/<gid>/wand-pagina")
def api_wand_pagina(gid):
    g = find_game(get_lib(), gid)
    if not g:
        abort(404)
    t = wand.trainer(g)
    if not t:
        return jsonify({"error": "O Wand não tem trainer para este jogo."}), 400
    try:
        wand.abrir(wand.link_pagina(t))
    except Exception as e:
        return jsonify({"error": f"Não consegui abrir o Wand. ({e})"}), 400
    return jsonify({"ok": True})


def juntar(ids, principal):
    with lock:
        lib = get_lib()
        gs = [g for g in (find_game(lib, i) for i in ids) if g]
        if len(gs) < 2:
            raise ValueError("Escolha pelo menos dois jogos para juntar.")
        if any(g["id"] in running for g in gs):
            raise ValueError("Feche o jogo antes de juntar.")
        p = next((g for g in gs if g["id"] == principal), gs[0])
        apagar = []
        for o in gs:
            if o is p:
                continue
            p["outras_fontes"] = list(p.get("outras_fontes") or []) + fontes(o)
            p["playtime"] = int((p.get("playtime") or 0) + (o.get("playtime") or 0))
            p["sessoes"] = sorted(list(p.get("sessoes") or []) + list(o.get("sessoes") or []))
            p["last_played"] = max([x for x in (p.get("last_played"), o.get("last_played")) if x] or [None])
            p["added"] = min(x for x in (p.get("added"), o.get("added"), time.time()) if x)
            p["tags"] = sorted(set(p.get("tags") or []) | set(o.get("tags") or []), key=str.lower)
            p["favorite"] = bool(p.get("favorite") or o.get("favorite"))
            for k in ("description", "developer", "url", "year", "version", "latest_version", "status", "engine", "genres", "situacao"):
                if not p.get(k) and o.get(k):
                    p[k] = o[k]
            if o.get("nota") and o["nota"] not in (p.get("nota") or ""):
                p["nota"] = ((p.get("nota") or "") + "\n\n" + o["nota"]).strip()
            if o.get("cover"):
                if p.get("cover"):
                    apagar.append(o["cover"])
                else:
                    p["cover"] = o["cover"]
            lib["games"].remove(o)
        # a mesma forma de abrir não precisa aparecer duas vezes
        vistas, unicas = {chave_fonte(fonte_principal(p)) if p.get("loja") else norm_path(p.get("exe"))}, []
        for f in p["outras_fontes"]:
            k = chave_fonte(f) if f.get("loja") else norm_path(f.get("exe"))
            if k not in vistas:
                vistas.add(k)
                unicas.append(f)
        p["outras_fontes"] = unicas
        save_lib(lib)
    for c in apagar:
        apagar_arquivo(COVERS / c)
    return p


@app.post("/api/juntar")
def api_juntar():
    b = request.get_json(force=True) or {}
    try:
        g = juntar(b.get("ids") or [], b.get("principal"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(game_out(g))


@app.post("/api/nao-juntar")
def api_nao_juntar():
    ids = sorted((request.get_json(force=True) or {}).get("ids") or [])
    with lock:
        cfg = get_cfg()
        if ids and "|".join(ids) not in cfg["nao_juntar"]:
            cfg["nao_juntar"].append("|".join(ids))
            save_cfg(cfg)
    return jsonify({"ok": True})


@app.post("/api/games/<gid>/fonte-principal")
def api_fonte_principal(gid):
    i = (request.get_json(force=True) or {}).get("indice")
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            abort(404)
        if not isinstance(i, int) or not 0 <= i < len(g["outras_fontes"]):
            abort(400)
        atual = fonte_principal(g)
        atual["nome"] = g["name"] if atual["loja"] else "Arquivo do jogo"
        nova = g["outras_fontes"][i]
        g["outras_fontes"][i] = atual
        usar_fonte(g, nova)
        save_lib(lib)
        return jsonify(game_out(g))


@app.post("/api/games/<gid>/separar")
def api_separar(gid):
    i = (request.get_json(force=True) or {}).get("indice")
    with lock:
        lib = get_lib()
        g = find_game(lib, gid)
        if not g:
            abort(404)
        if not isinstance(i, int) or not 0 <= i < len(g["outras_fontes"]):
            abort(400)
        f = g["outras_fontes"].pop(i)
        nome = f.get("nome") if f.get("nome") and f.get("nome") != "Arquivo do jogo" else g["name"]
        novo = new_game(nome, "")
        usar_fonte(novo, f)
        lib["games"].append(novo)
        save_lib(lib)
    with lock:
        cfg = get_cfg()
        cfg["nao_juntar"].append("|".join(sorted([gid, novo["id"]])))
        save_cfg(cfg)
    e = _entrada_de_fonte(f) if f.get("loja") else None
    threading.Thread(target=lambda: _completar_loja(novo["id"], e) if e else (get_cfg().get("sgdb_key") and auto_cover(novo["id"])),
                     daemon=True).start()
    return jsonify({"ok": True, "id": novo["id"]})


leitura.iniciar(app, {"DATA": DATA, "COVERS": COVERS, "lock": lock, "get_cfg": get_cfg, "navegador_app": navegador_app,
                      "save_cfg": save_cfg, "img_headers": _img_headers})
wand.iniciar({"DATA": DATA, "get_cfg": get_cfg, "abrir_link": lambda link: _abrir_link(link)})
# ---------------------------------------------------------------- atalhos do ícone perto do relógio

def atalhos_bandeja(n=3):
    """Os últimos jogos jogados e as últimas séries lidas, para "Jogar de novo" e "Continuar lendo"."""
    jogos = sorted((g for g in get_lib()["games"] if g.get("last_played") and not g.get("hidden")),
                   key=lambda g: -g["last_played"])[:n]
    d = leitura._load()
    por_id = {s["id"]: s for s in d["series"]}
    vistos, series = set(), []
    for x in reversed(d["leituras"]):
        sid = x.get("s")
        if sid not in por_id or sid in vistos:
            continue
        vistos.add(sid)
        if len(series) == n or len(vistos) > 40:
            break
        o = leitura.serie_out(por_id[sid])
        p = o.get("proximo_cap") or {}
        if p.get("existe") is False:
            continue  # em dia: não tem o que continuar
        rotulo = (("Continuar " if p.get("continuar") else "") + "cap. " + str(p["num"])) if p.get("num") else ""
        series.append({"id": sid, "nome": o["name"], "rotulo": rotulo, "url": p.get("url") or o.get("url_lido") or o.get("url_serie") or "",
                       "local": p.get("site") == "local"})
    return {"jogos": [{"id": g["id"], "nome": g["name"]} for g in jogos], "series": series}


def abrir_atalho(tipo, ident):
    """Chamado pelo menu do ícone. Devolve False quando precisa abrir a janela da Estante no lugar."""
    c = app.test_client()
    if tipo == "jogo":
        return c.post(f"/api/games/{ident}/launch").status_code == 200
    s = next((x for x in atalhos_bandeja(10)["series"] if x["id"] == ident), None)
    if not s or not s["url"] or s["local"]:
        return False  # quadrinho do PC ou série sem site conhecido: abre na Estante
    return c.post("/api/abrir-leitor", json={"url": s["url"]}).status_code == 200


def _marcar_boas_vindas():
    """A tela de boas-vindas aparece só numa instalação nova. Quem já tem dados (jogos, séries ou pastas) não vê.
    Decidido uma vez só, ao abrir, antes das lojas começarem a trazer jogos."""
    with lock:
        cfg = get_cfg()
        if "boas_vindas" in cfg:
            return
        tem_dados = bool(get_lib()["games"] or cfg["pastas"] or (_load(DATA / "leitura.json", {}) or {}).get("series"))
        cfg["boas_vindas"] = "feita" if tem_dados or os.environ.get("ESTANTE_SEM_BOAS_VINDAS") else "mostrar"
        save_cfg(cfg)


def _sem_acento(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")


@app.get("/api/busca")
def api_busca():
    """Busca única: a estante aberta já filtra na tela; aqui vêm os achados da outra (em = "jogos" ou "leitura")."""
    q = _sem_acento(request.args.get("q", "")).strip()
    if len(q) < 2:
        return jsonify({"itens": [], "total": 0})
    if request.args.get("em") == "leitura":
        series = (_load(DATA / "leitura.json", {}) or {}).get("series") or []
        achados = [s for s in series if any(q in _sem_acento(n) for n in [s.get("name")] + list(s.get("titulos_alt") or []))]
        itens = [{"id": s["id"], "nome": s.get("name") or "", "capa": f"/covers/{s['cover']}" if s.get("cover") else None,
                  "sub": s.get("tipo") or "Série"} for s in achados]
    else:
        achados = [g for g in get_lib()["games"] if not g.get("hidden") and q in _sem_acento(g.get("name"))]
        itens = [{"id": g["id"], "nome": g["name"], "capa": f"/covers/{g['cover']}" if g.get("cover") else None,
                  "sub": nome_loja(g.get("loja")) if g.get("loja") else "Jogo"} for g in achados]
    itens.sort(key=lambda x: (not _sem_acento(x["nome"]).startswith(q), x["nome"].lower()))
    return jsonify({"itens": itens[:8], "total": len(itens)})


@app.get("/api/estatisticas")
def api_estatisticas():
    if request.args.get("em") == "leitura":
        return jsonify(estatisticas.leitura(_load(DATA / "leitura.json", {}) or {}))
    return jsonify(estatisticas.jogos(get_lib()["games"]))


@app.post("/api/boas-vindas")
def api_boas_vindas():
    with lock:
        cfg = get_cfg()
        cfg["boas_vindas"] = "feita"
        save_cfg(cfg)
    return jsonify({"ok": True})


_marcar_boas_vindas()
atualizar.iniciar(app, {"DATA": DATA, "lock": lock, "get_cfg": get_cfg, "save_cfg": save_cfg,
                        "jogos_abertos": lambda: bool(running), "sair": lambda: [f() for f in AO_SAIR] or os._exit(0)})
copias.iniciar(app, {"DATA": DATA, "lock": lock, "abrir_pasta": lambda p: os.startfile(p) if WINDOWS else None,
                     "depois_de_restaurar": [leitura._esquecer_sites]})
tocando.iniciar(app, {"DATA": DATA, "lock": lock, "get_cfg": get_cfg, "save_cfg": save_cfg, "ler_json": ler_json,
                      "gravar_json": gravar_json, "navegador_app": lambda: navegador_app() if WINDOWS else ""})


if __name__ == "__main__":
    # modo de teste (com terminal). O jeito normal de abrir é pelo atalho, que usa o Estante.pyw.
    url = f"http://127.0.0.1:{PORTA}"
    print("\n  Estante rodando em", url)
    print("  Deixe esta janela aberta enquanto usa. Para fechar, é só fechar esta janela.\n")
    vigiar_pastas()
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORTA, debug=False, threaded=True)
