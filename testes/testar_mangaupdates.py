"""Conta do MangaUpdates: entrar, acesso protegido pelo Windows, troca nos dois sentidos, séries de fora,
duvidosas, acesso vencido e desconectar. Com um MangaUpdates de mentira. Rode: python3 testar_mangaupdates.py"""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import contextlib
import io
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
from pathlib import Path

S = Path(_SAIDA)
T = S / "mangaupdates"
shutil.rmtree(T, ignore_errors=True)
T.mkdir(parents=True)
os.environ["ESTANTE_DATA"] = str(T / "dados")
sys.path.insert(0, _PROJ)
sys.path.insert(0, os.path.dirname(__file__))
import sem_janelas  # noqa: E402,F401  (nada abre de verdade no Windows)
import app  # noqa: E402
import leitura  # noqa: E402
import mangaupdates as mu  # noqa: E402
import testar_leitura_mocks as mocks  # noqa: E402

leitura._http_json = mocks.http_falso
leitura.enfileirar = lambda *a, **k: None
mu.time.sleep = lambda s: None  # o MangaUpdates de mentira não precisa de espera
SENHA, TOKEN = "segredo-123", "tok-abc-987"

# ---- MangaUpdates de mentira
LA = {109: (0, 8, "Pelo Link"), 999: (0, 2, "Número Velho"), 101: (0, 60, "Série A"), 102: (0, 20, "Série B"), 103: (0, 10, "Série C"),
      105: (1, 0, "Série Nova Lá"), 106: (0, 3, "Sem Ligacao"), 107: (0, 7, "Tower of Gods")}
CHAMADAS = []
VALIDO = {"token": TOKEN}


def _erro(cod, corpo=None):
    return urllib.error.HTTPError("https://api.mangaupdates.com", cod, "erro", {},
                                  io.BytesIO(json.dumps(corpo).encode()) if corpo else None)


def falso(metodo, caminho, corpo=None, token=""):
    CHAMADAS.append((metodo, caminho, json.loads(json.dumps(corpo)) if corpo is not None else None, token))
    if caminho == "/account/login":
        if corpo["username"] == "pessoa-teste" and corpo["password"] == SENHA:
            return {"status": "success", "reason": "Successfully logged in", "context": {"session_token": TOKEN, "uid": 7}}
        raise _erro(401)
    if token != VALIDO["token"]:
        raise _erro(401)
    if caminho == "/account/logout":
        return {"status": "success"}
    if caminho.startswith("/lists/") and caminho.endswith("/search"):
        lid = int(caminho.split("/")[2])
        itens = [{"record": {"series": {"id": sid, "title": t}, "list_id": lid, "status": {"chapter": cap}}}
                 for sid, (l, cap, t) in LA.items() if l == lid]
        return {"total_hits": len(itens), "results": itens}
    if caminho == "/lists/series/update":
        if any(it["series"]["id"] == 999 for it in corpo):
            raise _erro(400)  # o MangaUpdates juntou essa série com outra: recusa o lote inteiro
        for it in corpo:
            t = LA.get(it["series"]["id"], (0, 0, "?"))[2]
            LA[it["series"]["id"]] = (it["list_id"], it["status"]["chapter"], t)
        return {"status": "success"}
    if caminho == "/lists/series":
        if any(it["series"]["id"] == 998 for it in corpo):  # série que o MangaUpdates juntou com outra: recusa o lote
            raise _erro(400, {"status": "exception", "reason": "Validation error",
                              "context": {"errors": [{"field": "series.id", "error": "Invalid series"}]}})
        for it in corpo:
            LA[it["series"]["id"]] = (it["list_id"], it["status"]["chapter"], "adicionada")
        return {"status": "success"}
    raise _erro(404)


mu._pedido_http = falso
c = app.app.test_client()
ok = 0
saida = io.StringIO()  # tudo o que a Estante escreveria no estante.log


def check(cond, msg):
    global ok
    if not cond:
        print("FALHOU:", msg, file=sys.__stdout__, flush=True)
        print("--- registro:", saida.getvalue()[-1200:], mu.estado, file=sys.__stdout__, flush=True)
        raise SystemExit(1)
    ok += 1
    print("  ok -", msg, file=sys.__stdout__, flush=True)


def serie(nome):
    return next((s for s in leitura._load()["series"] if s["name"] == nome), None)


def chamadas(caminho):
    return [x for x in CHAMADAS if x[1] == caminho]


