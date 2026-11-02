"""
Leitor de quadrinhos do PC (como o OpenComic): mangás e HQs guardados no computador.

Cada subpasta de uma pasta escolhida vira uma série. Dentro dela, cada arquivo CBZ/ZIP, CBR/RAR (com o 7-Zip),
PDF ou pasta de imagens vira um capítulo. Um arquivo solto na pasta escolhida vira uma série de um capítulo só.
Os arquivos só são lidos: nada é alterado, movido ou apagado.
"""
import hashlib
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from flask import abort, jsonify, request, send_file

import leitura as L

IMAGENS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")
ARQUIVOS = (".cbz", ".zip", ".cbr", ".rar", ".pdf")
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
        ".avif": "image/avif", ".bmp": "image/bmp"}


def _natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def numero_do_nome(nome):
    """'Solo Leveling - Cap 012.cbz' -> 12; 'v03 c015.5' -> 15.5; 'Volume 2' -> 2."""
    base = re.sub(r"\.(cbz|zip|cbr|rar|pdf)$", "", nome, flags=re.I)
    for rx in (r"(?:ch(?:apter)?|cap(?:[ií]tulo)?|chap|episode|ep|c)[\s._#-]*(\d+(?:\.\d+)?)",
               r"(?:v(?:ol(?:ume)?)?)[\s._#-]*(\d+(?:\.\d+)?)",
               r"(\d+(?:\.\d+)?)(?!.*\d)"):
        m = re.search(r"(?<![a-z])" + rx, base, re.I)
        if m:
            return float(m.group(1))
    return None


def sete_zip():
    for c in (r"%ProgramFiles%\7-Zip\7z.exe", r"%ProgramFiles(x86)%\7-Zip\7z.exe"):
        c = os.path.expandvars(c)
        if os.path.exists(c):
            return c
    return shutil.which("7z") or ""


def _tem_imagens(pasta):
    try:
        return any(f.suffix.lower() in IMAGENS for f in Path(pasta).iterdir() if f.is_file())
    except OSError:
        return False


def _capitulo(p):
    p = Path(p)
    if p.is_dir():
        return {"arq": str(p), "tipo": "pasta", "nome": p.name}
    ext = p.suffix.lower()
    tipo = {".cbz": "zip", ".zip": "zip", ".cbr": "rar", ".rar": "rar", ".pdf": "pdf"}.get(ext)
    return {"arq": str(p), "tipo": tipo, "nome": p.stem} if tipo else None


def _numerar(caps):
    """Dá um número para cada capítulo pelo nome; se os nomes não ajudarem, usa a ordem."""
    nums = [numero_do_nome(c["nome"]) for c in caps]
    if None in nums or len(set(nums)) != len(nums):
        for i, c in enumerate(sorted(caps, key=lambda c: _natural(c["nome"]))):
            c["n"] = float(i + 1)
    else:
        for c, n in zip(caps, nums):
            c["n"] = n
    return sorted(caps, key=lambda c: c["n"])


def escanear(raiz):
    """Lista as séries de uma pasta: {nome, pasta, caps: [{n, nome, arq, tipo}]}."""
    raiz = Path(raiz)
    out = []
    if not raiz.is_dir():
        return out
    for item in sorted(raiz.iterdir(), key=lambda p: _natural(p.name)):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            caps = []
            for sub in sorted(item.iterdir(), key=lambda p: _natural(p.name)):
                if sub.is_dir() and _tem_imagens(sub):
                    caps.append(_capitulo(sub))
                elif sub.is_file():
                    c = _capitulo(sub)
                    if c:
                        caps.append(c)
            if not caps and _tem_imagens(item):
                caps = [_capitulo(item)]  # a própria pasta é o capítulo
            if caps:
                out.append({"nome": item.name, "pasta": str(item), "caps": _numerar(caps)})
        elif item.suffix.lower() in ARQUIVOS:
            c = _capitulo(item)
            out.append({"nome": re.sub(r"[_.]+", " ", item.stem).strip(), "pasta": str(item), "caps": _numerar([c])})
    return out


def nome_bonito(n):
    n = re.sub(r"\s*[\[(].*?[\])]\s*", " ", n)
    return re.sub(r"\s+", " ", re.sub(r"[_]+", " ", n)).strip() or n


# ---------------------------------------------------------------- páginas

_cache_lock = threading.Lock()


def _pasta_cache():
    p = L.CTX["DATA"] / "cache_quadrinhos"
    p.mkdir(exist_ok=True)
    return p


