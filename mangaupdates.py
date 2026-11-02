"""
Sua conta do MangaUpdates: o capítulo onde você parou fica igual na Estante, no Mihon e no site.

Esta é a única exceção à regra de não guardar acesso de conta, e só deste jeito:
  - a senha é usada só para entrar e nunca é guardada nem escrita no registro (estante.log);
  - o que fica guardado é o acesso que o MangaUpdates devolve (session_token), num arquivo à parte
    (mangaupdates.acesso), protegido pela proteção de dados do próprio Windows para o seu usuário (DPAPI):
    só o seu usuário, neste computador, consegue ler. Nunca vai para o config.json;
  - "Desconectar" apaga esse arquivo; a extensão do navegador nunca recebe o acesso.

A troca vai nos dois sentidos e o capítulo lido só anda para frente. A situação na lista também: quando ela
mudou dos dois lados desde a última sincronização, vale a da Estante. Na primeira vez, nada é posto na sua lista
do MangaUpdates em massa: a tela mostra quantas séries faltam lá, e você escolhe pôr. Depois, uma série em que você
terminar um capítulo entra sozinha na lista. Os pedidos ao MangaUpdates vão devagar, com espaço entre eles.
"""
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request

import leitura as L

API = "https://api.mangaupdates.com/v1"
# números das listas no MangaUpdates (são os mesmos que o Mihon usa) e a situação equivalente na Estante
LISTAS = {0: "Lendo", 1: "Quero ler", 2: "Terminado", 3: "Larguei", 4: "Pausado"}
DA_ESTANTE = {"Lendo": 0, "Relendo": 0, "Quero ler": 1, "Terminado": 2, "Larguei": 3, "Pausado": 4}
POR_PAGINA = 100
INTERVALO_LER = 3600      # lê a sua lista no MangaUpdates de hora em hora
INTERVALO_MANDAR = 300    # e manda o que mudou na Estante a cada 5 minutos, de uma vez (sem um pedido por capítulo)

estado = {"sincronizando": False, "erro": "", "ultima": 0.0, "ultima_leitura": 0.0}
_lock = threading.Lock()


class AcessoVencido(Exception):
    pass


def _arq():
    return L.CTX["DATA"] / "mangaupdates.acesso"


# ---------------------------------------------------------------- proteção de dados do Windows (DPAPI)

def _dpapi(dados, proteger):
    if os.name != "nt":
        raise RuntimeError("A proteção do acesso usa a do Windows; fora do Windows a conta do MangaUpdates não é ligada.")
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(dados, len(dados))
    entrada, saida = BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    f = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    # 0x1 = CRYPTPROTECT_UI_FORBIDDEN: nunca abre janela pedindo nada
    if not f(ctypes.byref(entrada), None, None, None, None, 0x1, ctypes.byref(saida)):
        raise RuntimeError("A proteção de dados do Windows recusou o acesso guardado.")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        kernel32.LocalFree(saida.pbData)


def _guardar_acesso(token):
    tmp = _arq().with_suffix(".tmp")
    tmp.write_bytes(_dpapi(token.encode("utf-8"), True))
    os.replace(tmp, _arq())


def _acesso():
    try:
        return _dpapi(_arq().read_bytes(), False).decode("utf-8")
    except FileNotFoundError:
        return ""


# ---------------------------------------------------------------- pedidos ao MangaUpdates

def _pedido_http(metodo, caminho, corpo=None, token=""):
    h = {"User-Agent": "Estante/2.0 (organizador pessoal)", "Accept": "application/json"}
    dados = None
    if corpo is not None:
        dados = json.dumps(corpo).encode("utf-8")
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + caminho, data=dados, headers=h, method=metodo)
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read(10_000_000).decode("utf-8")
    return json.loads(txt) if txt.strip() else {}


