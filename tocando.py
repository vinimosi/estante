"""
Tocando agora: o que está tocando no Spotify, no YouTube ou no YouTube Music, com capa, botões e a letra.

De onde vem cada coisa:
  - a música, a capa, a posição e os botões vêm do painel de mídia do próprio Windows (o mesmo que aparece com as
    teclas de volume), pelos pacotes winrt pequenos. Nada de conta nem senha de serviço nenhum;
  - a letra vem do LRCLIB (lrclib.net), gratuito e sem conta. As letras já buscadas ficam guardadas na pasta
    "letras" dos dados;
  - Genius e Musixmatch não permitem que um programa como este mostre a letra inteira. Quando o LRCLIB não tem,
    o botão "Ver no Genius" abre a página da música numa janela. Com a chave gratuita do Genius (uma chave de
    programa, como a do SteamGridDB), a Estante acha a página certa pela busca oficial deles; sem ela, abre a busca.
"""
import asyncio
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import OrderedDict

from caminhos import VERSAO

CTX = {}  # preenchido por iniciar(): pasta de dados, lock e configurações da Estante
AGENTE = f"Estante {VERSAO} (organizador pessoal para Windows)"
LRCLIB = "https://lrclib.net/api"
GENIUS = "https://api.genius.com"
NAO_ACHOU_DE_NOVO = 3 * 86400   # letra que não existia no LRCLIB: procura de novo depois de 3 dias
CURTO = 40                      # no navegador, menos que isso é anúncio ou vídeo curto: sem letra
ESPERA_CAPA = 1.5               # a capa só é lida depois disso: antes, o Spotify ainda pode mostrar a da música anterior
ESPACO = 0.3                    # segundos entre um pedido e outro ao LRCLIB (um de cada vez, como eles pedem)
NO_HISTORICO = 30               # segundos tocando para a música entrar no histórico
HISTORICO_MAX = 5000
STATUS = {0: "fechado", 1: "aberto", 2: "mudando", 3: "parado", 4: "tocando", 5: "pausado"}
NAVEGADORES = ("msedge", "chrome", "firefox", "308046b0af4a39cb", "opera", "brave", "vivaldi")

_lock = threading.Lock()
_lock_lrclib = threading.Lock()
_ultima = {"quando": 0.0, "sessoes": []}
_visto = {}                 # app -> quando começou a tocar ou trocou de música (para escolher entre duas)
_antes = {}                 # app -> (música, situação) na leitura anterior
_primeira_vez = {}          # chave da música -> quando apareceu (a capa só é lida depois que ela assentou)
_capas = OrderedDict()      # chave da música -> (bytes, tipo)
_tentou_capa = {}
_faixas = OrderedDict()     # chave -> faixa, para a letra e o Genius acharem a música certa
_lrclib = {"ultimo": 0.0, "pausa_ate": 0.0}
_maior_duracao = {}         # chave da música -> maior duração já vista (no YouTube, a propaganda entra com o nome do vídeo)
_preferida = {"app": ""}    # fonte que você escolheu mostrar quando duas tocam juntas
_anotadas = {}              # app -> (música, quando começou) já posta no histórico


def _log(*a):
    print("[tocando]", *a)


# ---------------------------------------------------------------- painel de mídia do Windows

class _Painel:
    """O painel de mídia do Windows é lido numa linha só dele, sempre a mesma."""

    def __init__(self):
        self.loop = None
        self.trava = threading.Lock()

    def rodar(self, coro, espera=5):
        with self.trava:
            if self.loop is None:
                import winrt.windows.media.control  # noqa: F401  (avisa logo se faltar o componente)
                self.loop = asyncio.new_event_loop()
                threading.Thread(target=self.loop.run_forever, daemon=True, name="painel-de-midia").start()
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(espera)


_painel = _Painel()


def disponivel():
    """("", True) quando dá para ler o painel; senão, o motivo em português simples."""
    if os.name != "nt":
        return False, "O painel de mídia é do Windows; fora dele esta parte não funciona."
    try:
        import winrt.windows.media.control  # noqa: F401
        import winrt.windows.storage.streams  # noqa: F401
    except ImportError:
        return False, "Falta um componente pequeno do Windows. Abra o Instalar.bat de novo para ele ser instalado."
    return True, ""


def _segundos(v):
    return v.total_seconds() if hasattr(v, "total_seconds") else float(v or 0) / 10_000_000


