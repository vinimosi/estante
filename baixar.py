"""
Capítulos para ler sem internet, baixados da WeebCentral (weebcentral.com) do mesmo jeito que o Mihon faz:
a busca do site, a página com a lista de capítulos e a página de cada capítulo, que lista as imagens. As imagens
são arquivos comuns. Um pedido ao site a cada 2 segundos, como a extensão do Mihon.

Cada capítulo vira um arquivo CBZ em DATA/baixados/<série>/<número>.cbz, aberto pelo leitor da Estante.
Nada de capítulo pago, nada de verificação contra robôs: se o site pedir isso, o download para e avisa.
"""
import html as htmlmod
import io
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import deque
from pathlib import Path

from flask import abort, jsonify, request, send_file

import leitura as L
from caminhos import VERSAO

BASE = "https://weebcentral.com"
NOME_FONTE = "WeebCentral"
AGENTE = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Estante/{VERSAO}"
ESPACO_SITE = 2.0     # segundos entre um pedido e outro ao site (como a extensão do Mihon)
ESPACO_IMAGEM = 0.3   # entre uma imagem e outra
IMAGENS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
        ".avif": "image/avif"}

_rede = {"site": threading.Lock(), "imagem": threading.Lock()}
_ultimo = {"site": 0.0, "imagem": 0.0}


class Bloqueado(Exception):
    """O site pediu verificação contra robôs (ou recusou): a Estante não passa por isso."""


def _abrir(url, imagem=False):
    """Um pedido ao site, respeitando o espaço entre pedidos. Devolve os bytes."""
    qual = "imagem" if imagem else "site"
    with _rede[qual]:
        espera = (ESPACO_IMAGEM if imagem else ESPACO_SITE) - (time.time() - _ultimo[qual])
        if espera > 0:
            time.sleep(espera)
        try:
            corpo = _pedir(url, imagem)
        finally:
            _ultimo[qual] = time.time()
    if not imagem and (b"challenge-form" in corpo[:20000] or b"cf-chl-" in corpo[:20000]):
        raise Bloqueado("o site pediu verificação contra robôs")
    return corpo


def _pedir(url, imagem):
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Referer": BASE + "/",
                                               "Accept": "image/*" if imagem else "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read(60_000_000)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429, 503):
            raise Bloqueado(f"o site respondeu {e.code}") from None
        raise


def _texto(url):
    return _abrir(url).decode("utf-8", "replace")


# ---------------------------------------------------------------- o site

def buscar(nome):
    """[{id, slug, titulo, capa}] da busca da WeebCentral."""
    q = re.sub(r"[!#:(),-]", " ", nome).strip()
    url = (f"{BASE}/search/data?" + urllib.parse.urlencode({
        "text": q, "limit": 32, "offset": 0, "display_mode": "Full Display", "sort": "Best Match", "order": "Descending",
        "official": "Any", "anime": "Any", "adult": "Any"}))
    pagina = _texto(url)
    out, vistos = [], set()
    for m in re.finditer(r'<a href="https://weebcentral\.com/series/([A-Z0-9]+)/([^"]*)"(.*?)</a>', pagina, re.S):
        sid, slug, dentro = m.group(1), m.group(2), m.group(3)
        if sid in vistos:
            continue
        vistos.add(sid)
        alt = re.search(r'alt="(.*?) cover"', dentro)
        capa = re.search(r'<img src="([^"]+)"', dentro)
        out.append({"id": sid, "slug": slug, "titulo": htmlmod.unescape(alt.group(1)) if alt else slug.replace("-", " "),
                    "capa": capa.group(1) if capa else ""})
    return out


def capitulos(serie_id):
    """[{id, nome, n}] do mais novo para o mais antigo, só os que têm número."""
    pagina = _texto(f"{BASE}/series/{serie_id}/full-chapter-list")
    out = []
    for m in re.finditer(r'<a href="(?:https://weebcentral\.com)?/chapters/([A-Z0-9]+)"(.*?)</a>', pagina, re.S):
        nome = re.search(r'<span class="">\s*(.*?)\s*</span>', m.group(2), re.S)
        nome = htmlmod.unescape(nome.group(1)).strip() if nome else ""
        n = _numero(nome)
        if n is not None and not any(c["id"] == m.group(1) for c in out):
            out.append({"id": m.group(1), "nome": nome, "n": n})
    return out


