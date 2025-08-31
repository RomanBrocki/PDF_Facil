
"""
app_helpers.py — helpers do app (presets, formatação e utilidades leves).
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
    """Formata bytes em B/kB/MB com 2 casas (ponto -> vírgula)."""
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
    """Lê UploadedFile/BytesIO e reseta o ponteiro, retornando bytes."""
    try:
        data = uf.read()
        uf.seek(0)
        return data
    except Exception:
        return b""

def notify(key: str, msg: str, icon: str | None = None):
    """
    Registra / substitui um balão identificado por 'key'.
    Ex.: 'global' ou f'item:{idx}'.
    """
    if "_toasts" not in st.session_state:
        st.session_state._toasts = {}  # key -> {"msg": str, "icon": str, "ts": float}
    st.session_state._toasts[key] = {"msg": msg, "icon": icon or "", "ts": time.time()}

def render_toasts(duration: float = 5.0):
    """
    Re-renderiza todos os balões ativos (<= duration segundos).
    Não persiste elementos de UI entre reruns — reimprime a cada chamada.
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
    """Retorna True se for PDF pelo mimetype ou extensão."""
    name = getattr(uf, "name", "") or ""
    typ = (getattr(uf, "type", "") or "").lower()
    return typ.endswith("pdf") or name.lower().endswith(".pdf")

def kind_of(uf) -> str:
    """'pdf' ou 'image'."""
    return "pdf" if is_pdf(uf) else "image"


# --------- Percentual (clamp e string pronta) ---------
def format_pct(before: int, after: int) -> str:
    """
    Converte (before→after) em string de percentual:
      - se piorar ou ficar igual: '0%'
      - se reduzir: '-NN%'
    """
    if not before or before <= 0:
        return "0%"
    raw = round(100 * (1 - (after / max(before, 1))))
    delta = max(0, raw)  # nunca negativo pra não aparecer '--5%'
    return "0%" if delta == 0 else f"-{delta}%"

# --------- Ordenação e movimento de itens (UI state) ---------
def compute_sorted_order(uploaded, primary: str, reverse: bool) -> list[int]:
    """
    Retorna a ordem de índices conforme o critério:
      - primary ∈ {"Original", "Nome", "Tipo"}
      - reverse True inverte a direção
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
    """Move o item da posição 'pos' uma casa para cima em st.session_state.order."""
    order = st.session_state.get("order", [])
    if 0 < pos < len(order):
        order[pos - 1], order[pos] = order[pos], order[pos - 1]
        st.session_state.order = order  # garante persistência

def move_down(pos: int) -> None:
    """Move o item da posição 'pos' uma casa para baixo em st.session_state.order."""
    order = st.session_state.get("order", [])
    if 0 <= pos < len(order) - 1:
        order[pos + 1], order[pos] = order[pos], order[pos + 1]
        st.session_state.order = order  # garante persistência

def thumb_key(fi: int, pi: int, rot: int) -> tuple:
    name, size = st.session_state._unified_sig[fi]
    return (name or "", int(size or 0), int(pi), int(rot))

def get_thumb(uf, fi: int, pi: int, rot: int) -> bytes:
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
    """
    Redimensiona proporcionalmente para caber em (box_w x box_h),
    centraliza num canvas fixo e retorna PNG com transparência.
    Se 'bg' for fornecido (tupla RGB), usa fundo sólido; caso contrário, fundo transparente.
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