with app.lock:
    d = leitura._load()
    for nome, mu_id, lido, lista in [("Série A", 101, 50.0, "Lendo"), ("Série B", 102, 30.0, "Lendo"), ("Série C", 103, 10.0, "Terminado"),
                                     ("Série D", 104, 5.0, "Lendo"), ("Sem Ligacao", None, 1.0, "Lendo"), ("Tower of God", None, 600.0, "Lendo"),
                                     ("Série H", 108, 9.5, "Pausado"), ("Pelo Link", None, 12.0, "Lendo"), ("Número Velho", 999, 4.0, "Lendo")]:
        s = leitura.nova_serie(nome)
        s.update({"mu_id": mu_id, "ultimo_lido": lido, "lista_anilist": lista, "mu_tentado": True})
        if nome == "Pelo Link":
            s["url_mu"] = "https://www.mangaupdates.com/series/" + "31" + "/pelo-link"  # 31 em base 36 = 109
        d["series"].append(s)
    leitura._save(d)

with contextlib.redirect_stdout(saida):
    print("Entrar", file=sys.__stdout__)
    r = c.post("/api/leitura/mangaupdates/entrar", json={"usuario": "pessoa-teste", "senha": "errada"})
    check(r.status_code == 400 and "não aceitou" in r.get_json()["error"] and not mu.conectado(), "senha errada: avisa e não liga nada")
    check(c.post("/api/leitura/mangaupdates/entrar", json={"usuario": "pessoa-teste", "senha": SENHA},
                 headers={"Origin": "https://site-qualquer.com"}).status_code == 403, "outros sites não conseguem mandar usuário e senha")
    r = c.post("/api/leitura/mangaupdates/entrar", json={"usuario": "pessoa-teste", "senha": SENHA})
    check(r.status_code == 200 and r.get_json()["conectado"] and r.get_json()["usuario"] == "pessoa-teste", "usuário e senha certos: conta ligada")
    arq = T / "dados" / "mangaupdates.acesso"
    bruto = arq.read_bytes()
    check(arq.exists() and TOKEN.encode() not in bruto and SENHA.encode() not in bruto,
          "o acesso fica num arquivo à parte, protegido pelo Windows (não dá para ler o acesso nele)")
    check(mu._acesso() == TOKEN, "e a própria Estante, no seu usuário, consegue abrir")
    cfg_txt = (T / "dados" / "config.json").read_text("utf-8")
    check(TOKEN not in cfg_txt and SENHA not in cfg_txt and '"usuario": "pessoa-teste"' in cfg_txt, "nada de acesso nem senha no config.json, só o nome de usuário")
    check(all(TOKEN not in json.dumps(c.get(u).get_json()) for u in ("/api/leitura/mangaupdates", "/api/leitura/sites", "/api/leitura/minhas", "/api/config")),
          "nenhuma rota da Estante devolve o acesso (a extensão nunca recebe)")

    print("Primeira sincronização", file=sys.__stdout__)
    fim = time.time() + 10
    while time.time() < fim and (mu.estado["sincronizando"] or not mu._cfg().get("ultima")):
        time.sleep(0.1)
    st = c.get("/api/leitura/mangaupdates").get_json()
    check(serie("Série A")["ultimo_lido"] == 60, "leu mais adiantado lá (no Mihon): a Estante avança do 50 para o 60")
    atualizacoes = chamadas("/lists/series/update")
    check(len(atualizacoes[0][2]) > 1 and all(len(x[2]) < len(atualizacoes[0][2]) for x in atualizacoes[1:]),
          "o que mudou foi num pedido só; como o MangaUpdates recusou o lote por causa de uma série, dividiu até achar ela")
    check("recusou a série 999" in saida.getvalue() and mu.estado["erro"] == "",
          "a recusa vai para o registro e não atrapalha o resto da sincronização")
    enviados = {x["series"]["id"]: x for x in atualizacoes[0][2]}
    check(serie("Pelo Link")["mu_id"] == 109 and LA[109][1] == 12, "série sem número, mas com o link do MangaUpdates: ligada pelo link e sincronizada")
    check(LA[999][1] == 2 and LA[102][1] == 30, "a série recusada fica de fora e as outras vão mesmo assim")
    check(enviados[102]["status"]["chapter"] == 30, "a Estante estava mais adiantada (30 contra 20): o MangaUpdates avança")
    check(enviados[103]["list_id"] == 2 and LA[103][0] == 2, "situação diferente na primeira vez: vale a da Estante (Terminado)")
    check(101 not in enviados, "série em que o MangaUpdates estava à frente não é mandada de volta")
    check(not chamadas("/lists/series") and 104 not in LA and st["faltam_la"] == 2,
          "séries da Estante que não estão na lista de lá não são postas em massa (a tela mostra quantas)")
    check(serie("Sem Ligacao")["mu_id"] == 106, "série de lá com o mesmo nome de uma da Estante sem ligação: ligada sozinha")
    check([x["titulo"] for x in st["fora"]] == ["Série Nova Lá"], "série que só está lá aparece para trazer")
    check([x["titulo"] for x in st["duvidosas"]] == ["Tower of Gods"] and st["duvidosas"][0]["parecidas"][0]["nome"] == "Tower of God",
          "nome só parecido (Tower of Gods / Tower of God): a Estante pergunta em vez de chutar")

    print("Depois", file=sys.__stdout__)
    n = len(CHAMADAS)
    mu.sincronizar(ler=False)
    check(len(CHAMADAS) == n, "sem nada mudado, a verificação de 5 em 5 minutos não pede nada ao MangaUpdates")
    LA[101] = (4, 60, "Série A")
    mu.sincronizar(ler=True)
    check(serie("Série A")["lista_anilist"] == "Pausado", "mudou a situação só lá (Pausado): vem para a Estante")
    a = serie("Série A")
    c.patch(f"/api/leitura/{a['id']}", json={"ultimo_lido": 65})
    c.patch(f"/api/leitura/{serie('Série D')['id']}", json={"ultimo_lido": 6})
    c.patch(f"/api/leitura/{serie('Série B')['id']}", json={"ultimo_lido": 31.5})
    n = len(CHAMADAS)
    mu.sincronizar(ler=False)
    novas = CHAMADAS[n:]
    upd = [x for x in novas if x[1] == "/lists/series/update"]
    add = [x for x in novas if x[1] == "/lists/series"]
    check(len(upd) == 1 and {x["series"]["id"] for x in upd[0][2]} == {101, 102} and LA[101][1] == 65 and LA[102][1] == 31,
          "capítulos lidos na Estante vão juntos num pedido (31.5 vai como 31, porque lá o capítulo é inteiro)")
    check(len(add) == 1 and add[0][2][0]["series"]["id"] == 104 and LA[104][1] == 6, "terminou um capítulo de uma série que não estava lá: ela entra na lista")

    print("Sem internet na hora de mandar", file=sys.__stdout__)
    c.patch(f"/api/leitura/{serie('Série B')['id']}", json={"ultimo_lido": 40})
    _falso_ok = mu._pedido_http

    def sem_rede(metodo, caminho, corpo=None, token=""):
        if caminho == "/lists/series/update":
            raise urllib.error.URLError("sem internet")
        return _falso_ok(metodo, caminho, corpo, token)
    mu._pedido_http = sem_rede
    mu.sincronizar(ler=False)
    check(serie("Série B")["mu_sinc"]["cap"] == 31 and LA[102][1] == 31, "sem internet: a mudança não conta como mandada")
    mu._pedido_http = _falso_ok
    mu.sincronizar(ler=False)
    check(LA[102][1] == 40 and serie("Série B")["mu_sinc"]["cap"] == 40, "e vai na sincronização seguinte")

    print("Pôr na lista, trazer e confirmar", file=sys.__stdout__)
    with app.lock:
        d = leitura._load()
        j = leitura.nova_serie("Juntada Lá")
        j.update({"mu_id": 998, "ultimo_lido": 3.0, "lista_anilist": "Lendo", "mu_tentado": True})
        d["series"].append(j)
        leitura._save(d)
    c.post("/api/leitura/mangaupdates/por-na-lista")
    fim = time.time() + 10
    while time.time() < fim and not (mu._cfg().get("ultimo_por") and not mu.estado["sincronizando"]):
        time.sleep(0.1)
    check(LA.get(108, (None, None))[:2] == (4, 9), "Pôr na lista: a série que faltava foi para lá, com a situação e o capítulo")
    st = c.get("/api/leitura/mangaupdates").get_json()
    up = st["ultimo_por"]
    check(998 not in LA and up["postas"] == 1 and [x["nome"] for x in up["recusadas"]] == ["Juntada Lá"]
          and "Invalid series" in up["recusadas"][0]["motivo"] and st["faltam_la"] == 1,
          "uma série recusada não impede as outras; a tela mostra qual foi recusada e o motivo")
    check(serie("Juntada Lá").get("mu_sinc") in (None, {}) and serie("Série H")["mu_sinc"] == {"lista": "Pausado", "cap": 9},
          "só as que entraram ficam marcadas como sincronizadas")
    r = c.post("/api/leitura/mangaupdates/trazer", json={}).get_json()
    check(r["novas"] == 1 and serie("Série Nova Lá")["mu_id"] == 105 and serie("Série Nova Lá")["lista_anilist"] == "Quero ler",
          "Trazer: a série que só estava lá entrou na Estante, já ligada")
    check(c.post("/api/leitura/mangaupdates/trazer", json={}).status_code == 400 and len([s for s in leitura._load()["series"] if s["name"] == "Série Nova Lá"]) == 1,
          "trazer de novo não duplica")
    st = c.post("/api/leitura/mangaupdates/ligar", json={"mu_id": 107, "id": serie("Tower of God")["id"]}).get_json()
    check(serie("Tower of God")["mu_id"] == 107 and not st["duvidosas"], "“É esta”: a duvidosa fica ligada à série certa")
    mu.sincronizar(ler=True)
    check(serie("Tower of God")["ultimo_lido"] == 600, "e o capítulo dela continua o da Estante (600), maior que o de lá")

    print("Acesso vencido e desconectar", file=sys.__stdout__)
    VALIDO["token"] = "outro"
    r = mu.sincronizar(ler=True)
    st = c.get("/api/leitura/mangaupdates").get_json()
    check(r.get("vencido") and st["vencido"] and st["conectado"], "acesso vencido: a Estante marca e pede para entrar de novo, sem travar")
    check(c.get("/api/leitura").status_code == 200, "e a Leitura continua funcionando")
    VALIDO["token"] = TOKEN
    c.post("/api/leitura/mangaupdates/entrar", json={"usuario": "pessoa-teste", "senha": SENHA})
    check(not c.get("/api/leitura/mangaupdates").get_json()["vencido"], "entrar de novo resolve")
    st = c.post("/api/leitura/mangaupdates/sair").get_json()
    check(not st["conectado"] and not (T / "dados" / "mangaupdates.acesso").exists() and chamadas("/account/logout"),
          "Desconectar avisa o MangaUpdates e apaga o acesso guardado")
    check(serie("Série A")["ultimo_lido"] == 65, "as séries e os capítulos na Estante continuam iguais")