def _numero(nome):
    if re.search(r"\b(special|side ?story|extra|bonus|omake|notice|announcement|hiatus|illustration)", nome, re.I) \
            and not re.search(r"\bchapter\s*\d", nome, re.I):
        return None  # extras ("Side Story 2") ficam de fora: senão virariam o capítulo 2
    m = re.search(r"(?:chapter|episode|ch\.?)\s*(\d+(?:\.\d+)?)", nome, re.I) or re.search(r"(\d+(?:\.\d+)?)(?!.*\d)", nome)
    return float(m.group(1)) if m else None


def imagens(cap_id):
    pagina = _texto(f"{BASE}/chapters/{cap_id}/images?is_prev=False&reading_style=long_strip")
    secao = pagina[pagina.find('id="chapter-images"'):] if 'id="chapter-images"' in pagina else pagina
    return [htmlmod.unescape(u) for u in re.findall(r'<img\s[^>]*?src="(https?://[^"]+)"', secao, re.S)
            if "/static/" not in u]


# ---------------------------------------------------------------- arquivos

def pasta():
    p = L.CTX["DATA"] / "baixados"
    p.mkdir(exist_ok=True)
    return p


def arquivo(sid, n):
    return pasta() / sid / f"{L.num_txt(n)}.cbz"


def baixados(s):
    """Os capítulos baixados de uma série, em ordem: [{n, nome}] (só os que o arquivo ainda existe)."""
    out = []
    for k, c in (s.get("baixados") or {}).items():
        n = L.num(k)
        if n is not None and arquivo(s["id"], n).exists():
            out.append({"n": n, "nome": c.get("nome") or ""})
    return sorted(out, key=lambda c: c["n"])


def baixar_capitulo(sid, cap, progresso=None):
    urls = imagens(cap["id"])
    if not urls:
        raise ValueError("o capítulo não tem imagens (pode ser pago ou ter saído do site)")
    destino = arquivo(sid, cap["n"])
    destino.parent.mkdir(parents=True, exist_ok=True)
    parte = destino.with_suffix(".parte")
    with zipfile.ZipFile(parte, "w", zipfile.ZIP_STORED) as z:  # as imagens já vêm comprimidas
        for i, u in enumerate(urls):
            ext = os.path.splitext(urllib.parse.urlparse(u).path)[1].lower()
            z.writestr(f"{i + 1:03d}{ext if ext in IMAGENS else '.jpg'}", _abrir(u, imagem=True))
            if progresso:
                progresso(i + 1, len(urls))
    os.replace(parte, destino)
    with L.CTX["lock"]:
        d = L._load()
        s = L.achar(d, sid)
        if s:
            s.setdefault("baixados", {})[L.num_txt(cap["n"])] = {"nome": cap["nome"], "paginas": len(urls), "t": time.time()}
            L._save(d)
        elif destino.exists():
            destino.unlink()  # a série foi apagada enquanto baixava


def tamanho():
    total = arquivos = 0
    for f in pasta().rglob("*.cbz"):
        total += f.stat().st_size
        arquivos += 1
    return total, arquivos


def apagar(sid, quais):
    """quais: lista de números, "lidos" ou "todos". Devolve quantos apagou."""
    feitos = 0
    with L.CTX["lock"]:
        d = L._load()
        s = L.achar(d, sid)
        if not s:
            return 0
        lido = s.get("ultimo_lido")
        for k in list((s.get("baixados") or {}).keys()):
            n = L.num(k)
            if quais == "todos" or (quais == "lidos" and lido is not None and n is not None and n <= lido) \
                    or (isinstance(quais, list) and n in quais):
                f = arquivo(sid, n)
                if f.exists():
                    f.unlink()
                s["baixados"].pop(k, None)
                feitos += 1
        L._save(d)
    try:
        (pasta() / sid).rmdir()  # só some se ficou vazia
    except OSError:
        pass
    return feitos


# ---------------------------------------------------------------- a fila (um capítulo de cada vez, devagar)

_fila = deque()
_fila_lock = threading.Lock()
estado = {"ativo": False, "atual": None, "feitos": 0, "erros": 0, "erro": ""}


def enfileirar(sid, caps):
    with _fila_lock:
        ja = {(x[0], x[1]["n"]) for x in _fila}
        if estado["atual"]:
            ja.add((estado["atual"]["id"], estado["atual"]["n"]))  # o que está baixando agora também conta
        novos = [c for c in caps if (sid, c["n"]) not in ja]
        _fila.extend((sid, c) for c in novos)
        if not estado["ativo"]:
            estado.update(ativo=True, feitos=0, erros=0, erro="")
            threading.Thread(target=_trabalhar, daemon=True).start()
    return len(novos)


