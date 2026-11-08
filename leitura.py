"""
Estante de Leitura: um marcador inteligente para mangás, manhwas e HQs lidos nos sites.

A Estante NÃO baixa nem mostra as páginas dos capítulos. A leitura continua nos sites; aqui ficam
a capa, os dados da série, o capítulo em que você parou e o aviso de capítulo novo.

De onde vêm as informações:
  - a extensão do navegador avisa qual capítulo você abriu (série, número, link e capa);
  - capa, descrição, gêneros e status vêm do AniList (acesso público, sem conta);
  - capítulos novos vêm do MangaUpdates (acesso público, sem conta) e das páginas de série
    que você abre nos sites (a extensão lê a lista de capítulos que já está na tela).
"""
import difflib
import hashlib
import html as htmlmod
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from flask import Blueprint, Response, abort, jsonify, request

from caminhos import apagar_arquivo, gravar_json, ler_json

bp = Blueprint("leitura", __name__)
CTX = {}  # preenchido por iniciar(): pasta de dados, capas, lock e configurações da Estante
VERSAO = 1

# Regras de cada site. Os padrões são escritos no formato do navegador ((?<nome>...)) e convertidos
# aqui para o Python. A extensão usa exatamente as mesmas regras, que ela pega da Estante.
SITES_PADRAO = [
    {"chave": "comix", "nome": "Comix", "dominio": "comix.to", "antigos": ["comix.ws"],
     "capitulo": r"^/title/(?<slug>[^/]+)/\d+-chapter-(?<num>\d+(?:\.\d+)?)",
     "serie": r"^/title/(?<slug>[^/]+?)/?$",
     "modelo_serie": "/title/{slug}", "modelo_capitulo": "",
     # a sua lista no site (Comix: Perfil > Followed Titles). A extensão lê os cartões da tela e passa as páginas
     # sozinha quando a página é aberta pela Estante (endereço terminado em #estante-ligar).
     "lista": {"endereco": "/user?tab=titles", "caminho": r"^/user/?$", "parametro": "tab=titles",
               "cartao": "a.card[href^='/title/']", "titulo": ".card__title", "capitulos": ".card__ch",
               "proxima": "button[aria-label='Next page']", "pagina_ativa": ".npager__num.is-active"},
     # página de últimas atualizações que a extensão olha a cada 15 minutos. No Comix é a página inicial: logada,
     # ela traz "New Chapters from Followed Comics" com o código de cada série (hid, o começo do endereço dela)
     # e o último capítulo. Não traz o link do capítulo, então a extensão abre a página da série que teve capítulo novo.
     "atualizacoes": {"endereco": "/", "codigo": "hid", "numero": "latestChapter"},
     # a busca do site, para ligar as séries "Sem site": a caixa de busca do topo mostra os resultados numa lista
     # embaixo dela enquanto você digita. A extensão digita o nome de cada série, devagar, e manda os resultados.
     # O endereço da série começa por um código (19wgn-memorize): o resto é o nome dela.
     "busca": {"campo": "form.search__form input", "resultado": ".search-pop a.search-pop__item-link",
               "codigo_no_endereco": True, "espera": 8},
     # o leitor do Comix não rola a página: cada página do capítulo é uma caixa .rpage-page (as que ainda não
     # carregaram mostram "4 / 125"). A página onde você está é a caixa que aparece na tela.
     "paginas": ".rpage-page"},
    {"chave": "asura", "nome": "Asura Scans", "dominio": "asurascans.com", "antigos": ["asuracomic.net"],
     "capitulo": r"^/(?:comics|series)/(?<slug>[^/]+?)(?:-(?=[a-f]*\d)[0-9a-f]{8})?/chapter/(?<num>\d+(?:\.\d+)?)",
     "serie": r"^/(?:comics|series)/(?<slug>[^/]+?)(?:-(?=[a-f]*\d)[0-9a-f]{8})?/?$",
     "modelo_serie": "/comics/{slug}", "modelo_capitulo": "/comics/{slug}/chapter/{n}",
     # a página inicial lista os capítulos recentes; cada link de capítulo tem o nome da série
     "atualizacoes": {"endereco": "/"}},
    {"chave": "demonic", "nome": "Demonic Scans", "dominio": "demonicscans.org", "antigos": [],
     "capitulo": r"^/title/(?<slug>[^/]+)/chapter/(?<num>\d+(?:\.\d+)?)",
     # os botões Anterior/Próximo e a lista de capítulos usam outro formato, que leva para o de cima
     "capitulo_extra": r"^/chaptered\.php\?(?=.*\bmanga=(?<slug>\d+))(?=.*\bchapter=(?<num>\d+(?:\.\d+)?))",
     "serie": r"^/manga/(?<slug>[^/?]+?)/?$",
     "modelo_serie": "/manga/{slug}", "modelo_capitulo": "/title/{slug}/chapter/{n}/1",
     # um bloco por série: o link da série e, logo abaixo, os capítulos novos dela (40 séries por página)
     "atualizacoes": {"endereco": "/lastupdates.php"}},
]
# Numa instalação nova, a lista de sites começa vazia: cada pessoa escolhe os seus nas Configurações,
# onde os sites acima aparecem para acrescentar com um clique. (Os testes põem os três aqui.)
SITES_INICIAIS = ()
# Para sites que você acrescentar: o número do capítulo vem de "chapter-12", "chapter/12", "capitulo-12"...
GENERICO_CAP = r"(?:chapter|chapitre|capitulo|cap[ií]tulo|episode|ch)[-_/ ]?(?<num>\d+(?:\.\d+)?)"

STATUS_ANILIST = {"RELEASING": "Em andamento", "FINISHED": "Completa", "HIATUS": "Em hiato",
                  "CANCELLED": "Cancelada", "NOT_YET_RELEASED": "Ainda não lançada"}
TIPO_PAIS = {"KR": "Manhwa", "CN": "Manhua", "TW": "Manhua", "JP": "Mangá"}
LISTA_ARQUIVO = {"reading": "Lendo", "plan to read": "Quero ler", "completed": "Terminado", "dropped": "Larguei",
                 "on-hold": "Pausado", "on hold": "Pausado", "rereading": "Relendo"}
LISTA_ANILIST = {"CURRENT": "Lendo", "PLANNING": "Quero ler", "COMPLETED": "Terminado", "DROPPED": "Larguei",
                 "PAUSED": "Pausado", "REPEATING": "Relendo"}


# ---------------------------------------------------------------- armazenamento

def _arq():
    return CTX["DATA"] / "leitura.json"


def _load():
    d = ler_json(_arq(), {})
    if not isinstance(d, dict):
        d = {}
    d.setdefault("versao", VERSAO)
    d.setdefault("series", [])
    d.setdefault("novidades", [])  # capítulos novos encontrados: {s, c, t}
    d.setdefault("leituras", [])   # cada capítulo aberto: {s, c, t} (para histórico e estatísticas)
    for s in d["series"]:
        for k, v in nova_serie("").items():
            if k not in s:
                s[k] = v if not isinstance(v, (list, dict)) else type(v)()
        if not s["por_site"] and (s.get("site") or s.get("outros")):
            _migrar_sites(s)
        if s.get("dados_de") == "mangaupdates" and not s.get("desc_limpa"):  # descrições salvas antes da limpeza
            s["description"], s["desc_limpa"] = limpar_descricao(s.get("description") or ""), True
    return d


def _migrar_sites(s):
    """Versão anterior: um site principal (com a lista de capítulos) e 'outros' sem lista. Passa tudo para por_site."""
    if s.get("site"):
        caps = dict(s.get("capitulos") or {})
        nums = [num(k) for k in caps if num(k) is not None]
        s["por_site"][s["site"]] = {"slug": s.get("slug") or "", "serie": s.get("caminho_serie") or "", "caps": caps,
                                    "ultimo": max(nums) if nums else None, "visto": None}
        s["site_lido"] = s.get("site_lido") or s["site"]
    for o in s.get("outros") or []:
        if o.get("site"):
            s["por_site"].setdefault(o["site"], {"slug": o.get("slug") or "", "serie": "", "caps": {}, "ultimo": None, "visto": None})
    s["capitulos"] = {}


def _save(d):
    gravar_json(_arq(), d, indent=1)


def nova_serie(nome):
    return {
        "id": uuid.uuid4().hex[:12], "name": (nome or "").strip(), "titulos_alt": [],
        "cover": None, "capa_manual": False, "description": "", "genres": [], "status": "", "tipo": "",
        "autor": "", "year": None,
        "site": "", "slug": "", "outros": [],      # outros: [{site, slug}] onde você também leu essa série
        "capitulos": {},                           # "12" -> caminho do capítulo no site
        "ultimo_lido": None, "caminho_lido": "", "proximo": "", "ultima_leitura": None,
        "ultimo_disponivel": None, "novo_desde": None, "verificado_em": None,
        "anilist_id": None, "anilist_tentado": False, "mu_id": None, "mu_tentado": False,
        "por_site": {},      # site -> {slug, serie (link da série), caps {capítulo: link}, ultimo, visto}
        "primeiro": {},      # capítulo -> {site, t}: em que site cada capítulo novo apareceu primeiro
        "site_lido": "", "dados_de": "", "capa_de": "", "url_mu": "",
        "lendo": None,       # capítulo aberto e ainda não terminado: {n, caminho, site, pct, pagina, total, t}
        "lista_anilist": "", "lista_vista": False, "url_anilist": "", "tags": [], "favorite": False, "hidden": False, "added": time.time(),
    }


def cfg_leitura():
    cfg = CTX["get_cfg"]()
    lc = cfg.setdefault("leitura", {})
    lc.setdefault("sites", [dict(s) for s in SITES_PADRAO if s["chave"] in SITES_INICIAIS])
    lc.setdefault("anilist_usuario", "")
    lc.setdefault("extensao_vista", None)
    lc.setdefault("preferido", "")  # site onde os capítulos abrem de preferência ("" = o que lançou primeiro)
    return cfg, lc


REGRAS = ("capitulo", "capitulo_extra", "serie", "modelo_serie", "modelo_capitulo", "lista", "atualizacoes", "paginas", "busca")


_sites_cache = {"lista": None, "olhado": 0.0, "arquivo": None}


def sites():
    """Lista de sites. As regras dos sites conhecidos vêm sempre da versão atual da Estante,
    para uma correção de regra chegar a quem já usava; nome e endereço são os que você escolheu.
    Fica guardada na memória: montar a Leitura pede a lista milhares de vezes (uma por link de capítulo), e ler
    o config.json a cada vez deixava a tela lenta com muitas séries. Se o arquivo mudar, ela é refeita."""
    agora = time.time()
    if _sites_cache["lista"] is not None and agora - _sites_cache["olhado"] < 0.5:
        return _sites_cache["lista"]
    try:
        st = os.stat(CTX["DATA"] / "config.json")
        marca = (st.st_mtime_ns, st.st_size)
    except OSError:
        marca = None
    _sites_cache["olhado"] = agora
    if _sites_cache["lista"] is not None and marca is not None and marca == _sites_cache["arquivo"]:
        return _sites_cache["lista"]
    _sites_cache.update(lista=_montar_sites(), arquivo=marca)
    return _sites_cache["lista"]


def _esquecer_sites():
    _sites_cache["lista"] = None


def _montar_sites():
    out = []
    for s in cfg_leitura()[1]["sites"]:
        s = dict(s)
        padrao = next((p for p in SITES_PADRAO if p["chave"] == s.get("chave")), None)
        if padrao:
            for k in REGRAS:
                s[k] = padrao.get(k, "")
            s["antigos"] = list(dict.fromkeys(list(s.get("antigos") or []) + [d for d in padrao["antigos"] + [padrao["dominio"]] if d != s.get("dominio")]))
        out.append(s)
    return out


def site_por_chave(chave):
    return next((s for s in sites() if s["chave"] == chave), None)


# ---------------------------------------------------------------- números e nomes

def num(x):
    try:
        v = float(str(x).replace(",", "."))
        return v if math.isfinite(v) and v >= 0 else None
    except (TypeError, ValueError):
        return None


def num_txt(v):
    if v is None:
        return ""
    return str(int(v)) if float(v).is_integer() else ("%g" % v)


