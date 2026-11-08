"""Indicações da Leitura: "no clima de quê?", escolha da semana, parecidas com uma série, a próxima quando uma série
acaba e a retrospectiva do mês ou do ano. Tudo sai dos dados de quem usa (a lista, os gêneros, o que leu e quando),
com a nota e as parecidas da comunidade do AniList e do MangaUpdates. Não existe lista fixa com o gosto de ninguém.

O MangaUpdates já vem em cada verificação da série (nota_mu, recs_mu, temas, guardados pelo aplicar_mu). O AniList
vem por uma fila devagar, 50 séries por pedido, a cada 30 dias por série (campo "al" da série)."""
import datetime
import random
import threading
import time
import urllib.error
from collections import Counter

from flask import abort, jsonify, request

import leitura as L

CAMPOS_AL = """id averageScore isAdult tags { name rank isMediaSpoiler }
recommendations(perPage: 10, sort: RATING_DESC) { nodes { rating mediaRecommendation {
  id title { english romaji } coverImage { large } averageScore genres countryOfOrigin isAdult tags { name rank isMediaSpoiler } } } }"""
REFAZER_AL = 30 * 86400
LIDAS = ("Lendo", "Terminado")
ADULTO = {"hentai", "adult", "smut"}

# cada clima é um conjunto de gêneros e etiquetas (do AniList e dos temas do MangaUpdates), em minúsculas;
# "sem" tira o que não combina (algo leve não pode ser tragédia)
CLIMAS = [
    {"chave": "romance", "nome": "Romance", "marcas": {"romance", "shoujo", "josei", "love triangle", "enemies to lovers",
     "office lover", "boys' love", "yuri", "heterosexual", "childhood friend/s"}},
    {"chave": "acao", "nome": "Ação", "marcas": {"action", "martial arts", "super power", "swordplay", "dungeon", "battle", "murim"}},
    {"chave": "comedia", "nome": "Comédia", "marcas": {"comedy", "parody", "satire", "gag humor"}},
    {"chave": "terror", "nome": "Terror", "marcas": {"horror", "thriller", "survival", "gore", "zombie", "death game", "psychological horror"}},
    {"chave": "leve", "nome": "Algo leve", "marcas": {"slice of life", "iyashikei", "food", "cooking", "family life",
     "cute girls doing cute things"}, "sem": {"tragedy", "horror", "gore"}},
    {"chave": "isekai", "nome": "Isekai", "marcas": {"isekai", "reincarnation", "transported to another world",
     "reincarnated in another world", "regression", "returner", "summoned to another world"}},
    {"chave": "drama", "nome": "Drama", "marcas": {"drama", "tragedy"}},
    {"chave": "fantasia", "nome": "Fantasia", "marcas": {"fantasy", "supernatural", "magic", "dragons", "elf", "demons"}},
    {"chave": "misterio", "nome": "Mistério", "marcas": {"mystery", "psychological", "detective", "crime"}},
]


# ---------------------------------------------------------------- o que a pessoa lê

def _marcas(s):
    al = s.get("al") or {}
    return {x.lower() for x in list(s.get("genres") or []) + list(al.get("tags") or []) + list(s.get("temas") or []) if x}


def _adulta(s):
    return bool((s.get("al") or {}).get("adulto")) or bool({g.lower() for g in s.get("genres") or []} & ADULTO)


def _nota(s):
    """De 0 a 1: a do AniList, se tiver; senão a do MangaUpdates; senão None."""
    al = (s.get("al") or {}).get("nota")
    if al:
        return al / 100
    mu = s.get("nota_mu")
    return mu / 10 if mu else None


def _lida(s):
    return not s.get("hidden") and (s.get("lista_anilist") in LIDAS or s.get("favorite") or (s.get("ultimo_lido") or 0) > 0)


