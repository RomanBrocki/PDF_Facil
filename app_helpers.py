"""
app_helpers.py

Utilitários para a interface Streamlit:
- Presets de compressão e rótulos
- Formatação de tamanhos e percentuais
- Toasts (notificações efêmeras) com state
- Ordenação e reordenação de páginas no state
- Geração de thumbnails cacheadas (PDF/JPG/PNG)
"""

from __future__ import annotations
from typing import Dict
import time
import streamlit as st
from PIL import Image, ImageOps
import io
import fitz  # PyMuPDF

try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS  # pyright: ignore[reportAttributeAccessIssue]
except AttributeError:
    # Pillow < 10 mantém o alias antigo
    RESAMPLE_LANCZOS = Image.LANCZOS  # pyright: ignore[reportAttributeAccessIssue]

# Limite global de upload (soma de todos os arquivos enviados de uma vez)
TOTAL_UPLOAD_CAP_MB = 75

# Previews: parâmetros “leves”
PREVIEW_PDF_DPI = 60
PREVIEW_BOX_W, PREVIEW_BOX_H = 220, 300

# --------- PRESETS ---------
# Mapa de níveis internos -> parâmetros da engine
LEVELS: Dict[str, dict] = {
    "none": {"mode": "none", "dpi": None, "jpg_q": None},
    # "smart": rasteriza apenas páginas "imagem-only" (detectadas), preservando vetores/texto
    "min":  {"mode": "smart", "dpi": 200, "jpg_q": 85},
    # "all": rasteriza todas as páginas
    "med":  {"mode": "all",   "dpi": 150, "jpg_q": 70},
    "max":  {"mode": "all",   "dpi": 110, "jpg_q": 50},
}

LABEL_TO_VAL = {"Nenhuma": "none", "Mínima": "min", "Média": "med", "Máxima": "max"}
VAL_TO_LABEL = {v: k for k, v in LABEL_TO_VAL.items()}


# --------- FORMATAÇÃO ---------
def format_size(num_bytes: int | None) -> str:
    """Formata número de bytes em string legível (B/kB/MB).

    Args:
        num_bytes (int | None): Quantidade em bytes ou None.

    Returns:
        str: Valor formatado. Usa vírgula como separador decimal.
    """

    if num_bytes is None:
        return "—"
    kb = 1024.0
    mb = kb * 1024.0
    if num_bytes >= mb:
        return f"{num_bytes/mb:.2f} MB".replace(".", ",")
    if num_bytes >= kb:
        return f"{num_bytes/kb:.0f} kB".replace(".", ",")
    return f"{num_bytes} B"


# --------- LEITURA SEGURA DE UPLOAD ---------
def read_uploaded_as_bytes(uf) -> bytes:
    """Lê um arquivo de upload (UploadedFile/BytesIO) e retorna bytes.

    Reseta o ponteiro após a leitura para não interferir em usos futuros.

    Args:
        uf: Objeto de upload do Streamlit ou similar.

    Returns:
        bytes: Conteúdo binário do arquivo. Retorna b"" em caso de erro.
    """

    try:
        data = uf.read()
        uf.seek(0)
        return data
    except Exception:
        return b""

def notify(key: str, msg: str, icon: str | None = None):
    """Registra/atualiza um toast identificado por chave no session_state.

    Args:
        key (str): Identificador do toast (ex.: "global", "item:3").
        msg (str): Mensagem a exibir.
        icon (str | None): Emoji/ícone opcional (ex.: "⚠️", "📦").

    Returns:
        None
    """

    if "_toasts" not in st.session_state:
        st.session_state._toasts = {}  # key -> {"msg": str, "icon": str, "ts": float}
    st.session_state._toasts[key] = {"msg": msg, "icon": icon or "", "ts": time.time()}

def render_toasts(duration: float = 5.0):
    """Renderiza todos os toasts ativos e descarta os expirados.

    A função reapresenta os toasts a cada rerun do Streamlit, respeitando
    o tempo máximo de exibição.

    Args:
        duration (float): Duração máxima (s) para manter cada toast visível.

    Returns:
        None
    """

    now = time.time()
    toasts = st.session_state.get("_toasts", {})
    # filtra ativos e descarta expirados
    active = {}
    for key, data in toasts.items():
        if now - data["ts"] <= duration:
            active[key] = data
    st.session_state._toasts = active  # mantém só os ativos

    # imprime em ordem (estável)
    for key in sorted(active.keys()):
        data = active[key]
        icon = (data["icon"] + " ") if data["icon"] else ""
        st.info(f"{icon}{data['msg']}")

