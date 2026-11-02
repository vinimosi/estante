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

print(f"\nTudo certo: {ok} verificações.")