def perfil(d):
    """O peso de cada gênero no que a pessoa lê: as séries lidas contam, as favoritas contam em dobro e cada
    capítulo aberto no histórico soma um pouco. De 0 a 1 (o gênero mais lido vale 1)."""
    lidos = Counter(x["s"] for x in d.get("leituras") or [])
    peso = Counter()
    for s in d["series"]:
        if not _lida(s):
            continue
        p = (2 if s.get("favorite") else 1) + min(3, lidos.get(s["id"], 0) * 0.2)
        for g in s.get("genres") or []:
            peso[g.lower()] += p
    topo = max(peso.values() or [1])
    return {g: v / topo for g, v in peso.items()}


def _afinidade(generos, pf):
    ws = sorted((pf.get(g.lower(), 0) for g in generos or []), reverse=True)[:3]
    return sum(ws) / 3 if ws else 0.3


# só para o texto do motivo; os gêneros continuam como vêm do MangaUpdates e do AniList no resto da Estante
GENEROS_PT = {"action": "ação", "adventure": "aventura", "comedy": "comédia", "drama": "drama", "fantasy": "fantasia",
              "horror": "terror", "mystery": "mistério", "psychological": "psicológico", "romance": "romance",
              "slice of life": "slice of life", "supernatural": "sobrenatural", "martial arts": "artes marciais",
              "historical": "histórico", "school life": "vida escolar", "sci-fi": "ficção científica", "sports": "esporte",
              "tragedy": "tragédia", "thriller": "suspense", "seinen": "seinen", "shounen": "shounen", "shoujo": "shoujo",
              "josei": "josei", "isekai": "isekai"}


def _generos_fortes(generos, pf, n=2):
    """Os gêneros desta série que a pessoa mais lê, em português, para o motivo (sem os adultos)."""
    gs = [g for g in sorted(generos or [], key=lambda g: -pf.get(g.lower(), 0))
          if pf.get(g.lower(), 0) > 0.3 and g.lower() in GENEROS_PT]
    return [GENEROS_PT[g.lower()] for g in gs][:n]


# ---------------------------------------------------------------- candidatas

def _na_estante(d):
    """Para saber se uma indicação já está na estante: pelo número do AniList, do MangaUpdates ou pelo nome."""
    por_al, por_mu, por_nome = {}, {}, {}
    for s in d["series"]:
        if s.get("anilist_id"):
            por_al[s["anilist_id"]] = s
        if s.get("mu_id"):
            por_mu[s["mu_id"]] = s
        for n in [s["name"]] + list(s.get("titulos_alt") or []):
            k = L.chave_nome(n)
            if k:
                por_nome.setdefault(k, s)
    return lambda aid=None, mid=None, nome="": (por_al.get(aid) if aid else None) or (por_mu.get(mid) if mid else None) \
        or (por_nome.get(L.chave_nome(nome)) if nome else None)


def _recs_das_lidas(d, achar):
    """As parecidas das séries que a pessoa leu, juntas: quantas lidas apontam para cada uma, e quais."""
    juntas = {}
    for s in d["series"]:
        if not _lida(s):
            continue
        for r in (s.get("al") or {}).get("recs") or []:
            k = ("a", r["anilist_id"])
            j = juntas.setdefault(k, {**r, "fontes": [], "peso": 0})
            j["fontes"].append(s["name"])
            j["peso"] += max(1, r.get("votos") or 1)
        for r in s.get("recs_mu") or []:
            if any(L.chave_nome(j["nome"]) == L.chave_nome(r["nome"]) for j in juntas.values()):
                continue
            k = ("m", r["mu_id"])
            j = juntas.setdefault(k, {"mu_id": r["mu_id"], "nome": r["nome"], "capa": r["capa"], "genres": [], "nota": None,
                                      "adulto": False, "fontes": [], "peso": 0})
            j["fontes"].append(s["name"])
            j["peso"] += 1
    return juntas


