"""Desenha o ícone da Estante (usado no atalho e perto do relógio)."""
import math

from PIL import Image, ImageDraw


def desenhar(size=256):
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 64
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(14 * u), fill=(229, 160, 13, 255))
    escuro = (22, 18, 10, 255)
    d.rounded_rectangle([14 * u, 14 * u, 24 * u, 50 * u], radius=max(1, int(2 * u)), fill=escuro)
    d.rounded_rectangle([27 * u, 14 * u, 37 * u, 50 * u], radius=max(1, int(2 * u)), fill=escuro)
    # livro inclinado
    cx, cy, w, h, a = 46 * u, 33 * u, 10 * u, 34 * u, math.radians(12)
    cantos = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    d.polygon([(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in cantos], fill=escuro)
    return img


def salvar_ico(caminho):
    desenhar(256).save(caminho, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