def chave_nome(t):
    t = htmlmod.unescape(t or "").lower()
    t = re.sub(r"[’'`´]", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def limpar_titulo(t):
    """'Solo Leveling Chapter 108 - Read Online | Asura Scans' -> 'Solo Leveling'"""
    t = htmlmod.unescape(t or "").strip()
    t = re.split(r"\s*(?:[-|–—:·•]\s*)?\b(?:chapter|ch\.|chapitre|cap[ií]tulo|episode|ep\.)\s*\d", t, flags=re.I)[0]
    t = re.split(r"(?<=[a-z])(?:Chapter|Ch\.)\s*\d", t)[0]  # "Solo LevelingChapter 109"
    t = re.sub(r"\s*[|–—]\s*[^|–—]*$", "", t) if re.search(r"\s[|–—]\s", t) else t
    t = re.sub(r"\s+-\s+(read|ler)\b.*$", "", t, flags=re.I)
    return t.strip(" -|–—:")


def titulo_do_slug(slug, site=None):
    s = slug or ""
    if site == "comix":
        s = re.sub(r"^[a-z0-9]+-(?=.)", "", s)  # tira o código do comix ("rm2xv-")
    s = re.sub(r"^\d+-", "", s)
    s = re.sub(r"-(?=[a-f]*\d)[0-9a-f]{8}$", "", s)
    for _ in range(3):  # alguns sites codificam duas vezes ("%2527" -> "%27" -> "'")
        s = urllib.parse.unquote(s)
    s = s.replace("-", " ").replace("_", " ").strip()
    return " ".join(w if w.isupper() else w.capitalize() for w in s.split())


def _py(rx):
    return re.compile(re.sub(r"\(\?<(?=[A-Za-z])", "(?P<", rx), re.I)


def entender_link(url):
    """Descobre o site, a série e o número do capítulo pelo próprio link."""
    url = (url or "").strip()
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    caminho = (u.path or "/") + (("?" + u.query) if u.query else "")
    for s in sites():
        doms = [s["dominio"]] + list(s.get("antigos") or [])
        if not any(host == d or host.endswith("." + d) for d in doms):
            continue
        out = {"site": s["chave"], "caminho": caminho, "slug": "", "num": None}
        for regra in ("capitulo", "capitulo_extra"):
            m = _py(s[regra]).search(caminho) if s.get(regra) else None
            if m:
                out.update(slug=m.group("slug"), num=num(m.group("num")), tipo="capitulo")
                return out
        if s.get("serie"):
            m = _py(s["serie"]).search(caminho)
            if m:
                out.update(slug=m.group("slug"), tipo="serie")
                return out
        m = _py(GENERICO_CAP).search(caminho)  # site acrescentado por você: regra genérica
        if m:
            out.update(slug=_slug_generico(caminho), num=num(m.group("num")), tipo="capitulo")
            return out
        out["tipo"] = "outro"
        return out
    return None


_PALAVRA_CAP = re.compile(r"(?:chapter|chapitre|capitulo|cap[ií]tulo|episode|ch)(?=[-_/ ]?\d)", re.I)


def _slug_generico(caminho):
    """Em sites sem regra própria, a série é o pedaço do link antes de 'chapter'."""
    partes = [p for p in caminho.split("/") if p]
    for i, p in enumerate(partes):
        m = _PALAVRA_CAP.search(p)
        if m or (re.fullmatch(r"(?:chapter|chapitre|capitulo|cap[ií]tulo|episode|ch)", p, re.I) and i + 1 < len(partes)):
            antes = p[:m.start()].strip("-_ ") if m else ""
            return antes or (partes[i - 1] if i > 0 else "")
    return partes[0] if partes else ""


def url_site(chave, caminho):
    s = site_por_chave(chave)
    if not s or not caminho:
        return ""
    return "https://" + s["dominio"] + (caminho if caminho.startswith("/") else "/" + caminho)


# ---------------------------------------------------------------- internet (AniList e MangaUpdates)

def _http_json(url, dados=None, timeout=20):
    h = {"User-Agent": "Estante/2.0 (organizador pessoal)", "Accept": "application/json"}
    corpo = None
    if dados is not None:
        corpo = json.dumps(dados).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=corpo, headers=h, method="POST" if corpo else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(5_000_000).decode("utf-8"))


CAMPOS_ANILIST = """id title { romaji english native } synonyms coverImage { extraLarge large } description(asHtml: false)
genres status chapters countryOfOrigin startDate { year } siteUrl
staff(perPage: 4, sort: RELEVANCE) { edges { role node { name { full } } } }"""


def anilist(query, variaveis):
    r = _http_json("https://graphql.anilist.co", {"query": query, "variables": variaveis})
    if r.get("errors"):
        raise RuntimeError(r["errors"][0].get("message", "erro do AniList"))
    return r.get("data") or {}


def anilist_buscar(texto):
    q = "query ($s: String) { Page(perPage: 10) { media(search: $s, type: MANGA, sort: SEARCH_MATCH) { " + CAMPOS_ANILIST + " } } }"
    return (anilist(q, {"s": texto}).get("Page") or {}).get("media") or []


def anilist_por_id(aid):
    q = "query ($id: Int) { Media(id: $id, type: MANGA) { " + CAMPOS_ANILIST + " } }"
    return anilist(q, {"id": int(aid)}).get("Media")


def _nomes_anilist(m):
    t = m.get("title") or {}
    return [x for x in [t.get("english"), t.get("romaji"), t.get("native")] + list(m.get("synonyms") or []) if x]


def melhor(titulo, candidatos, nomes_de, limite=0.88):
    """Escolhe o resultado cujo nome mais se parece com o título. Devolve None se nenhum for parecido o bastante."""
    alvo = chave_nome(titulo)
    melhor_c, melhor_r = None, 0
    for c in candidatos:
        for n in nomes_de(c):
            k = chave_nome(n)
            if not k:
                continue
            r = 1.0 if k == alvo else difflib.SequenceMatcher(None, alvo, k).ratio()
            if r > melhor_r:
                melhor_c, melhor_r = c, r
    return melhor_c if melhor_r >= limite else None


def dados_anilist(m):
    desc = htmlmod.unescape(re.sub(r"<br\s*/?>", "\n", m.get("description") or ""))
    desc = re.sub(r"<[^>]+>", "", desc)
    desc = re.sub(r"\n{3,}", "\n\n", re.sub(r"\(Source:[^)]*\)\s*$", "", desc.strip())).strip()
    autor = ""
    for e in ((m.get("staff") or {}).get("edges") or []):
        if re.search(r"story|original", e.get("role") or "", re.I):
            autor = ((e.get("node") or {}).get("name") or {}).get("full") or ""
            break
    t = m.get("title") or {}
    return {
        "anilist_id": m.get("id"), "name": t.get("english") or t.get("romaji") or "",
        "titulos_alt": list(dict.fromkeys(_nomes_anilist(m)))[:12],
        "capa_url": (m.get("coverImage") or {}).get("extraLarge") or (m.get("coverImage") or {}).get("large") or "",
        "description": desc[:5000], "genres": list(m.get("genres") or [])[:12],
        "status": STATUS_ANILIST.get(m.get("status") or "", ""), "tipo": TIPO_PAIS.get(m.get("countryOfOrigin") or "", ""),
        "year": (m.get("startDate") or {}).get("year"), "autor": autor, "chapters": m.get("chapters"),
        "url_anilist": m.get("siteUrl") or "",
    }


def anilist_por_mal(ids):
    """Busca de uma vez (50 por vez) as séries pelo número delas no MyAnimeList."""
    q = "query ($ids: [Int]) { Page(perPage: 50) { media(idMal_in: $ids, type: MANGA) { idMal " + CAMPOS_ANILIST + " } } }"
    return (anilist(q, {"ids": [int(i) for i in ids]}).get("Page") or {}).get("media") or []


def anilist_por_ids(ids):
    """Busca de uma vez (50 por vez) as séries pelo número delas no AniList."""
    q = "query ($ids: [Int]) { Page(perPage: 50) { media(id_in: $ids, type: MANGA) { " + CAMPOS_ANILIST + " } } }"
    return (anilist(q, {"ids": [int(i) for i in ids]}).get("Page") or {}).get("media") or []


def mu_buscar(texto):
    r = _http_json("https://api.mangaupdates.com/v1/series/search", {"search": texto, "perpage": 10})
    return [x.get("record") or {} for x in r.get("results") or []]


def mu_serie(mid):
    return _http_json(f"https://api.mangaupdates.com/v1/series/{int(mid)}")


