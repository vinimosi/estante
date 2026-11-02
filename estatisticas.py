"""
Estatísticas das duas estantes: tempo jogado e capítulos lidos por semana, os mais jogados e os mais lidos.
Tudo sai dos dados que a Estante já guarda (cada vez que você jogou e cada capítulo aberto); nada é buscado fora.
"""
import math
import time

SEMANAS = 12


def inicio_da_semana(t):
    """Segunda-feira, 0h, da semana de t (no horário deste computador)."""
    lt = time.localtime(t)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - lt.tm_wday, 0, 0, 0, 0, 0, -1))


def por_semana(eventos, agora=None, n=SEMANAS):
    """eventos = [(quando, valor)]. Devolve as últimas n semanas, da mais antiga para a atual: [{inicio, valor}]."""
    agora = time.time() if agora is None else agora
    inicios = [inicio_da_semana(agora)]
    for _ in range(n - 1):
        inicios.insert(0, inicio_da_semana(inicios[0] - 3600))  # uma hora antes da segunda-feira: a semana anterior
    soma = dict.fromkeys(inicios, 0)
    for t, v in eventos:
        if t >= inicios[0]:
            k = inicio_da_semana(t)
            if k in soma:
                soma[k] += v
    return [{"inicio": int(k), "valor": soma[k]} for k in inicios]


def jogos(games, agora=None):
    agora = time.time() if agora is None else agora
    gs = [g for g in games if not g.get("hidden")]
    sess = [(t, d) for g in gs for t, d in (g.get("sessoes") or [])]
    situacoes = {}
    for g in gs:
        if g.get("situacao"):
            situacoes[g["situacao"]] = situacoes.get(g["situacao"], 0) + 1
    top = sorted((g for g in gs if g.get("playtime")), key=lambda g: -g["playtime"])[:10]
    return {
        "total": int(sum(g.get("playtime") or 0 for g in gs)),
        "jogados": sum(1 for g in gs if g.get("playtime")),
        "jogos": len(gs),
        "semana": int(sum(d for t, d in sess if t >= agora - 7 * 86400)),
        "mes": int(sum(d for t, d in sess if t >= agora - 30 * 86400)),
        "por_semana": por_semana(sess, agora),
        "desde": int(min(t for t, d in sess)) if sess else None,  # antes disso só existia o total de cada jogo
        "top": [{"id": g["id"], "nome": g.get("name") or "", "valor": int(g["playtime"])} for g in top],
        "situacoes": situacoes,
    }


def leitura(d, agora=None):
    agora = time.time() if agora is None else agora
    series = [s for s in d.get("series") or [] if not s.get("hidden")]
    ids = {s["id"]: s for s in series}
    lidos = [x for x in d.get("leituras") or [] if x.get("s") in ids]
    conta = {}
    for x in lidos:
        conta[x["s"]] = conta.get(x["s"], 0) + 1
    top = sorted(conta.items(), key=lambda kv: -kv[1])[:10]
    listas = {}
    for s in series:
        if s.get("lista_anilist"):
            listas[s["lista_anilist"]] = listas.get(s["lista_anilist"], 0) + 1
    return {
        "series": len(series),
        "comecadas": sum(1 for s in series if s.get("ultimo_lido") is not None),
        "capitulos": int(sum(math.floor(s["ultimo_lido"]) for s in series if (s.get("ultimo_lido") or 0) > 0)),
        "semana": sum(1 for x in lidos if x["t"] >= agora - 7 * 86400),
        "mes": sum(1 for x in lidos if x["t"] >= agora - 30 * 86400),
        "por_semana": por_semana([(x["t"], 1) for x in lidos], agora),
        "desde": int(min(x["t"] for x in lidos)) if lidos else None,  # o registro de cada capítulo aberto começou aqui
        "top": [{"id": k, "nome": ids[k].get("name") or "", "valor": v} for k, v in top],
        "listas": listas,
    }