def candidatas(d=None):
    """As séries que valem indicar, cada uma com nota, gêneros, marcas, motivo e pontuação.
    Da estante: as da lista Quero ler e as pausadas. De fora: as parecidas das que a pessoa leu (sem conteúdo adulto)."""
    d = d or L._load()
    pf, achar = perfil(d), _na_estante(d)
    recs = _recs_das_lidas(d, achar)
    apontadas = {}  # série da estante -> as lidas que apontam para ela
    out = []
    for (tipo, rid), r in recs.items():
        s = achar(aid=r.get("anilist_id"), mid=r.get("mu_id"), nome=r["nome"])
        if s:
            apontadas.setdefault(s["id"], r["fontes"])
            continue
        if r.get("adulto"):
            continue
        nota = (r["nota"] / 100) if r.get("nota") else None
        out.append({"chave": f"{tipo}:{rid}", "de_fora": True, "anilist_id": r.get("anilist_id"), "mu_id": r.get("mu_id"),
                    "nome": r["nome"], "capa": r.get("capa") or "", "nota": r.get("nota"), "genres": r.get("genres") or [],
                    "marcas": {g.lower() for g in list(r.get("genres") or []) + list(r.get("tags") or [])}, "tipo": r.get("tipo") or "",
                    "motivo": "Parecida com " + _lista_nomes(r["fontes"]) + ", que você leu",
                    "pontos": 0.55 * (nota if nota is not None else 0.6) + 0.45 * _afinidade(r.get("genres"), pf)
                    + 0.04 * min(3, len(r["fontes"]))})
    for s in d["series"]:
        if s.get("hidden") or s.get("lista_anilist") not in ("Quero ler", "Pausado"):
            continue
        nota = _nota(s)
        if s["id"] in apontadas:
            motivo = "Parecida com " + _lista_nomes(apontadas[s["id"]]) + ", que você leu"
        elif s.get("lista_anilist") == "Pausado":
            motivo = f"Você pausou no capítulo {L.num_txt(s['ultimo_lido'])}" if s.get("ultimo_lido") else "Está entre as pausadas"
        else:
            gs = _generos_fortes(s.get("genres"), pf)
            motivo = "Está na sua lista Quero ler" + (" e é de " + " e ".join(gs) + ", que você mais lê" if gs else "")
        out.append({"chave": "s:" + s["id"], "de_fora": False, "id": s["id"], "nome": s["name"],
                    "capa": f"/covers/{s['cover']}" if s.get("cover") else "", "nota": round(nota * 100) if nota else None,
                    "genres": s.get("genres") or [], "marcas": _marcas(s), "tipo": s.get("tipo") or "", "motivo": motivo,
                    "lista": s.get("lista_anilist"), "lido": L.num_txt(s.get("ultimo_lido")) if s.get("ultimo_lido") else "",
                    "pontos": 0.55 * (nota if nota is not None else 0.6) + 0.45 * _afinidade(s.get("genres"), pf)
                    + (0.1 if s["id"] in apontadas else 0) + (0.3 if s.get("lista_anilist") == "Quero ler" else 0.2)})
    out.sort(key=lambda c: -c["pontos"])
    return out


def _lista_nomes(nomes):
    nomes = list(dict.fromkeys(nomes))
    if len(nomes) == 1:
        return nomes[0]
    if len(nomes) == 2:
        return nomes[0] + " e " + nomes[1]
    return f"{nomes[0]}, {nomes[1]} e mais {len(nomes) - 2}"


def _no_clima(c, clima):
    return bool(c["marcas"] & clima["marcas"]) and not (c["marcas"] & clima.get("sem", set()))


def _saida(c):
    return {k: v for k, v in c.items() if k not in ("marcas", "pontos")}


