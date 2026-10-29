"""Renderização final com ffmpeg: cortes, enquadramento 9:16, legendas e elementos gráficos.

Trechos parados usam crop e escala do próprio ffmpeg. Trechos com zoom animado são gerados
quadro a quadro em Python (OpenCV), com posição e escala fracionárias: o crop do ffmpeg só anda
em pixels inteiros e fazia o zoom tremer. Os quadros animados vão para um arquivo temporário sem
perda (FFV1) que entra no grafo final no lugar do trecho.

HDR (HLG ou PQ do iPhone): por padrão o vídeo sai em HDR, HEVC 10 bits. Legendas e gráficos são
desenhados numa camada transparente em SDR e convertidos para a curva HDR antes de sobrepor, para
as cores da marca aparecerem iguais às do SDR (branco SDR = 203 nits, BT.2408).
"""

import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from .plano import Trecho


def _escapar_caminho_filtro(caminho: Path) -> str:
    return str(caminho).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


# Curvas de aceleração (p vai de 0 a 1).
_SUAVIZACAO = {
    "suave": lambda p: p * p * (3 - 2 * p),                                          # acelera e desacelera
    "rapido": lambda p: 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2,        # idem, mais marcado
}

# Parâmetros de cor do vídeo de saída por curva de transferência.
_COR_SDR = ("bt709", "bt709", "bt709")
_COR_HDR = {t: ("bt2020", t, "bt2020nc") for t in ("arib-std-b67", "smpte2084")}

_ESCALA = "flags=lanczos+accurate_rnd+full_chroma_int"


def _para_sdr(transferencia: str) -> str:
    """Converte HDR (BT.2020, HLG ou PQ) para SDR BT.709 sem deixar a imagem lavada.

    Mobius mantém os tons médios (pele) praticamente iguais e só comprime os realces.
    Usado só quando [video] hdr = "converter".
    """
    return (
        f"setparams=color_primaries=bt2020:color_trc={transferencia}:colorspace=bt2020nc,"
        "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
        "tonemap=tonemap=mobius:param=0.6:desat=0,"
        "zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
    )


def _janela(t: Trecho, p: float) -> tuple[float, float, float, float]:
    """Janela (x, y, largura, altura) no instante p (0 a 1) da animação do trecho.

    A escala varia em progressão geométrica (velocidade de zoom constante para o olho) e o
    centro da janela anda junto com ela.
    """
    x0, y0, w0, h0 = t.quadro_inicial
    x1, y1, w1, h1 = t.quadro
    e = _SUAVIZACAO[t.tipo](min(1.0, max(0.0, p)))
    w = w0 * (w1 / w0) ** e
    h = h0 * (h1 / h0) ** e
    cx = (x0 + w0 / 2) + ((x1 + w1 / 2) - (x0 + w0 / 2)) * e
    cy = (y0 + h0 / 2) + ((y1 + h1 / 2) - (y0 + h0 / 2)) * e
    return cx - w / 2, cy - h / 2, w, h


