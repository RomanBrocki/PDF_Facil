"""
pdf_ops.py

Motor de processamento puro (sem Streamlit):
- Estimativas de tamanho (PDF/por página/imagem)
- Compressão real (smart/all) com guard-rails
- Conversão imagem→PDF (1 página)
- União/merge por itens ou por páginas já flatten
- Split/rotação por página

Todas as funções trabalham com bytes e metadados simples.
"""


from __future__ import annotations

import io
from typing import Dict, Iterable, List, Tuple, cast, Any

import img2pdf
import fitz  # PyMuPDF
from PIL import Image
# Pillow 9 vs 10+: constante de reamostragem
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS  # pyright: ignore[reportAttributeAccessIssue]
except AttributeError:
    # Pillow < 10 mantém o alias antigo
    RESAMPLE_LANCZOS = Image.LANCZOS  # pyright: ignore[reportAttributeAccessIssue]

# retrocompatibilidade

from pypdf import PdfReader, PdfWriter

from app_helpers import LEVELS


# ===========================
#   ESTIMATIVAS (rápidas)
# ===========================
def _is_image_only(page: "fitz.Page") -> bool:


    """Detecta se uma página é 'imagem-only' (sem texto e sem vetores).

    Heurística usada pelo preset 'min' para decidir rasterização seletiva.

    Args:
        page (fitz.Page): Página do PyMuPDF.

    Returns:
        bool: True se não houver texto nem vetores; False caso contrário.
    """
    p = cast(Any, page)
    try:
        has_text = bool(p.get_text("text"))             # pyright: ignore[reportAttributeAccessIssue]
    except Exception:
        has_text = False
    try:
        has_vectors = len(p.get_drawings()) > 0         # pyright: ignore[reportAttributeAccessIssue]
    except Exception:
        has_vectors = False
    return (not has_text) and (not has_vectors)


def estimate_pdf_size(pdf_bytes: bytes, level: str) -> int:
    """Estima o tamanho final de um PDF após aplicar um nível de compressão.

    Args:
        pdf_bytes (bytes): PDF de entrada.
        level (str): 'none'|'min'|'med'|'max'.

    Returns:
        int: Tamanho estimado em bytes do PDF resultante.
    """

    params = LEVELS.get(level or "none", LEVELS["none"])
    mode = params["mode"]
    dpi = params["dpi"]
    jpg_q = params["jpg_q"]

    if mode == "none":
        return len(pdf_bytes)

    # "all": renderiza todas as páginas -> JPEG -> converte p/ PDF
    if mode == "all":
        doc = fitz.open("pdf", pdf_bytes)
        jpg_pages = []
        for i in range(doc.page_count):
            pg = doc.load_page(i)
            pix = pg.get_pixmap(dpi=dpi, alpha=False)  # pyright: ignore[reportAttributeAccessIssue]
            jpg_pages.append(pix.tobytes("jpeg", jpg_quality=jpg_q))
        doc.close()
        try:
            est_pdf = cast(bytes, img2pdf.convert(jpg_pages))
        except Exception:
            est_pdf = b"".join(jpg_pages) + b"\x00" * (1024 * len(jpg_pages))
        return len(est_pdf)

    # "smart": rasteriza só páginas imagem-only; copia as demais
    if mode == "smart":
        src = fitz.open("pdf", pdf_bytes)
        dst = fitz.open()

        def _copy_page(dst_doc, src_doc, i: int):
            dst_doc.insert_pdf(src_doc, from_page=i, to_page=i)

        def _rasterize_to(dst_doc, page_obj: "fitz.Page", dpi_val: int, jpeg_q: int):
            pix = page_obj.get_pixmap(dpi=dpi_val, alpha=False)  # pyright: ignore[reportAttributeAccessIssue]
            img_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_q)
            rect = page_obj.rect
            p = dst_doc.new_page(width=rect.width, height=rect.height)
            p.insert_image(rect, stream=img_bytes)

        for i in range(src.page_count):
            page = src.load_page(i)
            if _is_image_only(page):
                _rasterize_to(dst, page, dpi, jpg_q)
            else:
                _copy_page(dst, src, i)


        est_bytes = dst.write(garbage=4, deflate=True, clean=True)# pyright: ignore[reportArgumentType]
        dst.close()
        src.close()
        return len(est_bytes)

    return len(pdf_bytes)