def indicar(clima, pular=()):
    cl = next((x for x in CLIMAS if x["chave"] == clima), None)
    if not cl:
        raise ValueError("Clima desconhecido.")
    # quem bate com mais de uma marca do clima (Romance e Josei, ou Isekai e Reincarnation) vem antes
    todas = sorted((c for c in candidatas() if _no_clima(c, cl)), key=lambda c: -(c["pontos"] + 0.12 * min(2, len(c["marcas"] & cl["marcas"]))))
    resto = [c for c in todas if c["chave"] not in set(pular)]
    if not resto and todas:  # já viu todas: começa de novo
        resto = todas
    return {"clima": cl["nome"], "item": _saida(resto[0]) if resto else None, "total": len(todas)}


def semana_atual():
    a, s, _ = datetime.date.today().isocalendar()
    return f"{a}-{s:02d}"


def escolha_da_semana():
    """Uma série escolhida para a semana inteira, entre as mais bem pontuadas. Fica guardada até a semana virar."""
    cfg, lc = L.cfg_leitura()
    sem = semana_atual()
    guardada = lc.get("escolha_semana") or {}
    if guardada.get("semana") == sem and guardada.get("item"):
        return guardada
    topo = candidatas()[:12]
    item = _saida(random.Random(sem).choice(topo)) if topo else None
    with L.CTX["lock"]:
        cfg, lc = L.cfg_leitura()
        lc["escolha_semana"] = {"semana": sem, "item": item}
        L.CTX["save_cfg"](cfg)
    return lc["escolha_semana"]


def parecidas(sid):
    """As parecidas com uma série (AniList primeiro, completa com o MangaUpdates), dizendo quais já estão na estante.
    Conteúdo adulto só aparece como parecida de uma série adulta."""
    d = L._load()
    s = L.achar(d, sid)
    if not s:
        return None
    achar, adulta = _na_estante(d), _adulta(s)
    out, vistos = [], set()
    itens = [{**r, "fonte": "al"} for r in (s.get("al") or {}).get("recs") or []] + \
            [{**r, "fonte": "mu", "genres": [], "nota": None, "adulto": False} for r in s.get("recs_mu") or []]
    for r in itens:
        k = L.chave_nome(r["nome"])
        if not k or k in vistos or (r.get("adulto") and not adulta):
            continue
        vistos.add(k)
        e = achar(aid=r.get("anilist_id"), mid=r.get("mu_id"), nome=r["nome"])
        if e and e["id"] == sid:
            continue
        out.append({"nome": e["name"] if e else r["nome"], "capa": (f"/covers/{e['cover']}" if e and e.get("cover") else r.get("capa") or ""),
                    "nota": r.get("nota"), "genres": r.get("genres") or [], "anilist_id": r.get("anilist_id"), "mu_id": r.get("mu_id"),
                    "id": e["id"] if e else None, "lista": e.get("lista_anilist") if e else None})
    return out[:10]


def adicionar(dados):
    """Põe uma indicação de fora na lista Quero ler. Os dados e a capa chegam depois, como numa importação."""
    nome = (dados.get("nome") or "").strip()
    if not nome:
        raise ValueError("Falta o nome da série.")
    aid, mid = dados.get("anilist_id"), dados.get("mu_id")
    with L.CTX["lock"]:
        d = L._load()
        e = _na_estante(d)(aid=aid, mid=mid, nome=nome)
        if e:
            return e["id"], False
        s = L.nova_serie(nome)
        s.update({"lista_anilist": "Quero ler", "anilist_id": aid or None, "mu_id": mid or None})
        d["series"].append(s)
        L._save(d)
    L.enfileirar(s["id"])
    return s["id"], True


# ---------------------------------------------------------------- retrospectiva