def _pedido(metodo, caminho, corpo=None):
    token = _acesso()
    if not token:
        raise AcessoVencido()
    try:
        return _pedido_http(metodo, caminho, corpo, token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            _marcar(vencido=True)
            raise AcessoVencido() from None
        raise


def _cfg():
    return L.cfg_leitura()[1].setdefault("mangaupdates", {})


def _marcar(**campos):
    with L.CTX["lock"]:
        cfg, lc = L.cfg_leitura()
        lc.setdefault("mangaupdates", {}).update(campos)
        L.CTX["save_cfg"](cfg)


def conectado():
    try:
        return _arq().exists()
    except KeyError:
        return False


def entrar(usuario, senha):
    """Entra na conta. A senha só passa por aqui: não é guardada nem escrita em lugar nenhum."""
    usuario = (usuario or "").strip()
    if not usuario or not senha:
        raise ValueError("Digite o usuário e a senha do MangaUpdates.")
    try:
        r = _pedido_http("PUT", "/account/login", {"username": usuario, "password": senha})
    except urllib.error.HTTPError as e:
        if e.code in (400, 401):
            raise ValueError("O MangaUpdates não aceitou esse usuário e senha. Confira e tente de novo.") from None
        raise ValueError(f"O MangaUpdates não respondeu agora (erro {e.code}). Tente de novo daqui a pouco.") from None
    except urllib.error.URLError:
        raise ValueError("Não consegui falar com o MangaUpdates. Confira a internet e tente de novo.") from None
    finally:
        senha = None  # noqa: F841  (não fica nada da senha por aqui)
    token = ((r or {}).get("context") or {}).get("session_token")
    if not token:
        raise ValueError("O MangaUpdates respondeu, mas não mandou o acesso. Tente de novo daqui a pouco.")
    _guardar_acesso(token)
    _marcar(usuario=usuario, vencido=False, desde=time.time())
    estado["erro"] = ""
    return usuario


def sair():
    """Desconecta: avisa o MangaUpdates (se der) e apaga o acesso guardado."""
    try:
        if conectado():
            _pedido("POST", "/account/logout")
    except Exception as e:
        print("[mangaupdates] não consegui avisar a saída (o acesso é apagado mesmo assim):", type(e).__name__)
    try:
        _arq().unlink()
    except FileNotFoundError:
        pass
    _marcar(usuario="", vencido=False, fora=[], duvidosas=[], faltam_la=0, sem_ligacao=0)


# ---------------------------------------------------------------- sincronizar

def ligar_pelos_links(d):
    """Séries que têm o link do MangaUpdates (vindo da lista do Comix, por exemplo) mas não o número da série:
    o código do link (mangaupdates.com/series/6z1uqw7) é o próprio número, escrito em base 36. Devolve quantas ligou."""
    n = 0
    for s in d["series"]:
        if s.get("mu_id") or s.get("local"):
            continue
        cod = L._mu_slug(s.get("url_mu"))
        if cod:
            try:
                s["mu_id"] = int(cod, 36)
                n += 1
            except ValueError:
                pass
    return n


ESPERA_MUDANCA = 6  # o MangaUpdates pede 5 segundos entre uma mudança e outra na lista


def _motivo(e):
    """O motivo que o MangaUpdates dá ao recusar um pedido (vem no corpo da resposta)."""
    try:
        corpo = json.loads(e.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return ""
    if not isinstance(corpo, dict):
        return ""
    motivo = str(corpo.get("reason") or "")
    ctx = corpo.get("context")
    if isinstance(ctx, dict) and ctx.get("errors"):
        motivo += " " + json.dumps(ctx["errors"], ensure_ascii=False)[:300]
    return motivo.strip()


def _mandar(caminho, itens):
    """Manda as mudanças de uma vez. Se o MangaUpdates recusar o lote (uma série que ele juntou com outra, por
    exemplo), divide o lote ao meio até achar as que ele recusa, com espaço entre os pedidos, e manda o resto.
    Devolve as recusadas: [(item, motivo)]."""
    recusadas = []

    def tentar(lote):
        for _ in range(4):
            try:
                _pedido("POST", caminho, lote)
                return
            except urllib.error.HTTPError as e:
                if e.code == 412:  # mandou rápido demais: espera e tenta de novo
                    time.sleep(ESPERA_MUDANCA)
                    continue
                if e.code != 400:
                    raise
                motivo = _motivo(e)
            if len(lote) == 1:
                recusadas.append((lote[0], motivo))
                return
            meio = len(lote) // 2
            time.sleep(ESPERA_MUDANCA)
            tentar(lote[:meio])
            time.sleep(ESPERA_MUDANCA)
            tentar(lote[meio:])
            return
        raise RuntimeError("o MangaUpdates pediu para esperar várias vezes seguidas")
    tentar(list(itens))
    for it, motivo in recusadas[:20]:
        print(f"[mangaupdates] recusou a série {it['series']['id']}: {motivo or 'sem motivo'}")
    return recusadas


def ler_minha_lista():
    """Todas as séries das suas listas no MangaUpdates: {número da série: (lista, capítulo, título)}."""
    out = {}
    for lid in LISTAS:
        pagina = 1
        while True:
            r = _pedido("POST", f"/lists/{lid}/search", {"page": pagina, "perpage": POR_PAGINA})
            res = r.get("results") or []
            for it in res:
                rec, meta = it.get("record") or {}, (it.get("metadata") or {}).get("series") or {}
                sid = (rec.get("series") or {}).get("id") or meta.get("series_id")
                if sid:
                    cap = L.num(((rec.get("status") or {}).get("chapter")))
                    out[int(sid)] = (lid, cap or 0, (rec.get("series") or {}).get("title") or meta.get("title") or "")
            if len(res) < POR_PAGINA or pagina * POR_PAGINA >= (r.get("total_hits") or 0):
                break
            pagina += 1
            time.sleep(1.5)
        time.sleep(1.5)
    return out


def sincronizar(ler=True):
    """ler=True: lê a sua lista no MangaUpdates e acerta a Estante, depois manda o que mudou na Estante.
    ler=False: só manda (é o que roda a cada 5 minutos, sem pedir nada ao MangaUpdates se nada mudou)."""
    if not conectado():
        return {"ok": False}
    if not _lock.acquire(blocking=False):
        return {"ok": False, "ocupado": True}
    estado.update(sincronizando=True, erro="")
    try:
        lista = ler_minha_lista() if ler else None
        ligar_por_nome, fora, duvidosas = {}, [], []
        if lista is not None:
            # séries da sua lista que ainda não estão ligadas a nenhuma da Estante. Feito numa cópia, sem travar
            # a Estante: pelo nome (ou nome alternativo) só quando um único bate; nome só parecido = duvidosa.
            copia = L._load()
            ligar_pelos_links(copia)
            ja = {s["mu_id"] for s in copia["series"] if s.get("mu_id")}
            livres = [s for s in copia["series"] if not s.get("mu_id") and not s.get("local")]
            nomes_de = lambda x: [x["name"]] + list(x.get("titulos_alt") or [])  # noqa: E731
            nomes = {}
            for s in livres:
                for n in {L.chave_nome(x) for x in nomes_de(s)}:
                    nomes.setdefault(n, []).append(s)
            for sid, (lid, cap, titulo) in lista.items():
                if sid in ja:
                    continue
                achadas = nomes.get(L.chave_nome(titulo)) or []
                if len(achadas) == 1 and achadas[0]["id"] not in ligar_por_nome.values():
                    ligar_por_nome[sid] = achadas[0]["id"]
                    continue
                item = {"mu_id": sid, "titulo": titulo, "lista": LISTAS[lid], "cap": cap}
                parecida = achadas[:3] if achadas else ([p] if (p := L.melhor(titulo, livres, nomes_de, 0.88)) else [])
                if parecida:  # duvidosa: a Estante pergunta em vez de chutar
                    item["parecidas"] = [{"id": s["id"], "nome": s["name"]} for s in parecida]
                    duvidosas.append(item)
                else:
                    fora.append(item)
        mandar, por, avancou, mudou_sit = [], [], 0, 0
        antes = {}  # como estava cada série mandada, para voltar atrás se o envio falhar (sem internet, por exemplo)
        with L.CTX["lock"]:
            d = L._load()
            ligar_pelos_links(d)
            for sid, serie_id in ligar_por_nome.items():
                s = L.achar(d, serie_id)
                if s and not s.get("mu_id"):
                    s["mu_id"] = sid
            por_mu = {s["mu_id"]: s for s in d["series"] if s.get("mu_id")}
            for sid, s in por_mu.items():
                sinc = s.get("mu_sinc") or {}
                lido = s.get("ultimo_lido") or 0
                sit = s.get("lista_anilist") or ""
                la = lista.get(sid) if lista is not None else None
                if la is not None:
                    lid, cap, _ = la
                    if cap and cap > lido:  # leu mais adiantado em outro lugar (Mihon, site): a Estante avança
                        s["ultimo_lido"] = lido = cap
                        avancou += 1
                    sit_la = LISTAS[lid]
                    if sit_la != sit:
                        mudou_aqui = sit != sinc.get("lista", sit_la)
                        if not mudou_aqui:  # mudou só no MangaUpdates: vem para cá
                            s["lista_anilist"] = sit = sit_la
                            mudou_sit += 1
                    sinc = {"lista": sit_la if sit == sit_la else sinc.get("lista", sit_la), "cap": cap}
                    s["mu_sinc"] = sinc
                elif lista is not None and sinc:
                    s["mu_sinc"] = sinc = {}  # saiu da sua lista lá
                # o que mudou na Estante desde a última sincronização vai para lá
                lid_aqui = DA_ESTANTE.get(sit)
                if lid_aqui is None:
                    continue
                cap_aqui = int(math.floor(lido))
                if sinc:
                    if cap_aqui > (sinc.get("cap") or 0) or sit != sinc.get("lista"):
                        mandar.append({"series": {"id": sid}, "list_id": lid_aqui, "status": {"chapter": cap_aqui}})
                        antes[sid] = (dict(sinc), bool(s.get("mu_terminou_capitulo")))
                        s["mu_sinc"] = {"lista": sit, "cap": max(cap_aqui, sinc.get("cap") or 0)}
                elif s.get("mu_terminou_capitulo"):  # terminou um capítulo depois de ligar a conta: entra na lista
                    por.append({"series": {"id": sid}, "list_id": lid_aqui, "status": {"chapter": cap_aqui}})
                    antes[sid] = ({}, True)
                    s["mu_sinc"] = {"lista": sit, "cap": cap_aqui}
                s.pop("mu_terminou_capitulo", None)
            if lista is not None:
                faltam = sum(1 for sid, s in por_mu.items() if sid not in lista and s.get("lista_anilist") in DA_ESTANTE)
                sem = sum(1 for s in d["series"] if not s.get("mu_id") and not s.get("local") and s.get("lista_anilist") in DA_ESTANTE)
            L._save(d)
        try:
            if mandar:
                _mandar("/lists/series/update", mandar)  # as recusadas (400) ficam como estão: mandar de novo daria o mesmo
                time.sleep(1.5)
            recusadas = {it["series"]["id"] for it, _ in _mandar("/lists/series", por)} if por else set()
        except Exception:
            # não chegou lá (sem internet, acesso vencido...): volta como estava, para ir na próxima vez
            with L.CTX["lock"]:
                d = L._load()
                for s in d["series"]:
                    if s.get("mu_id") in antes:
                        s["mu_sinc"], terminou = antes[s["mu_id"]]
                        if terminou:
                            s["mu_terminou_capitulo"] = True
                L._save(d)
            raise
        if por:
            if recusadas:  # não entraram: continuam fora da lista lá
                with L.CTX["lock"]:
                    d = L._load()
                    for s in d["series"]:
                        if s.get("mu_id") in recusadas:
                            s["mu_sinc"] = {}
                    L._save(d)
        campos = {"vencido": False}
        if lista is not None:
            campos.update(fora=fora, duvidosas=duvidosas, faltam_la=faltam, sem_ligacao=sem, na_lista=len(lista))
            estado["ultima_leitura"] = time.time()
        estado["ultima"] = time.time()
        _marcar(**campos, ultima=estado["ultima"])
        if avancou or mudou_sit or mandar or por:
            print(f"[mangaupdates] {avancou} série(s) avançada(s), {mudou_sit} situação(ões) vinda(s) de lá, "
                  f"{len(mandar)} atualizada(s) lá, {len(por)} posta(s) na sua lista")
        return {"ok": True, "avancou": avancou, "situacoes": mudou_sit, "mandadas": len(mandar), "postas": len(por)}
    except AcessoVencido:
        estado["erro"] = "vencido"
        return {"ok": False, "vencido": True}
    except Exception as e:
        print("[mangaupdates] sincronizar:", type(e).__name__, e)
        estado["erro"] = "Não consegui falar com o MangaUpdates agora. A Estante tenta de novo sozinha."
        return {"ok": False, "erro": estado["erro"]}
    finally:
        estado["sincronizando"] = False
        _lock.release()


def por_na_lista():
    """Põe na sua lista do MangaUpdates as séries da Estante que ainda não estão lá (você pediu, na tela).
    Só as que o MangaUpdates aceitar ficam marcadas como sincronizadas; as recusadas aparecem na tela, com o motivo."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "ocupado": True}
    estado.update(sincronizando=True, erro="")
    try:
        lista = ler_minha_lista()
        itens, nomes = [], {}
        for s in L._load()["series"]:
            sid, lid = s.get("mu_id"), DA_ESTANTE.get(s.get("lista_anilist") or "")
            if sid and lid is not None and sid not in lista and sid not in nomes:
                cap = int(math.floor(s.get("ultimo_lido") or 0))
                itens.append({"series": {"id": sid}, "list_id": lid, "status": {"chapter": cap}})
                nomes[sid] = (s["name"], s["lista_anilist"], cap)
        recusadas = []
        for i in range(0, len(itens), 100):  # de 100 em 100, com espaço entre os pedidos
            if i:
                time.sleep(ESPERA_MUDANCA)
            recusadas += _mandar("/lists/series", itens[i:i + 100])
        fora = {it["series"]["id"]: motivo for it, motivo in recusadas}
        with L.CTX["lock"]:
            d = L._load()
            for s in d["series"]:
                sid = s.get("mu_id")
                if sid in nomes and sid not in fora:
                    s["mu_sinc"] = {"lista": nomes[sid][1], "cap": nomes[sid][2]}
            L._save(d)
        postas = len(itens) - len(fora)
        _marcar(vencido=False, faltam_la=len(fora), ultimo_por={
            "quando": time.time(), "postas": postas,
            "recusadas": [{"mu_id": sid, "nome": nomes[sid][0], "motivo": m} for sid, m in fora.items()][:100]})
        print(f"[mangaupdates] pôr na lista: {postas} posta(s), {len(fora)} recusada(s)")
        return {"ok": True, "postas": postas, "recusadas": len(fora)}
    except AcessoVencido:
        estado["erro"] = "vencido"
        return {"ok": False, "vencido": True}
    except Exception as e:
        print("[mangaupdates] pôr na lista:", type(e).__name__, e)
        estado["erro"] = "Não consegui pôr as séries na sua lista do MangaUpdates agora. Tente de novo daqui a pouco."
        return {"ok": False, "erro": estado["erro"]}
    finally:
        estado["sincronizando"] = False
        _lock.release()


def ligar(mu_id, sid):
    """Você confirmou que a série da sua lista do MangaUpdates é esta da Estante."""
    with L.CTX["lock"]:
        d = L._load()
        s = L.achar(d, sid)
        if not s:
            raise ValueError("Série não encontrada.")
        s["mu_id"] = int(mu_id)
        L._save(d)
        cfg, lc = L.cfg_leitura()
        m = lc.setdefault("mangaupdates", {})
        m["duvidosas"] = [x for x in m.get("duvidosas") or [] if x["mu_id"] != int(mu_id)]
        L.CTX["save_cfg"](cfg)


def nao_e(mu_id):
    """Você disse que não é nenhuma das parecidas: a série vai para as que podem ser trazidas como nova."""
    with L.CTX["lock"]:
        cfg, lc = L.cfg_leitura()
        m = lc.setdefault("mangaupdates", {})
        item = next((x for x in m.get("duvidosas") or [] if x["mu_id"] == int(mu_id)), None)
        if item:
            m["duvidosas"].remove(item)
            item.pop("parecidas", None)
            m.setdefault("fora", []).append(item)
        L.CTX["save_cfg"](cfg)


def vigiar():
    """A cada 5 minutos manda o que mudou na Estante; de hora em hora lê a sua lista lá."""
    def loop():
        time.sleep(30)
        while True:
            try:
                if conectado() and not _cfg().get("vencido"):
                    sincronizar(ler=time.time() - estado["ultima_leitura"] > INTERVALO_LER)
            except Exception as e:
                print("[mangaupdates]", type(e).__name__, e)
            time.sleep(INTERVALO_MANDAR)
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------- rotas

def situacao():
    m = _cfg()
    return {"conectado": conectado(), "usuario": m.get("usuario", ""), "vencido": bool(m.get("vencido")) and conectado(),
            "ultima": m.get("ultima"), "sincronizando": estado["sincronizando"], "erro": estado["erro"] if estado["erro"] != "vencido" else "",
            "na_lista": m.get("na_lista"), "faltam_la": m.get("faltam_la", 0), "sem_ligacao": m.get("sem_ligacao", 0),
            "fora": (m.get("fora") or [])[:300], "duvidosas": (m.get("duvidosas") or [])[:100], "windows": os.name == "nt",
            "ultimo_por": m.get("ultimo_por")}


def _em_segundo_plano(f, *a):
    def w():
        try:
            f(*a)
        except Exception as e:
            print("[mangaupdates]", type(e).__name__, e)
    threading.Thread(target=w, daemon=True).start()


def rotas(bp):
    from flask import jsonify, request

    @bp.get("/api/leitura/mangaupdates")
    def api_mu_situacao():
        return jsonify(situacao())

    @bp.post("/api/leitura/mangaupdates/entrar")
    def api_mu_entrar():
        b = request.get_json(force=True) or {}
        try:
            entrar(b.get("usuario"), b.get("senha"))
        except (ValueError, RuntimeError) as e:
            return jsonify({"error": str(e)}), 400
        finally:
            b = None  # noqa: F841  (a senha não fica guardada nem neste pedido)
        with L.CTX["lock"]:  # o que foi lido antes de ligar a conta não vai em massa para a sua lista de lá
            d = L._load()
            for s in d["series"]:
                s.pop("mu_terminou_capitulo", None)
            L._save(d)
        _em_segundo_plano(sincronizar, True)
        return jsonify(situacao())

    @bp.post("/api/leitura/mangaupdates/sair")
    def api_mu_sair():
        sair()
        return jsonify(situacao())

    @bp.post("/api/leitura/mangaupdates/sincronizar")
    def api_mu_sincronizar():
        if not conectado():
            return jsonify({"error": "Entre na sua conta do MangaUpdates primeiro."}), 400
        _em_segundo_plano(sincronizar, True)
        return jsonify(situacao())

    @bp.post("/api/leitura/mangaupdates/por-na-lista")
    def api_mu_por():
        if not conectado():
            return jsonify({"error": "Entre na sua conta do MangaUpdates primeiro."}), 400
        _em_segundo_plano(por_na_lista)
        return jsonify(situacao())

    @bp.post("/api/leitura/mangaupdates/trazer")
    def api_mu_trazer():
        """Traz para a Estante as séries da sua lista do MangaUpdates que não estão nela (a mesma importação da lista)."""
        ids = {int(x) for x in (request.get_json(force=True) or {}).get("ids") or []}
        m = _cfg()
        itens = [x for x in m.get("fora") or [] if not ids or x["mu_id"] in ids]
        if not itens:
            return jsonify({"error": "Não há séries para trazer."}), 400
        if L._importando["ativo"]:
            return jsonify({"error": "Já tem uma importação em andamento. Espere ela terminar."}), 400
        entradas = [{"mal": None, "mu_id": x["mu_id"], "titulo": x["titulo"], "cap": x["cap"], "lista": x["lista"]} for x in itens]
        novas = L.importar_lista(entradas, True)
        with L.CTX["lock"]:
            cfg, lc = L.cfg_leitura()
            mm = lc.setdefault("mangaupdates", {})
            trazidos = {x["mu_id"] for x in itens}
            mm["fora"] = [x for x in mm.get("fora") or [] if x["mu_id"] not in trazidos]
            L.CTX["save_cfg"](cfg)
        L._importando.update(ativo=True, feitos=0, total=len(novas), novas=len(novas), erro="")
        threading.Thread(target=L._completar_importadas, args=(novas,), daemon=True).start()
        return jsonify({"ativo": True, "total": len(itens), "novas": len(novas)})

    @bp.post("/api/leitura/mangaupdates/ligar")
    def api_mu_ligar():
        b = request.get_json(force=True) or {}
        try:
            ligar(b.get("mu_id"), b.get("id"))
        except (ValueError, TypeError) as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(situacao())

    @bp.post("/api/leitura/mangaupdates/nao-e")
    def api_mu_nao_e():
        nao_e((request.get_json(force=True) or {}).get("mu_id"))
        return jsonify(situacao())
