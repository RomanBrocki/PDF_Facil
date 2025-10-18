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
#   HELPER: JPEG COM QUALIDADE AJUSTÁVEL (sem novas deps)
# ===========================
def _jpeg_bytes_with_band(
    img: Image.Image,
    q_start: int,
    keep_min: float | None,
    keep_max: float | None,
    baseline_len: int,
    q_floor: int = 40,
    subsamp_default: int | None = None,
) -> tuple[bytes, bool]:
    """
    Re-encode em JPEG ajustando qualidade para manter o tamanho DENTRO de uma faixa
    medida contra 'baseline_len' (tamanho do PDF-base do original).
    Retorna (jpeg_bytes, reached_floor) onde reached_floor=True indica que o piso foi atingido.
    """
    # IMPORT LOCAL para não alterar seus imports globais
    import math

    # sempre RGB para JPEG
    if img.mode not in ("RGB",):
        img = img.convert("RGB")

    def _enc(qv: int, subsamp: int | None = None,
             optimize: bool = True, progressive: bool = True) -> bytes:
        buf = io.BytesIO()
        try:
            use_sub = subsamp if subsamp is not None else subsamp_default
            if use_sub is None:
                img.save(buf, "JPEG", quality=int(qv), optimize=optimize, progressive=progressive)
            else:
                img.save(buf, "JPEG", quality=int(qv), optimize=optimize, progressive=progressive, subsampling=use_sub)
        except TypeError:
            # Pillow antigo sem 'subsampling'
            img.save(buf, "JPEG", quality=int(qv), optimize=optimize, progressive=progressive)
        return buf.getvalue()

    q = max(1, min(int(q_start), 95))
    out = _enc(q)

    # 1) teto (compressão mínima desejada)
    if keep_max is not None:
        ceil_len = int(baseline_len * keep_max)
        while len(out) > ceil_len and q > q_floor:
            q -= 3
            out = _enc(q)

        # 1a) Se ainda não atingiu o teto no piso de qualidade, tenta downscale guiado (apenas se q_floor <= 32)
        if len(out) > ceil_len and q <= q_floor and q_floor <= 32:
            target_ratio = ceil_len / max(1, len(out))  # (0,1]
            scale = max(0.60, min(0.98, math.sqrt(target_ratio) * 0.98))
            w, h = img.size
            MIN_LONG_SIDE = 960
            while len(out) > ceil_len and max(w, h) > MIN_LONG_SIDE:
                w = max(1, int(w * scale)); h = max(1, int(h * scale))
                img = img.resize((w, h), RESAMPLE_LANCZOS)
                out = _enc(q)  # mantém 'q' atual

    # 2) piso (evitar secar demais)
    reached_floor = True
    if keep_min is not None:
        floor_len = int(baseline_len * keep_min)
        while len(out) < floor_len and q < 95:
            q += 3
            out = _enc(q)

        if len(out) < floor_len:
            # tentar “engordar”: 4:4:4 + quality 100
            out2 = _enc(100, subsamp=0)
            if len(out2) > len(out):
                out = out2
            if len(out) < floor_len:
                # último recurso: sem optimize/progressive
                out3 = _enc(100, subsamp=0, optimize=False, progressive=False)
                if len(out3) > len(out):
                    out = out3

        reached_floor = (len(out) >= floor_len)

    return out, reached_floor


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
def _estimate_pdf_page_len_guardrail(pdf_bytes: bytes, page_idx: int, level: str) -> int:
    """
    Estima o tamanho *escolhido* pelo guard-rail para UMA página de PDF.

    Reproduz a mesma regra do merge_pages:
      - base_bytes = PDF 1:1 dessa página
      - candidatos conforme 'level' e LEVELS
      - compara base vs candidatos e retorna o menor len(...)
    """
    try:
        src = fitz.open("pdf", pdf_bytes)
        if page_idx < 0 or page_idx >= src.page_count:
            src.close()
            return 0

        # 1) base: a página 1:1 como PDF solo
        base_doc = fitz.open()
        base_doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)
        base_bytes = base_doc.write(garbage=4, deflate=True, clean=True)  # pyright: ignore[reportArgumentType]
        base_doc.close()
        base_len = len(base_bytes)

        # 2) helper de candidato
        params = LEVELS.get(level or "none", LEVELS["none"])
        mode = params["mode"]; dpi = int(params["dpi"] or 150); jpg_q = int(params["jpg_q"] or 75)
        pg = src.load_page(page_idx)

        def _cand_len(level_key: str) -> int:
            pr = LEVELS.get(level_key, LEVELS["none"])
            md = pr["mode"]; dp = int(pr["dpi"] or 150); jq = int(pr["jpg_q"] or 75)

            if md == "none":
                return base_len

            if md == "smart" and not _is_image_only(pg):
                return base_len

            dpi_eff = _cap_dpi_for_page(pg, dp)  # usa o mesmo cap do merge
            mat = fitz.Matrix(dpi_eff/72.0, dpi_eff/72.0)
            pix = pg.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)  # pyright: ignore[reportAttributeAccessIssue]
            jpg_b = pix.tobytes("jpeg", jpg_quality=jq)
            del pix
            try:
                pdf1 = cast(bytes, img2pdf.convert(jpg_b))  # embrulha em PDF 1-pag
                return len(pdf1)
            except Exception:
                # raro: se falhar o wrapper em PDF, usa JPEG como proxy (+1024 p/ aproximar)
                return len(jpg_b) + 1024

        if level == "min":
            return min(base_len, _cand_len("min"))
        elif level == "med":
            return min(base_len, _cand_len("min"), _cand_len("med"))
        elif level == "max":
            return min(base_len, _cand_len("min"), _cand_len("med"), _cand_len("max"))
        else:
            return base_len
    except Exception:
        return len(pdf_bytes)
    finally:
        try:
            src.close()
        except Exception:
            pass