async def _bytes_da_capa(ref):
    from winrt.windows.storage.streams import DataReader
    stream = await ref.open_read_async()
    leitor = DataReader(stream)
    await leitor.load_async(stream.size)
    buf = bytearray(stream.size)
    leitor.read_bytes(buf)
    return bytes(buf)


async def _ler_async(querem_capa):
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Gerente
    g = await Gerente.request_async()
    atual = g.get_current_session()
    atual_id = atual.source_app_user_model_id if atual else ""
    out, vistos = [], {}
    for s in g.get_sessions():
        app_id = s.source_app_user_model_id or "?"
        vistos[app_id] = vistos.get(app_id, 0) + 1
        if vistos[app_id] > 1:
            app_id += f"#{vistos[app_id]}"
        try:
            p = await s.try_get_media_properties_async()
        except Exception as e:
            _log("não consegui ler uma sessão:", e)
            continue
        info, tl = s.get_playback_info(), s.get_timeline_properties()
        ctl = info.controls
        try:
            atualizado = tl.last_updated_time.timestamp()
        except (OSError, OverflowError, ValueError):
            atualizado = 0.0
        d = {"app": app_id, "titulo": p.title or "", "artista": p.artist or "", "album": p.album_title or "",
             "status": STATUS.get(int(info.playback_status), "parado"),
             "posicao": _segundos(tl.position), "duracao": max(0.0, _segundos(tl.end_time) - _segundos(tl.start_time)),
             "atualizado": atualizado, "atual": app_id == atual_id,
             "botoes": {"tocar": ctl.is_play_enabled, "pausar": ctl.is_pause_enabled,
                        "anterior": ctl.is_previous_enabled, "proximo": ctl.is_next_enabled,
                        "posicao": ctl.is_playback_position_enabled}}
        if chave(d) in querem_capa and p.thumbnail:
            try:
                d["capa"] = await _bytes_da_capa(p.thumbnail)
            except Exception as e:
                _log("não consegui ler a capa:", e)
        out.append(d)
    return out


async def _comando_async(app_id, acao, segundos=0.0):
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Gerente
    g = await Gerente.request_async()
    vistos = {}
    for s in g.get_sessions():
        sid = s.source_app_user_model_id or "?"
        vistos[sid] = vistos.get(sid, 0) + 1
        if vistos[sid] > 1:
            sid += f"#{vistos[sid]}"
        if sid == app_id:
            if acao == "posicao":  # pular para um ponto da música (em unidades de 100 nanossegundos)
                return bool(await s.try_change_playback_position_async(int(max(0.0, segundos) * 10_000_000)))
            f = {"tocar": s.try_play_async, "pausar": s.try_pause_async, "alternar": s.try_toggle_play_pause_async,
                 "anterior": s.try_skip_previous_async, "proximo": s.try_skip_next_async}[acao]
            return bool(await f())
    return False


def _ler_sessoes(querem_capa):
    """Lista do que o painel do Windows mostra agora (nos testes, um painel de mentira entra no lugar)."""
    return _painel.rodar(_ler_async(set(querem_capa)))


def _comando(app_id, acao, segundos=0.0):
    return _painel.rodar(_comando_async(app_id, acao, segundos))


# ---------------------------------------------------------------- qual música mostrar

def chave(f):
    base = "|".join((f.get("app", "").split("#")[0], f.get("titulo", ""), f.get("artista", ""))).lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def e_navegador(app_id):
    a = (app_id or "").lower()
    return any(n in a for n in NAVEGADORES)


def nome_da_fonte(app_id):
    a = (app_id or "").lower()
    for trecho, nome in (("spotify", "Spotify"), ("msedge", "Edge"), ("chrome", "Chrome"), ("firefox", "Firefox"),
                         ("308046b0af4a39cb", "Firefox"), ("opera", "Opera"), ("brave", "Brave"), ("vivaldi", "Vivaldi"),
                         ("zunemusic", "Media Player"), ("music.ui", "Media Player"), ("foobar", "foobar2000"),
                         ("vlc", "VLC"), ("itunes", "iTunes"), ("deezer", "Deezer"), ("tidal", "TIDAL")):
        if trecho in a:
            return nome
    nome = (app_id or "").split("!")[-1].split("#")[0]
    return re.sub(r"\.exe$", "", nome, flags=re.I) or "Outro programa"


