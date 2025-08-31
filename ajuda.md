# 📄 PDF Fácil — Guia de Uso

App simples: você envia **PDF/JPG/PNG**, organiza no grid (ordenar, girar, manter) e gera um **único PDF** com compressão opcional.

---

## 📂 Upload
- Tipos: **PDF, JPG, PNG**.
- Envie múltiplos de uma vez.
- **Limites de envio**:
  - **50 MB por arquivo** (config do servidor).
  - **75 MB por lote** (soma de arquivos); se passar, o app avisa e interrompe o fluxo do lote.

---

## 🔀 Ordenar / Selecionar
- **Manual** (ex.: `3,1,2`) ou **Automático** (Original/Nome/Tipo).
- Marque **Manter** para incluir no resultado.
- Setas **↑/↓** movem páginas individualmente.

---

## 🔄 Rotação
- 90/180/270° por página.
- O preview já reflete a rotação.

---

## 📉 Compressão
- **Global** (tudo) ou **individual** (por página).
- Perfis:
  - **Nenhuma**: mantém como está.
  - **Mínima**: rasteriza apenas páginas imagem-only (ganho com baixo custo de CPU).
  - **Média** / **Máxima**: reduções mais fortes; use quando precisar de arquivos pequenos.

---

## 📊 Estimativa (opcional)
- Mostra “antes → depois” estimado e o percentual de economia.
- **Guard-rails / Fallbacks**:
  - Se não houver ganho real, o app mantém o **original** daquela página/arquivo.
  - Resultado final **nunca fica maior** que a entrada.

---

## 🖼️ Previews e desempenho
- Previews são **cacheados** para poupar recursos:
  - Ao **girar** uma página, **apenas ela** é recalculada.
  - Ao **mudar ordem**, apenas as posições trocadas re-renderizam (o resto vem do cache).
  - Ao **alterar outras configs** (ex.: compressão), **previews não são recalculados**.
  - Ao **adicionar arquivos**, só os **novos** têm preview gerado.
- Previews usam **resolução reduzida** para não estourar memória em PDFs grandes.

---

## ✂️ Dividir / 📥 Download
- Use “Manter” para criar sub-conjuntos e gerar PDFs menores.
- Clique em **Gerar PDF** e baixe o arquivo final.

---

## 🔒 Dados
- Os arquivos **não são armazenados**: ficam só na sessão ativa. Ao encerrar, são descartados.
- Não há envio a terceiros.

---

## 📬 Suporte & Código
- Dúvidas/bugs: abra uma **Issue** no GitHub do projeto.

- Código aberto disponível em: [GitHub - Roman Brocki](https://github.com/romanbrocki/converte_une_pdf)  

---