def _cap_dpi_for_page(page: "fitz.Page", target_dpi: int) -> int:
    """
    Limita o DPI efetivo para evitar rasterizações gigantes em páginas muito grandes.
    Mantém ~até 5MP por página como alvo. Se não conseguir medir, devolve o target_dpi.
    """
    try:
        rect = page.rect
        w_in = rect.width / 72.0
        h_in = rect.height / 72.0
        # pixels estimados no DPI alvo
        px = (w_in * target_dpi) * (h_in * target_dpi)
        if px <= 5_000_000:
            return int(target_dpi)
        scale = (5_000_000 / max(px, 1.0)) ** 0.5
        return max(72, int(target_dpi * scale))
    except Exception:
        return int(target_dpi)


def estimate_pdf_size(pdf_bytes: bytes, level: str) -> int:
    """Estima o tamanho final de um PDF após aplicar um nível de compressão.

    ***Agora usa o MESMO guard-rail do merge_pages***:
    para cada página, compara o PDF 1:1 com os candidatos rasterizados e soma o menor.

    Nota: somamos um overhead pequeno para aproximar o write() final.
    """
    try:
        src = fitz.open("pdf", pdf_bytes)
        pages = src.page_count
        src.close()
    except Exception:
        return len(pdf_bytes)

    # Overheads (ajuste fino opcional)
    EST_OVERHEAD_DOC = 2048
    EST_OVERHEAD_PER_PAGE = 512

    total = 0
    for i in range(pages):
        total += _estimate_pdf_page_len_guardrail(pdf_bytes, i, level)

    return max(0, total + EST_OVERHEAD_DOC + EST_OVERHEAD_PER_PAGE * pages)


def estimate_pdf_page_size(pdf_bytes: bytes, page_idx: int, level: str) -> int:
    """Estima o tamanho de UMA página após aplicar um nível.

    Agora usa o MESMO guard-rail do merge_pages (base vs candidatos).
    """
    return _estimate_pdf_page_len_guardrail(pdf_bytes, page_idx, level)