def retrospectiva(periodo="mes", ref=""):
    """O mês ou o ano na Leitura, pelo histórico de capítulos abertos."""
    hoje = datetime.date.today()
    if periodo == "ano":
        ano = int(ref) if str(ref).isdigit() else hoje.year
        ini, fim, nome, chave = datetime.datetime(ano, 1, 1), datetime.datetime(ano + 1, 1, 1), str(ano), str(ano)
    else:
        try:
            ano, mes = [int(x) for x in str(ref).split("-")]
        except ValueError:
            ano, mes = hoje.year, hoje.month
        ini = datetime.datetime(ano, mes, 1)
        fim = datetime.datetime(ano + (mes == 12), mes % 12 + 1, 1)
        chave = f"{ano}-{mes:02d}"
        nome = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
                "novembro", "dezembro"][mes - 1] + f" de {ano}"
    t0, t1 = ini.timestamp(), fim.timestamp()
    d = L._load()
    por_id = {s["id"]: s for s in d["series"]}
    todas = [x for x in d.get("leituras") or [] if x.get("s") in por_id]
    primeira = {}
    for x in todas:
        primeira[x["s"]] = min(primeira.get(x["s"], x["t"]), x["t"])
    caps = {}
    for x in todas:
        if t0 <= x["t"] < t1:
            caps.setdefault((x["s"], x["c"]), x["t"])
    por_serie, por_dia, generos, tipos = Counter(), Counter(), Counter(), Counter()
    for (sid, _c), t in caps.items():
        por_serie[sid] += 1
        por_dia[datetime.date.fromtimestamp(t).isoformat()] += 1
        s = por_id[sid]
        for g in s.get("genres") or []:
            if g.lower() not in ADULTO:
                generos[g] += 1
        if s.get("tipo"):
            tipos[s["tipo"]] += 1

    def serie(sid, n):
        s = por_id[sid]
        return {"id": sid, "nome": s["name"], "capa": f"/covers/{s['cover']}" if s.get("cover") else "", "capitulos": n}

    dia, n_dia = por_dia.most_common(1)[0] if por_dia else ("", 0)
    meses = sorted({datetime.date.fromtimestamp(x["t"]).strftime("%Y-%m") for x in todas})
    return {
        "periodo": "ano" if periodo == "ano" else "mes", "ref": chave, "nome": nome,
        "vista": L.cfg_leitura()[1].get("retro_vista") == chave, "capitulos": len(caps), "dias": len(por_dia), "series": len(por_serie),
        "mais_lidas": [serie(sid, n) for sid, n in por_serie.most_common(5)],
        "dia_top": {"data": dia, "capitulos": n_dia} if dia else None,
        "generos": [g for g, _ in generos.most_common(3)], "tipos": dict(tipos.most_common()),
        "comecadas": [serie(sid, por_serie[sid]) for sid, t in sorted(primeira.items(), key=lambda kv: kv[1]) if t0 <= t < t1][:12],
        "pouco": len(caps) < 10, "desde": min((x["t"] for x in todas), default=None), "meses": meses,
    }


# ---------------------------------------------------------------- AniList devagar

_al = {"rodando": False, "feitos": 0}


def enriquecer(lote=50, pausa=2.0):
    """Busca no AniList a nota, as etiquetas e as parecidas das séries que têm o número de lá, 50 por pedido,
    as que a pessoa está lendo ou quer ler primeiro. Cada série é refeita a cada 30 dias."""
    if _al["rodando"]:
        return 0
    _al.update(rodando=True, feitos=0)
    try:
        agora = time.time()
        d = L._load()
        ordem = {"Lendo": 0, "Quero ler": 1, "Pausado": 2}
        alvo = sorted((s for s in d["series"] if s.get("anilist_id") and not s.get("hidden")
                       and agora - ((s.get("al") or {}).get("em") or 0) > REFAZER_AL),
                      key=lambda s: (not s.get("favorite"), ordem.get(s.get("lista_anilist"), 3)))
        ids = [s["anilist_id"] for s in alvo]
        for i in range(0, len(ids), lote):
            parte = ids[i:i + lote]
            q = "query ($ids: [Int]) { Page(perPage: 50) { media(id_in: $ids, type: MANGA) { " + CAMPOS_AL + " } } }"
            for tentativa in range(3):
                try:
                    media = (L.anilist(q, {"ids": parte}).get("Page") or {}).get("media") or []
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or tentativa == 2:
                        raise
                    time.sleep(60)  # o AniList pediu para esperar
            por = {m["id"]: m for m in media}
            with L.CTX["lock"]:
                d = L._load()
                for s in d["series"]:
                    if s.get("anilist_id") in parte:
                        s["al"] = dados_al(por.get(s["anilist_id"]))
                L._save(d)
            _al["feitos"] += len(parte)
            time.sleep(pausa)
        return _al["feitos"]
    finally:
        _al["rodando"] = False


