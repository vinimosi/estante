"""Monta um 'PC de mentira' com as 7 lojas instaladas, para testar a Estante sem Windows."""
import os as _os
import tempfile as _tf
from pathlib import Path as _P
_PROJ = str(_P(__file__).resolve().parent.parent)
_SAIDA = _os.environ.get("ESTANTE_TESTES_SAIDA") or str(_P(_tf.gettempdir()) / "estante-testes")
import base64
import json
import os
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJ = Path(_PROJ)
sys.path.insert(0, str(PROJ))


class RegistroFalso:
    def __init__(self):
        self.d = {}

    def por(self, caminho, **vals):
        self.d.setdefault(caminho.lower(), {"_nome": caminho, "v": {}})["v"].update(vals)

    def valores(self, c):
        return dict(self.d.get(c.lower(), {}).get("v", {}))

    def subchaves(self, c):
        pref = c.lower().rstrip("\\") + "\\"
        out = []
        for k, item in self.d.items():
            if k.startswith(pref):
                nome = item["_nome"][len(pref):].split("\\")[0]
                if nome not in out:
                    out.append(nome)
        return out


def img(caminho, cor, texto, tam=(600, 900)):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", tam, cor)
    d = ImageDraw.Draw(im)
    for i in range(0, tam[1], 60):
        d.rectangle([0, i, tam[0], i + 28], fill=tuple(min(255, c + 18) for c in cor))
    d.text((30, tam[1] - 120), texto, fill=(255, 255, 255))
    im.save(caminho)


def exe(caminho):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"MZ" + b"\0" * 2000)