# --------- Tipo de arquivo ---------
def is_pdf(uf) -> bool:
    """Detecta se um upload aparenta ser PDF pelo mimetype ou extensão.

    Args:
        uf: Objeto de upload do Streamlit (ou compatível) com .name/.type.

    Returns:
        bool: True se for PDF; False caso contrário.
    """

    name = getattr(uf, "name", "") or ""
    typ = (getattr(uf, "type", "") or "").lower()
    return typ.endswith("pdf") or name.lower().endswith(".pdf")

def kind_of(uf) -> str:
    """Classifica o upload como 'pdf' ou 'image'.

    Args:
        uf: Objeto de upload do Streamlit (ou compatível).

    Returns:
        str: 'pdf' ou 'image'.
    """

    return "pdf" if is_pdf(uf) else "image"


# --------- Percentual (clamp e string pronta) ---------
def format_pct(before: int, after: int) -> str:
    """Converte (antes→depois) em string percentual de economia.

    Regra: se não houver melhora (after >= before), retorna "0%".
    Caso contrário, retorna "-NN%".

    Args:
        before (int): Tamanho original.
        after (int): Tamanho após compressão/estimativa.

    Returns:
        str: Percentual formatado (ex.: "-37%").
    """

    if not before or before <= 0:
        return "0%"
    raw = round(100 * (1 - (after / max(before, 1))))
    delta = max(0, raw)  # nunca negativo pra não aparecer '--5%'
    return "0%" if delta == 0 else f"-{delta}%"

# --------- Ordenação e movimento de itens (UI state) ---------
def compute_sorted_order(uploaded, primary: str, reverse: bool) -> list[int]:
    """Calcula a ordem de índices conforme critério.

    Args:
        uploaded: Lista de arquivos enviados (objetos UploadedFile).
        primary (str): Um de {"Original", "Nome", "Tipo"}.
        reverse (bool): Inverte a direção da ordenação quando True.

    Returns:
        list[int]: Lista de índices reordenados.
    """

    n = len(uploaded)
    if n == 0:
        return []
    idxs = list(range(n))

    if primary == "Original":
        return idxs if not reverse else list(reversed(idxs))

    if primary == "Nome":
        idxs.sort(key=lambda i: (uploaded[i].name or "").lower(), reverse=reverse)
        return idxs

    if primary == "Tipo":
        idxs.sort(
            key=lambda i: (
                ((uploaded[i].type or "").split("/")[-1] or "").lower(),
                (uploaded[i].name or "").lower(),
            ),
            reverse=reverse,
        )
        return idxs

    return idxs

def move_up(pos: int) -> None:
    """Move o item da posição 'pos' uma casa para cima na ordem global.

    Args:
        pos (int): Posição atual (0-based).

    Returns:
        None
    """

    order = st.session_state.get("order", [])
    if 0 < pos < len(order):
        order[pos - 1], order[pos] = order[pos], order[pos - 1]
        st.session_state.order = order  # garante persistência

def move_down(pos: int) -> None:
    """Move o item da posição 'pos' uma casa para baixo na ordem global.

    Args:
        pos (int): Posição atual (0-based).

    Returns:
        None
    """

    order = st.session_state.get("order", [])
    if 0 <= pos < len(order) - 1:
        order[pos + 1], order[pos] = order[pos], order[pos + 1]
        st.session_state.order = order  # garante persistência

def thumb_key(fi: int, pi: int, rot: int) -> tuple:
    """Gera a chave estável do cache de thumbnail para (arquivo, página, rotação).

    A chave incorpora nome e tamanho do arquivo de origem, índice de página
    e rotação aplicada, garantindo invalidação correta.

    Args:
        fi (int): Índice do arquivo no upload atual.
        pi (int): Índice da página (0-based) dentro do arquivo.
        rot (int): Rotação em graus (0/90/180/270).

    Returns:
        tuple: Tupla hashable usada como chave de cache.
    """

    name, size = st.session_state._unified_sig[fi]
    return (name or "", int(size or 0), int(pi), int(rot))

