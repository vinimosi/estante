"""Etapa 11, ler sem internet: achar a série na WeebCentral, baixar capítulos devagar (como o Mihon), ler no leitor
da Estante sem internet, marcar o lido e apagar. Com uma WeebCentral de mentira, com páginas iguais às de verdade.
Rode: python3 testar_baixar.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import io
import os
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

S = Path(_SAIDA)
T = S / "baixar"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import baixar  # noqa: E402
import leitura  # noqa: E402
import lojas  # noqa: E402
from PIL import Image  # noqa: E402

for loja in lojas.LEITORES:
    lojas.LEITORES[loja] = lambda *a, **k: {"encontrada": False, "jogos": []}
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


# ---- WeebCentral de mentira (o mesmo jeito das páginas de verdade)
SERIES = {"01AAAAAAAAAAAAAAAAAAAAAAAA": ("Solo Leveling", "Solo-Leveling", [1, 2, 3, 4, 5, 5.5, 6]),
          "01BBBBBBBBBBBBBBBBBBBBBBBB": ("Solo Leveling: Ragnarok", "Solo-Leveling-Ragnarok", [1, 2]),
          "01CCCCCCCCCCCCCCCCCCCCCCCC": ("Twin Star", "Twin-Star", [1]),
          "01DDDDDDDDDDDDDDDDDDDDDDDD": ("Twin Stars", "Twin-Stars", [1])}
PEDIDOS, TRAVAR = [], {"bloqueio": False}


def png(cor):
    b = io.BytesIO()
    Image.new("RGB", (60, 90), cor).save(b, "PNG")
    return b.getvalue()


def cap_id(sid, n):
    return sid[:16] + ("%010d" % int(n * 10))


def falso(url, imagem=False):
    PEDIDOS.append((url, time.time()))
    if TRAVAR["bloqueio"]:
        raise baixar.Bloqueado("o site respondeu 429")
    if imagem:
        return png((int(url.rsplit("-", 1)[1].split(".")[0]) * 40 % 255, 90, 160))
    if "/search/data?" in url:
        q = url.split("text=")[1].split("&")[0].replace("+", " ").lower()
        achadas = [(k, v) for k, v in SERIES.items() if q.split()[0] in v[0].lower()]
        return "".join(f'''<article class="bg-base-300 flex gap-4 p-4"><section class="w-full">
          <a href="https://weebcentral.com/series/{k}/{v[1]}"><article><picture>
          <img src="https://temp.compsci88.com/cover/fallback/{k}.jpg" alt="{v[0]} cover" width="400"></picture></article></a>
          </section></article>''' for k, v in achadas).encode()
    if "/full-chapter-list" in url:
        k = url.split("/series/")[1].split("/")[0]
        return "".join(f'''<div x-data><a href="/chapters/{cap_id(k, n)}" class="hover:bg-base-300 flex-1">
          <span class="me-2"><img src="/static/images/chapter-badge-official.svg"></span>
          <span class="grow flex items-center gap-2"><span class="">Chapter {leitura.num_txt(n)}</span></span></a></div>'''
                       for n in reversed(SERIES[k][2])).encode()
    if "/images?" in url:
        cid = url.split("/chapters/")[1].split("/")[0]
        n = int(cid[16:]) / 10
        return (f'<section id="chapter-images" x-data="{{ scrollDown() {{}} }}">' + "".join(
            f'<img\n\t\tsrc="https://hot.planeptune.us/manga/X/{int(n):04d}-{p:03d}.png"\n\t\talt="Page {p}" />' for p in range(1, 4))
            + '<img src="/static/images/broken_image.jpg"></section>').encode()
    raise RuntimeError("sem internet no teste: " + url)


baixar._pedir = falso
baixar.ESPACO_SITE = 0

print("Achar a série na WeebCentral")
d = leitura._load()
s1, s2, s3, s4 = (leitura.nova_serie(n) for n in ("Na Honjaman Level Up", "Twin Star Exorcists", "Série Que Não Existe", "Quadrinho do PC"))
s1["titulos_alt"] = ["Solo Leveling", "Only I Level Up"]
s1["ultimo_lido"] = 2.0
s2["titulos_alt"] = ["Twin Star"]
s4["local"] = {"pasta": "x", "caps": [], "paginas": {}}
d["series"] += [s1, s2, s3, s4]
leitura._save(d)
r = c.get(f"/api/leitura/{s1['id']}/baixar").get_json()
check(r["ligada"]["id"] == "01AAAAAAAAAAAAAAAAAAAAAAAA" and r["ligada"]["titulo"] == "Solo Leveling",
      "pelo nome alternativo, um único resultado com o mesmo nome (Ragnarok também veio, mas é outra): ligada sozinha")
check([x["n"] for x in r["capitulos"]] == [1, 2, 3, 4, 5, 5.5, 6] and r["lido"] == 2, "lista os capítulos que estão lá, em ordem")
r = c.get(f"/api/leitura/{s2['id']}/baixar").get_json()
check(r["ligada"]["slug"] == "Twin-Star", "Twin Star e Twin Stars: só um tem o mesmo nome")
r = c.get(f"/api/leitura/{s3['id']}/baixar").get_json()
check(r["ligada"] is None and r["parecidas"] == [], "série que não está lá: diz que não achou")
check(c.get(f"/api/leitura/{s4['id']}/baixar").status_code == 400, "quadrinho do PC não precisa baixar")
d = leitura._load()
leitura.achar(d, s3["id"])["titulos_alt"] = ["Solo"]
leitura._save(d)
r = c.get(f"/api/leitura/{s3['id']}/baixar").get_json()
check(r["ligada"] is None and len(r["parecidas"]) == 2, "nome só parecido: mostra as parecidas para você escolher")
c.post(f"/api/leitura/{s3['id']}/baixar/ligar", json=r["parecidas"][1])
check(leitura.achar(leitura._load(), s3["id"])["weebcentral"]["id"] == r["parecidas"][1]["id"], "“É esta”: fica ligada à escolhida")
check(c.post(f"/api/leitura/{s3['id']}/baixar/ligar", json={"id": "../x"}).status_code == 400, "endereço estranho é recusado")

print("Baixar")
r = c.post(f"/api/leitura/{s1['id']}/baixar", json={"nums": [3, 4, 5.5]}).get_json()
check(r["na_fila"] == 3, "três capítulos na fila")
fim = time.time() + 20
while time.time() < fim and baixar.estado["ativo"]:
    time.sleep(0.05)
arq = baixar.arquivo(s1["id"], 3)
with zipfile.ZipFile(arq) as z:
    nomes = z.namelist()
check(arq.exists() and nomes == ["001.png", "002.png", "003.png"], "cada capítulo vira um CBZ com as páginas em ordem")
check(not any("broken_image" in u for u, _ in PEDIDOS), "a imagem de “página quebrada” do site não entra")
x = next(s for s in c.get("/api/leitura").get_json()["series"] if s["id"] == s1["id"])
check([b["n"] for b in x["baixados"]] == [3, 4, 5.5] and x["baixados"][2]["nome"] == "Chapter 5.5", "a série mostra os baixados")
r = c.get(f"/api/leitura/{s1['id']}/baixar").get_json()
check([x["n"] for x in r["capitulos"] if x["baixado"]] == [3, 4, 5.5], "e a lista do site marca os que já estão baixados")
check(c.post(f"/api/leitura/{s1['id']}/baixar", json={"nums": [3, 4]}).get_json()["na_fila"] == 0, "baixado não baixa de novo")
check(not list(baixar.pasta().rglob("*.parte")), "nenhum arquivo pela metade")

print("Devagar, como o Mihon")
PEDIDOS.clear()
baixar.ESPACO_SITE = 0.4
baixar._ultimo["site"] = 0
c.post(f"/api/leitura/{s1['id']}/baixar", json={"nums": [6]})
while baixar.estado["ativo"]:
    time.sleep(0.05)
ts = [t for u, t in PEDIDOS if "weebcentral.com" in u]
check(len(ts) >= 2 and all(b - a >= 0.38 for a, b in zip(ts, ts[1:])), "um pedido ao site de cada vez, com espaço entre eles")
baixar.ESPACO_SITE = 0

print("Site bloqueou")
TRAVAR["bloqueio"] = True
baixar.enfileirar(s1["id"], [{"id": cap_id("01AAAAAAAAAAAAAAAAAAAAAAAA", 1), "nome": "Chapter 1", "n": 1.0},
                             {"id": cap_id("01AAAAAAAAAAAAAAAAAAAAAAAA", 2), "nome": "Chapter 2", "n": 2.0}])
while baixar.estado["ativo"]:
    time.sleep(0.05)
st = c.get("/api/leitura/baixando").get_json()
check("parou" in st["erro"] and st["erros"] == 2 and not st["pendentes"], "o site recusou: para tudo e avisa, sem insistir")
TRAVAR["bloqueio"] = False
check(not baixar.arquivo(s1["id"], 1).exists(), "e não fica capítulo pela metade")

print("Ler sem internet")
baixar._pedir = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem internet"))
r = c.get(f"/api/leitura/baixado/{s1['id']}/3").get_json()
check(r["paginas"] == 3 and r["pagina"] == 0, "sem internet, o capítulo abre com as páginas")
img = c.get(f"/api/leitura/baixado/{s1['id']}/3/2")
check(img.status_code == 200 and img.mimetype == "image/png" and img.data[:4] == b"\x89PNG", "cada página vem do arquivo baixado")
check(c.get(f"/api/leitura/baixado/{s1['id']}/3/9").status_code == 404, "página que não existe")
check(c.get(f"/api/leitura/baixado/{s1['id']}/2").status_code == 404, "capítulo que não foi baixado")
c.post(f"/api/leitura/baixado/{s1['id']}/3/progresso", json={"pagina": 1})
check(c.get(f"/api/leitura/baixado/{s1['id']}/3").get_json()["pagina"] == 1, "lembra a página onde você parou")
c.post(f"/api/leitura/baixado/{s1['id']}/4/progresso", json={"pagina": 2, "fim": True})
s = leitura.achar(leitura._load(), s1["id"])
check(s["ultimo_lido"] == 4 and s.get("mu_terminou_capitulo") and leitura._load()["leituras"][-1]["site"] == "baixado",
      "chegar ao fim conta como lido (e vai para o MangaUpdates)")

print("Apagar")
r = c.post(f"/api/leitura/{s1['id']}/baixados/apagar", json={"quais": "lidos"}).get_json()
s = leitura.achar(leitura._load(), s1["id"])
check(r["apagados"] == 2 and sorted(s["baixados"]) == ["5.5", "6"] and not baixar.arquivo(s1["id"], 3).exists(),
      "apagar os já lidos deixa os outros")
r = c.get("/api/leitura/baixados").get_json()
check(r["capitulos"] == 2 and r["bytes"] > 0, "a aba Geral sabe quanto espaço os baixados ocupam")

print("Casos da revisão")
baixar._pedir = falso
check(baixar._numero("Side Story 2") is None and baixar._numero("Chapter 12") == 12 and baixar._numero("Special Chapter 3") == 3,
      "extras sem número de capítulo (Side Story 2) não viram o capítulo 2")
lento = {"seg": 0.3}
_rapido = falso


def devagar(url, imagem=False):
    if imagem:
        time.sleep(lento["seg"])
    return _rapido(url, imagem)


baixar._pedir = devagar
c.post(f"/api/leitura/{s1['id']}/baixar", json={"nums": [1]})
fim = time.time() + 5
while time.time() < fim and not baixar.estado["atual"]:
    time.sleep(0.02)
r = c.post(f"/api/leitura/{s1['id']}/baixar", json={"nums": [1]}).get_json()
check(r["na_fila"] == 0 and r["pendentes"][s1["id"]] == ["1"], "pedir de novo o capítulo que está baixando não baixa duas vezes")
while baixar.estado["ativo"]:
    time.sleep(0.05)
baixar._pedir = falso
x = next(s for s in c.get("/api/leitura").get_json()["series"] if s["id"] == s1["id"])
check([b["n"] for b in x["baixados"]] == [1, 5.5, 6], "o capítulo 1 baixou uma vez só")
r = c.get(f"/api/leitura/baixado/{s1['id']}/6").get_json()
check(r["paginas"] == 3, "o leitor acha o capítulo pelo número, mesmo depois de um capítulo menor ter chegado")
d = leitura._load()
sj = leitura.nova_serie("Outra Entrada")
sj["nota"] = "Nota da outra."
d["series"].append(sj)
leitura._save(d)
baixar.enfileirar(sj["id"], [{"id": cap_id("01AAAAAAAAAAAAAAAAAAAAAAAA", 2), "nome": "Chapter 2", "n": 2.0}])
while baixar.estado["ativo"]:
    time.sleep(0.05)
leitura.juntar_series([s1["id"], sj["id"]], s1["id"])
s = leitura.achar(leitura._load(), s1["id"])
check(sorted(s["baixados"]) == ["1", "2", "5.5", "6"] and baixar.arquivo(s1["id"], 2).exists() and "Nota da outra." in s["nota"],
      "juntar séries junta os baixados (os arquivos vão para a principal) e as notas")
pasta_s3 = baixar.pasta() / s3["id"]
c.post(f"/api/leitura/{s3['id']}/baixar", json={"nums": [1]})
while baixar.estado["ativo"]:
    time.sleep(0.05)
check(pasta_s3.exists(), "(a outra série tem um capítulo baixado)")
c.delete(f"/api/leitura/{s3['id']}")
check(not pasta_s3.exists(), "apagar a série apaga também os capítulos baixados dela")

print("Tela")
baixar._pedir = falso
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8788, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
OUT = S / "telas"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1320, "height": 860})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8788/")
    pg.evaluate("trocarEstante('leitura')")
    pg.wait_for_selector("#content .card")
    pg.evaluate(f"openDrawer('{s2['id']}')")
    pg.wait_for_selector("#baixarBtn")
    pg.click("#baixarBtn")
    pg.wait_for_selector("#baixarCorpo button.btn.primary")
    check("Twin Star" in pg.inner_text("#baixarCorpo") and "1 capítulo" in pg.inner_text("#baixarCorpo"),
          "a janela mostra a série achada e quantos capítulos ela tem")
    pg.screenshot(path=str(OUT / "baixar_janela.png"))
    pg.click("#baixarCorpo button.btn.primary")
    pg.wait_for_selector("#lerBaixado", timeout=20000)
    check("1 capítulo baixado" in pg.inner_text("#secBaixados"), "baixou e o painel mostra")
    pg.screenshot(path=str(OUT / "baixar_painel.png"))
    pg.click("#lerBaixado")
    pg.wait_for_selector("#leitor.show img")
    pg.wait_for_function("[...document.querySelectorAll('#leitor img')].some(i => i.complete && i.naturalWidth > 0)")
    check("Twin Star Exorcists" in pg.inner_text("#leitor .lbar"), "abre no leitor da Estante")
    pg.screenshot(path=str(OUT / "baixar_leitor.png"))
    pg.keyboard.press("Escape")
    pg.evaluate("closeDrawer(); openSettings('geral')")
    pg.wait_for_selector("#baixCfg .btn")
    check("ocupando" in pg.inner_text("#baixCfg"), "a aba Geral mostra o espaço usado")
    check(not erros, "sem erros na página: " + "; ".join(erros))
    b.close()
srv.shutdown()
print(f"\nTudo certo: {ok} verificações.")