def limpar_descricao(texto):
    """Descrições do MangaUpdates vêm com HTML, links em markdown e listas de links ("Source", "Original Novel",
    "Official Translations"...). Fica só o texto da história."""
    t = htmlmod.unescape(re.sub(r"<br\s*/?>", "\n", texto or "", flags=re.I))
    t = re.sub(r"<[^>]+>", "", t)
    linhas = []
    for linha in t.split("\n"):
        limpa = linha.strip().strip("*_ ").strip()
        if re.match(r"^\(?\s*(source|fonte|original (novel|webtoon|web ?novel|webcomic)|official translations?|links?|raws?|"
                    r"also (known|available)|note|chapters? [0-9]|volumes?\b)\b", limpa, re.I):
            break  # daqui para baixo é lista de links, não história
        linhas.append(linha)
    t = "\n".join(linhas)
    t = re.sub(r"\[([^\]]*)\]\((?:https?://|/)[^)]*\)", r"\1", t)   # [texto](link) -> texto
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"(\*\*|__|(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w))", "", t)  # negrito e itálico do markdown
    t = re.sub(r"[ \t]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


TIPO_MU = {"manga": "Mangá", "manhwa": "Manhwa", "manhua": "Manhua", "doujinshi": "Doujinshi", "novel": "Novel",
           "oel": "OEL", "artbook": "Artbook", "filipino": "Filipino", "indonesian": "Indonesian", "thai": "Thai", "vietnamese": "Vietnamese"}


def dados_mu(info):
    """Dados de uma série no MangaUpdates (fonte principal da Leitura)."""
    st = (info.get("status") or "").lower()
    if "hiatus" in st:
        status = "Em hiato"
    elif re.search(r"cancel|discontinu|dropped", st):
        status = "Cancelada"
    elif info.get("completed") or re.search(r"\bcomplete", st):
        status = "Completa"
    elif st:
        status = "Em andamento"
    else:
        status = ""
    desc = limpar_descricao(info.get("description") or "")
    autor = next((a.get("name") for a in info.get("authors") or [] if isinstance(a, dict) and (a.get("type") or "").lower() == "author"), "")
    ano = str(info.get("year") or "")
    img = ((info.get("image") or {}).get("url") or {})
    return {
        "mu_id": info.get("series_id"), "name": htmlmod.unescape(info.get("title") or ""),
        "titulos_alt": [htmlmod.unescape(a.get("title")) for a in info.get("associated") or [] if isinstance(a, dict) and a.get("title")][:12],
        "capa_url": img.get("original") or img.get("thumb") or "", "description": desc[:5000],
        "genres": [g.get("genre") for g in info.get("genres") or [] if isinstance(g, dict) and g.get("genre")][:15],
        "status": status, "tipo": TIPO_MU.get((info.get("type") or "").lower(), info.get("type") or ""),
        "year": int(ano) if ano.isdigit() else None, "autor": htmlmod.unescape(autor or ""),
        "latest": num(info.get("latest_chapter")), "url_mu": info.get("url") or "",
    }


# ---------------------------------------------------------------- capas

def guardar_capa(sid, url, referer=None):
    h = CTX["img_headers"](referer)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read(15_000_000)
        ctype = (r.headers.get_content_type() or "").lower()
    if not ctype.startswith("image/") and not re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", url, re.I):
        raise ValueError("isso não é uma imagem")
    ext = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(ctype, ".jpg")
    return guardar_capa_bytes(sid, raw, ext)


def guardar_capa_bytes(sid, raw, ext, manual=False):
    with CTX["lock"]:
        d = _load()
        s = achar(d, sid)
        if not s:
            return None
        antiga = s.get("cover")
        nome = f"l_{sid}_{int(time.time() * 1000)}{ext}"
        (CTX["COVERS"] / nome).write_bytes(raw)
        s["cover"] = nome
        if manual:
            s["capa_manual"] = True
        _save(d)
    if antiga:
        apagar_arquivo(CTX["COVERS"] / antiga)
    return nome


def achar(d, sid):
    return next((s for s in d["series"] if s["id"] == sid), None)


# ---------------------------------------------------------------- completar dados (em segundo plano)

_fila = []
_fila_lock = threading.Lock()
_trabalhando = threading.Event()


def enfileirar(sid, forcar=False):
    with _fila_lock:
        if (sid, forcar) not in _fila:
            _fila.append((sid, forcar))
    if not _trabalhando.is_set():
        _trabalhando.set()
        threading.Thread(target=_trabalhar, daemon=True).start()


def _trabalhar():
    try:
        while True:
            with _fila_lock:
                if not _fila:
                    return
                sid, forcar = _fila.pop(0)
            try:
                completar(sid, forcar)
            except Exception as e:
                print(f"[leitura] não consegui completar {sid}: {e}")
            time.sleep(0.8)  # devagar, para respeitar os limites do AniList e do MangaUpdates
    finally:
        _trabalhando.clear()


def aplicar_anilist(sid, a, trocar_nome=False):
    """Dados do AniList. Quando o MangaUpdates já deu os dados, o AniList só completa o que faltou."""
    with CTX["lock"]:
        d = _load()
        s = achar(d, sid)
        if not s:
            return None
        s["anilist_id"] = a["anilist_id"]
        s["anilist_tentado"] = True
        do_mu = s.get("dados_de") == "mangaupdates"
        if trocar_nome and a["name"] and not do_mu:
            s["name"] = a["name"]
        nomes = [s["name"]] + list(s.get("titulos_alt") or []) + a["titulos_alt"]
        s["titulos_alt"] = [n for n in dict.fromkeys(nomes) if n and n != s["name"]][:20]
        for k in ("description", "genres", "status", "tipo", "year", "autor"):
            if a.get(k) and (not s.get(k) or not do_mu):
                s[k] = a[k]
        if a.get("description") and not do_mu:
            s["dados_de"] = "anilist"
        if a.get("chapters") and (s.get("ultimo_disponivel") or 0) < a["chapters"]:
            s["ultimo_disponivel"] = float(a["chapters"])
        s["url_anilist"] = a.get("url_anilist") or ""
        capa = a["capa_url"] if a.get("capa_url") and not s.get("capa_manual") and (not s.get("cover") or s.get("capa_de") not in ("mangaupdates",)) else ""
        _save(d)
    if capa:
        try:
            if guardar_capa(sid, capa):
                _marcar(sid, capa_de="anilist")
        except Exception as e:
            print(f"[leitura] capa do AniList: {e}")
    return True


def _marcar(sid, **campos):
    with CTX["lock"]:
        d = _load()
        s = achar(d, sid)
        if s:
            s.update(campos)
            _save(d)


def aplicar_mu(sid, m, trocar_nome=False, refazer=False):
    """Dados do MangaUpdates: a fonte principal (capa, descrição, gêneros, status, tipo, autor e capítulos).
    Com refazer (o botão de buscar de novo), a capa do MangaUpdates é baixada de novo quando mudou lá."""
    with CTX["lock"]:
        d = _load()
        s = achar(d, sid)
        if not s:
            return None
        ja_vista = bool(s.get("verificado_em") or s.get("lista_vista"))
        s["mu_id"], s["mu_tentado"], s["verificado_em"] = m["mu_id"], True, time.time()
        if trocar_nome and m["name"]:
            s["name"] = m["name"]
        nomes = [s["name"]] + list(s.get("titulos_alt") or []) + [m["name"]] + m["titulos_alt"]
        s["titulos_alt"] = [n for n in dict.fromkeys(nomes) if n and n != s["name"]][:20]
        for k in ("description", "genres", "status", "tipo", "year", "autor"):
            if m.get(k):
                s[k] = m[k]
        if m.get("description"):
            s["dados_de"], s["desc_limpa"] = "mangaupdates", True
        s["url_mu"] = m.get("url_mu") or s.get("url_mu") or ""
        if m.get("latest") and s.get("origem") != "local":  # nos quadrinhos do PC, só contam os arquivos que você tem
            _subiu(d, s, m["latest"], avisar=ja_vista, site="")
        nova = refazer and (not s.get("cover") or s.get("capa_mu_url") != m.get("capa_url"))
        capa = m["capa_url"] if m.get("capa_url") and not s.get("capa_manual") and (s.get("capa_de") != "mangaupdates" or nova) else ""
        _save(d)
    if capa:
        try:
            if guardar_capa(sid, capa):
                _marcar(sid, capa_de="mangaupdates", capa_mu_url=capa)
        except Exception as e:
            print(f"[leitura] capa do MangaUpdates: {e}")
    return m.get("latest")


def completar(sid, forcar=False):
    """Dados de uma série: primeiro o MangaUpdates; o AniList entra para o que faltar."""
    d = _load()
    s = achar(d, sid)
    if not s:
        return
    if forcar:
        _marcar(sid, mu_tentado=False)
    verificar(sid, trocar_nome=bool(s.get("nome_do_link")))
    s = achar(_load(), sid)
    if s and (not s.get("description") or not s.get("cover")) and (forcar or (not s.get("anilist_id") and not s.get("anilist_tentado"))):
        try:
            a = None
            if s.get("anilist_id"):
                a = anilist_por_id(s["anilist_id"])
            else:
                for nome in [s["name"]] + list(s.get("titulos_alt") or [])[:2]:
                    a = melhor(nome, anilist_buscar(nome), _nomes_anilist)
                    if a:
                        break
            if a:
                aplicar_anilist(sid, dados_anilist(a), trocar_nome=bool(s.get("nome_do_link")) and not s.get("mu_id"))
            else:
                _marcar(sid, anilist_tentado=True)
        except Exception as e:
            print(f"[leitura] AniList para {s['name']}: {e}")
    s = achar(_load(), sid)
    if s and not s.get("cover") and s.get("capa_site"):
        try:
            if guardar_capa(sid, s["capa_site"], referer=url_site(s.get("site"), "/")):
                _marcar(sid, capa_de="site")
        except Exception as e:
            print(f"[leitura] capa do site: {e}")


def verificar(sid, trocar_nome=False):
    """Busca a série no MangaUpdates: dados (fonte principal) e o último capítulo que saiu."""
    d = _load()
    s = achar(d, sid)
    if not s:
        return None
    mid = s.get("mu_id")
    try:
        if not mid and not s.get("mu_tentado"):
            for nome in [s["name"]] + list(s.get("titulos_alt") or [])[:3]:
                r = melhor(nome, mu_buscar(nome), lambda x: [x.get("title") or "", x.get("hit_title") or ""])
                if r:
                    mid = r.get("series_id")
                    break
        if not mid:
            _marcar(sid, mu_tentado=True, verificado_em=time.time() if s.get("verificado_em") else None)
            return None
        return aplicar_mu(sid, dados_mu(mu_serie(mid)), trocar_nome=trocar_nome)
    except Exception as e:
        print(f"[leitura] MangaUpdates para {s['name']}: {e}")
        return None


def _subiu(d, s, ultimo, avisar=True, site=""):
    """Registra um novo último capítulo disponível. Com avisar, ele entra em Novidades (com o site onde saiu).
    Na primeira verificação de uma série não avisa: é só a Estante descobrindo até onde a série já foi."""
    antes = s.get("ultimo_disponivel")
    if antes is not None and ultimo <= antes:
        return False
    s["ultimo_disponivel"] = ultimo
    if avisar and antes is not None and (s.get("ultimo_lido") is None or ultimo > s["ultimo_lido"]):
        s["novo_desde"] = time.time()
        d["novidades"].append({"s": s["id"], "c": ultimo, "t": time.time(), "site": site})
        d["novidades"] = d["novidades"][-400:]
    return True


def _ps(s, site, slug=""):
    e = s.setdefault("por_site", {}).setdefault(site, {"slug": slug, "serie": "", "caps": {}, "ultimo": None, "visto": None})
    if slug:
        e["slug"] = slug
    return e


def _max_sites(s, menos=None):
    vals = [p.get("ultimo") for k, p in (s.get("por_site") or {}).items() if k != menos and p.get("ultimo") is not None]
    return max(vals) if vals else None


def _anotar_caps(d, s, site, caps, avisar):
    """Guarda os capítulos vistos num site ({número: link}) e anota em que site cada capítulo novo apareceu primeiro,
    como o Mihon faz com as fontes. Na primeira vez que um site é olhado, ele não "ganha" capítulos antigos."""
    if not caps:
        return
    e = _ps(s, site)
    ja_olhado = e.get("ultimo") is not None
    antes = _max_sites(s)
    for n, cam in caps.items():
        e["caps"][num_txt(n)] = cam
        if ja_olhado and len(s["por_site"]) > 1 and (antes is None or n > antes):
            s["primeiro"].setdefault(num_txt(n), {"site": site, "t": time.time()})
    maior = max(caps)
    if e.get("ultimo") is None or maior > e["ultimo"]:
        e["ultimo"] = maior
    if len(s["primeiro"]) > 60:
        s["primeiro"] = dict(sorted(s["primeiro"].items(), key=lambda kv: num(kv[0]) or 0)[-60:])
    _subiu(d, s, _max_sites(s), avisar=avisar, site=site)


_verificando = {"ativo": False, "feitos": 0, "total": 0, "ultima": 0}


def atualizar_do_mu(sid):
    """Busca de novo no MangaUpdates os dados de uma série que já está ligada a ele: descrição, situação, gêneros,
    autor, nomes alternativos e a capa (menos a que você escolheu). O nome e o capítulo lido não mudam."""
    s = achar(_load(), sid)
    if not s:
        raise KeyError(sid)
    if not s.get("mu_id"):
        raise ValueError("Esta série não está ligada ao MangaUpdates. Use “Buscar dados no MangaUpdates”.")
    return aplicar_mu(sid, dados_mu(mu_serie(s["mu_id"])), refazer=True)


_atualizando = {"ativo": False, "feitos": 0, "total": 0, "erros": 0}
_atualizando_lock = threading.Lock()


def atualizar_todas_do_mu(intervalo=2.0):
    """O mesmo para todas as séries ligadas ao MangaUpdates, uma a cada 2 segundos, para não estourar o limite deles.
    Se o MangaUpdates pedir para esperar, espera um minuto e tenta de novo."""
    with _atualizando_lock:  # dois cliques seguidos não começam duas voltas
        if _atualizando["ativo"]:
            return dict(_atualizando)
        ids = [s["id"] for s in _load()["series"] if s.get("mu_id")]
        _atualizando.update(ativo=True, feitos=0, total=len(ids), erros=0)

    def w():
        try:
            for sid in ids:
                for tentativa in range(2):
                    try:
                        atualizar_do_mu(sid)
                        break
                    except urllib.error.HTTPError as e:
                        if e.code == 429 and not tentativa:
                            time.sleep(60)
                            continue
                        print(f"[leitura] buscar de novo no MangaUpdates {sid}: {e}")
                        _atualizando["erros"] += 1
                        break
                    except Exception as e:
                        print(f"[leitura] buscar de novo no MangaUpdates {sid}: {e}")
                        _atualizando["erros"] += 1
                        break
                _atualizando["feitos"] += 1
                time.sleep(intervalo)
        finally:
            _atualizando["ativo"] = False
    threading.Thread(target=w, daemon=True).start()
    return dict(_atualizando)


_lancamentos = {"ultima": 0.0}


def verificar_lancamentos():
    """Lançamentos recentes do MangaUpdates de uma vez só (uma página traz uns dois dias de lançamentos de todas as
    séries), em vez de perguntar série por série. Capítulo novo de uma série sua entra em Novidades."""
    _lancamentos["ultima"] = time.time()
    r = _http_json("https://api.mangaupdates.com/v1/releases/days?page=1&include_metadata=true")
    maiores = {}
    for it in r.get("results") or []:
        sid = ((it.get("metadata") or {}).get("series") or {}).get("series_id")
        nums = [num(x) for x in re.findall(r"\d+(?:\.\d+)?", str((it.get("record") or {}).get("chapter") or ""))]
        nums = [x for x in nums if x is not None]
        if sid and nums:
            maiores[sid] = max(maiores.get(sid, 0), max(nums))  # "12-13" conta como 13
    novos = 0
    with CTX["lock"]:
        d = _load()
        for s in d["series"]:
            n = maiores.get(s.get("mu_id"))
            if n and _subiu(d, s, n, avisar=True):
                novos += 1
        if novos:
            _save(d)
    return novos


def verificar_todas(forcar=False):
    if _verificando["ativo"]:
        return dict(_verificando)
    ids = [s["id"] for s in _series_ativas(_load())]  # as que você está lendo primeiro
    _verificando.update(ativo=True, feitos=0, total=len(ids), ultima=time.time())

    def w():
        try:
            for sid in ids:
                try:
                    verificar(sid)
                except Exception as e:
                    print(f"[leitura] verificar {sid}: {e}")
                _verificando["feitos"] += 1
                time.sleep(1.0)
        finally:
            _verificando["ativo"] = False
    threading.Thread(target=w, daemon=True).start()
    return dict(_verificando)


def vigiar(intervalo_horas=12):
    """A cada hora, os lançamentos recentes do MangaUpdates de uma vez. Série por série, ao abrir (se fizer tempo)
    e a cada 12 horas, para pegar o que escapou. Também olha as pastas de quadrinhos do PC."""
    import mangaupdates
    import quadrinhos
    quadrinhos.vigiar()
    mangaupdates.vigiar()
    def loop():
        time.sleep(20)
        while True:
            try:
                series = _load()["series"]
                if series and time.time() - _lancamentos["ultima"] > 3600:
                    novos = verificar_lancamentos()
                    if novos:
                        print(f"[leitura] MangaUpdates: {novos} capítulo(s) novo(s) nos lançamentos recentes")
            except Exception as e:
                print("[leitura] lançamentos do MangaUpdates:", e)
            try:
                series = _load()["series"]
                ultima = max([s.get("verificado_em") or 0 for s in series] or [0])
                if series and time.time() - ultima > intervalo_horas * 3600:
                    verificar_todas()
            except Exception as e:
                print("[leitura]", e)
            time.sleep(600)
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------- registrar o que você leu

def _achar_serie(d, site, slug, titulo):
    for s in d["series"]:
        if any(k == site and (p.get("slug") or "") == slug for k, p in (s.get("por_site") or {}).items()):
            return s
    k = chave_nome(titulo)
    if k:
        for s in d["series"]:
            if k in [chave_nome(n) for n in [s["name"]] + list(s.get("titulos_alt") or [])]:
                return s
    return None


def _caminho_de(url, site):
    info = entender_link(url) if url else None
    return info if info and info["site"] == site else None


def _marcar_lido(s, n, caminho, site):
    if s.get("ultimo_lido") is None or n >= s["ultimo_lido"]:
        if s.get("ultimo_lido") is None or n > s["ultimo_lido"]:
            s["mu_terminou_capitulo"] = True  # com a conta do MangaUpdates ligada, a série entra na sua lista de lá
        s["ultimo_lido"], s["caminho_lido"], s["site_lido"] = n, caminho, site


def registrar(dados):
    """Recebe da extensão (ou do link colado) o que foi aberto no site e atualiza a série."""
    info = entender_link(dados.get("url") or "")
    if not info:
        raise ValueError("Esse site não está na lista de sites de leitura. Você pode acrescentar ele nas Configurações.")
    tipo = info.get("tipo")
    n = num(dados.get("capitulo")) if dados.get("capitulo") not in (None, "") else info.get("num")
    if tipo == "capitulo" and n is None:
        raise ValueError("Não consegui entender o número do capítulo nesse link.")
    if tipo not in ("capitulo", "serie"):
        raise ValueError("Esse link não parece ser de um capítulo ou de uma série.")
    titulo = limpar_titulo(dados.get("titulo") or "")
    nome_do_link = not titulo
    titulo = titulo or titulo_do_slug(info["slug"], info["site"])
    agora = time.time()
    quando = num(dados.get("quando"))  # a extensão guarda o capítulo se a Estante estiver fechada e manda depois
    if quando and agora - 30 * 86400 < quando / 1000 < agora:
        agora = quando / 1000
    nova = False
    with CTX["lock"]:
        d = _load()
        s = _achar_serie(d, info["site"], info["slug"], titulo)
        if not s:
            if tipo != "capitulo":
                return {"ok": True, "ignorado": "série que não está na estante"}
            s = nova_serie(titulo)
            s["nome_do_link"] = nome_do_link  # nome tirado do link: o do MangaUpdates, quando achar, é melhor
            d["series"].append(s)
            nova = True
        # o mesmo título em outro site: a série fica ligada aos dois (como as fontes do Mihon)
        e = _ps(s, info["site"], info["slug"] if tipo == "capitulo" or info["site"] not in s["por_site"] else "")
        if not s.get("site") or tipo == "capitulo":
            s["site"], s["slug"] = info["site"], e.get("slug") or info["slug"]  # site principal = onde você leu por último
        if dados.get("capa") and not s.get("cover"):
            s["capa_site"] = dados["capa"]
        if tipo == "serie":
            e["serie"] = info["caminho"]
        # "novo": a extensão viu o capítulo na página de últimas atualizações e já comparou com o último que a Estante conhecia
        avisar = bool(e.get("visto") or s.get("verificado_em") or s.get("lista_vista") or dados.get("novo"))
        if tipo == "capitulo":
            caps = {n: info["caminho"]}
            p = _caminho_de(dados.get("proximo"), info["site"])
            if p and p.get("num") is not None and p["num"] > n:
                caps[p["num"]] = p["caminho"]
            _anotar_caps(d, s, info["site"], caps, avisar)
            acompanha = any(k in dados for k in ("lendo", "posicao", "terminou"))
            if not acompanha or dados.get("terminou"):
                # link colado (ou extensão antiga): conta como lido. Com a extensão nova, só no fim do capítulo.
                _marcar_lido(s, n, info["caminho"], info["site"])
            else:
                # abriu o capítulo n: os anteriores estão lidos, e o n fica "lendo" com a posição onde você parou
                anteriores = [num(k) for k in (s["por_site"].get(info["site"], {}).get("caps") or {}) if num(k) is not None and num(k) < n]
                antes = max(anteriores) if anteriores else None
                if float(n).is_integer() and n >= 2 and (antes is None or n - 1 > antes):
                    antes = n - 1  # abriu o 125: o 124 está lido, mesmo que a Estante não tenha visto o link dele
                if antes is not None:
                    cam = (s["por_site"].get(info["site"], {}).get("caps") or {}).get(num_txt(antes), "")
                    _marcar_lido(s, antes, cam, info["site"])
                if s.get("ultimo_lido") is None or n > s["ultimo_lido"]:
                    pos = dados.get("posicao") or {}
                    velho = s.get("lendo") or {}
                    mesmo = velho.get("n") == n
                    s["lendo"] = {"n": n, "caminho": info["caminho"], "site": info["site"], "t": agora,
                                  "pct": num(pos.get("pct")) if pos else (velho.get("pct") if mesmo else 0),
                                  "pagina": int(pos.get("pagina") or 0) if pos else (velho.get("pagina") if mesmo else 0),
                                  "total": int(pos.get("total") or 0) if pos else (velho.get("total") if mesmo else 0)}
            if s.get("lendo") and s.get("ultimo_lido") is not None and s["lendo"].get("n", 0) <= s["ultimo_lido"]:
                s["lendo"] = None
            s["ultima_leitura"] = agora
            if s.get("novo_desde") and s.get("ultimo_lido") is not None and s.get("ultimo_disponivel") is not None and s["ultimo_lido"] >= s["ultimo_disponivel"]:
                s["novo_desde"] = None
            ult = d["leituras"][-1] if d["leituras"] else None
            if "posicao" not in dados and (not ult or ult.get("s") != s["id"] or ult.get("c") != n or agora - ult.get("t", 0) > 3600):
                d["leituras"].append({"s": s["id"], "c": n, "t": agora, "site": info["site"]})
                d["leituras"] = d["leituras"][-20000:]
            if s.get("ultimo_disponivel") is None or n > s["ultimo_disponivel"]:
                s["ultimo_disponivel"] = n
        caps = {}
        for c in (dados.get("capitulos") or [])[:5000]:  # lista de capítulos vista na página da série
            p = _caminho_de(c.get("url") if isinstance(c, dict) else c, info["site"])
            if p and p.get("num") is not None:
                caps[p["num"]] = p["caminho"]
        if caps:
            _anotar_caps(d, s, info["site"], caps, avisar)
        if dados.get("capitulos") is not None:
            e["visto"] = time.time()
            s["lista_vista"] = True
        _save(d)
        sid = s["id"]
        precisa = nova or (not s.get("cover") and s.get("capa_site")) or not (s.get("mu_tentado") or s.get("mu_id"))
    if precisa:
        enfileirar(sid)
    return {"ok": True, "id": sid, "nova": nova, "nome": titulo if nova else s["name"],
            "capitulo": num_txt(n) if tipo == "capitulo" else None}


# ---------------------------------------------------------------- como a série aparece na tela

def _link_cap(s, site, n):
    """Link do capítulo n num site: o visto de verdade, ou montado pelo formato do site."""
    e = (s.get("por_site") or {}).get(site) or {}
    cam = (e.get("caps") or {}).get(num_txt(n))
    if cam:
        return url_site(site, cam), True
    st = site_por_chave(site)
    if st and st.get("modelo_capitulo") and e.get("slug"):
        return url_site(site, st["modelo_capitulo"].replace("{slug}", e["slug"]).replace("{n}", num_txt(n))), False
    return "", False


_pref = {"valor": "", "quando": 0.0}


def _preferido():
    """Guardado por alguns segundos: a lista de quase 800 séries pergunta isso para cada série."""
    if time.time() - _pref["quando"] > 3:
        try:
            _pref["valor"] = cfg_leitura()[1].get("preferido") or ""
        except Exception as e:
            print("[leitura] site preferido:", e)
            _pref["valor"] = ""
        _pref["quando"] = time.time()
    return _pref["valor"]


def _principal(s, pref=None):
    """O site principal da série: o preferido nas Configurações, quando a série está nele."""
    pref = _preferido() if pref is None else pref
    return pref if pref and pref in (s.get("por_site") or {}) else s.get("site")


def _ordem_sites(s, n, pref=None):
    """Em que ordem tentar os sites para o capítulo n: o preferido nas Configurações, depois o que lançou
    o capítulo primeiro, depois o principal."""
    ps = s.get("por_site") or {}
    pref = _preferido() if pref is None else pref
    prim = (s.get("primeiro") or {}).get(num_txt(n), {}).get("site")
    ordem = list(dict.fromkeys(x for x in [pref, prim, s.get("site")] if x in ps))
    ordem += sorted([k for k in ps if k not in ordem], key=lambda k: -(ps[k].get("ultimo") or 0))
    return ordem


def proximo_capitulo(s):
    """O próximo capítulo a ler e o link dele, no site que lançou esse capítulo primeiro.
    Se você parou no meio de um capítulo, o próximo é continuar ele."""
    lido = s.get("ultimo_lido")
    le = s.get("lendo")
    if le and (lido is None or le["n"] > lido) and le.get("caminho"):
        st = site_por_chave(le.get("site"))
        return {"num": num_txt(le["n"]), "url": url_site(le["site"], le["caminho"]), "existe": True, "site": le.get("site"),
                "site_nome": st["nome"] if st else "", "continuar": True, "pct": round((le.get("pct") or 0) * 100),
                "pagina": le.get("pagina") or 0, "total": le.get("total") or 0}
    ps = s.get("por_site") or {}
    conhecidos = sorted({num(k) for e in ps.values() for k in (e.get("caps") or {}) if num(k) is not None})
    if lido is None:
        n = conhecidos[0] if conhecidos else 1.0
    else:
        maiores = [c for c in conhecidos if c > lido]
        n = maiores[0] if maiores else math.floor(lido) + 1.0
    url, site, visto = "", "", False
    pref = _preferido()
    for k in _ordem_sites(s, n, pref):  # primeiro um site que já mostrou esse capítulo de verdade
        u, v = _link_cap(s, k, n)
        if u and (v or (ps[k].get("ultimo") or 0) >= n):
            url, site, visto = u, k, True
            break
    principal = _principal(s, pref)
    if not url and principal:  # senão, o principal pelo formato do site (pode ainda não ter saído)
        url, _ = _link_cap(s, principal, n)
        site = principal if url else ""
    disp = s.get("ultimo_disponivel")
    existe = disp is None or n <= disp or visto
    ultimos = [e.get("ultimo") for e in ps.values()]
    if existe and not visto and s.get("status") == "Completa" and ultimos and None not in ultimos and n > max(ultimos):
        # série terminada e nenhum site tem esse capítulo: acabou. Acontece com one-shots que o site numera 0
        # e o MangaUpdates conta como 1 capítulo.
        existe = False
    st = site_por_chave(site)
    return {"num": num_txt(n), "url": url, "existe": existe, "site": site, "site_nome": st["nome"] if st else ""}


def serie_out(s):
    d = dict(s)
    d["cover_url"] = f"/covers/{s['cover']}" if s.get("cover") else None
    lido, disp = s.get("ultimo_lido"), s.get("ultimo_disponivel")
    d["nao_lidos"] = max(0, int(math.floor(disp) - math.floor(lido or 0))) if disp is not None else 0
    d["tem_novo"] = d["nao_lidos"] > 0 and lido is not None
    d["proximo_cap"] = proximo_capitulo(s)
    pref = _preferido()
    principal = _principal(s, pref)
    st = site_por_chave(principal)
    d["site_nome"] = st["nome"] if st else ""
    d["site_principal"] = principal or ""
    ps = s.get("por_site") or {}
    sites_info = []
    for k, e in ps.items():
        sk = site_por_chave(k)
        serie = url_site(k, e["serie"]) if e.get("serie") else (
            url_site(k, sk["modelo_serie"].replace("{slug}", e["slug"])) if sk and e.get("slug") and sk.get("modelo_serie") else "")
        sites_info.append({"site": k, "nome": sk["nome"] if sk else k, "ultimo_txt": num_txt(e.get("ultimo")),
                           "url_serie": serie, "principal": k == principal})
    d["sites_info"] = sorted(sites_info, key=lambda x: (not x["principal"], x["nome"]))
    d["url_serie"] = next((x["url_serie"] for x in d["sites_info"] if x["principal"]), "")
    d["url_lido"] = url_site(s.get("site_lido") or s.get("site"), s.get("caminho_lido")) if s.get("caminho_lido") else ""
    caps = {}
    for k in {k for e in ps.values() for k in (e.get("caps") or {})}:
        n = num(k)
        if n is None:
            continue
        for site in _ordem_sites(s, n, pref):
            u, v = _link_cap(s, site, n)
            if v:
                caps[k] = u
                break
    d["capitulos"] = caps
    e_p = ps.get(principal) or {}
    d["modelo_url"] = url_site(principal, st["modelo_capitulo"].replace("{slug}", e_p["slug"])) if st and st.get("modelo_capitulo") and e_p.get("slug") else ""
    d["primeiro_site"] = {k: (site_por_chave(v.get("site")) or {}).get("nome", "") for k, v in (s.get("primeiro") or {}).items()}
    d["lido_txt"] = num_txt(lido)
    d["disp_txt"] = num_txt(disp)
    if s.get("local"):  # quadrinhos do PC: o próximo é o primeiro capítulo depois do lido
        caps = s["local"]["caps"]
        i = next((k for k, c in enumerate(caps) if lido is None or c["n"] > lido), None)
        if i is None and s.get("cap_aberto") is not None and s["cap_aberto"] < len(caps):
            i = s["cap_aberto"]
        d["local"] = {"caps": [{"n": c["n"], "nome": c["nome"], "tipo": c["tipo"]} for c in caps], "pasta": s["local"]["pasta"],
                      "paginas": s["local"].get("paginas") or {}, "proximo": i}
        d["proximo_cap"] = {"num": num_txt(caps[i]["n"]) if i is not None else "", "url": "", "existe": i is not None, "site": "local",
                            "site_nome": "seu PC"}
        d["site_nome"] = "No seu PC"
        d["site_principal"] = "local"
    d.pop("capa_site", None)
    d.pop("por_site", None)
    d.pop("baixados_pagina", None)
    if s.get("baixados"):  # capítulos baixados para ler sem internet
        import baixar
        d["baixados"] = baixar.baixados(s)
    else:
        d.pop("baixados", None)
    return d


# ---------------------------------------------------------------- rotas

# ---------------------------------------------------------------- versão da extensão
# A extensão instalada no navegador conta a versão dela. Quando a da pasta "extensao" é mais nova (a Estante foi
# atualizada e a extensão não foi recarregada), a tela pede para clicar em "Recarregar" na página de extensões.

_manifesto = {"mtime": None, "versao": ""}


def versao_da_pasta():
    arq = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extensao", "manifest.json")
    try:
        mt = os.path.getmtime(arq)
        if mt != _manifesto["mtime"]:
            with open(arq, encoding="utf-8") as f:
                _manifesto.update(mtime=mt, versao=str(json.load(f).get("version") or ""))
    except (OSError, ValueError) as e:
        print("[leitura] não consegui ler a versão da extensão da pasta:", e)
    return _manifesto["versao"]


def _versao_tupla(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def extensao_velha(lc):
    """A extensão já conversou com a Estante, mas é mais velha que a da pasta (ou de antes de contar a versão)."""
    pasta = versao_da_pasta()
    return bool(lc.get("extensao_vista") and pasta and _versao_tupla(lc.get("extensao_versao")) < _versao_tupla(pasta))


def _anotar_extensao(versao, navegador=""):
    versao = str(versao or "")[:20]
    if not re.match(r"^\d+(\.\d+){0,3}$", versao):
        return
    with CTX["lock"]:
        cfg, lc = cfg_leitura()
        if lc.get("extensao_versao") == versao and (navegador not in ("chrome", "edge") or lc.get("navegador") == navegador):
            return
        lc["extensao_versao"] = versao
        if navegador in ("chrome", "edge"):
            lc["navegador"] = navegador
        CTX["save_cfg"](cfg)


_lista_cache = {"chave": None, "quando": 0.0, "series": "", "novidades": [], "historico": []}


def _lista_pronta(lc):
    """A lista de séries já montada, guardada na memória. A tela pergunta a cada poucos segundos, e montar tudo de
    novo (ler o leitura.json inteiro, fazer os links de cada capítulo) levava um décimo de segundo a cada vez.
    É refeita quando o leitura.json ou os sites mudam, e no máximo a cada minuto (capítulos baixados que sumiram)."""
    try:
        st = os.stat(_arq())
        marca = (st.st_mtime_ns, st.st_size)
    except OSError:
        marca = None
    chave = (marca, json.dumps(lc.get("sites"), sort_keys=True), lc.get("preferido") or "")
    c = _lista_cache
    if marca is None or c["chave"] != chave or time.time() - c["quando"] > 60:
        d = _load()
        ids = {s["id"] for s in d["series"]}
        series = []
        for s in d["series"]:
            o = serie_out(s)
            o.pop("description", None)  # a descrição só aparece no painel da série: vem por /api/leitura/sobre
            series.append(o)
        c.update(chave=chave, quando=time.time(), series=json.dumps(series, ensure_ascii=False, separators=(",", ":")),
                 novidades=[n for n in reversed(d["novidades"]) if n["s"] in ids][:200],
                 historico=[x for x in reversed(d["leituras"]) if x["s"] in ids][:300])
    return c


@bp.get("/api/leitura/sobre")
def api_sobre():
    s = achar(_load(), request.args.get("id") or "")
    if not s:
        abort(404)
    return jsonify({"description": s.get("description") or ""})


@bp.get("/api/leitura")
def api_lista():
    lc = cfg_leitura()[1]
    pronta = _lista_pronta(lc)
    corpo = json.dumps({
        "series": None,
        "novidades": pronta["novidades"],
        "historico": pronta["historico"],
        "verificando": _verificando,
        "extensao_vista": lc.get("extensao_vista"),
        "extensao_versao": lc.get("extensao_versao") or "",
        "extensao_pasta": versao_da_pasta(),
        "extensao_velha": extensao_velha(lc),
        "navegador": lc.get("navegador") or "",
    }, ensure_ascii=False, separators=(",", ":")).replace('"series":null', '"series":' + pronta["series"], 1)
    # A tela pergunta de tempos em tempos. Se nada mudou desde a última vez, a lista inteira (uns 2 MB) não vai de novo.
    marca = hashlib.md5(corpo.encode("utf-8")).hexdigest()[:16]
    if request.args.get("marca") == marca:
        return jsonify({"igual": True, "marca": marca})
    return Response(corpo[:-1] + f',"marca":"{marca}"}}', mimetype="application/json")


@bp.post("/api/leitura/progresso")
def api_progresso():
    """Usado pela extensão do navegador."""
    try:
        r = registrar(request.get_json(force=True) or {})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    with CTX["lock"]:
        cfg, lc = cfg_leitura()
        lc["extensao_vista"] = time.time() if request.headers.get("X-Estante-Extensao") else lc.get("extensao_vista")
        if request.headers.get("X-Estante-Navegador") in ("chrome", "edge"):
            lc["navegador"] = request.headers["X-Estante-Navegador"]  # a janela de leitura abre onde a extensão está
        CTX["save_cfg"](cfg)
    if request.headers.get("X-Estante-Versao"):
        _anotar_extensao(request.headers["X-Estante-Versao"])
    return jsonify(r)


@bp.post("/api/leitura/lista-site")
def api_lista_site():
    """A extensão manda os cartões da sua lista num site (no Comix, Perfil > Followed Titles): nome, endereço da série
    e capítulos (lido / último). A Estante liga cada série ao endereço dela no site. Primeiro pelo nome que a série tem
    nessa lista (vem da importação do CSV do Comix); senão, pelo nome ou nomes alternativos, só quando um único bate.
    O capítulo lido só anda para frente."""
    b = request.get_json(force=True) or {}
    st = site_por_chave(b.get("site") or "")
    if not st:
        return jsonify({"error": "Site desconhecido."}), 400
    chave = st["chave"]
    ligadas, ja, sem_par = 0, 0, []
    with CTX["lock"]:
        d = _load()
        pelo_nome_lista = {chave_nome(s["nome_" + chave]): s for s in d["series"] if s.get("nome_" + chave)}
        pelo_nome = {}
        for s in d["series"]:
            for n in {chave_nome(x) for x in [s["name"]] + list(s.get("titulos_alt") or [])}:
                if n:
                    pelo_nome.setdefault(n, []).append(s)
        for c in b.get("cartoes") or []:
            slug, titulo = str(c.get("slug") or "").strip(), str(c.get("titulo") or "").strip()
            if not slug or not titulo:
                continue
            k = chave_nome(titulo)
            s = pelo_nome_lista.get(k) or (pelo_nome[k][0] if len(pelo_nome.get(k) or []) == 1 else None)
            if not s:
                sem_par.append(titulo)
                continue
            e = (s.get("por_site") or {}).get(chave)
            if e and e.get("slug") == slug:
                ja += 1
            else:
                e = _ps(s, chave, slug)
                ligadas += 1
            if st.get("modelo_serie") and not e.get("serie"):
                e["serie"] = st["modelo_serie"].replace("{slug}", slug)
            if not s.get("site"):
                s["site"] = chave
            s.setdefault("nome_" + chave, titulo)
            lido, ultimo = num(c.get("lido")), num(c.get("ultimo"))
            if lido and (s.get("ultimo_lido") is None or lido > s["ultimo_lido"]):
                s["ultimo_lido"] = lido
            if ultimo:
                if e.get("ultimo") is None or ultimo > e["ultimo"]:
                    e["ultimo"] = ultimo
                _subiu(d, s, ultimo, avisar=bool(s.get("verificado_em") or s.get("lista_vista")), site=chave)
        _save(d)
    if sem_par:
        print(f"[leitura] lista do {st['nome']}: sem série na Estante para {len(sem_par)}: {', '.join(sem_par[:20])}")
    return jsonify({"ligadas": ligadas, "ja": ja, "sem_par": len(sem_par), "nomes_sem_par": sem_par[:30]})


BUSCA_DE_NOVO = 7 * 86400  # série procurada num site sem achar: só procura de novo depois de uma semana
_TIPOS_NO_NOME = re.compile(r"(?:MANHWA|MANHUA|MANGA|OTHER|NOVEL|ONE[- ]?SHOT|DOUJINSHI|WEBTOON|COMIC)\s*(?:[·•|-].*)?$")


def _nomes_busca(s):
    return [n for n in dict.fromkeys([s["name"]] + list(s.get("titulos_alt") or [])) if n and n.strip()][:3]


@bp.get("/api/leitura/para-buscar")
def api_para_buscar():
    """As séries que ainda não estão ligadas a este site, para a extensão procurar uma por uma na busca dele.
    As que você está lendo vêm primeiro; as procuradas há menos de uma semana sem achar ficam de fora."""
    st = site_por_chave(request.args.get("site") or "")
    if not st or not st.get("busca"):
        return jsonify({"error": "Este site não tem busca nas regras."}), 400
    agora, out = time.time(), []
    for s in _load()["series"]:
        if s.get("local") or s.get("hidden") or s.get("por_site"):  # só as que não estão em site nenhum
            continue
        if agora - ((s.get("buscada") or {}).get(st["chave"]) or 0) < BUSCA_DE_NOVO:
            continue
        out.append((s.get("lista_anilist") != "Lendo", -(s.get("ultima_leitura") or 0), {"id": s["id"], "nomes": _nomes_busca(s)}))
    out.sort(key=lambda x: x[:2])
    return jsonify({"series": [x[2] for x in out]})


def _chaves_resultado(r, codigo_no_endereco):
    """Os jeitos de comparar um resultado da busca com os nomes da série: o nome que está no endereço
    (sem o código do começo) e o texto do resultado, sem o tipo e o capítulo que o site põe depois do nome."""
    slug = str(r.get("slug") or "")
    nome_end = slug.split("-", 1)[1] if codigo_no_endereco and "-" in slug else slug
    texto = _TIPOS_NO_NOME.sub("", str(r.get("texto") or "").strip()).strip()
    return {k for k in (chave_nome(nome_end.replace("-", " ")), chave_nome(texto)) if k}


@bp.post("/api/leitura/busca-site")
def api_busca_site():
    """A extensão procurou uma série na busca do site e manda os resultados. A Estante só liga quando um único
    resultado tem o mesmo nome (ou um nome alternativo) da série; com dois parecidos ou nenhum, não chuta."""
    b = request.get_json(force=True) or {}
    st = site_por_chave(b.get("site") or "")
    if not st or not st.get("busca"):
        return jsonify({"error": "Site desconhecido."}), 400
    chave, cod = st["chave"], bool(st["busca"].get("codigo_no_endereco"))
    with CTX["lock"]:
        d = _load()
        s = achar(d, b.get("id") or "")
        if not s:
            abort(404)
        s.setdefault("buscada", {})[chave] = time.time()
        if chave in (s.get("por_site") or {}):
            _save(d)
            return jsonify({"ligada": True, "ja": True})
        nomes = {chave_nome(n) for n in _nomes_busca(s) + list(s.get("titulos_alt") or [])} - {""}
        bate = {}
        for r in b.get("resultados") or []:
            slug = str(r.get("slug") or "").strip()
            if slug and _chaves_resultado(r, cod) & nomes:
                bate[slug] = r
        de_outra = {e.get("slug") for x in d["series"] if x is not s for k, e in (x.get("por_site") or {}).items() if k == chave}
        livres = [k for k in bate if k not in de_outra]
        if len(bate) != 1 or not livres:
            _save(d)
            motivo = "nenhum" if not bate else "varios" if len(bate) > 1 else "de_outra"
            return jsonify({"ligada": False, "motivo": motivo})
        slug = livres[0]
        e = _ps(s, chave, slug)
        if st.get("modelo_serie") and not e.get("serie"):
            e["serie"] = st["modelo_serie"].replace("{slug}", slug)
        s["site"] = chave
        _save(d)
    return jsonify({"ligada": True, "slug": slug})


@bp.get("/api/leitura/posicao")
def api_posicao():
    """A extensão pergunta onde você parou neste capítulo, para rolar a página até lá."""
    info = entender_link(request.args.get("url", ""))
    if not info or info.get("tipo") != "capitulo":
        return jsonify({})
    s = _achar_serie(_load(), info["site"], info["slug"], "")
    le = (s or {}).get("lendo") or {}
    if le.get("n") == info.get("num") and (le.get("pagina") or le.get("pct")):
        return jsonify({"pagina": le.get("pagina") or 0, "pct": le.get("pct") or 0, "total": le.get("total") or 0})
    return jsonify({})


@bp.post("/api/leitura/link")
def api_link():
    """Registrar manualmente colando o link de um capítulo."""
    url = ((request.get_json(force=True) or {}).get("url") or "").strip()
    info = entender_link(url)
    if not info:
        return jsonify({"error": "Esse site não está na lista de sites de leitura. Acrescente nas Configurações."}), 400
    if info.get("tipo") != "capitulo":
        return jsonify({"error": "Cole o link de um capítulo (a página onde você lê), não o da série."}), 400
    try:
        r = registrar({"url": url})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(r)


@bp.get("/api/leitura/entender")
def api_entender():
    info = entender_link(request.args.get("url", ""))
    if info:
        info["titulo"] = titulo_do_slug(info.get("slug"), info.get("site"))
        info["num_txt"] = num_txt(info.get("num"))
    return jsonify(info or {})


EDITAVEIS = {"name", "tags", "favorite", "hidden", "description", "autor", "status", "year", "genres", "lista_anilist", "modo_leitor", "nota"}
MODOS_LEITOR = ("rolagem", "ltr", "rtl")  # leitor dos quadrinhos do PC: cada série lembra o seu


@bp.patch("/api/leitura/<sid>")
def api_editar(sid):
    b = request.get_json(force=True) or {}
    with CTX["lock"]:
        d = _load()
        s = achar(d, sid)
        if not s:
            abort(404)
        for k, v in b.items():
            if k in EDITAVEIS:
                if k == "tags":
                    v = sorted({str(t).strip() for t in v if str(t).strip()}, key=str.lower)
                if k == "modo_leitor" and v not in MODOS_LEITOR:
                    continue
                if k == "nota":
                    v = str(v or "")[:5000]
                s[k] = v
        if "ultimo_lido" in b:
            n = num(b["ultimo_lido"]) if b["ultimo_lido"] not in (None, "") else None
            if n is not None and (s.get("ultimo_lido") is None or n > s["ultimo_lido"]):
                s["mu_terminou_capitulo"] = True
            s["ultimo_lido"] = n
            if s.get("lendo") and (n is None or s["lendo"].get("n", 0) <= n):
                s["lendo"] = None
            e = (s.get("por_site") or {}).get(s.get("site")) or {}
            s["caminho_lido"] = (e.get("caps") or {}).get(num_txt(n), "") if n is not None else ""
            s["site_lido"] = s.get("site") or ""
            if n is not None:
                s["ultima_leitura"] = s.get("ultima_leitura") or time.time()
                if s.get("ultimo_disponivel") is None or n > s["ultimo_disponivel"]:
                    s["ultimo_disponivel"] = n
                if s.get("ultimo_disponivel") is not None and n >= s["ultimo_disponivel"]:
                    s["novo_desde"] = None
        if "link" in b and b["link"]:  # liga a série a um site (mais um, sem tirar os outros) e usa ele como principal
            info = entender_link(b["link"])
            if not info or not info.get("slug"):
                return jsonify({"error": "Não reconheci esse link. Use o link da série ou de um capítulo num dos sites da lista."}), 400
            e = _ps(s, info["site"], info["slug"] if info.get("tipo") == "capitulo" or info["site"] not in s["por_site"] else "")
            if info.get("tipo") == "serie":
                e["serie"] = info["caminho"]
            if info.get("num") is not None:
                _anotar_caps(d, s, info["site"], {info["num"]: info["caminho"]}, avisar=False)
            s["site"], s["slug"] = info["site"], e.get("slug") or info["slug"]
        if b.get("tirar_site"):
            s["por_site"].pop(b["tirar_site"], None)
            if s.get("site") == b["tirar_site"]:
                s["site"] = next(iter(s["por_site"]), "")
                s["slug"] = (s["por_site"].get(s["site"]) or {}).get("slug", "")
        if b.get("principal") in (s.get("por_site") or {}):
            s["site"] = b["principal"]
        _save(d)
        return jsonify(serie_out(s))


# ---------------------------------------------------------------- juntar séries
# Duas entradas que são a mesma obra (por exemplo, lida em dois sites com nomes diferentes) viram uma só, sem perder
# nada: sites e links de capítulos, capítulo lido (o maior), onde você parou, histórico, novidades, coleções,
# favorito e dados. Nome, capa e situação na lista ficam os da série escolhida como principal (a situação da outra
# só entra quando a principal não tem nenhuma).

def _juntar_site(p, o):
    for k, e in (o.get("por_site") or {}).items():
        pe = p["por_site"].get(k)
        if not pe:
            p["por_site"][k] = e
            continue
        pe["caps"] = {**(e.get("caps") or {}), **(pe.get("caps") or {})}
        pe["ultimo"] = max([x for x in (pe.get("ultimo"), e.get("ultimo")) if x is not None] or [None])
        pe["visto"] = max([x for x in (pe.get("visto"), e.get("visto")) if x] or [None])
        for c in ("slug", "serie"):
            pe[c] = pe.get(c) or e.get(c) or ""


def juntar_series(ids, principal):
    apagar = []
    with CTX["lock"]:
        d = _load()
        ss = [s for s in (achar(d, i) for i in dict.fromkeys(ids or [])) if s]
        if len(ss) < 2:
            raise ValueError("Escolha pelo menos duas séries para juntar.")
        if sum(1 for s in ss if s.get("local")) > 1:
            raise ValueError("Duas séries de pastas diferentes do seu PC não podem virar uma só.")
        p = next((s for s in ss if s["id"] == principal), ss[0])
        outras = [s for s in ss if s is not p]
        for o in outras:
            _juntar_site(p, o)
            for n, x in (o.get("primeiro") or {}).items():
                if n not in p["primeiro"] or (x.get("t") or 0) < (p["primeiro"][n].get("t") or 0):
                    p["primeiro"][n] = x
            if (o.get("ultimo_lido") or -1) > (p.get("ultimo_lido") or -1):
                for c in ("ultimo_lido", "caminho_lido", "site_lido"):
                    p[c] = o.get(c)
            lendo = [x for x in (p.get("lendo"), o.get("lendo")) if x]
            p["lendo"] = max(lendo, key=lambda x: (x.get("n") or 0, x.get("t") or 0)) if lendo else None
            p["ultima_leitura"] = max([x for x in (p.get("ultima_leitura"), o.get("ultima_leitura")) if x] or [None])
            p["ultimo_disponivel"] = max([x for x in (p.get("ultimo_disponivel"), o.get("ultimo_disponivel")) if x is not None] or [None])
            p["novo_desde"] = min([x for x in (p.get("novo_desde"), o.get("novo_desde")) if x] or [None])
            p["added"] = min(x for x in (p.get("added"), o.get("added"), time.time()) if x)
            p["tags"] = sorted(set(p.get("tags") or []) | set(o.get("tags") or []), key=str.lower)
            p["favorite"] = bool(p.get("favorite") or o.get("favorite"))
            p["hidden"] = bool(p.get("hidden") and o.get("hidden"))
            p["mu_terminou_capitulo"] = bool(p.get("mu_terminou_capitulo") or o.get("mu_terminou_capitulo"))
            alt = list(p.get("titulos_alt") or []) + [o["name"]] + list(o.get("titulos_alt") or [])
            p["titulos_alt"] = [t for t in dict.fromkeys(alt) if t and t.lower() != p["name"].lower()]
            if not p.get("mu_id") and o.get("mu_id"):
                for c in ("mu_id", "mu_sinc", "url_mu", "mu_tentado"):
                    if o.get(c) is not None:
                        p[c] = o[c]
            if not p.get("local") and o.get("local"):
                p["local"], p["cap_aberto"] = o["local"], o.get("cap_aberto")
            if o.get("nota") and o["nota"] not in (p.get("nota") or ""):
                p["nota"] = ((p.get("nota") or "") + "\n\n" + o["nota"]).strip()
            if not p.get("weebcentral") and o.get("weebcentral"):
                p["weebcentral"] = o["weebcentral"]
            for k, x in (o.get("baixados") or {}).items():  # os arquivos passam para a pasta da principal
                de, para = CTX["DATA"] / "baixados" / o["id"] / f"{k}.cbz", CTX["DATA"] / "baixados" / p["id"] / f"{k}.cbz"
                if k not in (p.get("baixados") or {}) and de.exists():
                    para.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(de, para)
                    p.setdefault("baixados", {})[k] = x
            for k, x in (o.get("baixados_pagina") or {}).items():
                p.setdefault("baixados_pagina", {}).setdefault(k, x)
            for c in ("lista_anilist", "description", "genres", "status", "tipo", "autor", "year", "anilist_id", "url_anilist",
                      "mal_id", "al_importado", "nome_comix", "capa_site", "site", "slug", "dados_de"):
                if not p.get(c) and o.get(c):
                    p[c] = o[c]
            if o.get("cover"):
                if not p.get("cover") or (o.get("capa_manual") and not p.get("capa_manual")):
                    if p.get("cover"):
                        apagar.append(p["cover"])
                    p["cover"], p["capa_manual"] = o["cover"], bool(o.get("capa_manual"))
                else:
                    apagar.append(o["cover"])
        if p.get("lendo") and p.get("ultimo_lido") is not None and (p["lendo"].get("n") or 0) <= p["ultimo_lido"]:
            p["lendo"] = None  # o capítulo aberto numa delas já tinha sido lido na outra
        if p.get("ultimo_disponivel") is not None and p.get("ultimo_lido") is not None and p["ultimo_disponivel"] <= p["ultimo_lido"]:
            p["novo_desde"] = None
        ids_outras = {o["id"] for o in outras}
        for x in d["leituras"]:
            if x["s"] in ids_outras:
                x["s"] = p["id"]
        vistas, novidades = set(), []
        for x in d["novidades"]:
            if x["s"] in ids_outras:
                x["s"] = p["id"]
            if (x["s"], x["c"]) not in vistas:
                vistas.add((x["s"], x["c"]))
                novidades.append(x)
        d["novidades"] = novidades
        d["series"] = [s for s in d["series"] if s["id"] not in ids_outras]
        _save(d)
    for c in apagar:
        apagar_arquivo(CTX["COVERS"] / c)
    return p


@bp.post("/api/leitura/juntar")
def api_juntar_series():
    b = request.get_json(force=True) or {}
    try:
        s = juntar_series(b.get("ids") or [], b.get("principal"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(serie_out(s))


@bp.delete("/api/leitura/<sid>")
def api_apagar(sid):
    with CTX["lock"]:
        d = _load()
        s = achar(d, sid)
        if not s:
            abort(404)
        d["series"] = [x for x in d["series"] if x["id"] != sid]
        _save(d)
    if s.get("cover"):
        apagar_arquivo(CTX["COVERS"] / s["cover"])
    import shutil
    shutil.rmtree(CTX["DATA"] / "baixados" / sid, ignore_errors=True)  # os capítulos baixados dela
    return jsonify({"ok": True})


@bp.get("/api/leitura/anilist")
def api_anilist_busca():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    try:
        res = anilist_buscar(q)
    except Exception as e:
        return jsonify({"error": f"Não consegui falar com o AniList: {e}"}), 400
    out = []
    for m in res:
        a = dados_anilist(m)
        out.append({"id": a["anilist_id"], "nome": a["name"], "capa": a["capa_url"], "ano": a["year"], "tipo": a["tipo"],
                    "status": a["status"], "capitulos": a["chapters"], "outros": a["titulos_alt"][:3]})
    return jsonify(out)


@bp.post("/api/leitura/<sid>/anilist")
def api_usar_anilist(sid):
    b = request.get_json(force=True) or {}
    try:
        m = anilist_por_id(b.get("anilist_id"))
        if not m:
            raise ValueError("série não encontrada")
        aplicar_anilist(sid, dados_anilist(m), trocar_nome=bool(b.get("trocar_nome")))
    except Exception as e:
        return jsonify({"error": f"Não consegui usar os dados do AniList: {e}"}), 400
    with CTX["lock"]:
        d = _load()
        s = achar(d, sid)
        if s:
            s["mu_tentado"], s["mu_id"] = False, None  # procura de novo no MangaUpdates com o nome certo
            _save(d)
    threading.Thread(target=verificar, args=(sid,), daemon=True).start()
    return jsonify(serie_out(achar(_load(), sid)))


@bp.get("/api/leitura/mu")
def api_mu_busca():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    try:
        res = mu_buscar(q)
    except Exception as e:
        return jsonify({"error": f"Não consegui falar com o MangaUpdates: {e}"}), 400
    out = []
    for r in res:
        img = ((r.get("image") or {}).get("url") or {})
        out.append({"id": r.get("series_id"), "nome": htmlmod.unescape(r.get("title") or ""), "capa": img.get("thumb") or img.get("original") or "",
                    "ano": r.get("year"), "tipo": TIPO_MU.get((r.get("type") or "").lower(), r.get("type") or "")})
    return jsonify(out)


@bp.post("/api/leitura/<sid>/mu")
def api_usar_mu(sid):
    """Você escolheu a série certa no MangaUpdates: usa os dados e a capa dela."""
    b = request.get_json(force=True) or {}
    s = achar(_load(), sid)
    if not s:
        abort(404)
    try:
        m = dados_mu(mu_serie(b.get("mu_id")))
    except Exception as e:
        return jsonify({"error": f"Não consegui usar os dados do MangaUpdates: {e}"}), 400
    _marcar(sid, capa_de="" if not s.get("capa_manual") else s.get("capa_de"), verificado_em=s.get("verificado_em") or time.time())
    aplicar_mu(sid, m, trocar_nome=bool(b.get("trocar_nome")))
    return jsonify(serie_out(achar(_load(), sid)))


@bp.post("/api/leitura/nova")
def api_nova():
    """Acrescentar uma série escolhida na busca do AniList (sem ter lido ainda pela extensão)."""
    b = request.get_json(force=True) or {}
    if b.get("mu_id"):  # escolhida na busca do MangaUpdates
        try:
            mu = dados_mu(mu_serie(b["mu_id"]))
        except Exception as e:
            return jsonify({"error": f"Não consegui falar com o MangaUpdates: {e}"}), 400
        with CTX["lock"]:
            d = _load()
            existe = next((x for x in d["series"] if x.get("mu_id") == mu["mu_id"]), None)
            if existe:
                return jsonify({"error": f"“{existe['name']}” já está na estante."}), 400
            s = nova_serie(mu["name"])
            s["verificado_em"] = time.time()
            d["series"].append(s)
            n = num(b.get("ultimo_lido"))
            if n is not None:
                s["ultimo_lido"] = n
            info = entender_link(b.get("link") or "") if b.get("link") else None
            if info and info.get("slug"):
                e = _ps(s, info["site"], info["slug"])
                if info.get("tipo") == "serie":
                    e["serie"] = info["caminho"]
                s["site"], s["slug"] = info["site"], info["slug"]
            _save(d)
        aplicar_mu(s["id"], mu)
        return jsonify(serie_out(achar(_load(), s["id"])))
    try:
        m = anilist_por_id(b.get("anilist_id"))
    except Exception as e:
        return jsonify({"error": f"Não consegui falar com o AniList: {e}"}), 400
    if not m:
        return jsonify({"error": "Série não encontrada no AniList."}), 400
    a = dados_anilist(m)
    with CTX["lock"]:
        d = _load()
        existe = next((s for s in d["series"] if s.get("anilist_id") == a["anilist_id"]), None)
        if existe:
            return jsonify({"error": f"“{existe['name']}” já está na estante."}), 400
        s = nova_serie(a["name"])
        d["series"].append(s)
        n = num(b.get("ultimo_lido"))
        if n is not None:
            s["ultimo_lido"], s["ultima_leitura"] = n, time.time()
        _save(d)
    aplicar_anilist(s["id"], a)
    if b.get("link"):
        with CTX["lock"]:
            d = _load()
            info = entender_link(b["link"])
            if info and info.get("slug"):
                x = achar(d, s["id"])
                e = _ps(x, info["site"], info["slug"])
                if info.get("tipo") == "serie":
                    e["serie"] = info["caminho"]
                x["site"], x["slug"] = info["site"], info["slug"]
                if info.get("num") is not None:
                    _anotar_caps(d, x, info["site"], {info["num"]: info["caminho"]}, avisar=False)
                _save(d)
    threading.Thread(target=verificar, args=(s["id"],), daemon=True).start()  # dados do MangaUpdates e capítulos
    return jsonify(serie_out(achar(_load(), s["id"])))


_importando = {"ativo": False, "feitos": 0, "total": 0, "novas": 0, "erro": ""}


def ler_lista_xml(raw):
    """Lê a lista exportada no formato do MyAnimeList (o AniList e o MyAnimeList exportam assim)."""
    import gzip
    import xml.etree.ElementTree as ET
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    raiz = ET.fromstring(raw)
    out = []
    for m in raiz.iter("manga"):
        titulo = (m.findtext("manga_title") or m.findtext("series_title") or "").strip()
        mal = (m.findtext("manga_mangadb_id") or m.findtext("series_mangadb_id") or "").strip()
        if not titulo:
            continue
        out.append({"mal": int(mal) if mal.isdigit() and int(mal) > 0 else None, "titulo": titulo,
                    "cap": num(m.findtext("my_read_chapters")) or 0,
                    "lista": LISTA_ARQUIVO.get((m.findtext("my_status") or "").strip().lower(), "")})
    return out


LISTA_PARA_ARQUIVO = {"Lendo": "Reading", "Quero ler": "Plan to Read", "Terminado": "Completed", "Larguei": "Dropped",
                      "Pausado": "On-Hold", "Relendo": "Reading"}


def lista_xml(series):
    """A lista de leitura no formato do MyAnimeList, o mesmo que a importação lê (e que o AniList e outros aceitam)."""
    import xml.etree.ElementTree as ET
    raiz = ET.Element("myanimelist")
    info = ET.SubElement(raiz, "myinfo")
    ET.SubElement(info, "user_export_type").text = "2"  # 2 = lista de mangás
    n = 0
    for s in sorted(series, key=lambda x: (x.get("name") or "").lower()):
        if s.get("local") or not s.get("name"):
            continue  # quadrinhos do PC não são de nenhuma lista
        m = ET.SubElement(raiz, "manga")
        ET.SubElement(m, "manga_mangadb_id").text = str(s.get("mal_id") or 0)
        ET.SubElement(m, "manga_title").text = s["name"]
        ET.SubElement(m, "my_read_chapters").text = num_txt(s.get("ultimo_lido")) or "0"
        lista = s.get("lista_anilist") or ("Lendo" if s.get("ultimo_lido") is not None else "Quero ler")
        ET.SubElement(m, "my_status").text = LISTA_PARA_ARQUIVO.get(lista, "Reading")
        ET.SubElement(m, "update_on_import").text = "1"
        n += 1
    info.insert(0, ET.Element("user_total_manga"))
    info[0].text = str(n)
    ET.indent(raiz)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(raiz, encoding="utf-8")


@bp.get("/api/leitura/exportar")
def api_exportar():
    corpo = lista_xml(_load()["series"])
    nome = "estante-leitura-" + time.strftime("%Y-%m-%d") + ".xml"
    return Response(corpo, mimetype="application/xml", headers={"Content-Disposition": f'attachment; filename="{nome}"'})


PASTAS_COMIX = {"reading": "Lendo", "completed": "Terminado", "plan to read": "Quero ler", "dropped": "Larguei",
                "on-hold": "Pausado", "on hold": "Pausado"}


def ler_lista_comix(raw):
    """Lê a lista exportada pelo Comix em CSV (Perfil > Import / Export > Export > CSV (Comix)):
    title, chapter, folder, url_mal, url_al, url_mu. Pastas criadas por você no Comix (como "Favoritos")
    viram favorito na Estante, sem mudar a situação da série."""
    import csv
    import io
    texto = raw.decode("utf-8-sig", "replace")
    out = []
    for r in csv.DictReader(io.StringIO(texto)):
        titulo = (r.get("title") or "").strip()
        if not titulo:
            continue
        pasta = (r.get("folder") or "").strip()
        mal = re.search(r"myanimelist\.net/manga/(\d+)", r.get("url_mal") or "")
        al = re.search(r"anilist\.co/manga/(\d+)", r.get("url_al") or "")
        mu = re.search(r"mangaupdates\.com/series/([0-9a-z]+)", r.get("url_mu") or "", re.I)
        out.append({"mal": int(mal.group(1)) if mal else None, "al": int(al.group(1)) if al else None,
                    "mu": mu.group(1).lower() if mu else "", "titulo": titulo, "cap": num(r.get("chapter")) or 0,
                    "lista": PASTAS_COMIX.get(pasta.lower(), ""), "favorito": bool(pasta) and pasta.lower() not in PASTAS_COMIX,
                    "nome_comix": titulo})
    return out


def _mu_slug(url):
    m = re.search(r"/series/([0-9a-z]+)", url or "", re.I)
    return m.group(1).lower() if m else ""


def importar_lista(entradas, usar_capitulo=True):
    """Coloca na Leitura as séries de uma lista. Nada é duplicado e o capítulo lido só avança, nunca volta.
    A série é achada pelo número do AniList, do MyAnimeList ou do MangaUpdates; só sem nenhum deles, pelo nome."""
    novas = []
    with CTX["lock"]:
        d = _load()
        por_al = {s.get("anilist_id"): s for s in d["series"] if s.get("anilist_id")}
        por_al.update({s.get("al_importado"): s for s in d["series"] if s.get("al_importado") and not s.get("anilist_id")})
        por_mal = {s.get("mal_id"): s for s in d["series"] if s.get("mal_id")}
        por_mu = {_mu_slug(s.get("url_mu")): s for s in d["series"] if _mu_slug(s.get("url_mu"))}
        por_mu_id = {s.get("mu_id"): s for s in d["series"] if s.get("mu_id")}
        for e in entradas:
            s = (por_al.get(e.get("al")) if e.get("al") else None) or (por_mal.get(e["mal"]) if e["mal"] else None) \
                or (por_mu.get(e.get("mu")) if e.get("mu") else None) or (por_mu_id.get(e.get("mu_id")) if e.get("mu_id") else None)
            if not s:
                k = chave_nome(e["titulo"])
                s = next((x for x in d["series"] if k and k in [chave_nome(n) for n in [x["name"]] + list(x.get("titulos_alt") or [])]), None)
            if not s:
                s = nova_serie(e["titulo"])
                d["series"].append(s)
                novas.append(s["id"])
            if e["mal"]:
                s["mal_id"] = e["mal"]
                por_mal[e["mal"]] = s
            if e.get("al") and not s.get("anilist_id"):
                s["al_importado"] = e["al"]  # os dados do AniList chegam por este número (_completar_importadas)
                por_al[e["al"]] = s
            if e.get("mu_id") and not s.get("mu_id"):
                s["mu_id"] = e["mu_id"]  # da sua conta do MangaUpdates: a série já fica ligada a ele
                por_mu_id[e["mu_id"]] = s
            if e.get("mu") and not s.get("mu_id"):
                try:
                    s["mu_id"] = int(e["mu"], 36)  # o código do link do MangaUpdates é o número da série em base 36
                except ValueError:
                    pass
            if e.get("mu") and not s.get("url_mu"):
                s["url_mu"] = "https://www.mangaupdates.com/series/" + e["mu"]
            if e.get("nome_comix"):
                s["nome_comix"] = e["nome_comix"]  # o nome na sua lista do Comix, para ligar a série ao endereço dela lá
            if e.get("favorito"):
                s["favorite"] = True
            if usar_capitulo and e["cap"] and (s.get("ultimo_lido") is None or e["cap"] > s["ultimo_lido"]):
                s["ultimo_lido"] = e["cap"]
            if e["lista"]:
                s["lista_anilist"] = e["lista"]
        _save(d)
    return novas


def _completar_importadas(ids):
    """Capas e dados das séries importadas: primeiro de 50 em 50 pelo número do MyAnimeList, depois o resto pelo nome."""
    try:
        d = _load()
        series = [s for s in d["series"] if s["id"] in set(ids)]
        achadas = set()
        com_al = [s for s in series if s.get("al_importado") and not s.get("anilist_id")]
        for i in range(0, len(com_al), 50):  # listas do Comix trazem o número do AniList: o jeito mais certo
            lote = com_al[i:i + 50]
            try:
                por_id = {m.get("id"): m for m in anilist_por_ids([s["al_importado"] for s in lote])}
            except Exception as e:
                print(f"[leitura] AniList (lote): {e}")
                por_id = {}
            for s in lote:
                m = por_id.get(s["al_importado"])
                if m:
                    try:
                        aplicar_anilist(s["id"], dados_anilist(m))
                        achadas.add(s["id"])
                    except Exception as e:
                        print(f"[leitura] {s['name']}: {e}")
                _importando["feitos"] += 1
            time.sleep(1.0)
        com_mal = [s for s in series if s.get("mal_id") and not s.get("anilist_id") and s["id"] not in achadas
                   and not s.get("al_importado")]
        for i in range(0, len(com_mal), 50):
            lote = com_mal[i:i + 50]
            try:
                por_mal = {m.get("idMal"): m for m in anilist_por_mal([s["mal_id"] for s in lote])}
            except Exception as e:
                print(f"[leitura] AniList (lote): {e}")
                por_mal = {}
            for s in lote:
                m = por_mal.get(s["mal_id"])
                if m:
                    try:
                        aplicar_anilist(s["id"], dados_anilist(m))
                        achadas.add(s["id"])
                    except Exception as e:
                        print(f"[leitura] {s['name']}: {e}")
                _importando["feitos"] += 1
            time.sleep(1.0)
        for s in series:
            if s["id"] not in achadas:
                enfileirar(s["id"])
                _importando["feitos"] += 1 if not s.get("mal_id") and not s.get("al_importado") else 0
    finally:
        _importando["ativo"] = False
    verificar_todas()


@bp.post("/api/leitura/importar-arquivo")
def api_importar_arquivo():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Escolha o arquivo da lista."}), 400
    raw = f.read(30_000_000)
    comix = raw.removeprefix(b"\xef\xbb\xbf").lower().startswith(b"title,chapter,folder")  # o CSV do Comix
    try:
        entradas = ler_lista_comix(raw) if comix else ler_lista_xml(raw)
    except Exception as e:
        print("[leitura] importar arquivo:", e)
        return jsonify({"error": "Não consegui ler esse arquivo. Use a lista exportada em XML pelo AniList ou pelo MyAnimeList, "
                                 "ou a exportada em CSV pelo Comix."}), 400
    if not entradas:
        return jsonify({"error": "Esse arquivo não tem nenhuma série."}), 400
    if _importando["ativo"]:
        return jsonify({"error": "Já tem uma importação em andamento. Espere ela terminar."}), 400
    usar = (request.form.get("usar_capitulo", "1") != "0")
    novas = importar_lista(entradas, usar)
    _importando.update(ativo=True, feitos=0, total=len(novas), novas=len(novas), erro="")
    threading.Thread(target=_completar_importadas, args=(novas,), daemon=True).start()
    return jsonify({"ativo": True, "total": len(entradas), "novas": len(novas), "comix": comix})


@bp.post("/api/leitura/importar-anilist")
def api_importar_anilist():
    corpo = request.get_json(force=True) or {}
    usuario = (corpo.get("usuario") or "").strip().lstrip("@")
    usar_capitulo = corpo.get("usar_capitulo", True) is not False
    if not usuario:
        return jsonify({"error": "Digite seu nome de usuário do AniList."}), 400
    if _importando["ativo"]:
        return jsonify(_importando)
    q = """query ($u: String) { MediaListCollection(userName: $u, type: MANGA) { lists { entries {
           progress status media { """ + CAMPOS_ANILIST + """ } } } } }"""
    try:
        r = anilist(q, {"u": usuario})
    except Exception as e:
        return jsonify({"error": f"Não consegui ler a lista de “{usuario}”. Confira o nome e se a lista é pública. ({e})"}), 400
    entradas = [e for lst in ((r.get("MediaListCollection") or {}).get("lists") or []) for e in lst.get("entries") or []]
    with CTX["lock"]:
        cfg, lc = cfg_leitura()
        lc["anilist_usuario"] = usuario
        CTX["save_cfg"](cfg)
    _importando.update(ativo=True, feitos=0, total=len(entradas), novas=0, erro="")
    novas, criadas = [], 0
    with CTX["lock"]:
        d = _load()
        for e in entradas:
            a = dados_anilist(e.get("media") or {})
            if not a["anilist_id"]:
                continue
            s = next((x for x in d["series"] if x.get("anilist_id") == a["anilist_id"]), None)
            if not s:
                k = [chave_nome(n) for n in [a["name"]] + a["titulos_alt"]]
                s = next((x for x in d["series"] if not x.get("anilist_id") and chave_nome(x["name"]) in k), None)
            if not s:
                s = nova_serie(a["name"])
                d["series"].append(s)
                novas.append((s["id"], a))
                criadas += 1
            elif not s.get("anilist_id"):
                novas.append((s["id"], a))
            p = num(e.get("progress"))
            if usar_capitulo and p and (s.get("ultimo_lido") is None or p > s["ultimo_lido"]):
                s["ultimo_lido"] = p
            s["lista_anilist"] = LISTA_ANILIST.get(e.get("status") or "", "")
        _save(d)
    _importando["novas"] = criadas

    def w():
        try:
            for sid, a in novas:
                try:
                    aplicar_anilist(sid, a)
                except Exception as ex:
                    print(f"[leitura] importar {a.get('name')}: {ex}")
                _importando["feitos"] += 1
                time.sleep(0.3)
            verificar_todas()
        finally:
            _importando["ativo"] = False
    threading.Thread(target=w, daemon=True).start()
    return jsonify(_importando)


@bp.get("/api/leitura/importar-anilist")
def api_importar_status():
    return jsonify(_importando)


@bp.post("/api/leitura/verificar")
def api_verificar():
    def lancamentos():
        try:
            verificar_lancamentos()
        except Exception as e:
            print("[leitura] lançamentos do MangaUpdates:", e)
    threading.Thread(target=lancamentos, daemon=True).start()  # os recentes de uma vez, antes da volta série por série
    return jsonify(verificar_todas())


@bp.get("/api/leitura/verificar")
def api_verificar_status():
    return jsonify(_verificando)


@bp.post("/api/leitura/atualizar-mu")
def api_atualizar_todas_mu():
    return jsonify(atualizar_todas_do_mu())


@bp.get("/api/leitura/atualizar-mu")
def api_atualizar_todas_mu_status():
    return jsonify(_atualizando)


@bp.post("/api/leitura/<sid>/atualizar-mu")
def api_atualizar_mu(sid):
    try:
        atualizar_do_mu(sid)
        if not achar(_load(), sid):
            abort(404)  # apagada enquanto buscava
    except KeyError:
        abort(404)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"[leitura] buscar de novo no MangaUpdates: {e}")
        return jsonify({"error": "O MangaUpdates não respondeu agora. Tente de novo daqui a pouco."}), 502
    return jsonify(serie_out(achar(_load(), sid)))


@bp.post("/api/leitura/<sid>/verificar")
def api_verificar_uma(sid):
    ultimo = verificar(sid)
    s = achar(_load(), sid)
    if not s:
        abort(404)
    return jsonify({"serie": serie_out(s), "achou": ultimo is not None})


@bp.post("/api/leitura/<sid>/capa")
def api_capa(sid):
    if "file" in request.files:
        f = request.files["file"]
        ext = os.path.splitext(f.filename or "")[1].lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            return jsonify({"error": "Use uma imagem JPG, PNG, WEBP ou GIF."}), 400
        nome = guardar_capa_bytes(sid, f.read(), ext, manual=True)
    else:
        try:
            nome = guardar_capa(sid, (request.get_json(force=True) or {}).get("url", ""))
            with CTX["lock"]:
                d = _load()
                if achar(d, sid):
                    achar(d, sid)["capa_manual"] = True
                    _save(d)
        except Exception as e:
            return jsonify({"error": f"Não deu pra salvar a capa: {e}"}), 400
    if not nome:
        abort(404)
    return jsonify(serie_out(achar(_load(), sid)))


@bp.get("/api/leitura/para-verificar")
def api_para_verificar():
    """Lista de páginas de série que a extensão olha de tempos em tempos (como o Mihon faz com as fontes),
    para saber em que site cada capítulo novo sai primeiro."""
    out = []
    for s in _series_ativas(_load()):
        for k, (slug, url) in _paginas_da_serie(s).items():
            out.append({"id": s["id"], "site": k, "slug": slug, "url": url})
    return jsonify(out[:900])


def _series_ativas(d):
    """As séries que ainda podem ter capítulo novo, na ordem em que vale olhar: primeiro as que você está lendo
    (as lidas mais recentemente antes), depois as que lançaram mais capítulos nos últimos 60 dias, depois o resto."""
    limite = time.time() - 60 * 86400
    lancou = {}
    for n in d.get("novidades") or []:
        if (n.get("t") or 0) > limite:
            lancou[n["s"]] = lancou.get(n["s"], 0) + 1
    ativas = [s for s in d["series"] if not s.get("hidden") and not s.get("local") and s.get("status") not in ("Completa", "Cancelada")
              and s.get("lista_anilist") not in ("Larguei", "Terminado")]
    return sorted(ativas, key=lambda s: (s.get("lista_anilist") != "Lendo", -lancou.get(s["id"], 0), -(s.get("ultima_leitura") or 0)))


def _paginas_da_serie(s):
    """{site: (slug, endereço da página da série)} para cada site ligado à série."""
    out = {}
    for k, e in (s.get("por_site") or {}).items():
        st = site_por_chave(k)
        if not st:
            continue
        cam = e.get("serie") or (st["modelo_serie"].replace("{slug}", e["slug"]) if e.get("slug") and st.get("modelo_serie") else "")
        if cam:
            out[k] = (e.get("slug") or "", url_site(k, cam))
    return out


@bp.get("/api/leitura/minhas")
def api_minhas():
    """A lista das suas séries que a extensão guarda para achar capítulos novos nas páginas de atualizações
    dos sites, mesmo com a Estante fechada: o endereço da série em cada site e o último capítulo que a Estante conhece."""
    out = []
    for s in _series_ativas(_load()):
        paginas = _paginas_da_serie(s)
        if paginas:
            out.append({"id": s["id"], "nome": s["name"], "lendo": s.get("lista_anilist") == "Lendo",
                        "ultimo": s.get("ultimo_disponivel"), "lido": s.get("ultimo_lido"),
                        "sites": {k: {"slug": slug, "url": url} for k, (slug, url) in paginas.items()}})
    return jsonify(out)


@bp.get("/api/leitura/sites")
def api_sites():
    """A extensão pega aqui a lista de sites e as regras para reconhecer capítulos (e conta a versão dela)."""
    if request.args.get("v"):
        _anotar_extensao(request.args["v"], request.args.get("nav", ""))
    ss = sites()
    # endereço de cada site, para a extensão montar o da página de últimas atualizações
    bases = {s["chave"]: url_site(s["chave"], "/") for s in ss if s.get("dominio")}
    conhecidos = [{"chave": s["chave"], "nome": s["nome"], "dominio": s["dominio"]} for s in SITES_PADRAO]
    return jsonify({"sites": ss, "generico": GENERICO_CAP, "preferido": _preferido(), "bases": bases, "conhecidos": conhecidos})


@bp.post("/api/leitura/sites")
def api_sites_salvar():
    b = request.get_json(force=True) or {}
    lista = b.get("sites")
    if not isinstance(lista, list):
        abort(400)
    with CTX["lock"]:
        cfg, lc = cfg_leitura()
        atuais = {s["chave"]: s for s in lc["sites"]}
        novos = []
        for it in lista:
            dom = re.sub(r"^https?://", "", str(it.get("dominio") or "").strip().lower()).split("/")[0]
            dom = dom[4:] if dom.startswith("www.") else dom
            if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", dom):
                return jsonify({"error": f"“{it.get('dominio')}” não parece um endereço de site (exemplo: asurascans.com)."}), 400
            chave = it.get("chave") or re.sub(r"[^a-z0-9]", "", dom.split(".")[0]) or uuid.uuid4().hex[:6]
            base = dict(atuais.get(chave) or {"chave": chave, "antigos": [], "capitulo": "", "serie": "",
                                              "modelo_serie": "", "modelo_capitulo": ""})
            if base.get("dominio") and base["dominio"] != dom:
                base["antigos"] = list(dict.fromkeys([base["dominio"]] + list(base.get("antigos") or [])))[:6]
            base["dominio"] = dom
            base["nome"] = (it.get("nome") or base.get("nome") or dom).strip()
            novos.append(base)
        lc["sites"] = novos
        if "preferido" in b:
            p = str(b.get("preferido") or "")
            lc["preferido"] = p if p in {s["chave"] for s in novos} else ""
        CTX["save_cfg"](cfg)
    _pref["quando"] = 0.0
    _esquecer_sites()
    return jsonify({"sites": sites(), "preferido": _preferido()})


def marcar_lido_no_leitor(d, s, n, fim, onde):
    """O leitor da Estante (quadrinhos do PC ou capítulos baixados) avisou que você está no capítulo n; fim = chegou
    ao fim dele. O capítulo lido só anda para frente, e o fim conta para o MangaUpdates como no site."""
    agora = time.time()
    s["ultima_leitura"] = agora
    if fim and (s.get("ultimo_lido") is None or n > s["ultimo_lido"]):
        s["ultimo_lido"] = n
        s["mu_terminou_capitulo"] = True
        if s.get("ultimo_disponivel") is not None and n >= s["ultimo_disponivel"]:
            s["novo_desde"] = None
        if (s.get("lendo") or {}).get("n", n + 1) <= n:
            s["lendo"] = None
    ult = d["leituras"][-1] if d["leituras"] else None
    if not ult or ult.get("s") != s["id"] or ult.get("c") != n or agora - ult.get("t", 0) > 3600:
        d["leituras"].append({"s": s["id"], "c": n, "t": agora, "site": onde})
        d["leituras"] = d["leituras"][-20000:]


def iniciar(app, ctx):
    CTX.update(ctx)
    import baixar
    import mangaupdates
    import quadrinhos
    baixar.rotas(bp)
    quadrinhos.rotas(bp)
    mangaupdates.rotas(bp)
    app.register_blueprint(bp)