def montar(T):
    T = Path(T)
    if T.exists():
        shutil.rmtree(T)
    reg = RegistroFalso()
    PF86, PF, PD = T / "PF86", T / "PF", T / "ProgramData"
    os.environ["ProgramFiles(x86)"], os.environ["ProgramFiles"], os.environ["ProgramData"] = str(PF86), str(PF), str(PD)

    # ---------- Steam: duas bibliotecas, ferramentas e trilha sonora que não devem entrar
    steam = PF86 / "Steam"
    libD = T / "D" / "SteamLibrary"
    reg.por(r"HKCU\Software\Valve\Steam", SteamPath=str(steam).replace("\\", "/"))
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(f'''"libraryfolders"
{{
\t"0"
\t{{
\t\t"path"\t\t"{str(steam)}"
\t\t"apps"\t\t{{ "620" "1" "228980" "1" }}
\t}}
\t"1"
\t{{
\t\t"path"\t\t"{str(libD)}"
\t\t"apps"\t\t{{ "1145360" "1" "570" "1" }}
\t}}
}}''', "utf-8")
    apps = [(steam, "620", "Portal 2", "Portal 2"), (steam, "228980", "Steamworks Common Redistributables", "Steamworks Shared"),
            (steam, "1500", "Celeste Original Soundtrack", "Celeste OST"),
            (libD, "1145360", "Hades", "Hades"), (libD, "570", "Dota 2", "dota 2 beta"),
            (libD, "999999", "Jogo Sem Pasta", "nao_existe")]
    for lib, appid, nome, pasta in apps:
        (lib / "steamapps").mkdir(parents=True, exist_ok=True)
        (lib / "steamapps" / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{nome}"\n\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"{pasta}"\n}}\n', "utf-8")
        if pasta != "nao_existe":
            exe(lib / "steamapps" / "common" / pasta / "game.exe")
    exe(steam / "steamapps" / "common" / "Portal 2" / "portal2.exe")
    img(steam / "appcache" / "librarycache" / "620" / "library_600x900.jpg", (40, 90, 140), "PORTAL 2 (capa local da Steam)")
    img(steam / "appcache" / "librarycache" / "570_library_600x900.jpg", (150, 30, 30), "DOTA 2 (capa local, formato antigo)")

    # ---------- Epic: um jogo, uma DLC, o Unreal Engine e uma instalação incompleta
    epic = PD / "Epic" / "EpicGamesLauncher" / "Data"
    (epic / "Manifests").mkdir(parents=True)
    exe(PF / "Epic Games" / "Hades" / "Hades.exe")
    exe(PF / "Epic Games" / "AlanWake2" / "AlanWake2.exe")
    itens = [
        {"AppName": "Min", "MainGameAppName": "Min", "DisplayName": "Hades", "InstallLocation": str(PF / "Epic Games" / "Hades"),
         "CatalogNamespace": "min", "CatalogItemId": "abc123", "AppCategories": ["public", "games", "applications"]},
        {"AppName": "MinDLC", "MainGameAppName": "Min", "DisplayName": "Hades DLC", "InstallLocation": str(PF / "Epic Games" / "Hades"),
         "CatalogNamespace": "min", "CatalogItemId": "dlc1", "AppCategories": ["addons"]},
        {"AppName": "UE_5.3", "DisplayName": "Unreal Engine 5.3", "InstallLocation": str(PF / "Epic Games"),
         "CatalogNamespace": "ue", "CatalogItemId": "ue", "AppCategories": ["engines"]},
        {"AppName": "Dodo", "MainGameAppName": "Dodo", "DisplayName": "Alan Wake 2", "InstallLocation": str(PF / "Epic Games" / "AlanWake2"),
         "CatalogNamespace": "dodo", "CatalogItemId": "aw2", "AppCategories": ["games"], "bIsIncompleteInstall": False},
        {"AppName": "Half", "DisplayName": "Baixando ainda", "InstallLocation": str(PF / "Epic Games" / "Hades"),
         "CatalogNamespace": "x", "CatalogItemId": "y", "AppCategories": ["games"], "bIsIncompleteInstall": True},
    ]
    for i, it in enumerate(itens):
        (epic / "Manifests" / f"{i:04d}ABCD.item").write_text(json.dumps(it), "utf-8")
    (epic / "Catalog").mkdir()
    cat = [{"id": "aw2", "title": "Alan Wake 2", "description": "Um thriller de terror psicológico.", "developer": "Remedy",
            "keyImages": [{"type": "DieselGameBoxTall", "url": "https://exemplo.invalid/aw2_tall.jpg"}]}]
    (epic / "Catalog" / "catcache.bin").write_bytes(base64.b64encode(json.dumps(cat).encode()))

    # ---------- GOG: um jogo com Galaxy instalado e uma DLC registrada
    gog = T / "GOG Games" / "The Witcher 3"
    exe(gog / "bin" / "x64" / "witcher3.exe")
    (gog / "goggame-1207664663.info").write_text(json.dumps({"gameId": "1207664663", "rootGameId": "1207664663", "name": "The Witcher 3: Wild Hunt",
        "playTasks": [{"isPrimary": True, "type": "FileTask", "path": "bin\\x64\\witcher3.exe"}]}), "utf-8")
    reg.por(r"HKLM\SOFTWARE\WOW6432Node\GOG.com\Games\1207664663", gameName="The Witcher 3: Wild Hunt", path=str(gog), exe=str(gog / "bin/x64/witcher3.exe"))
    exe(PF86 / "GOG Galaxy" / "GalaxyClient.exe")
    reg.por(r"HKLM\SOFTWARE\WOW6432Node\GOG.com\GalaxyClient\paths", client=str(PF86 / "GOG Galaxy"))

    # ---------- EA app
    bf = PF / "EA Games" / "Battlefield 1"
    exe(bf / "bf1.exe")
    (bf / "__Installer").mkdir(parents=True)
    (bf / "__Installer" / "installerdata.xml").write_text('''<?xml version="1.0" encoding="utf-8"?>
<DiPManifest version="4.0"><contentIDs><contentID>1026023</contentID><contentID>1026024</contentID></contentIDs>
<gameTitles><gameTitle locale="en_US">Battlefield 1</gameTitle><gameTitle locale="pt_BR">Battlefield 1</gameTitle></gameTitles></DiPManifest>''', "utf-8")
    reg.por(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{BF1}", DisplayName="Battlefield™ 1", InstallLocation=str(bf),
            UninstallString=f'"{bf}\\__Installer\\Touchup.exe" uninstall_game')
    (PF / "Electronic Arts" / "EA Desktop").mkdir(parents=True)

    # ---------- Ubisoft Connect
    ac = PF86 / "Ubisoft" / "games" / "Assassin's Creed Origins"
    exe(ac / "ACOrigins.exe")
    reg.por(r"HKLM\SOFTWARE\WOW6432Node\Ubisoft\Launcher", InstallDir=str(PF86 / "Ubisoft" / "Ubisoft Game Launcher"))
    reg.por(r"HKLM\SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs\3539", InstallDir=str(ac).replace("\\", "/") + "/")
    reg.por(r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Uplay Install 3539", DisplayName="Assassin's Creed Origins")
    reg.por(r"HKLM\SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs\9999", InstallDir=str(T / "nao_existe"))

    # ---------- Battle.net: Overwatch (código conhecido) e um jogo sem código (abre pelo abridor da pasta)
    bnet = PF86 / "Battle.net"
    exe(bnet / "Battle.net.exe")
    ow = PF86 / "Overwatch"
    exe(ow / "Overwatch Launcher.exe")
    cod = PF86 / "Call of Duty"
    exe(cod / "Call of Duty Launcher.exe")
    un = r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    reg.por(un + r"\Overwatch", DisplayName="Overwatch", Publisher="Blizzard Entertainment", InstallLocation=str(ow),
            UninstallString=f'"{PF86}\\Battle.net\\Blizzard Uninstaller.exe" --lang=ptBR --uid=prometheus --displayname="Overwatch"')
    reg.por(un + r"\Call of Duty", DisplayName="Call of Duty", Publisher="Blizzard Entertainment", InstallLocation=str(cod),
            UninstallString=f'"{PF86}\\Battle.net\\Blizzard Uninstaller.exe" --lang=ptBR --uid=jogo_novo --displayname="Call of Duty"')
    reg.por(un + r"\Battle.net", DisplayName="Battle.net", Publisher="Blizzard Entertainment", InstallLocation=str(bnet),
            UninstallString=f'"{PF86}\\Battle.net\\Battle.net Launcher.exe" --uid=battle.net --uninstall')

    # ---------- Xbox: disco com .GamingRoot apontando para XboxGames
    drive = T / "DiscoE"
    drive.mkdir()
    (drive / ".GamingRoot").write_bytes(b"RGBX" + b"\x01\x00\x00\x00" + "XboxGames\x00".encode("utf-16-le"))
    fz = drive / "XboxGames" / "Forza Horizon 5" / "Content"
    exe(fz / "ForzaHorizon5.exe")
    (fz / "MicrosoftGame.config").write_text('''<?xml version="1.0" encoding="utf-8"?>
<Game configVersion="1"><Identity Name="Microsoft.624F8B84B80" Publisher="CN=A4954634-DF4B-47C7-AB70-D3215D246AF1" Version="1.0.0.0"/>
<ExecutableList><Executable Name="ForzaHorizon5.exe" Id="Game"/></ExecutableList>
<ShellVisuals DefaultDisplayName="Forza Horizon 5" PublisherDisplayName="Microsoft Studios" SplashScreenImage="Assets\\Splash.png" Square480x480Logo="Assets\\Logo480.png"/></Game>''', "utf-8")
    (fz / "appxmanifest.xml").write_text('''<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="Microsoft.624F8B84B80" Publisher="CN=A4954634-DF4B-47C7-AB70-D3215D246AF1" Version="1.0.0.0"/>
<Properties><DisplayName>ms-resource:DisplayName</DisplayName></Properties>
<Applications><Application Id="Game" Executable="ForzaHorizon5.exe"/></Applications></Package>''', "utf-8")
    img(fz / "Assets" / "Splash.png", (20, 110, 60), "FORZA HORIZON 5 (imagem do pacote Xbox)", (1920, 1080))

    # ---------- jogos avulsos (sem loja)
    exe(T / "Jogos" / "Stardew Valley" / "Stardew Valley.exe")
    exe(T / "Jogos" / "Hades" / "Hades.exe")
    return reg, drive


def aplicar(reg, drive):
    import lojas
    lojas.REG = reg
    lojas.unidades = lambda: [str(drive)]