def get_thumb(uf, fi: int, pi: int, rot: int) -> bytes:
    """Obtém (ou gera) a miniatura PNG de uma página/arquivo e cacheia.

    Respeita a rotação solicitada e usa resolução reduzida para PDFs.

    Args:
        uf: Objeto UploadedFile referente ao arquivo de origem.
        fi (int): Índice do arquivo no upload atual.
        pi (int): Índice da página (0-based).
        rot (int): Rotação aplicada (0/90/180/270).

    Returns:
        bytes: PNG em bytes da miniatura.
    """

    key = thumb_key(fi, pi, rot)
    cache = st.session_state._thumb_cache
    if key in cache:
        return cache[key]

    # Prefere cache do app (se existir) para evitar I/O repetido
    data = None
    try:
        data = st.session_state._upload_bytes.get(fi, None)
    except Exception:
        data = None
    if data is None:
        data = read_uploaded_as_bytes(uf)

    # Gera imagem base
    if is_pdf(uf):
        try:
            doc = fitz.open("pdf", data)
            pg = doc.load_page(pi)
            pix = pg.get_pixmap(dpi=PREVIEW_PDF_DPI, alpha=False)  # type: ignore[attr-defined]
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            doc.close()
        except Exception:
            img = Image.new("RGB", (180, 240), (230, 230, 230))
    else:
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            img = Image.new("RGB", (180, 240), (230, 230, 230))

    if rot in (90, 180, 270):
        img = img.rotate(-rot, expand=True)

    png = thumb_into_box(img, box_w=PREVIEW_BOX_W, box_h=PREVIEW_BOX_H)
    cache[key] = png
    return png


def thumb_into_box(img: Image.Image, box_w: int = 240, box_h: int = 320, bg=None) -> bytes:
    """Ajusta a imagem para caber em um canvas fixo e retorna PNG.

    Se 'bg' não for definido, gera PNG RGBA com fundo transparente, permitindo
    que o tema do Streamlit apareça atrás (ótimo para dark mode).
    Se 'bg' for (R,G,B), usa canvas RGB sólido.

    Args:
        img (PIL.Image.Image): Imagem a encaixar.
        box_w (int): Largura do canvas (px).
        box_h (int): Altura do canvas (px).
        bg (tuple | None): Fundo sólido RGB ou None para transparência.

    Returns:
        bytes: PNG exportado (preserva alfa quando RGBA).
    """

    # 1) Redimensiona proporcionalmente para caber no retângulo interno (com pequena margem)
    inner_w, inner_h = box_w - 8, box_h - 8
    fitted = ImageOps.contain(img, (inner_w, inner_h), method=RESAMPLE_LANCZOS)

    # 2) Canvas de saída:
    #    - Se 'bg' não for passado -> RGBA TRANSPARENTE (deixa o tema do Streamlit aparecer)
    #    - Se 'bg' existir (ex.: (240,240,240)) -> usa RGB sólido
    if bg is None:
        canvas = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))  # totalmente transparente
        # garante que a imagem colada tenha alfa (para usar como máscara)
        fitted_rgba = fitted.convert("RGBA")
    else:
        canvas = Image.new("RGB", (box_w, box_h), bg)
        fitted_rgba = fitted.convert("RGBA")

    # 3) Centraliza
    x = (box_w - fitted_rgba.width) // 2
    y = (box_h - fitted_rgba.height) // 2
    # 4) Cola usando a própria imagem como máscara (preserva bordas suaves)
    canvas.paste(fitted_rgba, (x, y), fitted_rgba)

    # 5) Exporta como PNG (mantém transparência quando RGBA)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()




# --- Helper: aplica uma nova ordem (permutação) às listas de estado por PÁGINA ---
def reorder_page_state(new_order_idx: list[int]) -> None:
    """Aplica uma nova permutação ao estado por PÁGINA no session_state.

    Reordena de forma consistente:
    - pages_flat
    - keep_map
    - rot_map
    - level_page

    Args:
        new_order_idx (list[int]): Permutação 0-based com o mesmo comprimento
            das listas de estado.

    Returns:
        None
    """

    pf = st.session_state.pages_flat
    km = st.session_state.keep_map
    rm = st.session_state.rot_map
    lv = st.session_state.level_page

    if not new_order_idx or len(new_order_idx) != len(pf):
        return  # nada a fazer / ordem inválida

    st.session_state.pages_flat = [pf[i] for i in new_order_idx]
    st.session_state.keep_map   = [km[i] for i in new_order_idx]
    st.session_state.rot_map    = [rm[i] for i in new_order_idx]
    st.session_state.level_page = [lv[i] for i in new_order_idx]
