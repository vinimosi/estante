"""Capítulos novos mais perto da hora: lançamentos do MangaUpdates de uma vez, a lista das séries que a extensão
guarda e a ordem da volta completa. Rode: python3 testar_novidades.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import os
import shutil
import sys
import time
from pathlib import Path

S = Path(_SAIDA)
T = S / "novidades"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import leitura  # noqa: E402
import testar_leitura_mocks as mocks  # noqa: E402

leitura._http_json = mocks.http_falso
leitura.enfileirar = lambda *a, **k: None
c = app.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


def serie(nome):
    return next(s for s in leitura._load()["series"] if s["name"] == nome)


with app.lock:
    d = leitura._load()
    for nome, mu, lista, disp, lido, sites, extra in [
        ("Lendo Pouco", 11, "Lendo", 50.0, 49.0, {"comix": "aa1-lendo-pouco"}, {"ultima_leitura": 100}),
        ("Lendo Muito", 12, "Lendo", 80.0, 80.0, {"asura": "lendo-muito"}, {"ultima_leitura": 200}),
        ("Lança Sempre", 13, "Quero ler", 30.0, None, {"demonic": "Lanca-Sempre"}, {}),
        ("Quieta", 14, "Pausado", 10.0, 5.0, {"comix": "zz9-quieta"}, {}),
        ("Terminei", 15, "Terminado", 100.0, 100.0, {"comix": "tt1-terminei"}, {}),
        ("Sem Site", 16, "Lendo", 5.0, 1.0, {}, {}),
    ]:
        s = leitura.nova_serie(nome)
        s.update({"mu_id": mu, "lista_anilist": lista, "ultimo_disponivel": disp, "ultimo_lido": lido, "verificado_em": 1.0}, **extra)
        for k, slug in sites.items():
            leitura._ps(s, k, slug)
        d["series"].append(s)
    leitura._save(d)
with app.lock:
    d = leitura._load()
    ls = next(s for s in d["series"] if s["name"] == "Lança Sempre")
    d["novidades"] = [{"s": ls["id"], "c": n, "t": time.time() - 86400 * n, "site": ""} for n in range(1, 6)]
    leitura._save(d)

print("Lista das séries para a extensão")
m = c.get("/api/leitura/minhas").get_json()
nomes = [x["nome"] for x in m]
check("Terminei" not in nomes and "Sem Site" not in nomes, "séries terminadas e séries sem site ficam de fora")
check(nomes[:2] == ["Lendo Muito", "Lendo Pouco"], f"as que você está lendo vêm primeiro (a lida mais recentemente antes) {nomes}")
check(nomes[2] == "Lança Sempre", "depois, as que lançam com mais frequência")
lp = next(x for x in m if x["nome"] == "Lendo Pouco")
check(lp["lendo"] and lp["ultimo"] == 50.0 and lp["sites"]["comix"]["slug"] == "aa1-lendo-pouco"
      and lp["sites"]["comix"]["url"].endswith("/title/aa1-lendo-pouco"), "cada série vai com o endereço em cada site e o último capítulo")
pv = c.get("/api/leitura/para-verificar").get_json()
check([x["slug"] for x in pv][:3] == ["lendo-muito", "aa1-lendo-pouco", "Lanca-Sempre"], "a volta completa segue a mesma ordem")

print("Lançamentos recentes do MangaUpdates, de uma vez")
mocks.LANCAMENTOS[:] = [
    {"record": {"title": "Lendo Pouco", "chapter": "51-52"}, "metadata": {"series": {"series_id": 11}}},
    {"record": {"title": "Lendo Muito", "chapter": "79"}, "metadata": {"series": {"series_id": 12}}},   # mais velho que o conhecido
    {"record": {"title": "Outra", "chapter": "3"}, "metadata": {"series": {"series_id": 999}}},          # não está na estante
    {"record": {"title": "Quieta", "chapter": "Oneshot"}, "metadata": {"series": {"series_id": 14}}},    # sem número
]
antes = len(mocks.chamadas)
novos = leitura.verificar_lancamentos()
check(novos == 1 and len(mocks.chamadas) == antes + 1, "um pedido só trouxe os lançamentos de todas as séries")
lp = serie("Lendo Pouco")
check(lp["ultimo_disponivel"] == 52.0 and any(n["s"] == lp["id"] and n["c"] == 52.0 for n in leitura._load()["novidades"]),
      "capítulo 51-52 conta como 52 e entra em Novidades")
check(serie("Lendo Muito")["ultimo_disponivel"] == 80.0 and serie("Quieta")["ultimo_disponivel"] == 10.0,
      "capítulo mais velho que o conhecido, ou sem número, não muda nada")
check(leitura.verificar_lancamentos() == 0, "pedir de novo não repete a novidade")

print("Botão Procurar capítulos novos agora")
mocks.LANCAMENTOS[:] = [{"record": {"title": "Lendo Muito", "chapter": "81"}, "metadata": {"series": {"series_id": 12}}}]
c.post("/api/leitura/verificar")
fim = time.time() + 10
while time.time() < fim and serie("Lendo Muito")["ultimo_disponivel"] != 81.0:
    time.sleep(0.2)
check(serie("Lendo Muito")["ultimo_disponivel"] == 81.0, "o botão também pede os lançamentos recentes na hora")

print("Volta completa que continua de onde parou")
fim = time.time() + 10
while time.time() < fim and leitura._verificando["ativo"]:
    time.sleep(0.2)
leitura._tentativa.clear()
with app.lock:
    d = leitura._load()
    for x in d["series"]:
        x["verificado_em"] = {"Lendo Muito": time.time(), "Lendo Pouco": None, "Lança Sempre": time.time() - 13 * 3600}.get(x["name"], time.time())
    leitura._save(d)
venc = [x["name"] for x in leitura._vencidas(leitura._load(), 12)]
check(venc == ["Lendo Pouco", "Lança Sempre"],
      f"mesmo com uma série olhada agora, as que passaram de 12 horas (ou nunca foram olhadas) entram na volta {venc}")
olhadas = []
_verificar = leitura.verificar


def verificar_falso(sid, trocar_nome=False):
    olhadas.append(next(x["name"] for x in leitura._load()["series"] if x["id"] == sid))
    if len(olhadas) == 1:
        leitura._marcar(sid, verificado_em=time.time())
        return None
    raise RuntimeError("a Estante fechou no meio da volta")


leitura.verificar = verificar_falso
leitura.verificar_todas(horas=12)
fim = time.time() + 10
while time.time() < fim and leitura._verificando["ativo"]:
    time.sleep(0.2)
check(olhadas == ["Lendo Pouco", "Lança Sempre"] and leitura._verificando["total"] == 2, "a volta automática passa só por essas, na ordem")
check([x["name"] for x in leitura._vencidas(leitura._load(), 12)] == [], "e a que deu erro não é tentada de novo antes de 12 horas")
leitura._tentativa.clear()
check([x["name"] for x in leitura._vencidas(leitura._load(), 12)] == ["Lança Sempre"],
      "numa próxima volta (a Estante reaberta), começa pela que faltou, e não do começo da lista")
leitura.verificar = _verificar

print("MangaUpdates de novo para as séries que não foram achadas")
procuradas = []
_buscar = leitura.mu_buscar
leitura.mu_buscar = lambda nome: procuradas.append(nome) or []
with app.lock:
    d = leitura._load()
    ss = next(x for x in d["series"] if x["name"] == "Sem Site")
    ss.update(mu_id=None, mu_tentado=True, mu_tentado_em=time.time() - 3 * 86400)
    leitura._save(d)
leitura.verificar(ss["id"])
check(not procuradas, "procurada há 3 dias: ainda não procura de novo")
leitura._marcar(ss["id"], mu_tentado_em=time.time() - 8 * 86400)
leitura.verificar(ss["id"])
check(procuradas and procuradas[0] == "Sem Site" and serie("Sem Site")["mu_tentado_em"] > time.time() - 60,
      "procurada há mais de uma semana: procura de novo (a série pode ter entrado lá) e anota quando")
procuradas.clear()
leitura._marcar(ss["id"], mu_tentado_em=None)
leitura.verificar(ss["id"])
check(procuradas, "as que foram procuradas antes desta versão (sem a data) também ganham uma nova chance")
leitura.mu_buscar = _buscar

print("Obra completa, tradução ainda saindo")
m = leitura.dados_mu({"series_id": 1, "title": "X", "status": "Novel - 1526 Chapters (Complete)\nManhua - Ongoing", "completed": False})
check(m["status"] == "Completa" and m["traducao_completa"] is False, "o MangaUpdates separa a obra original (status) da tradução (completed)")
with app.lock:
    d = leitura._load()
    for nome, lista, extra in [("Original Acabou", "Lendo", {"traducao_completa": False}), ("Tudo Acabou", "Lendo", {"traducao_completa": True}),
                               ("Sem Saber", "Lendo", {}), ("Sem Saber Quero", "Quero ler", {})]:
        x = leitura.nova_serie(nome)
        x.update({"status": "Completa", "lista_anilist": lista}, **extra)
        d["series"].append(x)
    leitura._save(d)
ativas = [x["name"] for x in leitura._series_ativas(leitura._load())]
check("Original Acabou" in ativas and "Tudo Acabou" not in ativas,
      "obra completa com a tradução saindo continua sendo olhada; com a tradução completa, sai")
check("Sem Saber" in ativas and "Sem Saber Quero" not in ativas,
      "sem a informação (dados antigos), as que você está lendo continuam sendo olhadas até o MangaUpdates responder")
oa = serie("Original Acabou")
leitura.aplicar_mu(oa["id"], {**leitura.dados_mu({"series_id": 77, "title": "Original Acabou", "status": "50 Chapters (Complete)", "completed": True}), "capa_url": ""})
check(serie("Original Acabou")["traducao_completa"] is True and "Original Acabou" not in [x["name"] for x in leitura._series_ativas(leitura._load())],
      "quando o MangaUpdates diz que a tradução acabou, ela sai das verificações")

print("Ritmo de lançamento de cada série")
DIA = 86400
agora = time.time()
x = {"id": "r1"}
for k in range(4):
    leitura._guardar_lancamento(x, 10 + k, agora - (4 - k) * 7 * DIA)
leitura._guardar_lancamento(x, 15, agora - 7 * DIA + 3600)  # dois capítulos no mesmo dia: um lançamento só
check(len(x["lancamentos"]) == 4 and x["lancamentos"][-1][0] == 15, "capítulos que saem juntos contam como um lançamento")
ritmo, ultimo = leitura._ritmo(x)
check(abs(ritmo - 7 * DIA) < 2 and ultimo == agora - 7 * DIA, "série semanal: aprende o ritmo de 7 dias")
x["verificado_em"] = agora - 13 * 3600
check(leitura._na_hora(x, agora=agora), "faz 7 dias do último capítulo: está na hora de olhar")
x["lancamentos"][-1][1] = agora - 2 * DIA
check(not leitura._na_hora(x, agora=agora), "saiu há 2 dias: espera chegar perto da próxima semana")
check(leitura._na_hora(x, agora=agora + 4 * DIA), "a partir de uns 6 dias depois, volta a olhar")
x["verificado_em"] = agora - 8 * DIA
check(leitura._na_hora(x, agora=agora), "olhada há mais de uma semana: olha mesmo fora do ritmo")
x["verificado_em"], x["lancamentos"] = agora - DIA, [[10 + k, agora - (51 - 7 * k) * DIA] for k in range(4)]
check(not leitura._na_hora(x, agora=agora), "parada há mais de 3 semanas (pausa): não olha todo dia")
x["verificado_em"] = agora - 4 * DIA
check(leitura._na_hora(x, agora=agora), "mas olha a cada 3 dias")
check(leitura._na_hora({"id": "r2", "lancamentos": [[1, agora - DIA]], "verificado_em": agora}, agora=agora),
      "série com poucos lançamentos anotados é olhada como sempre")
y = {"id": "r3", "verificado_em": agora - 13 * 3600}
idx = {"r3": [agora - 30 * DIA, agora - 20 * DIA, agora - 10 * DIA, agora - DIA]}
check(not leitura._na_hora(y, idx, agora), "aproveita as Novidades antigas para saber o ritmo (a cada 10 dias, saiu ontem)")
with app.lock:
    d = leitura._load()
    lm = next(s for s in d["series"] if s["name"] == "Lendo Muito")
    lm.pop("lancamentos", None)
    leitura._subiu(d, lm, 90.0)
    check(len(lm["lancamentos"]) == 1 and lm["lancamentos"][0][0] == 90.0, "capítulo novo anota o lançamento")
    lm["lancamentos"] = [[87 + k, agora - (3 - k) * 7 * DIA - DIA] for k in range(3)] + [[90.0, agora - DIA]]
    lm["verificado_em"] = agora - 13 * 3600
    leitura._save(d)
leitura._tentativa.clear()
check("Lendo Muito" not in [s["name"] for s in leitura._vencidas(leitura._load(), 12)],
      "a volta automática pula a série semanal que lançou ontem")
check("lendo-muito" not in [p["slug"] for p in c.get("/api/leitura/para-verificar").get_json()],
      "e a extensão também não abre a página dela")

print(f"\nTudo certo: {ok} verificações.")
