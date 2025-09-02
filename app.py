
# app.py — UI Streamlit (Unir/Reduzir + Dividir/Girar) com presets globais/individuais
from __future__ import annotations

from typing import List, Dict
import fitz  # PyMuPDF
import io

import streamlit as st

from app_helpers import (
    LEVELS, LABEL_TO_VAL, VAL_TO_LABEL,
    VAL_TO_LABEL_INDIV, LABEL_TO_VAL_INDIV,
    TOTAL_UPLOAD_CAP_MB, PREVIEW_PDF_DPI, 
    PREVIEW_BOX_W, PREVIEW_BOX_H,
    RATIO_BY_DENSITY, THUMB_W_BY_DENSITY,
    format_size, read_uploaded_as_bytes,
    notify, render_toasts,
    is_pdf, kind_of, format_pct,
    compute_sorted_order, move_up, move_down,
    reorder_page_state, thumb_into_box, thumb_key,
    get_thumb,
)

from pdf_ops import (
    estimate_pdf_size, estimate_image_pdf_size, estimate_pdf_page_size,
    image_to_pdf_bytes, compress_pdf, merge_items, merge_pages, split_pdf,
    RESAMPLE_LANCZOS,
)


st.set_page_config(page_title="Edição de PDFs e Imagens → PDF", page_icon="📄", layout="wide")
st.title("📄 PDF Fácil - Ferramentas para PDF")
st.caption("Edição de PDFs e Imagens com: União de arquivos, Conversão de imagens para PDF, Compressão, Rotação, Reordenação e Divisão.")

# Cache de miniaturas: (name, size, page, rot) -> PNG bytes
if "_thumb_cache" not in st.session_state:
    st.session_state._thumb_cache = {}

# Estado inicial
if "upload_key" not in st.session_state:
    st.session_state.upload_key = 0
if "order" not in st.session_state:
    st.session_state.order = []
if "compress" not in st.session_state:
    st.session_state.compress = {}  # idx -> none/min/med/max
if "last_global_ui" not in st.session_state:
    st.session_state.last_global_ui = "Nenhuma"