def _extrair_rar(arq):
    """CBR/RAR: o 7-Zip extrai uma vez para uma pasta de cache da Estante (o arquivo original não é mexido)."""
    exe = sete_zip()
    if not exe:
        raise RuntimeError("Para ler arquivos CBR/RAR, instale o 7-Zip (7-zip.org). Os CBZ funcionam sem ele.")
    st = os.stat(arq)
    chave = hashlib.sha1(f"{arq}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]
    destino = _pasta_cache() / chave
    with _cache_lock:
        if not destino.exists():
            tmp = destino.with_suffix(".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            flags = 0x08000000 if os.name == "nt" else 0
            subprocess.run([exe, "x", "-y", f"-o{tmp}", arq], capture_output=True, timeout=300, creationflags=flags)
            os.replace(tmp, destino)
    return destino


def paginas(cap):
    """Lista de páginas de um capítulo (nomes internos, em ordem natural)."""
    tipo, arq = cap["tipo"], cap["arq"]
    if tipo == "zip":
        with zipfile.ZipFile(arq) as z:
            nomes = [n for n in z.namelist() if not n.endswith("/") and Path(n).suffix.lower() in IMAGENS and "__MACOSX" not in n]
        return sorted(nomes, key=_natural)
    if tipo == "pasta":
        return sorted([f.name for f in Path(arq).iterdir() if f.is_file() and f.suffix.lower() in IMAGENS], key=_natural)
    if tipo == "rar":
        d = _extrair_rar(arq)
        return sorted([str(f.relative_to(d)) for f in d.rglob("*") if f.is_file() and f.suffix.lower() in IMAGENS], key=_natural)
    return []


def ler_pagina(cap, nome):
    tipo, arq = cap["tipo"], cap["arq"]
    if tipo == "zip":
        with zipfile.ZipFile(arq) as z:
            return z.read(nome)
    base = Path(arq) if tipo == "pasta" else _extrair_rar(arq)
    alvo = (base / nome).resolve()
    if base.resolve() not in alvo.parents:
        abort(403)
    return alvo.read_bytes()


# ---------------------------------------------------------------- sincronizar com a Leitura

def pastas():
    return L.cfg_leitura()[1].setdefault("pastas_quadrinhos", [])


def sincronizar():
    """Coloca na Leitura as séries das pastas de quadrinhos e atualiza a lista de capítulos de cada uma."""
    encontradas = []
    for raiz in pastas():
        try:
            encontradas += escanear(raiz)
        except OSError as e:
            print(f"[quadrinhos] não consegui olhar {raiz}: {e}")
    novas, capas = [], []
    with L.CTX["lock"]:
        d = L._load()
        por_pasta = {s["local"]["pasta"]: s for s in d["series"] if s.get("local")}
        for e in encontradas:
            s = por_pasta.get(e["pasta"])
            if not s:
                s = L.nova_serie(nome_bonito(e["nome"]))
                s["origem"], s["site"] = "local", "local"
                s["local"] = {"pasta": e["pasta"], "caps": [], "paginas": {}}
                d["series"].append(s)
                novas.append(s["id"])
            antes = {c["arq"] for c in s["local"]["caps"]}
            s["local"]["caps"] = e["caps"]
            maior = max(c["n"] for c in e["caps"])
            novos = [c for c in e["caps"] if c["arq"] not in antes]
            if s.get("ultimo_disponivel") is None or maior > s["ultimo_disponivel"]:
                L._subiu(d, s, maior, avisar=bool(antes) and bool(novos), site="local")
            if not s.get("cover"):
                capas.append((s["id"], e["caps"][0]))
        # séries cuja pasta sumiu saem (a não ser que o disco ou a pasta principal esteja desligada)
        vivas = {e["pasta"] for e in encontradas}
        raizes = [Path(r) for r in pastas()]

        def fica(s):
            if not s.get("local") or s["local"]["pasta"] in vivas:
                return True
            p = Path(s["local"]["pasta"])
            if p.anchor and not os.path.exists(p.anchor):
                return True  # HD externo desligado
            raiz = next((r for r in raizes if r == p.parent or r in p.parents), None)
            return raiz is not None and not raiz.exists()  # pasta principal fora do ar: espera voltar
        d["series"] = [s for s in d["series"] if fica(s)]
        L._save(d)
    for sid, cap in capas:  # capa = primeira página do primeiro capítulo
        try:
            ps = paginas(cap)
            if ps:
                nome = ps[0]
                L.guardar_capa_bytes(sid, ler_pagina(cap, nome), Path(nome).suffix.lower() or ".jpg")
                L._marcar(sid, capa_de="arquivo")
        except Exception as ex:
            print(f"[quadrinhos] capa: {ex}")
    for sid in novas:
        L.enfileirar(sid)  # tenta achar a série no MangaUpdates para a descrição, os gêneros e uma capa melhor
    return len(novas)


def vigiar():
    def loop():
        while True:
            try:
                if pastas():
                    sincronizar()
            except Exception as e:
                print("[quadrinhos]", e)
            time.sleep(300)
    threading.Thread(target=loop, daemon=True).start()


def _serie_cap(sid, i):
    s = L.achar(L._load(), sid)
    if not s or not s.get("local"):
        abort(404)
    caps = s["local"]["caps"]
    if not 0 <= i < len(caps):
        abort(404)
    return s, caps[i]


def rotas(bp):
    @bp.get("/api/leitura/local/<sid>/<int:i>")
    def api_local_paginas(sid, i):
        s, cap = _serie_cap(sid, i)
        if cap["tipo"] == "pdf":
            return jsonify({"pdf": True, "paginas": 0})
        try:
            ps = paginas(cap)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"paginas": len(ps), "pagina": (s["local"].get("paginas") or {}).get(L.num_txt(cap["n"]), 0)})

    @bp.get("/api/leitura/local/<sid>/<int:i>/<int:p>")
    def api_local_pagina(sid, i, p):
        _, cap = _serie_cap(sid, i)
        try:
            ps = paginas(cap)
        except Exception:
            abort(404)
        if not 0 <= p < len(ps):
            abort(404)
        import io
        return send_file(io.BytesIO(ler_pagina(cap, ps[p])), mimetype=MIME.get(Path(ps[p]).suffix.lower(), "image/jpeg"),
                         max_age=86400)

    @bp.post("/api/leitura/local/<sid>/<int:i>/progresso")
    def api_local_progresso(sid, i):
        b = request.get_json(force=True) or {}
        with L.CTX["lock"]:
            d = L._load()
            s = L.achar(d, sid)
            if not s or not s.get("local") or not 0 <= i < len(s["local"]["caps"]):
                abort(404)
            n = s["local"]["caps"][i]["n"]
            s["local"].setdefault("paginas", {})[L.num_txt(n)] = int(b.get("pagina") or 0)
            s["cap_aberto"] = i
            L.marcar_lido_no_leitor(d, s, n, bool(b.get("fim")), "local")
            L._save(d)
        return jsonify({"ok": True})

    @bp.post("/api/leitura/local/<sid>/<int:i>/abrir")
    def api_local_abrir(sid, i):
        """PDF: abre na janela de leitura (o próprio navegador mostra o PDF)."""
        _, cap = _serie_cap(sid, i)
        url = Path(cap["arq"]).resolve().as_uri()
        try:
            nav = L.CTX["navegador_app"]((L.CTX["get_cfg"]().get("leitura") or {}).get("navegador", "")) if os.name == "nt" else ""
            if nav:
                subprocess.Popen([nav, f"--app={url}", "--window-size=1100,1000"])
            elif os.name == "nt":
                os.startfile(cap["arq"])
        except Exception as e:
            return jsonify({"error": f"Não consegui abrir o PDF: {e}"}), 400
        return jsonify({"ok": True})

    @bp.get("/api/leitura/pastas")
    def api_pastas():
        return jsonify({"pastas": [{"path": p, "ok": os.path.isdir(p)} for p in pastas()], "sete_zip": bool(sete_zip())})

    @bp.post("/api/leitura/pastas")
    def api_pastas_salvar():
        b = request.get_json(force=True) or {}
        with L.CTX["lock"]:
            cfg, lc = L.cfg_leitura()
            lista = lc.setdefault("pastas_quadrinhos", [])
            if b.get("acrescentar"):
                p = os.path.normpath(str(b["acrescentar"]).strip().strip('"'))
                if not os.path.isdir(p):
                    return jsonify({"error": "Essa pasta não existe."}), 400
                if p not in lista:
                    lista.append(p)
            if b.get("tirar"):
                lc["pastas_quadrinhos"] = [x for x in lista if x != b["tirar"]]
            L.CTX["save_cfg"](cfg)
        n = sincronizar()
        return jsonify({"ok": True, "novas": n, "pastas": pastas()})

    @bp.post("/api/leitura/pastas/sincronizar")
    def api_pastas_sinc():
        return jsonify({"novas": sincronizar()})