_PALAVRAS_ANUNCIO = ("advertisement", "anúncio", "anuncio", "publicidade", "patrocinado", "sponsored")


def e_anuncio(f):
    """Propagandas aparecem no painel como se fossem música. No Spotify: sem artista, ou sem álbum e com menos de um
    minuto (toda música de verdade lá tem álbum). No navegador: bem curtas, ou com o nome do vídeo mas bem mais curtas
    que ele (o YouTube mostra a propaganda com o nome do vídeo que vem depois)."""
    a = (f.get("artista") or "").strip().lower()
    t = (f.get("titulo") or "").strip().lower()
    dur = f.get("duracao") or 0
    if t in _PALAVRAS_ANUNCIO or any(t.startswith(p + " ") or t.startswith(p + ":") for p in _PALAVRAS_ANUNCIO):
        return True
    if "spotify" in f.get("app", "").lower():
        return not a or a == "spotify" or t == "spotify" or (not (f.get("album") or "").strip() and 0 < dur < 65)
    if e_navegador(f.get("app")):
        if 0 < dur < CURTO:
            return True
        maior = _maior_duracao.get(chave(f), 0)
        return 0 < dur < maior * 0.5 and maior - dur > 20
    return False


def escolher(sessoes):
    """A fonte que você escolheu, se ela ainda estiver no painel. Senão, a que está tocando (se forem duas, a que o
    Windows mostra); senão, a pausada que tocou por último."""
    validas = [s for s in sessoes if (s.get("titulo") or "").strip()]
    pref = [s for s in validas if s["app"] == _preferida["app"]]
    if pref:
        return pref[0]
    tocando = [s for s in validas if s["status"] == "tocando"]
    if tocando:
        return max(tocando, key=lambda s: (s.get("atual", False), _visto.get(s["app"], 0)))
    pausadas = [s for s in validas if s["status"] in ("pausado", "parado")]
    if pausadas:
        return max(pausadas, key=lambda s: (_visto.get(s["app"], 0), s.get("atual", False)))
    return None


def posicao_agora(f, agora=None):
    """O Spotify só avisa a posição a cada 4 ou 5 segundos e o navegador só quando algo muda:
    enquanto toca, a posição é a última informada mais o tempo que passou desde então."""
    agora = time.time() if agora is None else agora
    pos = f.get("posicao") or 0.0
    if f.get("status") == "tocando" and f.get("atualizado"):
        pos += max(0.0, agora - f["atualizado"])
    if f.get("duracao"):
        pos = min(pos, f["duracao"])
    return round(max(0.0, pos), 2)