log = saida.getvalue()
print(log[-600:] if "--ver" in sys.argv else "", end="")
print("Segredos")
check(SENHA not in log and TOKEN not in log, "nem a senha nem o acesso aparecem no que a Estante escreve no registro")
check(all(SENHA not in json.dumps(x[2]) for x in CHAMADAS if x[1] != "/account/login"), "a senha só foi usada no pedido de entrar")

print("Telas")
VALIDO["token"] = TOKEN
c.post("/api/leitura/mangaupdates/entrar", json={"usuario": "pessoa-teste", "senha": SENHA})
time.sleep(1)
with mu._lock:
    pass
leitura.cfg_leitura()  # garante as configurações
with app.lock:
    cfg, lc = leitura.cfg_leitura()
    lc["mangaupdates"].update(duvidosas=[{"mu_id": 200, "titulo": "Solo Levelling", "lista": "Lendo", "cap": 50, "parecidas": [{"id": "x", "nome": "Solo Leveling"}]}],
                              fora=[{"mu_id": 201, "titulo": "Uma Série de Lá", "lista": "Lendo", "cap": 3}], faltam_la=4, sem_ligacao=2)
    app.save_cfg(cfg)
from werkzeug.serving import make_server  # noqa: E402
srv = make_server("127.0.0.1", 8791, app.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright  # noqa: E402
(S / "telas").mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    nav = pw.chromium.launch()
    pg = nav.new_page(viewport={"width": 1320, "height": 900})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("http://127.0.0.1:8791/")
    pg.evaluate("localStorage.setItem('estante.estante', JSON.stringify('leitura'))")
    pg.reload()
    pg.wait_for_timeout(1200)
    pg.evaluate("openSettings()")
    pg.wait_for_selector("#muCfg .inline")
    t = pg.inner_text("#muCfg")
    check("Conta ligada: pessoa-teste" in t and "Solo Levelling" in t and "Uma Série de Lá" in t and "Pôr na lista" in t and "Desconectar" in t,
          "Configurações mostram a conta, as duvidosas, as séries de lá e os botões")
    pg.locator("#muCfg").scroll_into_view_if_needed()
    pg.screenshot(path=str(S / "telas" / "mu1_conectada.png"))
    pg.evaluate("closeModal()")
    c.post("/api/leitura/mangaupdates/sair")
    pg.evaluate("openSettings()")
    pg.wait_for_selector("#muSenha")
    check(pg.get_attribute("#muSenha", "type") == "password", "desconectada: campos de usuário e senha (a senha aparece escondida)")
    pg.fill("#muUsuario", "pessoa-teste")
    pg.fill("#muSenha", SENHA)
    pg.click("#muEntrarBtn")
    pg.wait_for_selector("text=Conta ligada: pessoa-teste", timeout=10000)
    check(mu.conectado(), "entrar pela tela funciona")
    pg.locator("#muCfg").scroll_into_view_if_needed()
    pg.screenshot(path=str(S / "telas" / "mu2_entrou.png"))
    check(not erros, f"sem erros na página {erros}")
    nav.close()
srv.shutdown()

print(f"\nTudo certo: {ok} verificações.")
