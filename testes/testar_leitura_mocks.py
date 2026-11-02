import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import io
import json
import sys
sys.path.insert(0, _PROJ)
import leitura
from PIL import Image

# ---------------- internet de mentira
ANI = {
    105398: {"id": 105398, "title": {"romaji": "Na Honjaman Level Up", "english": "Solo Leveling", "native": "나 혼자만 레벨업"},
             "synonyms": ["Only I Level Up"], "coverImage": {"extraLarge": "https://img.anilist/solo.jpg"},
             "description": "Dez anos atrás, portais surgiram.<br><br>Sung Jinwoo é o caçador mais fraco. (Source: Webtoon)",
             "genres": ["Action", "Fantasy"], "status": "FINISHED", "chapters": 200, "countryOfOrigin": "KR",
             "startDate": {"year": 2018}, "siteUrl": "https://anilist.co/manga/105398",
             "staff": {"edges": [{"role": "Story", "node": {"name": {"full": "Chugong"}}}]}},
    119257: {"id": 119257, "title": {"romaji": "Omniscient Reader", "english": "Omniscient Reader", "native": None}, "synonyms": ["ORV"],
             "coverImage": {"extraLarge": "https://img.anilist/orv.jpg"}, "description": "O fim do mundo.", "genres": ["Action"],
             "status": "RELEASING", "chapters": None, "countryOfOrigin": "KR", "startDate": {"year": 2020}, "siteUrl": "",
             "staff": {"edges": []}},
    999: {"id": 999, "title": {"romaji": "Tower of God", "english": "Tower of God", "native": None}, "synonyms": [],
          "coverImage": {"extraLarge": "https://img.anilist/tog.jpg"}, "description": "A torre.", "genres": ["Adventure"],
          "status": "RELEASING", "chapters": None, "countryOfOrigin": "KR", "startDate": {"year": 2010}, "siteUrl": "", "staff": {"edges": []}},
}
MU = {"Solo Leveling": (1, 200), "Omniscient Reader": (2, 230), "The Heavenly Demon Can't Live a Normal Life": (3, 150), "Tower of God": (4, 640)}
chamadas = []
LANCAMENTOS = []  # resposta de /v1/releases/days


def http_falso(url, dados=None, timeout=20):
    chamadas.append(url)
    if "anilist" in url:
        q, v = dados["query"], dados["variables"]
        if "MediaListCollection" in q:
            if v["u"] != "pessoa-teste":
                return {"errors": [{"message": "User not found"}]}
            return {"data": {"MediaListCollection": {"lists": [{"entries": [
                {"progress": 150, "status": "CURRENT", "media": ANI[105398]},
                {"progress": 600, "status": "PAUSED", "media": ANI[999]}]}]}}}
        if "Media(id" in q:
            return {"data": {"Media": ANI.get(v["id"])}}
        s = v["s"].lower()
        return {"data": {"Page": {"media": [m for m in ANI.values() if s in json.dumps(m).lower()]}}}
    if "series/search" in url:
        t = dados["search"]
        return {"results": [{"record": {"series_id": sid, "title": nome}} for nome, (sid, _) in MU.items() if t.lower() in nome.lower()]}
    if "releases/days" in url:  # lançamentos recentes de todas as séries (os testes põem o que quiserem em LANCAMENTOS)
        return {"total_hits": len(LANCAMENTOS), "page": 1, "results": LANCAMENTOS}
    if "api.mangaupdates.com/v1/series/" in url:
        sid = int(url.rstrip("/").split("/")[-1])
        nome, lat = next((n, lt) for n, (i, lt) in MU.items() if i == sid)
        return {"series_id": sid, "title": nome, "latest_chapter": lat, "url": f"https://www.mangaupdates.com/series/{sid}",
                "description": f"Descrição de {nome} no MangaUpdates.<br><br>Segunda linha. <i>(fonte)</i>",
                "image": {"url": {"original": f"https://cdn.mangaupdates.com/image/{sid}.jpg"}}, "type": "Manhwa", "year": "2018",
                "genres": [{"genre": "Action"}, {"genre": "Fantasy"}], "status": "Ongoing" if sid != 1 else "200 Chapters (Complete)",
                "completed": sid == 1, "authors": [{"name": "Chugong", "type": "Author"}, {"name": "Jang Sung-Rak", "type": "Artist"}],
                "associated": [{"title": "Only I Level Up"}] if sid == 1 else []}
    raise RuntimeError("sem internet no teste")


def capa_falsa(sid, url, referer=None):
    b = io.BytesIO()
    Image.new("RGB", (300, 450), (hash(url) % 255, 80, 120)).save(b, "JPEG")
    return leitura.guardar_capa_bytes(sid, b.getvalue(), ".jpg")