def estimate_pdf_page_size(pdf_bytes: bytes, page_idx: int, level: str) -> int:
    """Estima o tamanho de UMA página após aplicar um nível.

    Args:
        pdf_bytes (bytes): PDF de origem.
        page_idx (int): Índice 0-based da página.
        level (str): 'none'|'min'|'med'|'max'.

    Returns:
        int: Tamanho estimado em bytes para a página empacotada em PDF.
    """

    params = LEVELS.get(level or "none", LEVELS["none"])
    mode = params["mode"]; dpi = params["dpi"]; jpg_q = params["jpg_q"]

    doc = fitz.open("pdf", pdf_bytes)
    if page_idx < 0 or page_idx >= doc.page_count:
        doc.close()
        return 0

    pg = doc.load_page(page_idx)

    if mode == "none":
        tmp = fitz.open()
        tmp.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
        est = len(tmp.write(garbage=4, deflate=True, clean=True))  # pyright: ignore[reportArgumentType]
        tmp.close(); doc.close()
        return est

    if mode == "all":
        pix = pg.get_pixmap(dpi=dpi, alpha=False)  # pyright: ignore[reportAttributeAccessIssue]
        jpg_b = pix.tobytes("jpeg", jpg_quality=jpg_q)
        try:
            est_pdf = cast(bytes, img2pdf.convert(jpg_b))
        except Exception:
            est_pdf = jpg_b + b"\x00" * 1024
        doc.close()
        return len(est_pdf)

    if mode == "smart":
        if _is_image_only(pg):
            pix = pg.get_pixmap(dpi=dpi, alpha=False)  # pyright: ignore[reportAttributeAccessIssue]
            jpg_b = pix.tobytes("jpeg", jpg_quality=jpg_q)
            try:
                est_pdf = cast(bytes, img2pdf.convert(jpg_b))
            except Exception:
                est_pdf = jpg_b + b"\x00" * 1024
            doc.close()
            return len(est_pdf)

        tmp = fitz.open()
        tmp.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
        est = len(tmp.write(garbage=4, deflate=True, clean=True))  # pyright: ignore[reportArgumentType]
        tmp.close(); doc.close()
        return est

    doc.close()
    return 0


def estimate_image_pdf_size(img_bytes: bytes, level: str) -> int:
    """Estima o tamanho do PDF (1 página) gerado a partir de uma imagem.

    Args:
        img_bytes (bytes): PNG/JPG de entrada.
        level (str): 'none'|'min'|'med'|'max'.

    Returns:
        int: Tamanho estimado em bytes do PDF de 1 página.
    """

    params = LEVELS.get(level or "none", LEVELS["none"])
    mode = params["mode"]
    if mode == "none":
        try:
            return len(cast(bytes, img2pdf.convert(img_bytes)))
        except Exception:
            return len(img_bytes)

    im = Image.open(io.BytesIO(img_bytes))
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")

    if level == "min":
        max_side, quality = 2400, 85
    elif level == "med":
        max_side, quality = 2000, 70
    elif level == "max":
        max_side, quality = 1600, 50
    else:
        max_side, quality = None, 95

    if max_side is not None:
        w, h = im.size
        scale = min(max_side / max(w, h), 1.0)
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), RESAMPLE_LANCZOS)

    jpg_buf = io.BytesIO()
    im.save(jpg_buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    jpg_bytes = jpg_buf.getvalue()

    try:
        return len(cast(bytes, img2pdf.convert(jpg_bytes)))
    except Exception:
        return len(jpg_bytes) + 1024


# ===========================
#   COMPRESSÃO REAL
# ===========================
def compress_pdf(pdf_bytes: bytes, level: str | None) -> bytes:
    """Aplica compressão real a um PDF conforme o nível.

    Respeita guard-rails: se o resultado não for menor, devolve o original.

    Args:
        pdf_bytes (bytes): PDF de entrada.
        level (str | None): 'none'|'min'|'med'|'max' ou None.

    Returns:
        bytes: PDF possivelmente comprimido (ou original).
    """

    if not level or level in (None, "none"):
        return pdf_bytes

    params = LEVELS.get(level, LEVELS["none"])
    mode = params["mode"]
    dpi = params["dpi"]
    jpg_q = params["jpg_q"]

    # Rasteriza todas as páginas
    if mode == "all":
        try:
            src = fitz.open("pdf", pdf_bytes)
            jpg_pages = []
            for i in range(src.page_count):
                pg = src.load_page(i)
                pix = pg.get_pixmap(dpi=dpi, alpha=False)  # pyright: ignore[reportAttributeAccessIssue]
                jpg_pages.append(pix.tobytes("jpeg", jpg_quality=jpg_q))
            src.close()
            out_bytes = cast(bytes, img2pdf.convert(jpg_pages))
            return out_bytes if len(out_bytes) < len(pdf_bytes) else pdf_bytes
        except Exception:
            return pdf_bytes

    # Rasteriza apenas páginas "imagem-only"
    if mode == "smart":
        try:
            src = fitz.open("pdf", pdf_bytes)
            dst = fitz.open()

            def _copy_page(dst_doc, src_doc, i: int):
                dst_doc.insert_pdf(src_doc, from_page=i, to_page=i)

            def _rasterize_to(dst_doc, page_obj: "fitz.Page", dpi_val: int, jpeg_q: int):
                pix = page_obj.get_pixmap(dpi=dpi_val, alpha=False)  # pyright: ignore[reportAttributeAccessIssue]
                img_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_q)
                rect = page_obj.rect
                p = dst_doc.new_page(width=rect.width, height=rect.height)
                p.insert_image(rect, stream=img_bytes)

            for i in range(src.page_count):
                page = src.load_page(i)
                if _is_image_only(page):
                    _rasterize_to(dst, page, dpi, jpg_q)  # pyright: ignore[reportAttributeAccessIssue]
                else:
                    _copy_page(dst, src, i)

            out_bytes = dst.write(garbage=4, deflate=True, clean=True)# pyright: ignore[reportArgumentType]
            dst.close()
            src.close()
            return out_bytes if len(out_bytes) < len(pdf_bytes) else pdf_bytes
        except Exception:
            return pdf_bytes

    return pdf_bytes