def _trabalhar():
    try:
        while True:
            with _fila_lock:
                if not _fila:
                    estado.update(ativo=False, atual=None)  # dentro da trava: quem enfileirar agora começa outra volta
                    return
                sid, cap = _fila.popleft()
                estado["atual"] = {"id": sid, "serie": "", "n": cap["n"], "pagina": 0, "paginas": 0}
            s = L.achar(L._load(), sid)
            estado["atual"]["serie"] = (s or {}).get("name", "")
            try:
                baixar_capitulo(sid, cap, lambda i, t: estado["atual"].update(pagina=i, paginas=t))
                estado["feitos"] += 1
            except Bloqueado as e:
                print(f"[baixar] {NOME_FONTE} parou: {e}")
                estado["erro"] = f"A {NOME_FONTE} parou de responder ({e}). Tente de novo mais tarde."
                with _fila_lock:
                    estado["erros"] += 1 + len(_fila)
                    _fila.clear()
            except Exception as e:
                print(f"[baixar] capítulo {L.num_txt(cap['n'])} de {(s or {}).get('name', sid)}: {e}")
                estado["erros"] += 1
    except Exception as e:  # nunca deixa a fila marcada como ativa sem ninguém trabalhando nela
        print("[baixar] fila:", e)
        with _fila_lock:
            estado.update(ativo=False, atual=None)


def situacao():
    with _fila_lock:
        pend = {}
        for sid, c in _fila:
            pend.setdefault(sid, []).append(L.num_txt(c["n"]))
        if estado["atual"]:
            pend.setdefault(estado["atual"]["id"], []).insert(0, L.num_txt(estado["atual"]["n"]))
    return {**estado, "pendentes": pend}


# ---------------------------------------------------------------- ligar a série da Estante à da WeebCentral

def achar_no_site(s):
    """Procura pelo nome e pelos nomes alternativos. Liga sozinha quando um único resultado tem o mesmo nome."""
    nomes = [n for n in dict.fromkeys([s["name"]] + list(s.get("titulos_alt") or [])) if n][:3]
    chaves = {L.chave_nome(n) for n in [s["name"]] + list(s.get("titulos_alt") or [])} - {""}
    vistos, todos = set(), []
    for nome in nomes:
        for r in buscar(nome):
            if r["id"] not in vistos:
                vistos.add(r["id"])
                todos.append(r)
        iguais = [r for r in todos if L.chave_nome(r["titulo"]) in chaves or L.chave_nome(r["slug"].replace("-", " ")) in chaves]
        if len(iguais) == 1:
            return iguais[0], []
    return None, todos[:12]


def _ligar(sid, r):
    with L.CTX["lock"]:
        d = L._load()
        s = L.achar(d, sid)
        if not s:
            abort(404)
        s["weebcentral"] = {"id": r["id"], "slug": r.get("slug", ""), "titulo": r.get("titulo", "")}
        L._save(d)