def _tipo_da_imagem(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _ler_agora():
    """Lê o painel (no máximo uma vez a cada 0,7 s, mesmo com a janela e a faixa pedindo juntas)."""
    with _lock:
        agora = time.time()
        if agora - _ultima["quando"] < 0.7:
            return _ultima["sessoes"]
        querem = [k for k, t in _primeira_vez.items() if k not in _capas and agora - t >= ESPERA_CAPA and _tentou_capa.get(k, 0) < 4]
        sessoes = _ler_sessoes(querem)
        for s in sessoes:
            k = chave(s)
            _primeira_vez.setdefault(k, agora)
            if s["status"] == "tocando" and _antes.get(s["app"]) != (k, "tocando"):
                _visto[s["app"]] = agora   # começou a tocar ou trocou de música
            _antes[s["app"]] = (k, s["status"])
            if not e_anuncio(s):  # a duração de uma propaganda com o nome do vídeo não conta como a do vídeo
                _maior_duracao[k] = max(_maior_duracao.get(k, 0), s.get("duracao") or 0)
            if k in querem:
                _tentou_capa[k] = _tentou_capa.get(k, 0) + 1
            capa = s.pop("capa", None)
            if capa:
                _capas[k] = (capa, _tipo_da_imagem(capa))
                while len(_capas) > 20:
                    _capas.popitem(last=False)
        while len(_maior_duracao) > 200:
            _maior_duracao.pop(next(iter(_maior_duracao)))
        while len(_primeira_vez) > 200:
            _primeira_vez.pop(next(iter(_primeira_vez)))
        _ultima.update(quando=agora, sessoes=sessoes)
    anotar_historico(sessoes, agora)
    return sessoes


# ---------------------------------------------------------------- histórico de músicas

def _arq_historico():
    return CTX["DATA"] / "musicas.json"


def anotar_historico(sessoes, agora):
    """Uma música entra no histórico depois de tocar 30 s seguidos. Propaganda não entra, e a mesma música
    pausada e retomada logo depois não conta duas vezes."""
    for s in sessoes:
        if s["status"] != "tocando" or not (s.get("titulo") or "").strip() or e_anuncio(s):
            continue
        desde = _visto.get(s["app"])
        k = chave(s)
        if not desde or agora - desde < NO_HISTORICO or _anotadas.get(s["app"]) == (k, desde):
            continue
        _anotadas[s["app"]] = (k, desde)
        try:
            with CTX["lock"]:
                h = CTX["ler_json"](_arq_historico(), [])
                if not isinstance(h, list):
                    h = []
                if any(x.get("k") == k and x.get("t", 0) > agora - 15 * 60 for x in h[-20:]):
                    continue
                h.append({"t": int(desde), "k": k, "titulo": s["titulo"].strip(), "artista": (s.get("artista") or "").strip(),
                          "fonte": nome_da_fonte(s["app"]), "dur": round(s.get("duracao") or 0)})
                CTX["gravar_json"](_arq_historico(), h[-HISTORICO_MAX:])
        except Exception as e:
            _log("não consegui guardar no histórico:", e)


def historico(agora=None):
    """O que tocou hoje (desde a meia-noite) e um resumo dos últimos 7 dias."""
    agora = time.time() if agora is None else agora
    h = CTX["ler_json"](_arq_historico(), [])
    h = h if isinstance(h, list) else []
    lt = time.localtime(agora)
    meia_noite = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    semana = [x for x in h if x.get("t", 0) >= agora - 7 * 86400]

    def mais(chave_de, nome_de):
        conta, nomes = {}, {}
        for x in semana:
            c = chave_de(x)
            if c:
                conta[c] = conta.get(c, 0) + 1
                nomes[c] = nome_de(x)
        return [{"nome": nomes[c], "vezes": n} for c, n in sorted(conta.items(), key=lambda kv: -kv[1])[:10]]
    return {
        "hoje": [x for x in reversed(h) if x.get("t", 0) >= meia_noite][:200],
        "semana": len(semana),
        "minutos_semana": round(sum(min(x.get("dur") or 0, 900) for x in semana) / 60),
        "musicas": mais(lambda x: x.get("k"), lambda x: {"titulo": x["titulo"], "artista": x["artista"]}),
        "artistas": mais(lambda x: normal(x.get("artista") or ""), lambda x: x["artista"]),
    }


def vigiar(intervalo=15):
    """Lê o painel de vez em quando mesmo sem a janela aberta, para o histórico não perder músicas."""
    def loop():
        while True:
            time.sleep(intervalo)
            try:
                if _cfg().get("ligado", True) and disponivel()[0]:
                    _ler_agora()
            except Exception as e:
                _log("histórico:", e)
    threading.Thread(target=loop, daemon=True).start()


def fontes(sessoes):
    """As fontes com alguma música no painel, quando são mais de uma (para você escolher qual mostrar)."""
    v = [s for s in sessoes if (s.get("titulo") or "").strip()]
    if len(v) < 2:
        return []
    return [{"app": s["app"], "fonte": nome_da_fonte(s["app"]), "titulo": s["titulo"].strip(), "tocando": s["status"] == "tocando"}
            for s in v]


def faixa_atual():
    sessoes = _ler_agora()
    if _preferida["app"] and not any(s["app"] == _preferida["app"] for s in sessoes):
        _preferida["app"] = ""  # a fonte escolhida fechou: volta a escolher sozinha
    s = escolher(sessoes)
    if not s:
        return None
    k = chave(s)
    f = {"chave": k, "app": s["app"], "fonte": nome_da_fonte(s["app"]), "titulo": s["titulo"].strip(),
         "artista": s["artista"].strip(), "album": s["album"].strip(), "tocando": s["status"] == "tocando",
         "posicao": posicao_agora(s), "duracao": round(s.get("duracao") or 0.0, 2), "botoes": s["botoes"],
         "capa": f"/api/tocando/capa/{k}" if k in _capas else "", "anuncio": e_anuncio(s),
         "fontes": fontes(sessoes), "escolhida": bool(_preferida["app"])}
    _faixas[k] = f
    _faixas.move_to_end(k)
    while len(_faixas) > 30:
        _faixas.popitem(last=False)
    return f


# ---------------------------------------------------------------- limpar o nome que vem do YouTube

_LIXO = (r"official|oficial|video|vídeo|videoclipe|clipe|clip|lyrics?|letra|legendad[oa]|tradução|traducao|"
         r"audio|áudio|visuali[sz]er|hd|hq|4k|8k|1080p|720p|mv|m/v|remaster(ed)?|explicit|explícito|"
         r"color coded|full song|music video|performance video|dance video")
_RX_PARENTESES = re.compile(r"\s*[\(\[\{【]([^\)\]\}】]*)[\)\]\}】]")
_RX_LIXO = re.compile(r"\b(" + _LIXO + r")\b", re.I)
_RX_FEAT = re.compile(r"\s*[\(\[]?\s*\b(feat\.?|ft\.?|featuring|participação)\s[^\)\]]*[\)\]]?", re.I)
_RX_DEPOIS_DO_TRACO = re.compile(r"\s+[-–—]\s+((\d{4}\s+)?remaster(ed)?(\s+\d{4})?|ao vivo|live|radio edit|"
                                 r"single version|album version|mono|stereo|bonus track|versão.*|version)\s*$", re.I)
_SEPARADORES = re.compile(r"\s+[-–—~]\s+|\s+[-–—]|[-–—]\s+")


def limpar_titulo(t):
    """'Artista - Música (Official Video) [4K]' -> 'Artista - Música'. Partes entre parênteses que não são
    propaganda do vídeo (como '(Live At Wembley)') ficam."""
    t = (t or "").strip()
    t = _RX_PARENTESES.sub(lambda m: "" if _RX_LIXO.search(m.group(1)) else m.group(0), t)
    t = re.split(r"\s+[|│]\s+|\s+//\s+", t)[0]
    t = re.sub(r"(\s+#\S+)+\s*$", "", t)                     # hashtags no fim
    t = re.sub(r"\s+(official|oficial)\s+(music\s+)?(video|vídeo|audio|áudio|clipe)\s*$", "", t, flags=re.I)
    t = _RX_DEPOIS_DO_TRACO.sub("", t)
    t = re.sub(r'^["“”\']+|["“”\']+$', "", t.strip())
    return re.sub(r"\s{2,}", " ", t).strip(" -–—")


def limpar_canal(a):
    a = (a or "").strip()
    a = re.sub(r"\s*-\s*topic$", "", a, flags=re.I)          # canais automáticos do YouTube: "Artista - Topic"
    a = re.sub(r"\s*vevo$", "", a, flags=re.I)
    a = re.sub(r"\s+(official|oficial|tv|channel|canal)$", "", a, flags=re.I)
    return a.strip()


def sem_feat(t):
    return re.sub(r"\s{2,}", " ", _RX_FEAT.sub("", t or "")).strip()


def separar(t):
    """'Artista - Música' -> ('Artista', 'Música'); None quando não tem o traço."""
    partes = _SEPARADORES.split(t or "", maxsplit=1)
    if len(partes) == 2 and partes[0].strip() and partes[1].strip():
        return partes[0].strip(), partes[1].strip().strip('"“”')
    return None


def candidatos(f):
    """Jeitos de procurar a mesma música, do mais fiel ao mais limpo: (música, artista, álbum)."""
    t, a, alb = f.get("titulo", "").strip(), f.get("artista", "").strip(), f.get("album", "").strip()
    out = [(t, a, alb)]
    tl, al = limpar_titulo(t), limpar_canal(a)
    sep = separar(tl)
    if sep:
        out.append((sep[1], sep[0], ""))
    out.append((tl, al, ""))
    for mus, art, _ in list(out):
        if sem_feat(mus) != mus:
            out.append((sem_feat(mus), art, ""))
    vistos, unicos = set(), []
    for mus, art, alb_ in out:
        k = (normal(mus), normal(art), alb_)
        if mus and art and k not in vistos:
            vistos.add(k)
            unicos.append((mus, art, alb_))
    return unicos


def normal(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.replace("&", " and ")).strip()


def _base(t):
    return normal(_RX_PARENTESES.sub("", sem_feat(t or "")).split(" - ")[0])


def parecido(a, b):
    a, b = _base(a), _base(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    pa, pb = set(a.split()), set(b.split())
    return len(pa & pb) / max(len(pa), len(pb)) >= 0.6


def artista_parecido(a, b):
    na, nb = normal(a), normal(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    def nomes(s):  # "Anitta e Pedro Sampaio feat Fulano" -> {"anitta", "pedro sampaio", "fulano"}
        return {x.strip() for x in re.split(r"\s+(?:and|feat|ft|featuring|x|e|com|with|vs)\s+", s) if x.strip()}
    return bool(nomes(na) & nomes(nb))


# ---------------------------------------------------------------- letras (LRCLIB)

def _http_json(url, headers=None, espera=15):
    h = {"User-Agent": AGENTE, "Accept": "application/json"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=espera) as r:
        return json.loads(r.read(5_000_000).decode("utf-8"))


def _pasta():
    p = CTX["DATA"] / "letras"
    p.mkdir(exist_ok=True)
    return p


def _arq_letra(f):
    k = hashlib.sha1(f"{normal(f['artista'])}|{normal(f['titulo'])}".encode("utf-8")).hexdigest()[:20]
    return _pasta() / f"{k}.json"


def ler_lrc(txt):
    """'[01:02.50] linha' -> [[62.5, 'linha'], ...], em ordem. Linhas com dois horários entram duas vezes."""
    out = []
    for linha in (txt or "").splitlines():
        tempos = re.findall(r"\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]", linha)
        if not tempos:
            continue
        texto = re.sub(r"\[[^\]]*\]", "", linha).strip()
        for m, s in tempos:
            out.append([round(int(m) * 60 + float(s.replace(":", ".")), 2), texto])
    out.sort(key=lambda x: x[0])
    return out


def _linhas_de_verdade(r):
    txt = r.get("plainLyrics") or "\n".join(t for _, t in ler_lrc(r.get("syncedLyrics")))
    return [x for x in (txt or "").splitlines() if x.strip()]


def _serve(r):
    """Letras do LRCLIB com só uma ou duas linhas (como 'teste') são descartadas."""
    return bool(r) and (r.get("instrumental") or len(_linhas_de_verdade(r)) >= 4)


def _pedido_lrclib(caminho, params):
    agora = time.time()
    if agora < _lrclib["pausa_ate"]:
        raise RuntimeError("O LRCLIB pediu para esperar um pouco.")
    espera = ESPACO - (agora - _lrclib["ultimo"])
    if espera > 0:
        time.sleep(espera)
    _lrclib["ultimo"] = time.time()
    try:
        return _http_json(f"{LRCLIB}/{caminho}?" + urllib.parse.urlencode(params))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 429:
            try:
                _lrclib["pausa_ate"] = time.time() + float(e.headers.get("Retry-After") or 60)
            except (TypeError, ValueError, AttributeError):
                _lrclib["pausa_ate"] = time.time() + 60
        raise


def _escolher_na_busca(lista, mus, art, duracao):
    bons = [r for r in lista or [] if parecido(r.get("trackName") or r.get("name"), mus)
            and artista_parecido(r.get("artistName"), art) and _serve(r)]
    if not bons:
        return None

    def nota(r):
        perto = bool(duracao) and abs((r.get("duration") or 0) - duracao) <= 3
        return (perto, bool(r.get("syncedLyrics")), len(_linhas_de_verdade(r)))
    return max(bons, key=nota)


def buscar_lrclib(f):
    """Procura a letra: primeiro o pedido exato (nome, artista, álbum e duração), depois a busca geral."""
    dur = round(f.get("duracao") or 0)
    dur = dur if 1 <= dur <= 3600 else 0
    cands = candidatos(f)
    for mus, art, alb in cands[:4]:
        p = {"track_name": mus, "artist_name": art}
        if alb:
            p["album_name"] = alb
        if dur:
            p["duration"] = dur
        r = _pedido_lrclib("get", p)
        if _serve(r):
            return r
    mus, art, _ = cands[1] if len(cands) > 1 else cands[0]
    r = _escolher_na_busca(_pedido_lrclib("search", {"track_name": mus, "artist_name": art}), mus, art, dur)
    if r:
        return r
    return _escolher_na_busca(_pedido_lrclib("search", {"q": f"{art} {mus}"}), mus, art, dur)


def letra(f):
    """A letra da música, guardada na pasta de dados depois da primeira vez."""
    if f.get("anuncio"):
        return {"estado": "sem_busca"}
    arq = _arq_letra(f)
    with _lock_lrclib:
        guardada = CTX["ler_json"](arq, None)
        if guardada and (guardada["estado"] != "nao_achou" or time.time() - guardada.get("quando", 0) < NAO_ACHOU_DE_NOVO):
            return guardada
        try:
            r = buscar_lrclib(f)
        except Exception as e:
            _log("não consegui buscar a letra de", f.get("titulo"), "-", e)
            return {"estado": "erro", "erro": "Não consegui buscar a letra agora. Confira a internet e tente de novo."}
        out = {"titulo": f["titulo"], "artista": f["artista"], "quando": time.time(), "fonte": "LRCLIB",
               "genius_url": (guardada or {}).get("genius_url", "")}
        if not r:
            out.update(estado="nao_achou")
        elif r.get("instrumental"):
            out.update(estado="instrumental")
        else:
            linhas = ler_lrc(r.get("syncedLyrics"))
            # letra sincronizada de uma versão com outra duração ficaria fora do tempo: aí ela aparece inteira
            if linhas and f.get("duracao") and abs((r.get("duration") or 0) - f["duracao"]) > 3:
                linhas = []
            out.update(estado="achou", linhas=linhas or None,
                       texto=(r.get("plainLyrics") or "\n".join(t for _, t in ler_lrc(r.get("syncedLyrics")))).strip(),
                       lrclib_id=r.get("id"))
        CTX["gravar_json"](arq, out)
        return out


# ---------------------------------------------------------------- Genius (só o link para a página da música)

def _cfg():
    return CTX["get_cfg"]().get("tocando") or {}


def _termos(f):
    c = candidatos(f)
    mus, art, _ = c[1] if len(c) > 1 else c[0]
    return sem_feat(limpar_titulo(mus)), art


def busca_genius(chave_api, q):
    r = _http_json(f"{GENIUS}/search?" + urllib.parse.urlencode({"q": q}), {"Authorization": "Bearer " + chave_api})
    return [h.get("result") or {} for h in (r.get("response") or {}).get("hits") or [] if h.get("type") == "song"]


def link_genius(f):
    """A página da música no Genius (pela busca oficial deles, com a chave) ou, sem chave, a busca do Genius."""
    mus, art = _termos(f)
    arq = _arq_letra(f)
    guardada = CTX["ler_json"](arq, None) or {}
    if guardada.get("genius_url"):
        return guardada["genius_url"], True
    chave_api = _cfg().get("genius_key", "")
    if chave_api:
        try:
            for r in busca_genius(chave_api, f"{mus} {art}"):
                url = r.get("url") or ""
                if url.startswith("https://genius.com/") and parecido(r.get("title"), mus) \
                        and artista_parecido((r.get("primary_artist") or {}).get("name"), art):
                    if guardada:
                        guardada["genius_url"] = url
                        with _lock_lrclib:
                            CTX["gravar_json"](arq, guardada)
                    return url, True
        except Exception as e:
            _log("a busca do Genius falhou:", e)
    return "https://genius.com/search?" + urllib.parse.urlencode({"q": f"{mus} {art}"}), False


def _abrir_janela(url):
    nav = CTX["navegador_app"]() if os.name == "nt" else ""
    if nav:
        subprocess.Popen([nav, f"--app={url}", "--window-size=1000,1000"])
    else:
        webbrowser.open(url)


# ---------------------------------------------------------------- rotas

def _faixa_pela_chave(k):
    f = _faixas.get(k)
    if f is None:
        atual = faixa_atual()
        f = atual if atual and atual["chave"] == k else None
    return f


def rotas(app):
    from flask import Response, jsonify, request

    @app.get("/api/tocando")
    def api_tocando():
        if not _cfg().get("ligado", True):
            return jsonify({"ligado": False})
        ok, motivo = disponivel()
        if not ok:
            return jsonify({"ligado": True, "disponivel": False, "motivo": motivo})
        try:
            f = faixa_atual()
        except Exception as e:
            _log("não consegui ler o painel de mídia:", e)
            return jsonify({"ligado": True, "disponivel": True, "faixa": None, "erro": "Não consegui ler o que está tocando agora."})
        return jsonify({"ligado": True, "disponivel": True, "faixa": f})

    @app.get("/api/tocando/historico")
    def api_tocando_historico():
        return jsonify(historico())

    @app.post("/api/tocando/historico/limpar")
    def api_tocando_historico_limpar():
        with CTX["lock"]:
            CTX["gravar_json"](_arq_historico(), [])
        return jsonify({"ok": True})

    @app.get("/api/tocando/capa/<k>")
    def api_tocando_capa(k):
        c = _capas.get(k)
        if not c:
            return ("", 404)
        return Response(c[0], mimetype=c[1], headers={"Cache-Control": "max-age=3600"})

    @app.post("/api/tocando/controle")
    def api_tocando_controle():
        b = request.get_json(force=True) or {}
        acao = b.get("acao")
        if acao not in ("tocar", "pausar", "alternar", "anterior", "proximo", "posicao"):
            return jsonify({"error": "Botão desconhecido."}), 400
        try:
            segundos = float(b.get("segundos") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "Ponto da música inválido."}), 400
        app_id = b.get("app") or ((faixa_atual() or {}).get("app"))
        if not app_id:
            return jsonify({"error": "Nada tocando agora."}), 400
        try:
            ok = _comando(app_id, acao, segundos)
        except Exception as e:
            _log("o botão não funcionou:", e)
            ok = False
        with _lock:
            _ultima["quando"] = 0.0  # a próxima leitura já mostra o efeito
        if not ok:
            return jsonify({"error": "O programa que está tocando não aceitou esse botão."}), 400
        return jsonify({"ok": True})

    @app.post("/api/tocando/fonte")
    def api_tocando_fonte():
        """Quando duas fontes tocam juntas, qual mostrar ("" volta a escolher sozinha)."""
        _preferida["app"] = str((request.get_json(force=True) or {}).get("app") or "")
        return jsonify({"ok": True, "faixa": faixa_atual()})

    @app.get("/api/tocando/letra/<k>")
    def api_tocando_letra(k):
        f = _faixa_pela_chave(k)
        if not f:
            return jsonify({"error": "Essa música já não está tocando."}), 404
        out = dict(letra(f))
        out["chave"] = k
        out["tem_chave_genius"] = bool(_cfg().get("genius_key"))
        return jsonify(out)

    @app.post("/api/tocando/genius/<k>")
    def api_tocando_genius(k):
        f = _faixa_pela_chave(k)
        if not f:
            return jsonify({"error": "Essa música já não está tocando."}), 404
        url, pagina = link_genius(f)
        try:
            _abrir_janela(url)
        except Exception as e:
            return jsonify({"error": f"Não consegui abrir a janela do Genius: {e}"}), 400
        return jsonify({"ok": True, "url": url, "pagina": pagina})

    @app.get("/api/tocando/config")
    def api_tocando_cfg():
        c = _cfg()
        k = c.get("genius_key", "")
        ok, motivo = disponivel()
        return jsonify({"ligado": c.get("ligado", True), "genius": bool(k), "genius_dica": ("•••• " + k[-4:]) if k else "",
                        "disponivel": ok, "motivo": motivo})

    @app.post("/api/tocando/config")
    def api_tocando_cfg_set():
        b = request.get_json(force=True) or {}
        aviso = ""
        if b.get("genius_key"):
            k = str(b["genius_key"]).strip()
            try:
                busca_genius(k, "Bohemian Rhapsody Queen")
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    return jsonify({"error": "O Genius não aceitou essa chave. Confira se copiou o “Client Access Token” inteiro."}), 400
                aviso = "Guardei a chave, mas o Genius não respondeu agora para eu testar."
            except Exception:
                aviso = "Guardei a chave, mas não consegui falar com o Genius agora para testar."
        with CTX["lock"]:
            cfg = CTX["get_cfg"]()
            t = cfg.setdefault("tocando", {})
            if "ligado" in b:
                t["ligado"] = bool(b["ligado"])
            if b.get("genius_key"):
                t["genius_key"] = str(b["genius_key"]).strip()
            if b.get("tirar_genius"):
                t.pop("genius_key", None)
            CTX["save_cfg"](cfg)
        return jsonify({"ok": True, "aviso": aviso})


def iniciar(app, ctx):
    CTX.update(ctx)
    rotas(app)
    if not os.environ.get("ESTANTE_SEM_VIGIA_MUSICA"):
        vigiar()