def animar(video: Path, t: Trecho, inicio: float, fim: float, saida: Path,
           larg: int, alt: int, fps: Fraction, dimensoes: tuple[int, int], dez_bits: bool) -> None:
    """Gera os quadros de [inicio, fim] do trecho com o zoom animado, sem perda, em `saida`."""
    import cv2
    import numpy as np

    W, H = dimensoes
    pix = "yuv420p10le" if dez_bits else "yuv420p"
    tipo = np.uint16 if dez_bits else np.uint8
    # Reduz a imagem antes (sem passar do tamanho em que a janela mais fechada fica 1:1 com a
    # saída): menos dados no Python e quase nenhum serrilhado na redução do warp.
    menor = min(t.quadro_inicial[2], t.quadro[2])
    s = min(1.0, larg / menor)
    Ws, Hs = round(W * s / 2) * 2, round(H * s / 2) * 2
    sx, sy = Ws / W, Hs / H

    leitor = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t", f"{fim - inicio:.3f}",
         "-i", str(video), "-an", "-vf", f"scale={Ws}:{Hs}:{_ESCALA},format={pix}",
         "-f", "rawvideo", "-pix_fmt", pix, "-"],
        stdout=subprocess.PIPE,
    )
    escritor = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", pix,
         "-s", f"{larg}x{alt}", "-r", str(fps), "-i", "-", "-c:v", "ffv1", "-level", "1", str(saida)],
        stdin=subprocess.PIPE,
    )
    bytes_por = 2 if dez_bits else 1
    area_y, area_c = Ws * Hs, (Ws // 2) * (Hs // 2)
    tamanho = (area_y + 2 * area_c) * bytes_por
    deslocamento = inicio - t.inicio
    k = 0
    while True:
        dados = leitor.stdout.read(tamanho)
        if len(dados) < tamanho:
            break
        quadro = np.frombuffer(dados, tipo)
        planos = (quadro[:area_y].reshape(Hs, Ws),
                  quadro[area_y:area_y + area_c].reshape(Hs // 2, Ws // 2),
                  quadro[area_y + area_c:].reshape(Hs // 2, Ws // 2))
        p = (k / fps + deslocamento + t.anim_decorrido) / max(t.anim_duracao, 0.01)
        x, y, w, h = _janela(t, float(p))
        x, y, w, h = x * sx, y * sy, w * sx, h * sy
        saida_planos = []
        for i, plano in enumerate(planos):
            f = 1 if i == 0 else 2                      # croma tem metade da resolução
            ow, oh = larg // f, alt // f
            ex, ey = w / larg, h / alt                   # pixels da origem por pixel da saída
            # Mapa inverso (saída → origem) com centros de pixel alinhados.
            m = np.array([[ex, 0, x / f + 0.5 * ex - 0.5], [0, ey, y / f + 0.5 * ey - 0.5]])
            novo = cv2.warpAffine(plano, m, (ow, oh), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                                  borderMode=cv2.BORDER_REPLICATE)
            if dez_bits:
                # O bicúbico passa um pouco do original junto de pontos muito claros (reflexo nos
                # óculos em HDR: 1042). Acima de 1023 o FFV1 de 10 bits transbordava e gravava lixo
                # colorido até o quadro-chave seguinte. Em 8 bits o OpenCV já satura em 255.
                np.minimum(novo, 1023, out=novo)
            saida_planos.append(novo)
        escritor.stdin.write(b"".join(pl.tobytes() for pl in saida_planos))
        k += 1
    leitor.wait()
    escritor.stdin.close()
    if escritor.wait() != 0 or leitor.returncode != 0:
        raise RuntimeError(f"falha ao animar o trecho {t.inicio:.2f}–{t.fim:.2f}s")
    _verificar_sem_perda(saida)


def _verificar_sem_perda(arquivo: Path) -> None:
    """O FFV1 em fatias (level 3) às vezes gravava uma fatia corrompida; na leitura, o decodificador
    repetia aquele quarto do quadro anterior (rosto "partido" no vídeo final). Agora é level 1,
    sem fatias, e cada arquivo é conferido antes do uso."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-err_detect", "explode", "-i", str(arquivo), "-f", "null", "-"],
                       capture_output=True, text=True)
    if r.returncode != 0 or r.stderr.strip():
        raise RuntimeError(f"trecho animado com erro de gravação ({arquivo.name}): {r.stderr.strip()[:200]}")


def _pedacos(t: Trecho, fps: Fraction = Fraction(30)) -> list[tuple[float, float, bool]]:
    """Divide o trecho em pedaços (início, fim, animado). No "rapido", a animação dura pouco e o
    resto do trecho fica parado no enquadramento final; a divisão cai num quadro inteiro."""
    animado = bool(t.quadro and t.quadro_inicial and t.tipo in _SUAVIZACAO)
    if not animado:
        return [(t.inicio, t.fim, False)]
    if t.tipo == "rapido":
        resta = float(round((t.anim_duracao - t.anim_decorrido) * fps) / fps)
        if resta <= 0:
            return [(t.inicio, t.fim, False)]
        if resta < t.duracao - 0.05:
            return [(t.inicio, t.inicio + resta, True), (t.inicio + resta, t.fim, False)]
    return [(t.inicio, t.fim, True)]


def _parado(t: Trecho, larg: int, alt: int) -> str:
    if t.quadro:
        # Janela fixa calculada a partir dos olhos (ver rosto.enquadrar).
        x, y, w, h = t.quadro
        return f"crop={w}:{h}:{x}:{y},scale={larg}:{alt}:{_ESCALA}"
    # Sem rastreamento: zoom centralizado, cortando o excesso para 9:16.
    z = t.zoom
    return (f"scale={round(larg * z / 2) * 2}:{round(alt * z / 2) * 2}:force_original_aspect_ratio=increase:"
            f"{_ESCALA},crop={larg}:{alt}")


def tratamento_voz(volume_alvo: float = -14) -> str:
    """Tratamento de voz escolhido pelo usuário em 28/10/2026 (amostra "C", gravada com lapela):
    corte de graves, redução de ruído leve, um pouco de presença, compressão suave e volume no
    padrão dos Reels. A versão mais forte (afftdn nr=40, deesser, corte em 250 Hz) soou abafada."""
    # O afftdn atrasa o som em 1200 amostras a 48 kHz (25 ms, medido com um impulso): sem compensar,
    # a voz sai atrás da boca. Corta esse início e completa o fim, mantendo a duração.
    return ("aresample=48000,highpass=f=70,afftdn=nr=10:nf=-50:tn=1,"
            f"atrim=start_sample={_ATRASO_AFFTDN},asetpts=PTS-STARTPTS,apad=pad_len={_ATRASO_AFFTDN},"
            "equalizer=f=4000:t=q:w=1.5:g=2,acompressor=threshold=-24dB:ratio=2:attack=10:release=200,"
            f"loudnorm=I={volume_alvo}:TP=-1.5:LRA=9,aresample=48000")


_ATRASO_AFFTDN = 1200


# Nível declarado no vídeo. Sem ele, com a base de tempo de 1 µs da saída (vídeo de taxa variável),
# o x264 e o x265 deduziam a taxa de quadros errada e marcavam nível 6.2: o iPhone recusa o arquivo
# ("formato de arquivo incompatível"), embora o Mac reproduza. 1080x1920 a 30 fps cabe no 4.x.
_NIVEL_H264 = "4.2"
_NIVEL_HEVC = "5.1"


def _codificacao(cfg_video: dict, hdr_saida: str | None, fps: Fraction) -> list[str]:
    if hdr_saida:
        prim, trc, matriz = _COR_HDR[hdr_saida]
        codec = cfg_video.get("codec_hdr", "libx265")
        if codec == "hevc_videotoolbox":
            qualidade = ["-b:v", cfg_video.get("taxa_videotoolbox", "20M"), "-profile:v", "main10"]
        else:
            qualidade = ["-crf", str(cfg_video.get("crf_hdr", 18)), "-preset", cfg_video.get("preset_hdr", "medium"),
                         "-profile:v", "main10",
                         "-x265-params",
                         # GOP fechado: o reprodutor da Apple mostrava quadros com blocos deslocados
                         # (open-gop do x265) ao abrir ou pular no vídeo. Nível fixo: ver _NIVEL_H264.
                         # fps: o x265 confere o nível contra a taxa de quadros, que sem isto ele tira
                         # da base de tempo de 1 µs e recusa abrir ("frame rate is out of range").
                         f"colorprim={prim}:transfer={trc}:colormatrix={matriz}:open-gop=0:"
                         f"fps={fps.numerator}/{fps.denominator}:level-idc={_NIVEL_HEVC}:log-level=error"]
        return ["-c:v", codec, *qualidade, "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1",
                "-color_primaries", prim, "-color_trc", trc, "-colorspace", matriz, "-color_range", "tv"]
    codec = cfg_video["codec"]
    if codec == "libx264":
        qualidade = ["-crf", str(cfg_video["crf"]), "-preset", cfg_video.get("preset", "slow"), "-profile:v", "high",
                     "-level:v", _NIVEL_H264]
    else:
        qualidade = ["-b:v", cfg_video.get("taxa_videotoolbox", "20M")]
    return ["-c:v", codec, *qualidade, "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv"]


def renderizar(
    video: Path, trechos: list[Trecho], legendas_ass: Path | None, saida: Path,
    cfg_video: dict, fade_audio: float, dimensoes: tuple[int, int] | None = None,
    hdr: str | None = None, pasta_fontes: Path | None = None, fps: Fraction = Fraction(30),
    ganho_db: float = 0.0, filtro_audio: str = "",
    graficos_claros: Path | None = None, nits_claros: float = 600,
) -> None:
    """hdr: curva de transferência do original (ver midia.transferencia_hdr); None se SDR.
    pasta_fontes: onde procurar as fontes da legenda além das instaladas no Mac.
    ganho_db: ganho fixo do áudio (volume no padrão dos Reels), com limitador de picos.
    filtro_audio: cadeia de filtros do ffmpeg aplicada ao áudio editado (substitui o ganho).
    graficos_claros: ASS sobreposto por cima de tudo, com o branco a `nits_claros` no HDR (caixinha
    de pergunta do Instagram, que tem de sair branca)."""
    larg, alt = cfg_video["largura"], cfg_video["altura"]
    manter_hdr = bool(hdr) and cfg_video.get("hdr", "manter") == "manter"
    hdr_saida = hdr if manter_hdr else None
    pix = "yuv420p10le" if manter_hdr else "yuv420p"
    if hdr_saida:
        prim, trc, matriz = _COR_HDR[hdr_saida]
        cor = ""
    else:
        prim, trc, matriz = _COR_SDR
        cor = f",{_para_sdr(hdr)}" if hdr else ""
    params = f"format={pix},setparams=color_primaries={prim}:color_trc={trc}:colorspace={matriz}:range=tv,setsar=1"

    with tempfile.TemporaryDirectory() as pasta:
        # A entrada 0 só dá o áudio. Cada pedaço de vídeo é uma entrada própria, já posicionada
        # (-ss antes do -i): com todos lendo [0:v], o ffmpeg dividia a entrada e guardava na memória
        # os quadros que os pedaços seguintes ainda iam usar (13 GB num vídeo de 1:43 em HDR, o
        # MacBook de 8 GB travou).
        entradas = ["-i", str(video)]
        n_entradas = 1
        filtros = []
        for i, t in enumerate(trechos):
            pedacos = _pedacos(t, fps) if dimensoes else [(t.inicio, t.fim, False)]
            rotulos = []
            for j, (ini, fim, animado) in enumerate(pedacos):
                rotulo = f"v{i}_{j}"
                if animado:
                    arquivo = Path(pasta) / f"anim{i}_{j}.mkv"
                    animar(video, t, ini, fim, arquivo, larg, alt, fps, dimensoes, manter_hdr or bool(hdr))
                    n = n_entradas
                    entradas += ["-i", str(arquivo)]
                    n_entradas += 1
                    # Quadro a mais ou a menos na leitura não desloca o áudio: completa e corta.
                    origem = (f"[{n}:v]setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=0.1,"
                              f"trim=duration={fim - ini:.4f}")
                    if hdr:
                        origem += (f",setparams=color_primaries=bt2020:color_trc={hdr}:colorspace=bt2020nc:"
                                   "range=tv")
                    filtros.append(f"{origem}{cor},{params}[{rotulo}]")
                else:
                    # Grade de quadros fixa e duração exata: o pedaço tem tantos quadros quanto o
                    # áudio correspondente, e as emendas não acumulam diferença.
                    entradas += ["-ss", f"{ini:.4f}", "-t", f"{fim - ini + 0.5 / fps:.4f}", "-i", str(video)]
                    filtros.append(
                        f"[{n_entradas}:v]setpts=PTS-STARTPTS,"
                        f"fps={fps}:round=near,tpad=stop_mode=clone:stop_duration=0.1,trim=duration={fim - ini:.4f},"
                        f"{_parado(t, larg, alt)}{cor},{params}[{rotulo}]"
                    )
                    n_entradas += 1
                rotulos.append(f"[{rotulo}]")
            if len(rotulos) == 1:
                filtros.append(f"{rotulos[0]}null[v{i}]")
            else:
                filtros.append(f"{''.join(rotulos)}concat=n={len(rotulos)}:v=1:a=0[v{i}]")
            fade = min(fade_audio, t.duracao / 2)
            filtros.append(
                f"[0:a]atrim=start={t.inicio:.4f}:end={t.fim:.4f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:d={fade:.3f},afade=t=out:st={t.duracao - fade:.3f}:d={fade:.3f}[a{i}]"
            )
        juntos = "".join(f"[v{i}][a{i}]" for i in range(len(trechos)))
        filtros.append(f"{juntos}concat=n={len(trechos)}:v=1:a=1[vc][acru]")
        if filtro_audio:
            filtros.append(f"[acru]{filtro_audio}[ac]")
        elif abs(ganho_db) >= 0.5:
            # Ganho fixo (não comprime a fala) e limitador só para os picos não estourarem.
            filtros.append(f"[acru]volume={ganho_db:.1f}dB,alimiter=limit=0.84:level=false[ac]")
        else:
            filtros.append("[acru]anull[ac]")

        # Camadas de legenda/gráficos: (arquivo ASS, nits do branco no HDR). A caixinha de pergunta
        # vem à parte e mais clara: com o branco a 203 nits (o de referência, que mantém as cores
        # da marca) ela ficava cinza no iPhone, quase do tom da parede ao fundo.
        camadas = [(a, n) for a, n in ((legendas_ass, 203), (graficos_claros, nits_claros)) if a]
        atual = "[vc]"
        for k, (ass, nits) in enumerate(camadas):
            legenda = f"subtitles=filename='{_escapar_caminho_filtro(ass)}'"
            if pasta_fontes:
                legenda += f":fontsdir='{_escapar_caminho_filtro(pasta_fontes)}'"
            proximo = "[vout]" if k == len(camadas) - 1 else f"[vl{k}]"
            if hdr_saida:
                # Camada transparente em SDR, convertida para a curva HDR e sobreposta. A
                # transparência vai à parte: o zscale com r=tv também comprime o alfa para a faixa
                # limitada (opaco virava 92% e o transparente, um véu preto de 6% no vídeo todo).
                filtros.append(
                    f"color=c=black@0:s={larg}x{alt}:r={fps},format=rgba,{legenda}:alpha=1,"
                    f"split[cor{k}][alfa_bruto{k}]"
                )
                filtros.append(f"[alfa_bruto{k}]alphaextract,format=gray10le[alfa{k}]")
                filtros.append(
                    f"[cor{k}]format=gbrpf32le,zscale=tin=iec61966-2-1:t=linear:npl=203,zscale=pin=bt709:p=bt2020,"
                    f"zscale=t={hdr_saida}:npl={nits}:m=bt2020nc:r=tv,format=yuv420p10le[hdr{k}]"
                )
                filtros.append(f"[hdr{k}][alfa{k}]alphamerge[camada{k}]")
                filtros.append(f"{atual}[camada{k}]overlay=format=yuv420p10:shortest=1:eof_action=pass,{params}{proximo}")
            else:
                filtros.append(f"{atual}{legenda}{proximo}")
            atual = proximo
        if not camadas:
            filtros.append("[vc]null[vout]")

        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *entradas,
             "-filter_complex", ";".join(filtros), "-map", "[vout]", "-map", "[ac]",
             *_codificacao(cfg_video, hdr_saida, fps),
             "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(saida)],
            check=True,
        )
    _zerar_rotacao(saida, hevc=bool(hdr_saida))


def _zerar_rotacao(saida, hevc: bool = False):
    """O ffmpeg 7 copia a rotação do iPhone para a saída, já girada pelo autorotate,
    e o vídeo apareceria de lado. Reescreve o arquivo (sem recodificar) com rotação 0."""
    saida = Path(saida)
    temp = saida.with_name(saida.stem + ".rot" + saida.suffix)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-display_rotation", "0",
         "-i", str(saida), "-map", "0", "-c", "copy", *(["-tag:v", "hvc1"] if hevc else []), "-movflags", "+faststart", str(temp)],
        check=True,
    )
    temp.replace(saida)