with st.expander("🧪 Interface Única", expanded=True):
    # 1) Upload + Limpar tudo (full-width, botão integrado no cabeçalho)
    with st.container(border=True):
        hdr_l, hdr_r = st.columns([0.8, 0.2])
        with hdr_l:
            st.markdown("**Arquivos (PDF/JPG/PNG)**")
            st.caption("Limites: 50MB por arquivo (somando máximo 75MB). Arraste e solte ou clique em “Browse files”.")
        with hdr_r:
            if st.button("Limpar tudo", use_container_width=True, key="btn_clear_all"):
                st.session_state.upload_key += 1
                for k in ("pages_flat","keep_map","rot_map","level_page",
                        "_unified_sig","prev_global_choice","last_global_ui",
                        "_thumb_cache", "_upload_bytes", "orig_order_map"):
                    st.session_state.pop(k, None)
                st.rerun()

        # Uploader ocupa 100% da largura do container
        up_uni = st.file_uploader(
            label="Arquivos",
            type=["pdf", "jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key=f"uploader_unified_{st.session_state.upload_key}",
            label_visibility="collapsed",
            help="Selecione vários arquivos (somando até 75MB). A ordem por página pode ser ajustada adiante."
        )


    if up_uni:
        # Valor global "inicial" para o flatten (usa o último global salvo)
        g_val_init = LABEL_TO_VAL.get(st.session_state.get("last_global_ui", "Nenhuma"), "none")    
        
        # 2) Assinatura e cache dos uploads (bytes por arquivo + limite de lote)
        #    Criamos estruturas de estado por PÁGINA:
        #    - pages_flat: [(file_idx, page_idx)]
        #    - keep_map[i]: bool
        #    - rot_map[i]: int (0/90/180/270)
        #    - level_page[i]: 'none'|'min'|'med'|'max'
        # Assinatura dos uploads (nome + tamanho) para detectar mudanças
        # --- Cache de bytes por upload (lido 1x por lote) ---
        # Observação: aqui não dependemos de files_sig ainda.
        # Se a lista de nomes mudou em relação ao último _unified_sig, recriamos o cache.
        _curr_names = [getattr(uf, "name", "") for uf in up_uni]
        _prev_sig = st.session_state.get("_unified_sig", None)
        _prev_names = [n for (n, _) in _prev_sig] if _prev_sig else None

        if ("_upload_bytes" not in st.session_state) or (_prev_names != _curr_names):
            st.session_state._upload_bytes = {}
            for fi, uf in enumerate(up_uni):
                try:
                    st.session_state._upload_bytes[fi] = read_uploaded_as_bytes(uf)
                except Exception:
                    st.session_state._upload_bytes[fi] = b""

        files_sig = []
        for fi, uf in enumerate(up_uni):
            try:
                size_approx = getattr(uf, "size", None)
                if size_approx is None:
                    # agora usamos os bytes já cacheados na sessão (_upload_bytes)
                    size_approx = len(st.session_state._upload_bytes[fi])
            except Exception:
                size_approx = None
            files_sig.append((getattr(uf, "name", ""), size_approx))
            # --- Limite global (soma dos arquivos) ---
            _total_bytes = sum([(s or 0) for _, s in files_sig])
            _total_mb = _total_bytes / (1024 * 1024)
            if _total_mb > TOTAL_UPLOAD_CAP_MB:
                st.error(
                    f"Tamanho total enviado ≈ {_total_mb:.1f} MB, que excede o limite de "
                    f"{TOTAL_UPLOAD_CAP_MB} MB por lote. "
                    "Envie em partes menores ou compacte antes."
                )
                st.stop()  # interrompe o restante da UI para este envio
        # 3) Flatten de páginas (todas as páginas de todos os uploads)
        if ("pages_flat" not in st.session_state) or (st.session_state.get("_unified_sig") != files_sig):
            st.session_state._unified_sig = files_sig
            st.session_state.pages_flat = []
            st.session_state.keep_map = []
            st.session_state.rot_map = []
            st.session_state.level_page = []
            st.session_state.orig_order_map = {}
            _arrival = 0
            # monta flatten
            for fi, uf in enumerate(up_uni):
                data = st.session_state._upload_bytes.get(fi, b"")
                if is_pdf(uf):
                    try:
                        doc = fitz.open("pdf", data)
                        for pi in range(doc.page_count):
                            st.session_state.pages_flat.append((fi, pi))
                            st.session_state.keep_map.append(True)
                            st.session_state.rot_map.append(0)
                            st.session_state.level_page.append(g_val_init)
                            st.session_state.orig_order_map[(fi, pi)] = _arrival; _arrival += 1
                        doc.close()
                    except Exception:
                        pass
                else:
                    st.session_state.pages_flat.append((fi, 0))
                    st.session_state.keep_map.append(True)
                    st.session_state.rot_map.append(0)
                    st.session_state.level_page.append(g_val_init)
                    st.session_state.orig_order_map[(fi, 0)] = _arrival; _arrival += 1

        # 4) Controles do grid (preview de todas as páginas)
        st.caption("Selecione, gire, mova e ajuste compressão por página. Se alterado, o Preset Global sobrepõe os individuais.")
        # =======================  ORDENAR / REORDENAR PÁGINAS  =======================
        with st.container(border=True):
            st.markdown("**Reordenar páginas**")
            c1, c2, c3, c4 = st.columns([0.45, 0.22, 0.22, 0.11])

            with c1:
                manual_str = st.text_input(
                    "Ordem manual (1-based)",
                    placeholder="Ex.: 3,5,1,2,4",
                    key="order_pages_manual",
                    help="Use índices separados por vírgula. Duplicados e fora do intervalo são ignorados. Itens faltantes serão completados na ordem atual."
                )

            with c2:
                sort_primary_pages = st.selectbox(
                    "Ordenar por",
                    ["Original", "Nome", "Tipo"],
                    index=0,
                    key="sort_pages_primary",
                    help="Critério automático (usado se a ordem manual estiver vazia ou inválida)."
                )

            with c3:
                sort_dir_pages = st.radio(
                    "Direção",
                    ["Crescente", "Decrescente"],
                    index=0,
                    horizontal=True,
                    key="sort_pages_dir"
                )

            with c4:
                apply_pages_sort = st.button("Aplicar", use_container_width=True, key="btn_apply_pages_sort")

            # ---------- LÓGICA ----------
            if apply_pages_sort:
                n = len(st.session_state.pages_flat)
                current_order = list(range(n))

                # 1) Tenta ordem manual (prioridade)
                new_order = None
                raw = (manual_str or "").strip()
                if raw:
                    seen = set()
                    parsed = []
                    for tok in raw.replace(" ", "").split(","):
                        if not tok:
                            continue
                        if tok.isdigit():
                            k = int(tok) - 1  # 1-based -> 0-based
                            if 0 <= k < n and k not in seen:
                                parsed.append(k)
                                seen.add(k)
                    # completa com os que faltaram na ordem atual
                    for k in current_order:
                        if k not in seen:
                            parsed.append(k)

                    if len(parsed) == n:
                        new_order = parsed
                    else:
                        st.warning("Nada aplicado: verifique o formato. Dica: use números 1-based separados por vírgula.")

                # 2) Se não houve ordem manual válida, usa ordenação automática
                if new_order is None:
                    reverse = (sort_dir_pages == "Decrescente")

                    # chaves por página (olhando o arquivo de origem da página)
                    def _page_key(idx: int):
                        fi, pi = st.session_state.pages_flat[idx]
                        uf = up_uni[fi]
                        if sort_primary_pages == "Original":
                            return st.session_state.orig_order_map.get((fi, pi), idx)
                        if sort_primary_pages == "Nome":
                            return (getattr(uf, "name", "") or "").lower()
                        if sort_primary_pages == "Tipo":
                            # 'pdf' ou 'image' (mesma lógica dos helpers)
                            from app_helpers import is_pdf
                            typ = "pdf" if is_pdf(uf) else "image"
                            return (typ, (getattr(uf, "name", "") or "").lower())
                        return idx

                    new_order = sorted(current_order, key=_page_key, reverse=reverse)

                # 3) Aplica a nova ordem às 4 listas de estado
                reorder_page_state(new_order)
                st.rerun()
            st.markdown("---")
            st.markdown("**Editar preview**")

            # Densidade (cards por linha) — init 1x na sessão
            if "ui_density" not in st.session_state:
                st.session_state.ui_density = 5  # padrão: 5 colunas

            st.selectbox(
                "Densidade (cards por linha)",
                options=[5, 4, 3],
                key="ui_density",                        
                help="5 (mais compacto) → 3 (mais confortável)",
            )

            # espelho opcional para leitura no restante do código
            st.session_state.density = st.session_state.ui_density
        # =====================  FIM ORDENAR / REORDENAR PÁGINAS  =====================
        
        cols = st.columns(st.session_state.density)
        for i, (fi, pi) in enumerate(st.session_state.pages_flat):
            uf = up_uni[fi]
            

            with cols[i % st.session_state.density]:
                # --- layout do card: imagem (esq) + controles (dir) ---
                left, right = st.columns(RATIO_BY_DENSITY[st.session_state.density], gap="small")

                with left:
                    # miniatura (mantém resolução do pixmap; só limitamos a largura)
                    # PREVIEW via CACHE (um único ponto de geração)
                    rot = st.session_state.rot_map[i]
                    thumb_png = get_thumb(uf, fi, pi, rot)

                    # Fixar largura de exibição para estabilidade do grid
                    st.image(thumb_png, width=THUMB_W_BY_DENSITY[st.session_state.density], use_container_width=False)

                    # Caption de 1 linha (trunca o nome para evitar quebra)
                    _name = getattr(uf, "name", "") or ""
                    _name = (_name if len(_name) <= 28 else _name[:25] + "…")
                    st.caption(f"{_name} · pág {pi+1} · rot {rot}°")


                with right:
                    # ordem ↑↓ no topo
                    up_col, down_col = st.columns(2)
                    with up_col:
                        st.button("↑", key=f"up_u_{i}", use_container_width=True, disabled=(i == 0))
                    with down_col:
                        st.button("↓", key=f"down_u_{i}", use_container_width=True,
                                disabled=(i == len(st.session_state.pages_flat) - 1))

                    # girar
                    if st.button("Girar ↻", key=f"rot_u_{i}", use_container_width=True):
                        old_rot = st.session_state.rot_map[i]
                        new_rot = {0: 90, 90: 180, 180: 270, 270: 0}[old_rot]
                        st.session_state.rot_map[i] = new_rot
                        # invalida somente a miniatura anterior desta página
                        try:
                            old_key = thumb_key(fi, pi, old_rot)
                            st.session_state._thumb_cache.pop(old_key, None)
                        except Exception:
                            pass
                        st.rerun()

                    # --- Compressão individual (init 1x por key; sem index em todo rerun)
                    # --- Compressão individual (init 1x por key; opções conforme densidade)
                    select_key = f"lvl_u_{i}_{st.session_state.get('ui_rev', 0)}"

                    # Em densidade 3/4 mostramos rótulos longos; em 5 usamos abreviações
                    use_long = st.session_state.density in (3, 4)

                    if use_long:
                        options_indiv = ["Nenhuma", "Mínima", "Média", "Máxima"]
                    else:
                        # usa os rótulos curtos padronizados no helpers: ["Zero","Mín","Méd","Máx"]
                        options_indiv = list(VAL_TO_LABEL_INDIV.values())

                    # Valor interno atual desta página
                    cur_internal = st.session_state.level_page[i]  # "none"|"min"|"med"|"max"
                    cur_label = (VAL_TO_LABEL[cur_internal] if use_long else VAL_TO_LABEL_INDIV[cur_internal])

                    # Inicializa 1x OU realinha quando a densidade muda (se o valor salvo não existir nas novas opções)
                    if (select_key not in st.session_state) or (st.session_state[select_key] not in options_indiv):
                        st.session_state[select_key] = cur_label

                    lvl_lbl = st.selectbox(
                        "Compressão",
                        options_indiv,
                        key=select_key,   # sem 'index' aqui (evita o bug dos dois cliques)
                    )

                    # Atualiza o nível interno conforme o conjunto em uso
                    if use_long:
                        st.session_state.level_page[i] = LABEL_TO_VAL[lvl_lbl]
                    else:
                        st.session_state.level_page[i] = LABEL_TO_VAL_INDIV[lvl_lbl]

                    # Caption sempre com nome completo
                    nivel_val = st.session_state.level_page[i]  # ex.: "med"
                    st.caption(f"Compressão {VAL_TO_LABEL[nivel_val]}")
                    # manter / remover            
                    keep = st.checkbox("Manter", value=st.session_state.keep_map[i], key=f"keep_u_{i}")
                    st.session_state.keep_map[i] = keep

                # mover implementa swap + rerun (fora do 'right' pra rodar sempre que clicar)
                if st.session_state.get(f"up_u_{i}"):
                    n = len(st.session_state.pages_flat)
                    if i > 0:
                        current = list(range(n))
                        current[i - 1], current[i] = current[i], current[i - 1]
                        reorder_page_state(current)
                        st.rerun()

                if st.session_state.get(f"down_u_{i}"):
                    n = len(st.session_state.pages_flat)
                    if i < n - 1:
                        current = list(range(n))
                        current[i + 1], current[i] = current[i], current[i + 1]
                        reorder_page_state(current)
                        st.rerun()



        # badge de personalizado — compara com o global atual salvo na sessão
        g_val_badge = LABEL_TO_VAL.get(st.session_state.get("last_global_ui", "Nenhuma"), "none")
        lv = set(st.session_state.level_page) if st.session_state.level_page else {"none"}
        if (g_val_badge != "none" and (lv != {g_val_badge})) or (g_val_badge == "none" and len(lv) > 1):
            st.caption(":orange[Perfil: **Personalizado**]")


        st.divider()
        # 5) Rodapé refeito: Preset Global centralizado (linha inteira),
        #    depois 2x2: (esq) Compressão + Estimar | (dir) Nome do PDF + Gerar

        # ── Linha 1: título centralizado ─────────────────────────────────────────────
        sp_l, sp_c, sp_r = st.columns([0.25, 0.5, 0.25])
        with sp_c:
            st.markdown("<h2 style='text-align: center;'>Preset Global</h2>", unsafe_allow_html=True)


        # Divergência entre individuais e o global atual (para exibir 'Personalizado')
        levels_now   = st.session_state.level_page if "level_page" in st.session_state else []
        g_label_prev = st.session_state.get("last_global_ui", "Nenhuma")
        g_val_prev   = LABEL_TO_VAL.get(g_label_prev, "none")
        divergent    = False
        if levels_now:
            s = set(levels_now)
            divergent = (len(s) > 1) or (len(s) == 1 and next(iter(s)) != g_val_prev)

        base_opts = ["Nenhuma", "Mínima", "Média", "Máxima"]
        opts = base_opts + (["Personalizado"] if divergent else [])
        idx  = (opts.index("Personalizado") if divergent else opts.index(g_label_prev))

        st.divider()

        # ── Linha 2: duas colunas ────────────────────────────────────────────────────
        col_esq, col_dir = st.columns(2)

        with col_esq:
            # (topo esquerdo) seletor de Compressão (global)
            choice = st.selectbox("Compressão", opts, index=idx, key="unified_global_level")
            g_label = g_label_prev if (choice == "Personalizado") else choice
            g_val = LABEL_TO_VAL[g_label]

            # Propaga para todas as páginas (inclusive quando seleciona 'Nenhuma')
            if g_label != st.session_state.get("last_global_ui", "Nenhuma"):
                if "level_page" in st.session_state and st.session_state.level_page:
                    st.session_state.level_page = [g_val] * len(st.session_state.level_page)
                st.session_state.last_global_ui = g_label
                st.session_state.ui_rev = st.session_state.get("ui_rev", 0) + 1
                st.rerun()

            # (abaixo esquerdo) botão Estimar
            if st.button("Estimar tamanho final", use_container_width=True):
                total_before = total_after = 0
                for (fi, pi), keep, lvl in zip(
                    st.session_state.pages_flat,
                    st.session_state.keep_map,
                    st.session_state.level_page
                ):
                    if not keep:
                        continue
                    uf = up_uni[fi]
                    data = st.session_state._upload_bytes.get(fi, b"")
                    if is_pdf(uf):
                        total_before += estimate_pdf_page_size(data, pi, "none")
                        total_after  += estimate_pdf_page_size(data, pi, lvl)
                    else:
                        total_before += estimate_image_pdf_size(data, "none")
                        total_after  += estimate_image_pdf_size(data, lvl)

                st.session_state._last_est_before = total_before
                st.session_state._last_est_after  = total_after
                pct = format_pct(total_before, total_after)
                if total_after >= total_before:
                    notify("global", f"Nenhum ganho estimado: {format_size(total_before)} → {format_size(total_after)} (0%).", icon="⚠️")
                else:
                    notify("global", f"Total (estimado): {format_size(total_before)} → {format_size(total_after)}  ({pct})", icon="📦")
                render_toasts(duration=5.0)

        with col_dir:
            # (topo direito) Nome do PDF
            outname = st.text_input("Nome do PDF", value="saida.pdf", key="unified_outname")
            if not outname.lower().endswith(".pdf"):
                outname += ".pdf"

            # (abaixo direito) Gerar PDF
            if st.button("Gerar PDF", use_container_width=True):
                seq, rots = [], []
                for i, (fi, pi) in enumerate(st.session_state.pages_flat):
                    if not st.session_state.keep_map[i]:
                        continue
                    uf = up_uni[fi]
                    data = st.session_state._upload_bytes.get(fi, b"")
                    kind = "pdf" if is_pdf(uf) else "image"
                    lvl  = st.session_state.level_page[i]

                    # guard-rail por página: se não reduzir, força 'none' nesta página
                    try:
                        if kind == "pdf" and lvl != "none":
                            b0 = estimate_pdf_page_size(data, pi, "none")
                            b1 = estimate_pdf_page_size(data, pi, lvl)
                            if b1 >= b0:
                                lvl = "none"
                        if kind == "image" and lvl != "none":
                            b0 = estimate_image_pdf_size(data, "none")
                            b1 = estimate_image_pdf_size(data, lvl)
                            if b1 >= b0:
                                lvl = "none"
                    except Exception:
                        pass

                    seq.append((uf.name, data, kind, pi, lvl))
                    rots.append(st.session_state.rot_map[i])

                try:
                    final_bytes = merge_pages(seq, rots)
                    st.success("PDF gerado!")
                    st.download_button("⬇️ Baixar PDF", data=final_bytes, file_name=outname,
                                    mime="application/pdf", use_container_width=True)
                except Exception as e:
                    st.error(f"Erro ao gerar PDF: {e}")


with st.expander("ℹ️ Ajuda", expanded=False):
    with open("ajuda.md", "r", encoding="utf-8") as f:
        st.markdown(f.read(), unsafe_allow_html=False)

