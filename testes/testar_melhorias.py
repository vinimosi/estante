"""Melhorias da etapa 7: juntar séries, versão da extensão, erros que vão para o registro e a Leitura rápida com
800 séries. Rode: python3 testar_melhorias.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import contextlib
import io
import json
import os
import random
import shutil
import sys
import threading
import time
from pathlib import Path

S = Path(_SAIDA)
T = S / "melhorias"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import caminhos  # noqa: E402
import leitura  # noqa: E402
import lojas  # noqa: E402
import testar_leitura_mocks as mocks  # noqa: E402

leitura._http_json = mocks.http_falso
leitura.enfileirar = lambda *a, **k: None
for loja in lojas.LEITORES:
    lojas.LEITORES[loja] = lambda *a, **k: {"encontrada": False, "jogos": []}
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
    return next((s for s in leitura._load()["series"] if s["name"] == nome), None)


print("Juntar séries")
capa_a, capa_b = T / "dados" / "covers" / "l_a.jpg", T / "dados" / "covers" / "l_b.jpg"
capa_a.write_bytes(b"a")
capa_b.write_bytes(b"b")
with app.lock:
    d = leitura._load()
    a = leitura.nova_serie("The Greatest Estate Developer")
    a.update({"por_site": {"asura": {"slug": "greatest-estate", "serie": "/comics/greatest-estate", "caps": {"50": "/c/50", "51": "/c/51"}, "ultimo": 51.0, "visto": 100}},
              "ultimo_lido": 50.0, "caminho_lido": "/c/50", "site_lido": "asura", "ultima_leitura": 1000, "ultimo_disponivel": 51.0, "novo_desde": 900,
              "lista_anilist": "Lendo", "tags": ["Ação"], "cover": "l_a.jpg", "site": "asura", "mu_id": 77, "added": 500,
              "primeiro": {"51": {"site": "asura", "t": 800}}})
    b = leitura.nova_serie("Greatest Estate Developer (Comix)")
    b.update({"por_site": {"comix": {"slug": "ab1-greatest", "serie": "/title/ab1-greatest", "caps": {"60": "/t/60"}, "ultimo": 61.0, "visto": 200},
                           "asura": {"slug": "", "serie": "", "caps": {"49": "/c/49", "50": "/outro/50"}, "ultimo": 50.0, "visto": 50}},
              "ultimo_lido": 59.0, "caminho_lido": "/t/59", "site_lido": "comix", "ultima_leitura": 2000, "ultimo_disponivel": 61.0,
              "lendo": {"n": 60, "caminho": "/t/60", "site": "comix", "pct": 40, "pagina": 7, "total": 20, "t": 2000},
              "lista_anilist": "Pausado", "tags": ["Favoritas"], "favorite": True, "cover": "l_b.jpg", "added": 300,
              "description": "Um engenheiro acorda num romance.", "genres": ["Comedy"], "titulos_alt": ["GED"],
              "primeiro": {"51": {"site": "comix", "t": 700}, "61": {"site": "comix", "t": 1900}}})
    outra = leitura.nova_serie("Outra Série")
    d["series"] += [a, b, outra]
    d["leituras"] += [{"s": a["id"], "c": 50.0, "t": 1000, "site": "asura"}, {"s": b["id"], "c": 59.0, "t": 1900, "site": "comix"}]
    d["novidades"] += [{"s": a["id"], "c": 51.0, "t": 900, "site": "asura"}, {"s": b["id"], "c": 51.0, "t": 800, "site": "comix"},
                       {"s": b["id"], "c": 61.0, "t": 1950, "site": "comix"}]
    leitura._save(d)
    ida, idb, ido = a["id"], b["id"], outra["id"]

check(c.post("/api/leitura/juntar", json={"ids": [ida]}).status_code == 400, "uma série só não dá para juntar")
check(c.post("/api/leitura/juntar", json={"ids": [ida, idb]}, headers={"Origin": "https://site-qualquer.com"}).status_code == 403,
      "outros sites não conseguem juntar séries")
r = c.post("/api/leitura/juntar", json={"ids": [ida, idb], "principal": ida})
check(r.status_code == 200 and r.get_json()["name"] == "The Greatest Estate Developer", "juntou, com o nome da principal")
d = leitura._load()
check(len(d["series"]) == 2 and not leitura.achar(d, idb), "as duas viraram uma só")
s = leitura.achar(d, ida)
check(set(s["por_site"]) == {"asura", "comix"} and s["por_site"]["comix"]["slug"] == "ab1-greatest", "os dois sites ficaram na série")
check(s["por_site"]["asura"]["caps"] == {"49": "/c/49", "50": "/c/50", "51": "/c/51"} and s["por_site"]["asura"]["ultimo"] == 51.0,
      "no mesmo site, os links de capítulo se somam (os da principal valem)")
check(s["ultimo_lido"] == 59.0 and s["site_lido"] == "comix" and s["caminho_lido"] == "/t/59", "vale o capítulo lido mais adiantado")
check(s["lendo"] and s["lendo"]["n"] == 60 and s["lendo"]["pagina"] == 7, "e a página onde parou no capítulo aberto")
check(s["ultimo_disponivel"] == 61.0 and s["ultima_leitura"] == 2000 and s["added"] == 300, "último capítulo, última leitura e data de entrada certos")
check(s["primeiro"]["51"] == {"site": "comix", "t": 700} and "61" in s["primeiro"], "em que site cada capítulo saiu primeiro: vale o mais antigo")
check(s["lista_anilist"] == "Lendo", "a situação na lista é a da principal")
check(s["tags"] == ["Ação", "Favoritas"] and s["favorite"], "coleções e favorito somados")
check("Greatest Estate Developer (Comix)" in s["titulos_alt"] and "GED" in s["titulos_alt"], "o outro nome vira nome alternativo")
check(s["description"].startswith("Um engenheiro") and s["genres"] == ["Comedy"] and s["mu_id"] == 77, "dados que faltavam vêm da outra")
check(s["cover"] == "l_a.jpg" and capa_a.exists() and not capa_b.exists(), "a capa é a da principal, e a outra é apagada")
check([x["s"] for x in d["leituras"][-2:]] == [ida, ida], "o histórico da outra passa para a série")
nov = [x for x in d["novidades"] if x["s"] == ida]
check(sorted(x["c"] for x in nov) == [51.0, 61.0], "as novidades também, sem repetir o mesmo capítulo")
check(leitura.achar(d, ido) and leitura.achar(d, ido)["name"] == "Outra Série", "as outras séries não mudam")
with app.lock:
    d = leitura._load()
    for nome in ("Pasta A", "Pasta B"):
        x = leitura.nova_serie(nome)
        x.update({"local": {"pasta": str(T / nome), "caps": [], "paginas": {}}, "origem": "local", "site": "local"})
        d["series"].append(x)
    leitura._save(d)
r = c.post("/api/leitura/juntar", json={"ids": [serie("Pasta A")["id"], serie("Pasta B")["id"]]})
check(r.status_code == 400 and "pastas diferentes" in r.get_json()["error"], "duas pastas do PC não viram uma série só (avisa)")

print("Versão da extensão")
pasta = leitura.versao_da_pasta()
check(pasta == json.loads(Path(_PROJ, "extensao", "manifest.json").read_text("utf-8"))["version"], f"a Estante sabe a versão da extensão da pasta ({pasta})")
r = c.get("/api/leitura").get_json()
check(not r["extensao_velha"], "extensão que nunca conversou com a Estante: nenhum aviso de velha")
c.post("/api/leitura/progresso", json={"url": "https://asurascans.com/comics/x-1a2b3c4d/chapter/3", "titulo": "X Chapter 3"},
       headers={"Origin": "chrome-extension://abc", "X-Estante-Extensao": "1"})
check(c.get("/api/leitura").get_json()["extensao_velha"], "extensão antiga, de antes de contar a versão: avisa para recarregar")
c.get("/api/leitura/sites?v=1.2.0&nav=edge")
r = c.get("/api/leitura").get_json()
check(r["extensao_velha"] and r["extensao_versao"] == "1.2.0" and r["navegador"] == "edge", "versão mais velha que a da pasta: avisa")
c.get("/api/leitura/sites?v=" + pasta)
check(not c.get("/api/leitura").get_json()["extensao_velha"], "recarregada: o aviso some")
c.get("/api/leitura/sites?v=<script>")
check(leitura.cfg_leitura()[1]["extensao_versao"] == pasta, "versão esquisita é ignorada")

print("Erros vão para o registro")
saida = io.StringIO()
with contextlib.redirect_stdout(saida):
    caminhos.apagar_arquivo(T / "nao-existe.jpg")
check(saida.getvalue() == "", "arquivo que já não existe: nada a registrar")
pasta_trancada = T / "uma-pasta"
pasta_trancada.mkdir()
with contextlib.redirect_stdout(saida):
    caminhos.apagar_arquivo(pasta_trancada)
check("não consegui apagar uma-pasta" in saida.getvalue(), "falha de verdade ao apagar vai para o estante.log")
fonte = Path(_PROJ, "app.py").read_text("utf-8") + Path(_PROJ, "leitura.py").read_text("utf-8")
check("except Exception:\n            pass" not in fonte and ".unlink()\n        except OSError:\n            pass" not in fonte,
      "nenhum erro de capa passa em silêncio no app.py e no leitura.py")

print("Leitura rápida com 800 séries")
random.seed(7)
with app.lock:
    d = leitura._load()
    agora = time.time()
    for i in range(800):
        x = leitura.nova_serie(f"Série de Teste {i:03d} " + random.choice(["Dragão", "Torre", "Espada", "Rei", "Mago"]))
        n = random.randint(5, 300)
        x.update({"por_site": {"asura": {"slug": f"s{i}", "serie": f"/comics/s{i}", "caps": {str(k): f"/comics/s{i}/chapter/{k}" for k in range(n - 30, n + 1)},
                                         "ultimo": float(n), "visto": agora}},
                  "ultimo_lido": float(random.randint(1, n)), "ultimo_disponivel": float(n), "ultima_leitura": agora - random.randint(0, 9_000_000),
                  "lista_anilist": random.choice(["Lendo", "Quero ler", "Terminado", "Pausado"]), "genres": random.sample(["Action", "Fantasy", "Drama", "Romance", "Comedy", "Isekai"], 3),
                  "tipo": random.choice(["Manhwa", "Mangá", "Manhua"]), "status": random.choice(["Em andamento", "Completa"]), "site": "asura",
                  "description": "Descrição " * 40, "mu_id": 10000 + i, "verificado_em": agora})
        d["series"].append(x)
        d["leituras"] += [{"s": x["id"], "c": float(k), "t": agora - k * 3600, "site": "asura"} for k in range(6)]
    leitura._save(d)
t0 = time.perf_counter()
r = c.get("/api/leitura")
t_api = time.perf_counter() - t0
check(r.status_code == 200 and len(r.get_json()["series"]) == 805, f"a lista com 805 séries sai em {t_api:.2f} s, {len(r.data) // 1024} KB")
check(t_api < 3, "em menos de 3 segundos")

from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8795, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8795/")
    pg.wait_for_timeout(800)
    t0 = time.perf_counter()
    pg.click("#shelves >> text=Leitura")
    pg.wait_for_function("document.querySelectorAll('.grid .card').length >= 800", timeout=20000)
    t_abrir = time.perf_counter() - t0
    check(True, f"a estante de Leitura abre com as 805 séries em {t_abrir:.2f} s")
    check(t_abrir < 4, "em menos de 4 segundos")
    t_filtro = pg.evaluate("""() => { const t = performance.now(); const q = document.getElementById('q'); q.value = 'Dragão';
        q.dispatchEvent(new Event('input')); return performance.now() - t; }""")
    pg.wait_for_timeout(400)
    n = pg.locator(".grid .card").count()
    check(0 < n < 800, f"a busca filtra na hora ({n} séries, {t_filtro:.0f} ms)")
    pg.fill("#q", "")
    pg.wait_for_timeout(400)
    t_rolar = pg.evaluate("""async () => { const el = document.getElementById('content'); const t = performance.now(); let quadros = 0;
        await new Promise(res => { const passo = () => { el.scrollTop += 400; quadros++; if (el.scrollTop + el.clientHeight >= el.scrollHeight - 5 || quadros > 400) res(); else requestAnimationFrame(passo); }; passo(); });
        return (performance.now() - t) / quadros; }""")
    check(t_rolar < 50, f"rolar a estante inteira fica leve ({t_rolar:.1f} ms por quadro)")
    pg.screenshot(path=str(OUT / "m1_leitura_800.png"))

    print("Juntar séries pela tela")
    pg.evaluate("S.lastJson=''; load()")
    pg.wait_for_timeout(800)
    pg.fill("#q", "Greatest")
    pg.wait_for_timeout(500)
    pg.click(".grid .card:has-text('Greatest') .meta")
    pg.wait_for_selector("text=Juntar com outra série")
    pg.click("text=Juntar com outra série")
    pg.fill("#jq", "Outra")
    pg.wait_for_selector("#jList [data-j]")
    pg.click("#jList [data-j]")
    pg.wait_for_selector("#jOk")
    check(pg.locator("input[name=jp]").count() == 2, "o painel da série oferece juntar com outra, e a tela pede a principal")
    pg.screenshot(path=str(OUT / "m2_juntar_series.png"))
    pg.click("#jOk")
    pg.wait_for_timeout(800)
    check(serie("Outra Série") is None and "Outra Série" in serie("The Greatest Estate Developer")["titulos_alt"], "juntou pela tela")
    check(not erros, f"nenhum erro na página {erros}")
    b.close()
srv.shutdown()

print(f"\nTudo certo: {ok} verificações.")