def _tags(m, n=8):
    """As etiquetas mais certas do AniList (votadas acima de 60%), sem as que contam o final."""
    return [t["name"] for t in m.get("tags") or [] if (t.get("rank") or 0) >= 60 and not t.get("isMediaSpoiler")][:n]


def dados_al(m):
    if not m:
        return {"em": time.time()}
    recs = []
    for n in ((m.get("recommendations") or {}).get("nodes") or []):
        r = n.get("mediaRecommendation") or {}
        if not r.get("id") or (n.get("rating") or 0) < 1:
            continue
        t = r.get("title") or {}
        recs.append({"anilist_id": r["id"], "nome": t.get("english") or t.get("romaji") or "", "votos": n.get("rating") or 0,
                     "capa": (r.get("coverImage") or {}).get("large") or "", "nota": r.get("averageScore"),
                     "genres": list(r.get("genres") or [])[:8], "tipo": L.TIPO_PAIS.get(r.get("countryOfOrigin") or "", ""),
                     "tags": _tags(r),
                     "adulto": bool(r.get("isAdult"))})
    return {"em": time.time(), "nota": m.get("averageScore"), "adulto": bool(m.get("isAdult")),
            "tags": _tags(m, 15),
            "recs": [r for r in recs if r["nome"]][:10]}


def vigiar():
    def loop():
        time.sleep(90)
        while True:
            try:
                n = enriquecer()
                if n:
                    print(f"[indicações] AniList: nota, etiquetas e parecidas de {n} série(s)")
            except Exception as e:
                print("[indicações] AniList:", e)
            time.sleep(6 * 3600)
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------- rotas

def rotas(bp):
    @bp.get("/api/leitura/climas")
    def api_climas():
        cs = candidatas()
        return jsonify([{"chave": c["chave"], "nome": c["nome"], "total": sum(1 for x in cs if _no_clima(x, c))} for c in CLIMAS])

    @bp.get("/api/leitura/indicacao")
    def api_indicacao():
        try:
            return jsonify(indicar(request.args.get("clima") or "", [p for p in (request.args.get("pular") or "").split(",") if p]))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @bp.post("/api/leitura/indicacao/adicionar")
    def api_indicacao_adicionar():
        try:
            sid, nova = adicionar(request.get_json(force=True) or {})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"id": sid, "nova": nova})

    @bp.get("/api/leitura/semana")
    def api_semana():
        return jsonify(escolha_da_semana())

    @bp.get("/api/leitura/parecidas")
    def api_parecidas():
        r = parecidas(request.args.get("id") or "")
        if r is None:
            abort(404)
        return jsonify(r)

    @bp.get("/api/leitura/retrospectiva")
    def api_retrospectiva():
        return jsonify(retrospectiva(request.args.get("periodo") or "mes", request.args.get("ref") or ""))

    @bp.post("/api/leitura/retrospectiva/vista")
    def api_retrospectiva_vista():
        with L.CTX["lock"]:
            cfg, lc = L.cfg_leitura()
            lc["retro_vista"] = str((request.get_json(force=True) or {}).get("ref") or "")
            L.CTX["save_cfg"](cfg)
        return jsonify({"ok": True})