def rotas(bp):
    @bp.get("/api/leitura/<sid>/baixar")
    def api_baixar_ver(sid):
        """O que dá para baixar desta série: os capítulos da WeebCentral, com os que já estão baixados."""
        s = L.achar(L._load(), sid)
        if not s:
            abort(404)
        if s.get("local"):
            return jsonify({"error": "Esta série já está no seu PC."}), 400
        try:
            if not s.get("weebcentral"):
                r, parecidas = achar_no_site(s)
                if not r:
                    return jsonify({"ligada": None, "parecidas": parecidas})
                _ligar(sid, r)
                s = L.achar(L._load(), sid)
            caps = capitulos(s["weebcentral"]["id"])
        except Bloqueado as e:
            return jsonify({"error": f"A {NOME_FONTE} não respondeu agora ({e}). Tente de novo mais tarde."}), 502
        except Exception as e:
            print(f"[baixar] {s['name']}: {e}")
            return jsonify({"error": f"Não consegui falar com a {NOME_FONTE} agora. Tente de novo daqui a pouco."}), 502
        tem = {c["n"] for c in baixados(s)}
        pend = set(situacao()["pendentes"].get(sid, []))
        return jsonify({"ligada": s["weebcentral"], "fonte": NOME_FONTE, "lido": s.get("ultimo_lido"),
                        "capitulos": [{"n": c["n"], "nome": c["nome"], "baixado": c["n"] in tem, "na_fila": L.num_txt(c["n"]) in pend}
                                      for c in sorted(caps, key=lambda c: c["n"])]})

    @bp.post("/api/leitura/<sid>/baixar/ligar")
    def api_baixar_ligar(sid):
        b = request.get_json(force=True) or {}
        if not re.fullmatch(r"[A-Z0-9]{10,40}", str(b.get("id") or "")):
            return jsonify({"error": "Série inválida."}), 400
        if b.get("desligar"):
            with L.CTX["lock"]:
                d = L._load()
                s = L.achar(d, sid)
                if s:
                    s.pop("weebcentral", None)
                    L._save(d)
            return jsonify({"ok": True})
        _ligar(sid, {"id": b["id"], "slug": str(b.get("slug") or ""), "titulo": str(b.get("titulo") or "")})
        return jsonify({"ok": True})

    @bp.post("/api/leitura/<sid>/baixar")
    def api_baixar(sid):
        b = request.get_json(force=True) or {}
        s = L.achar(L._load(), sid)
        if not s or not s.get("weebcentral"):
            abort(404)
        nums = {L.num(x) for x in b.get("nums") or []} - {None}
        try:
            caps = [c for c in capitulos(s["weebcentral"]["id"]) if c["n"] in nums]
        except Exception as e:
            print(f"[baixar] {s['name']}: {e}")
            return jsonify({"error": f"Não consegui falar com a {NOME_FONTE} agora."}), 502
        tem = {c["n"] for c in baixados(s)}
        caps = sorted([c for c in caps if c["n"] not in tem], key=lambda c: c["n"])
        return jsonify({"na_fila": enfileirar(sid, caps), **situacao()})

    @bp.get("/api/leitura/baixando")
    def api_baixando():
        return jsonify(situacao())

    @bp.post("/api/leitura/<sid>/baixados/apagar")
    def api_baixados_apagar(sid):
        q = (request.get_json(force=True) or {}).get("quais")
        if q not in ("lidos", "todos") and not isinstance(q, list):
            return jsonify({"error": "Escolha o que apagar."}), 400
        return jsonify({"apagados": apagar(sid, q if not isinstance(q, list) else [L.num(x) for x in q])})

    @bp.get("/api/leitura/baixados")
    def api_baixados():
        total, n = tamanho()
        return jsonify({"bytes": total, "capitulos": n})

    @bp.post("/api/leitura/baixados/apagar-lidos")
    def api_baixados_apagar_lidos():
        ids = [s["id"] for s in L._load()["series"] if s.get("baixados")]
        feitos = sum(apagar(sid, "todos" if (request.get_json(force=True) or {}).get("todos") else "lidos") for sid in ids)
        if (request.get_json(force=True) or {}).get("todos"):
            shutil.rmtree(pasta(), ignore_errors=True)  # sobras de downloads interrompidos
        total, n = tamanho()
        return jsonify({"apagados": feitos, "bytes": total, "capitulos": n})

    # ---- o leitor (o mesmo dos quadrinhos do PC). O capítulo vem pelo número dele, e não pela posição na lista,
    # que muda quando outro capítulo termina de baixar enquanto você lê.
    def _cap(sid, cap):
        s = L.achar(L._load(), sid)
        n = L.num(cap)
        if not s or n is None:
            abort(404)
        c = next((c for c in baixados(s) if c["n"] == n), None)
        if not c:
            abort(404)
        return s, c

    def _paginas(sid, n):
        with zipfile.ZipFile(arquivo(sid, n)) as z:
            return sorted(x for x in z.namelist() if os.path.splitext(x)[1].lower() in IMAGENS)

    @bp.get("/api/leitura/baixado/<sid>/<cap>")
    def api_baixado_paginas(sid, cap):
        s, c = _cap(sid, cap)
        return jsonify({"paginas": len(_paginas(sid, c["n"])), "pagina": (s.get("baixados_pagina") or {}).get(L.num_txt(c["n"]), 0)})

    @bp.get("/api/leitura/baixado/<sid>/<cap>/<int:p>")
    def api_baixado_pagina(sid, cap, p):
        _, c = _cap(sid, cap)
        ps = _paginas(sid, c["n"])
        if not 0 <= p < len(ps):
            abort(404)
        with zipfile.ZipFile(arquivo(sid, c["n"])) as z:
            dados = z.read(ps[p])
        return send_file(io.BytesIO(dados), mimetype=MIME.get(os.path.splitext(ps[p])[1].lower(), "image/jpeg"), max_age=86400)

    @bp.post("/api/leitura/baixado/<sid>/<cap>/progresso")
    def api_baixado_progresso(sid, cap):
        _, c = _cap(sid, cap)
        b = request.get_json(force=True) or {}
        with L.CTX["lock"]:
            d = L._load()
            s = L.achar(d, sid)
            if not s:
                abort(404)
            s.setdefault("baixados_pagina", {})[L.num_txt(c["n"])] = int(b.get("pagina") or 0)
            L.marcar_lido_no_leitor(d, s, c["n"], bool(b.get("fim")), "baixado")
            L._save(d)
        return jsonify({"ok": True})