def estimate_image_pdf_size(img_bytes: bytes, level: str) -> int:
    """Estima o tamanho do PDF (1 página) gerado a partir de uma imagem, mirando a FAIXA vs PDF-base."""

    # PDF-base do original (baseline)
    try:
        pdf_orig = cast(bytes, img2pdf.convert(img_bytes))
    except Exception:
        # fallback: usa a própria imagem como proxy
        pdf_orig = img_bytes
    base_len = len(pdf_orig)

    params = LEVELS.get(level or "none", LEVELS["none"])
    mode = params["mode"]
    if mode == "none":
        return base_len

    im = Image.open(io.BytesIO(img_bytes))
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")

    # Regras calibradas por nível (ajuste fino livre)
    if level == "min":
        q_start = 88
        keep_max = 0.75   # <= 75% do baseline → ≥25% de redução
        keep_min = 0.65   # >= 65% do baseline → ≤35% de redução
        max_side = None
    elif level == "med":
        q_start = 75
        keep_max = 0.48   # <= 48% → ≥52% de redução
        keep_min = 0.30   # >= 30% → ≤70% de redução
        max_side = 1280
    elif level == "max":
        q_start = 65
        keep_max = 0.30   # <= 30% → ≥70% de redução
        keep_min = None
        max_side = 2000
    else:
        return base_len

    # Downscale (se configurado para o nível)
    if max_side is not None:
        w, h = im.size
        scale = min(max_side / max(w, h), 1.0)
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), RESAMPLE_LANCZOS)

    # JPEG dentro da faixa vs baseline
    q_floor = 45 if level == "min" else (30 if level == "med" else 24)
    subsamp = None if level == "min" else 2  # 4:2:0 no méd/max
    jpg_bytes, _ok_floor = _jpeg_bytes_with_band(
        im, q_start, keep_min, keep_max, base_len, q_floor=q_floor, subsamp_default=subsamp
    )

    # Monta PDF do candidato e aplica guard-rail vs baseline
    try:
        pdf_out = cast(bytes, img2pdf.convert(jpg_bytes))
    except Exception:
        pdf_out = jpg_bytes + b"\x00" * 1024

    return len(pdf_out) if len(pdf_out) < base_len else base_len


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
    """Converte PNG/JPG para PDF (1 página), mira a FAIXA vs PDF-base e mantém guard-rail."""

    # PDF-base do original (baseline)
    try:
        pdf_orig = cast(bytes, img2pdf.convert(file_bytes))
    except Exception:
        pdf_orig = file_bytes
    base_len = len(pdf_orig)

    if not level or level == "none":
        return pdf_orig

    im = Image.open(io.BytesIO(file_bytes))
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")

    if level == "min":
        q_start = 88
        keep_max = 0.75
        keep_min = 0.65
        max_side = None
    elif level == "med":
        q_start = 75
        keep_max = 0.48
        keep_min = 0.30
        max_side = 1280
    elif level == "max":
        q_start = 65
        keep_max = 0.30
        keep_min = None
        max_side = 2000
    else:
        return pdf_orig

    if max_side is not None:
        w, h = im.size
        scale = min(max_side / max(w, h), 1.0)
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), RESAMPLE_LANCZOS)

    q_floor = 45 if level == "min" else (30 if level == "med" else 24)
    subsamp = None if level == "min" else 2  # 4:2:0 no méd/max
    jpg_bytes, _ok_floor = _jpeg_bytes_with_band(
        im, q_start, keep_min, keep_max, base_len, q_floor=q_floor, subsamp_default=subsamp
    )

    # Converte candidato para PDF e aplica guard-rail
    try:
        pdf_out = cast(bytes, img2pdf.convert(jpg_bytes))
    except Exception:
        pdf_out = jpg_bytes + b"\x00" * 1024

    return pdf_out if len(pdf_out) < base_len else pdf_orig



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
            if page_idx < 0 or page_idx >= src.page_count:
                src.close()
                continue

            # Página fonte
            pg = src.load_page(page_idx)

            # 1) base_bytes: PDF 1:1 só com esta página (nenhuma alteração)
            base_doc = fitz.open()
            base_doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)
            base_bytes = base_doc.write(garbage=4, deflate=True, clean=True)  # pyright: ignore[reportArgumentType]
            base_doc.close()

            # 2) helper local: gera candidato conforme 'level_key' e LEVELS
            def _cand(level_key: str) -> bytes:
                params = LEVELS.get(level_key, LEVELS["none"])
                mode = params["mode"]
                dpi  = params["dpi"]
                jpg_q = params["jpg_q"]

                # none -> sempre devolve o base
                if mode == "none":
                    return base_bytes

                # smart: só rasteriza se for imagem-only, senão mantém base
                if mode == "smart" and not _is_image_only(pg):
                    return base_bytes

                # all OU smart+imagem-only -> rasteriza esta página
                dpi_eff = _cap_dpi_for_page(pg, int(dpi or 150))
                mat = fitz.Matrix(dpi_eff/72.0, dpi_eff/72.0)
                pix = pg.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)  # pyright: ignore[reportAttributeAccessIssue]
                jpg_b = pix.tobytes("jpeg", jpg_quality=int(jpg_q or 75))
                del pix
                try:
                    return cast(bytes, img2pdf.convert(jpg_b))  # embrulha em PDF 1-pag
                except Exception:
                    # fallback bruto (raríssimo): retorna o JPEG solto; inserir_pdf abaixo falharia,
                    # então preferimos cair pro base_bytes na comparação.
                    return jpg_b

            # 3) gera os candidatos respeitando monotonicidade (max ≤ med ≤ min ≤ base)
            #    - min: compara base vs min
            #    - med: compara base vs min vs med
            #    - max: compara base vs min vs med vs max
            if level == "min":
                cand_min = _cand("min")
                chosen = min((base_bytes, cand_min), key=len)
            elif level == "med":
                cand_min = _cand("min")
                cand_med = _cand("med")
                chosen = min((base_bytes, cand_min, cand_med), key=len)
            elif level == "max":
                cand_min = _cand("min")
                cand_med = _cand("med")
                cand_max = _cand("max")
                chosen = min((base_bytes, cand_min, cand_med, cand_max), key=len)
            else:
                chosen = base_bytes  # none

            # 4) insere a VERSÃO MENOR no destino e aplica rotação
            try:
                one = fitz.open("pdf", chosen)  # preferimos inserir PDF bem-formado
            except Exception:
                # se chosen não for PDF (fallback raríssimo), volta para base
                one = fitz.open("pdf", base_bytes)

            dst.insert_pdf(one, from_page=0, to_page=0)
            one.close()
            if angle:
                dst[-1].set_rotation(angle)  # pyright: ignore[reportAttributeAccessIssue]

            src.close()
            continue


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
