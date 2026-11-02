"""Importa a lista real (arquivo XML) com o AniList simulado."""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import os, sys, time, shutil, json
from pathlib import Path
S = Path(_SAIDA)
T = S / "xml"; shutil.rmtree(T, ignore_errors=True); T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ); sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app, leitura
import testar_leitura_mocks as mocks
ARQ = _os.environ.get("ESTANTE_LISTA_XML", "")
if not ARQ or not os.path.exists(ARQ):
    print("Pulei: defina ESTANTE_LISTA_XML com o caminho de uma lista exportada do AniList ou MyAnimeList.")
    raise SystemExit(0)
pedidos = []
def http(url, dados=None, timeout=20):
    if "anilist" in url and "idMal_in" in dados["query"]:
        ids = dados["variables"]["ids"]; pedidos.append(len(ids))
        # metade das séries é achada pelo número do MyAnimeList
        return {"data": {"Page": {"media": [dict(mocks.ANI[999], id=900000 + i, idMal=i, title={"english": f"Serie {i}", "romaji": None, "native": None}, synonyms=[]) for i in ids if i % 2 == 0]}}}
    if "anilist" in url:
        return {"data": {"Page": {"media": []}}}
    if "mangaupdates" in url:
        return {"results": []}
    raise RuntimeError("sem internet")
leitura._http_json = http
leitura.guardar_capa = lambda sid, url, referer=None: None
leitura.verificar_todas = lambda forcar=False: {}
c = app.app.test_client()
# já existe na Estante, lida até mais longe pela extensão
c.post("/api/leitura/link", json={"url": "https://comix.to/title/okkv-the-mysterious-worlds-greatest-martial-artist-little-prince/1-chapter-60"})
time.sleep(1)
t0 = time.time()
with open(ARQ, "rb") as f:
    r = c.post("/api/leitura/importar-arquivo", data={"file": (f, "manga-list.xml"), "usar_capitulo": "1"}, content_type="multipart/form-data").get_json()
print("resposta:", r, f"{time.time()-t0:.1f}s")
fim = time.time() + 60
while c.get("/api/leitura/importar-anilist").get_json()["ativo"] and time.time() < fim: time.sleep(0.5)
d = c.get("/api/leitura").get_json()["series"]
by = {s["name"]: s for s in d}
print("séries:", len(d), "| lotes AniList:", len(pedidos), max(pedidos))
lp = [s for s in d if "Artist Little Prince" in s["name"]]
print("Little Prince:", [(s["name"], s["lido_txt"], s["lista_anilist"]) for s in lp])
print("Tower of God:", by.get("Tower of God", {}).get("lido_txt"), by.get("Tower of God", {}).get("lista_anilist"))
print("listas:", {k: sum(1 for s in d if s["lista_anilist"] == k) for k in {s["lista_anilist"] for s in d}})
print("com AniList:", sum(1 for s in d if s.get("anilist_id")), "| continue lendo:", sum(1 for s in d if s.get("ultima_leitura")))
assert len(d) == 772 and len(lp) == 1 and lp[0]["lido_txt"] == "60" and lp[0]["lista_anilist"] == "Lendo"
r = c.post("/api/leitura/importar-arquivo", data={"file": (open(ARQ, "rb"), "x.xml")}, content_type="multipart/form-data").get_json()
time.sleep(1)
print("segunda vez:", r, "séries:", len(c.get("/api/leitura").get_json()["series"]))
assert r["novas"] == 0
print("OK")