def image_to_pdf_bytes(file_bytes: bytes, level: str | None) -> bytes:
    """Converte PNG/JPG para PDF de 1 página (com compressão opcional).

    Args:
        file_bytes (bytes): Imagem de entrada.
        level (str | None): 'none'|'min'|'med'|'max' ou None.

    Returns:
        bytes: PDF resultante (1 página).
    """

    if level in (None, "none"):
        try:
            return cast(bytes, img2pdf.convert(file_bytes))
        except Exception:
            pass

    # Abre imagem e padroniza
    im = Image.open(io.BytesIO(file_bytes))
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")

    # Parâmetros por nível (alinhados com presets)
    if level == "min":
        max_side, quality = 2400, 85
    elif level == "med":
        max_side, quality = 2000, 70
    elif level == "max":
        max_side, quality = 1600, 50
    else:
        max_side, quality = None, 95

    # Downscale se necessário
    if max_side is not None:
        w, h = im.size
        scale = min(max_side / max(w, h), 1.0)
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), RESAMPLE_LANCZOS)

    # Recompressão JPEG e wrap em PDF
    jpg_buf = io.BytesIO()
    im.save(jpg_buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    jpg_bytes = jpg_buf.getvalue()

    return cast(bytes, img2pdf.convert(jpg_bytes))


# ===========================
#   UNIÃO / MERGE
# ===========================
def merge_items(items: List[Tuple[str, bytes, str, str]]) -> bytes:
    """Une itens (PDF/imagem) em um único PDF.

    Para 'pdf', aplica compressão por item; para 'image', converte imagem→PDF.

    Args:
        items (List[Tuple[str, bytes, str, str]]): Tuplas (name, data, kind, level).

    Returns:
        bytes: PDF final unificado.
    """

    writer = PdfWriter()
    errors: List[str] = []

    def _append_pdf_bytes(pdf_b: bytes):
        try:
            reader = PdfReader(io.BytesIO(pdf_b))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    errors.append("PDF criptografado; ignorado.")
                    return
            for page in reader.pages:
                writer.add_page(page)
        except Exception as e:
            errors.append(f"Falha ao anexar PDF: {e}")

    for name, data, kind, level in items:
        if kind == "pdf":
            pdf_b = compress_pdf(data, level)
            _append_pdf_bytes(pdf_b)
        else:
            # imagem -> PDF 1 página (respeita o nível)
            pdf_b = image_to_pdf_bytes(data, level)
            _append_pdf_bytes(pdf_b)

    out_buf = io.BytesIO()
    writer.write(out_buf)
    return out_buf.getvalue()

def merge_pages(
    pages_flat: List[Tuple[str, bytes, str, int, str]],
    rotation_seq: List[int] | None = None
) -> bytes:
    """Monta um PDF final a partir de páginas já flatten (ordem global).

    Permite aplicar rotação por página e compressão por página.

    Args:
        pages_flat (List[Tuple[str, bytes, str, int, str]]): (name, data, kind, page_idx, level).
        rotation_seq (List[int] | None): Ângulos por posição (0/90/180/270).

    Returns:
        bytes: PDF final na ordem solicitada.
    """

    dst = fitz.open()
    rotations = rotation_seq or [0] * len(pages_flat)

    for pos, (name, data, kind, page_idx, level) in enumerate(pages_flat):
        try:
            angle = int(rotations[pos]) % 360
        except Exception:
            angle = 0

        if kind == "image":
            # imagem -> PDF bytes (respeita level) -> anexar página
            try:
                one_pdf = image_to_pdf_bytes(data, level)
            except Exception:
                one_pdf = image_to_pdf_bytes(data, "none")
            try:
                tmp = fitz.open("pdf", one_pdf)
                dst.insert_pdf(tmp, from_page=0, to_page=0)
                tmp.close()
                if angle:
                    dst[-1].set_rotation(angle)  # pyright: ignore[reportAttributeAccessIssue]
            except Exception:
                pass
            continue

        # kind == 'pdf'
        try:
            src = fitz.open("pdf", data)
            page_idx = max(0, min(page_idx, src.page_count - 1))
            pg = src.load_page(page_idx)

            if not level or level == "none":
                # cópia 1:1 da página
                dst.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                if angle:
                    dst[-1].set_rotation(angle)  # pyright: ignore[reportAttributeAccessIssue]
                src.close()
                continue

            # rasterização desta página respeitando LEVELS (mesma lógica da compressão)
            params = LEVELS.get(level, LEVELS["none"])
            mode = params["mode"]
            dpi = params["dpi"]
            jpg_q = params["jpg_q"]

            if mode == "smart":
                # só rasteriza se for 'imagem-only'; senão, copia 1:1
                if _is_image_only(pg):
                    pix = pg.get_pixmap(dpi=dpi, alpha=False)  # pyright: ignore[reportAttributeAccessIssue]
                    img_bytes = pix.tobytes("jpeg", jpg_quality=jpg_q)
                    rect = pg.rect
                    p = dst.new_page(width=rect.width, height=rect.height) # pyright: ignore[reportAttributeAccessIssue]
                    p.insert_image(rect, stream=img_bytes)
                    if angle:
                        dst[-1].set_rotation(angle)  # pyright: ignore[reportAttributeAccessIssue]
                else:
                    dst.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                    if angle:
                        dst[-1].set_rotation(angle)  # pyright: ignore[reportAttributeAccessIssue]

            elif mode == "all":
                # rasteriza esta página
                pix = pg.get_pixmap(dpi=dpi, alpha=False)  # pyright: ignore[reportAttributeAccessIssue]
                img_bytes = pix.tobytes("jpeg", jpg_quality=jpg_q)
                rect = pg.rect
                p = dst.new_page(width=rect.width, height=rect.height) # pyright: ignore[reportAttributeAccessIssue]
                p.insert_image(rect, stream=img_bytes)
                if angle:
                    dst[-1].set_rotation(angle)  # pyright: ignore[reportAttributeAccessIssue]
            else:
                # fallback: cópia crua
                dst.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                if angle:
                    dst[-1].set_rotation(angle)  # pyright: ignore[reportAttributeAccessIssue]

            src.close()

        except Exception:
            # falha isolada numa página não bloqueia o restante
            try:
                src.close()
            except Exception:
                pass
            continue

    out_bytes = dst.write(garbage=4, deflate=True, clean=True)  # pyright: ignore[reportArgumentType]
    dst.close()
    return out_bytes

# ===========================
#   DIVIDIR / GIRAR
# ===========================
def split_pdf(pdf_bytes: bytes, keep_pages_0based: List[int], rotation_map: Dict[int, int] | None = None) -> bytes:
    """Gera um novo PDF contendo apenas páginas selecionadas e rotações.

    Args:
        pdf_bytes (bytes): PDF de origem.
        keep_pages_0based (List[int]): Índices 0-based das páginas a manter.
        rotation_map (Dict[int, int] | None): Ângulos por índice (0/90/180/270).

    Returns:
        bytes: PDF contendo apenas as páginas escolhidas (com rotações).
    """

    src = fitz.open("pdf", pdf_bytes)
    dst = fitz.open()

    for i in sorted(set(keep_pages_0based)):
        if i < 0 or i >= src.page_count:
            continue
        dst.insert_pdf(src, from_page=i, to_page=i)
        if rotation_map and i in rotation_map:
            angle = rotation_map[i] % 360
            dp = dst[-1]
            try:
                dp.set_rotation(angle)
            except Exception:
                pass


    out_bytes = dst.write(garbage=4, deflate=True, clean=True)# pyright: ignore[reportArgumentType]
    dst.close()
    src.close()
    return out_bytes
