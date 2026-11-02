"""Jogos organizados em pastas e subpastas: categorias, pastas de versão, versões novas e coleções que seguem as pastas.
Rode: python3 testar_pastas.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import json
import os
import shutil
import sys
import threading
from pathlib import Path

S = Path(_SAIDA)
T = S / "pastas"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import falso_pc  # noqa: E402

J = T / "Jogos"  # a pasta acompanhada


def exe(rel):
    falso_pc.exe(J / rel)


def arq(rel, texto="x"):
    p = J / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, "utf-8")


exe("RPG/Dragon Quest Fan/DQFan.exe")
exe("RPG/Ação/Blade Saga-0.2-pc/BladeSaga.exe")
exe("RPG/Ação/Blade Saga-0.1-pc/BladeSaga.exe")            # versão antiga ao lado da nova
exe("Visual Novel/Outro Jogo/versão 0.5/OutroJogo.exe")     # pasta que é só a versão
exe("Visual Novel/Romance/Amor Eterno/AmorEterno.exe")      # Ren'Py: tem executáveis dentro de lib
arq("Visual Novel/Romance/Amor Eterno/game/script.rpy")
exe("Visual Novel/Romance/Amor Eterno/lib/py3-windows-x86_64/python.exe")
exe("Mundo Aberto/Cidade Neon/bin/x64/CidadeNeon.exe")      # executável só em bin\x64 (como o Cyberpunk)
arq("Mundo Aberto/Cidade Neon/engine/config.ini")
exe("Simulação/Trem Fever (2026)/TremFever.exe")            # como o Transport Fever 3: a mesma pasta dentro
exe("Simulação/Trem Fever (2026)/Trem Fever/TremFever.exe")
arq("Vídeos/Filmes/filme.txt")                              # categorias sem jogo nenhum
arq("Fotos/2025/foto.txt")

# a biblioteca de antes (formato 2), com uma coleção que tem barra no nome
(T / "dados").mkdir(parents=True)
(T / "dados" / "library.json").write_text(json.dumps({"versao": 2, "guardados": [], "games": [
    {"id": "velho1", "name": "Jogo Antigo", "exe": str(T / "Outro" / "antigo.exe"), "tags": ["Ação/Aventura", "Favoritos"]}]}), "utf-8")
falso_pc.exe(T / "Outro" / "antigo.exe")

import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402

app.completar_avulso = lambda gid: None  # sem internet neste teste
app.sync_lojas = lambda *a, **k: None
c = app.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg)


def jogos():
    return {g["name"]: g for g in c.get("/api/games").get_json()["games"]}


print("Dados antigos")
lib = app.get_lib()
check(lib["games"][0]["tags"] == ["Ação - Aventura", "Favoritos"], "coleção antiga com barra no nome não vira subcoleção (vira “Ação - Aventura”)")
app.save_lib(lib)
check((T / "dados" / "library-antes-v3.json").exists() and json.loads((T / "dados" / "library.json").read_text("utf-8"))["versao"] == 3,
      "cópia de segurança antes da conversão e formato novo gravado")

print("Busca nas pastas")
r = c.post("/api/scan", json={"folder": str(J)}).get_json()
por_pasta = {Path(x["pasta"]).relative_to(J).as_posix(): x for x in r}
check(set(por_pasta) == {"RPG/Dragon Quest Fan", "RPG/Ação/Blade Saga-0.2-pc", "RPG/Ação/Blade Saga-0.1-pc",
                         "Visual Novel/Outro Jogo/versão 0.5", "Visual Novel/Romance/Amor Eterno", "Mundo Aberto/Cidade Neon",
                         "Simulação/Trem Fever (2026)"}, f"cada jogo vira um jogo só e nenhuma categoria vira jogo {sorted(por_pasta)}")
check(not any("lib" in p or "Trem Fever/Trem Fever" in p for p in por_pasta), "pastas de dentro de um jogo (lib, a pasta repetida) não viram outro jogo")
check(por_pasta["RPG/Ação/Blade Saga-0.2-pc"]["colecao"] == "RPG/Ação" and por_pasta["RPG/Dragon Quest Fan"]["colecao"] == "RPG",
      "cada jogo sabe as categorias até ele (RPG/Ação)")
ov = por_pasta["Visual Novel/Outro Jogo/versão 0.5"]
check(ov["name"] == "Outro Jogo" and ov["colecao"] == "Visual Novel", "pasta que é só a versão: o nome e a coleção vêm da pasta de cima")
check(por_pasta["RPG/Ação/Blade Saga-0.1-pc"].get("antiga") and not por_pasta["RPG/Ação/Blade Saga-0.2-pc"].get("antiga"),
      "duas versões lado a lado: a mais antiga fica marcada para não entrar")
check(por_pasta["Mundo Aberto/Cidade Neon"]["exe"].endswith(os.path.join("bin", "x64", "CidadeNeon.exe")),
      "jogo com o executável só em bin\\x64 é achado")
check(por_pasta["Visual Novel/Romance/Amor Eterno"]["exe"].endswith("AmorEterno.exe"), "Ren'Py abre pelo executável certo, não pelo python de dentro")

print("Acompanhar a pasta")
cfg = app.get_cfg()
cfg["pastas"] = [str(J)]
app.save_cfg(cfg)
app.sync_folders()
gs = jogos()
check({"Dragon Quest Fan", "Blade Saga", "Outro Jogo", "Amor Eterno", "Cidade Neon", "Trem Fever"} <= set(gs) and len(gs) == 7,
      f"6 jogos novos, sem repetir a versão antiga {sorted(gs)}")
check(Path(app.find_game(app.get_lib(), gs["Blade Saga"]["id"])["exe"]).parent.name == "Blade Saga-0.2-pc", "entrou a versão mais nova")
check(all(not g["tags"] for n, g in gs.items() if n != "Jogo Antigo"), "com a opção desligada, as pastas não viram coleções")

print("Versões novas")
with app.lock:
    lib = app.get_lib()
    for g in lib["games"]:
        if g["name"] in ("Outro Jogo", "Blade Saga", "Dragon Quest Fan"):
            g["playtime"], g["tags"] = 3600, ["Minha coleção"]
    app.save_lib(lib)
exe("Visual Novel/Outro Jogo/versão 0.6/OutroJogo.exe")      # a 0.5 continua lá
shutil.rmtree(J / "RPG/Ação/Blade Saga-0.2-pc")
exe("RPG/Ação/Blade Saga-0.3-pc/BladeSaga.exe")
app.sync_folders()
gs = jogos()
check(len(gs) == 7, "versões novas não viram jogos repetidos")
og = app.find_game(app.get_lib(), gs["Outro Jogo"]["id"])
check(Path(og["pasta_jogo"]).name == "versão 0.6" and og["playtime"] == 3600 and og["tags"] == ["Minha coleção"],
      "versão nova numa subpasta, ao lado da antiga: o jogo passa a abrir por ela, com tempo jogado e coleções")
bs = app.find_game(app.get_lib(), gs["Blade Saga"]["id"])
check(Path(bs["exe"]).parent.name == "Blade Saga-0.3-pc" and bs["playtime"] == 3600, "pasta da versão trocada (0.2 virou 0.3): continua o mesmo jogo")
exe("RPG/Ação/Blade Saga-0.1b-pc/BladeSaga.exe")              # uma versão mais velha que aparece
app.sync_folders()
check(len(jogos()) == 7 and Path(app.find_game(app.get_lib(), gs["Blade Saga"]["id"])["exe"]).parent.name == "Blade Saga-0.3-pc",
      "versão mais velha que aparecer não vira outro jogo nem troca a atual")

print("Coleções que seguem as pastas")
check(c.post("/api/config", json={"colecoes_pastas": True}).get_json()["ok"], "opção ligada nas Configurações")
gs = jogos()
check(gs["Blade Saga"]["tags"] == ["Minha coleção", "RPG/Ação"] and gs["Blade Saga"]["colecao_pasta"] == "RPG/Ação",
      "o jogo entra na coleção da pasta, sem perder a coleção que você criou")
check(gs["Outro Jogo"]["tags"] == ["Minha coleção", "Visual Novel"] and gs["Trem Fever"]["tags"] == ["Simulação"], "cada jogo na coleção das pastas dele")
check(gs["Jogo Antigo"]["tags"] == ["Ação - Aventura", "Favoritos"], "jogo fora das pastas acompanhadas continua com as coleções dele")
shutil.move(str(J / "RPG/Dragon Quest Fan"), str(J / "RPG/Ação/Dragon Quest Fan"))
app.sync_folders()
dq = jogos()["Dragon Quest Fan"]
check(dq["tags"] == ["Minha coleção", "RPG/Ação"] and dq["playtime"] == 3600, "mudou o jogo de pasta: ele muda de coleção sozinho e mantém o resto")
lib_disco = json.loads((T / "dados" / "library.json").read_text("utf-8"))
check(all("RPG/Ação" not in g.get("tags", []) for g in lib_disco["games"]), "a coleção da pasta não se mistura com as suas no arquivo")
g = c.patch(f"/api/games/{dq['id']}", json={"tags": ["Minha coleção"]}).get_json()
check(g["tags"] == ["Minha coleção"], "tirar o jogo da coleção da pasta funciona")
app.sync_folders()
check(jogos()["Dragon Quest Fan"]["tags"] == ["Minha coleção"], "e ele não volta sozinho para ela")
g = c.patch(f"/api/games/{dq['id']}", json={"tags": ["Minha coleção", "RPG/Ação", " Nova / Sub "]}).get_json()
check(g["tags"] == ["Minha coleção", "Nova/Sub", "RPG/Ação"], "pôr de volta; e “Nova / Sub” vira a subcoleção Nova/Sub")
c.post("/api/config", json={"colecoes_pastas": False})
check(jogos()["Blade Saga"]["tags"] == ["Minha coleção"], "opção desligada: as coleções das pastas somem e as suas ficam")
c.post("/api/config", json={"colecoes_pastas": True})

print("Acompanhar mais pastas pelas Configurações")
falso_pc.exe(T / "Outros Jogos" / "Jogo Extra" / "JogoExtra.exe")
falso_pc.exe(T / "Mais Jogos" / "Terceiro" / "Terceiro.exe")
r = c.post("/api/pastas/acrescentar", json={"pasta": str(T / "Nao Existe")})
check(r.status_code == 400 and "não existe" in r.get_json()["error"], "pasta que não existe: avisa")
r = c.post("/api/pastas/acrescentar", json={"pasta": str(J)})
check(r.status_code == 400 and "já é acompanhada" in r.get_json()["error"], "a mesma pasta duas vezes: avisa")
r = c.post("/api/pastas/acrescentar", json={"pasta": str(J / "RPG")})
check(r.status_code == 400 and "dentro de uma pasta acompanhada" in r.get_json()["error"], "pasta que já fica dentro de uma acompanhada: avisa")
check(c.post("/api/pastas/acrescentar", json={"pasta": str(T / "Outros Jogos")}, headers={"Origin": "https://site-qualquer.com"}).status_code == 403,
      "outros sites não conseguem acrescentar pastas")
r = c.post("/api/pastas/acrescentar", json={"pasta": f'"{T / "Outros Jogos"}"'})
check(r.status_code == 200 and str(T / "Outros Jogos") in app.get_cfg()["pastas"], "pasta nova acompanhada (aceita o caminho colado com aspas)")
import time  # noqa: E402
fim = time.time() + 10
while time.time() < fim and "Jogo Extra" not in jogos():
    time.sleep(0.3)
check("Jogo Extra" in jogos(), "e os jogos dela já entram na estante")

print("Telas")
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8792, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
(S / "telas").mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    nav = pw.chromium.launch()
    pg = nav.new_page(viewport={"width": 1320, "height": 900})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8792/")
    pg.evaluate("localStorage.setItem('estante.estante', JSON.stringify('jogos')); localStorage.removeItem('estante.colAbertas')")
    pg.reload()
    pg.wait_for_selector(".card")
    nomes = lambda: pg.evaluate("[...document.querySelectorAll('.col-item .item')].map(b => b.childNodes[1].textContent.trim())")
    check("RPG" in nomes() and "Ação" not in nomes(), f"na barra lateral, RPG aparece fechada (a subcoleção Ação fica dentro) {nomes()}")
    rpg = pg.locator(".col-item", has=pg.locator(".item", has_text="RPG")).first
    rpg.locator(".caret").click()
    check("Ação" in nomes(), "clicar na setinha abre a coleção e mostra a subcoleção")
    rpg.locator(".item").click()
    titulos = sorted(pg.locator(".grid .card .t").all_inner_texts())
    check(titulos == ["Blade Saga", "Dragon Quest Fan"], f"clicar em RPG mostra também os jogos das subcoleções {titulos}")
    pg.screenshot(path=str(S / "telas" / "p1_colecoes_arvore.png"))
    pg.locator(".col-item .item").filter(has_text="Ação").filter(has_not_text="Aventura").first.click()
    check("RPG › Ação" in pg.inner_text(".head h1"), "a subcoleção aparece como RPG › Ação")
    pg.evaluate("openSettings()")
    pg.wait_for_selector("text=Criar e manter coleções seguindo as pastas")
    check(pg.locator("text=Criar e manter coleções seguindo as pastas >> xpath=.. >> input").is_checked(), "opção aparece ligada nas Configurações")
    check("Jogos\\RPG\\Ação" in pg.inner_text("#modal"), "o exemplo de caminho aparece certinho")
    pg.locator("text=Criar e manter coleções seguindo as pastas").scroll_into_view_if_needed()
    pg.screenshot(path=str(S / "telas" / "p2_opcao_colecoes.png"))
    pg.fill("#pNova", str(T / "Mais Jogos"))
    pg.click("#pNova ~ button.primary")
    pg.wait_for_function("document.querySelector('#modal') && document.querySelector('#modal').innerText.includes('Mais Jogos')", timeout=10000)
    check(str(T / "Mais Jogos") in app.get_cfg()["pastas"], "pelas Configurações: cola o caminho, clica em Acompanhar e a pasta entra na lista")
    pg.locator("#pNova").scroll_into_view_if_needed()
    pg.screenshot(path=str(S / "telas" / "p4_acompanhar_pasta.png"))
    pg.evaluate("closeModal(); openScan()")
    pg.fill("#sDir", str(J))
    pg.click("#modal button:has-text('Escanear')")
    pg.wait_for_selector(".scan-row")
    txt = pg.inner_text("#sOut")
    check("RPG › Ação" in txt and "Versão mais antiga" in txt, "a busca mostra a pasta de cada jogo e marca as versões antigas")
    pg.screenshot(path=str(S / "telas" / "p3_busca_pastas.png"))
    check(not erros, f"sem erros na página {erros}")
    nav.close()
srv.shutdown()

print(f"\nTudo certo: {ok} verificações.")
