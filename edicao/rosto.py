"""Rastreamento dos olhos e enquadramento do zoom.

Os olhos são detectados em quadros amostrados (YuNet, do OpenCV). Para cada trecho do vídeo,
a janela de corte é posicionada com os olhos na altura configurada (um pouco acima do centro)
e centralizados na horizontal, sem sair da imagem. Se algum olho fosse ficar fora da margem
segura, o zoom daquele trecho é reduzido até caber.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from statistics import median

MODELO = Path(__file__).resolve().parent / "modelos" / "face_detection_yunet_2023mar.onnx"


@dataclass
class Olhos:
    """Posição dos olhos num instante, em fração da largura/altura da imagem (0 a 1)."""
    t: float
    direito: tuple[float, float]
    esquerdo: tuple[float, float]

    @property
    def meio(self) -> tuple[float, float]:
        return ((self.direito[0] + self.esquerdo[0]) / 2, (self.direito[1] + self.esquerdo[1]) / 2)


@dataclass
class Quadro:
    """Janela de corte na imagem original, em pixels, e o zoom efetivamente aplicado."""
    x: int
    y: int
    largura: int
    altura: int
    zoom: float


def detectar_olhos(video: Path, largura_imagem: int, altura_imagem: int,
                   amostras_por_segundo: float = 5, largura_analise: int = 480) -> list[Olhos]:
    """Amostra quadros com o ffmpeg (já com a rotação do iPhone aplicada) e acha os olhos."""
    import cv2
    import numpy as np

    larg = largura_analise
    alt = round(altura_imagem * larg / largura_imagem / 2) * 2
    proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-vf", f"fps={amostras_por_segundo},scale={larg}:{alt}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE,
    )
    detector = cv2.FaceDetectorYN.create(str(MODELO), "", (larg, alt), 0.7)
    tamanho = larg * alt * 3
    resultado = []
    i = 0
    while True:
        dados = proc.stdout.read(tamanho)
        if len(dados) < tamanho:
            break
        imagem = np.frombuffer(dados, np.uint8).reshape(alt, larg, 3)
        _, rostos = detector.detect(imagem)
        if rostos is not None and len(rostos):
            # O maior rosto do quadro é o de quem está falando.
            r = max(rostos, key=lambda f: f[2] * f[3])
            resultado.append(Olhos(
                t=i / amostras_por_segundo,
                direito=(r[4] / larg, r[5] / alt),
                esquerdo=(r[6] / larg, r[7] / alt),
            ))
        i += 1
    proc.wait()
    return resultado


def enquadrar(olhos: list[Olhos], inicio: float, fim: float, zoom: float,
              largura_imagem: int, altura_imagem: int, saida_proporcao: float,
              altura_olhos: float, margem: float) -> Quadro:
    """Janela de corte para um trecho [inicio, fim] com o zoom pedido.

    saida_proporcao: largura/altura do vídeo final (9/16).
    altura_olhos: onde os olhos ficam no quadro final, em fração da altura a partir do topo.
    margem: distância mínima dos olhos até as bordas do quadro final, em fração.
    """
    W, H = largura_imagem, altura_imagem
    # Maior janela com a proporção de saída que cabe na imagem (zoom 1,0).
    if W / H > saida_proporcao:
        base_alt, base_larg = H, H * saida_proporcao
    else:
        base_larg, base_alt = W, W / saida_proporcao

    amostras = [o for o in olhos if inicio <= o.t <= fim]
    if not amostras:  # sem rosto detectado no trecho: usa o mais próximo, se houver
        amostras = sorted(olhos, key=lambda o: min(abs(o.t - inicio), abs(o.t - fim)))[:3]

    z = zoom
    while True:
        larg, alt = base_larg / z, base_alt / z
        if amostras:
            ex = median(o.meio[0] for o in amostras) * W
            ey = median(o.meio[1] for o in amostras) * H
            x = ex - larg / 2
            y = ey - altura_olhos * alt
        else:
            x, y = (W - larg) / 2, (H - alt) / 2
        x = min(max(0.0, x), W - larg)
        y = min(max(0.0, y), H - alt)
        if z <= 1.0 or not amostras or _olhos_dentro(amostras, x, y, larg, alt, W, H, margem):
            break
        z = max(1.0, round(z - 0.05, 2))

    # Dimensões pares (exigência do H.264) e dentro da imagem.
    larg_i = int(larg) // 2 * 2
    alt_i = int(alt) // 2 * 2
    return Quadro(int(round(x)), int(round(y)), larg_i, alt_i, z)


def _olhos_dentro(amostras, x, y, larg, alt, W, H, margem) -> bool:
    for o in amostras:
        for px, py in (o.direito, o.esquerdo):
            fx = (px * W - x) / larg
            fy = (py * H - y) / alt
            if not (margem <= fx <= 1 - margem and margem <= fy <= 1 - margem):
                return False
    return True
