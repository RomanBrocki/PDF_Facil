# 📄 PDF Fácil

Aplicação em **Python/Streamlit** para lidar com PDFs e imagens (JPG/PNG) com foco em simplicidade e eficiência.  
A ideia é centralizar numa só interface o que realmente importa no dia a dia: **unir arquivos, dividir, girar páginas, reordenar e comprimir** — sem complicação.

Criado por **Roman Brocki** em Python, com suporte do **ChatGPT-5** no desenvolvimento.

---

## 🚀 Funcionalidades

- **Unir PDFs e imagens** em um único PDF.
- **Converter JPG/PNG → PDF** (com ou sem compressão).
- **Comprimir PDFs** em 4 níveis:
  - **Nenhuma**: mantém como está.  
  - **Mínima**: comprime imagens de páginas que já eram imagem (ex.: PDFs escaneados).  
  - **Média**: converte todas as páginas em imagem para reduzir o tamanho.  
  - **Máxima**: mesma lógica da Média, mas com compressão mais forte (mantendo legibilidade).
- **Densidade do grid**: escolha entre 5, 4 ou 3 colunas no preview.  
  - Em **5 colunas** os seletores individuais usam abreviações (**Zero, Mín, Méd, Máx**) para caber no layout, e logo abaixo aparece o nome completo (**Nenhuma, Mínima, Média, Máxima**).  
  - Em **3 ou 4 colunas** eles exibem diretamente os nomes completos (**Nenhuma, Mínima, Média, Máxima**).  
  - Essa troca é automática e só afeta a interface; o processamento interno é sempre consistente.
- **Reordenar páginas** (manual ou por critérios: Original, Nome ou Tipo).
- **Girar páginas** (90/180/270°).
- **Dividir** (selecionar páginas específicas para um novo PDF).
- **Estimativa de tamanho** (antes → depois) para prever ganho de compressão.
- **Guard-rails**: se a compressão não gerar ganho real, a página/arquivo é mantida **sem alteração** (o resultado final **não fica maior** do que a entrada).

---

## 🔒 Proteção de Dados

- **Nenhum dado é armazenado** pelo app.  
- Os arquivos permanecem apenas na sessão ativa do navegador/servidor; ao encerrar a sessão, são descartados.
- Não há envio para terceiros nem persistência em banco de dados.

---

## ⚙️ Estrutura do Projeto

- **`app.py`** — interface **Streamlit** (upload, grid de páginas, ações, download).  
- **`app_helpers.py`** — utilitários de UI e estado (presets de compressão, formatação, notificações, ordenação, thumbnails/cache, etc.).  
- **`pdf_ops.py`** — **motor** (estimativas, compressão real, conversão de página em imagem *(rasterização)*, união, divisão, rotação). Tudo puro em bytes, sem Streamlit.
- **`requirements.txt`** — dependências mínimas (streamlit, PyMuPDF, pypdf, img2pdf, Pillow).  
- **`ajuda.md`** — manual curto exibido no app (renderizado via `st.markdown` dentro de um expander).  
- **`.streamlit/config.toml`** — configurações do servidor (ex.: limite de upload).

---

## 🧠 Desempenho & Previews

- **Previews são cacheados** para poupar CPU/RAM:
  - Ao **girar** uma página, **apenas ela** regenera o preview.
  - Ao **alterar ordem**, só as posições afetadas atualizam.
  - Ao **adicionar arquivos**, só os **novos** geram preview.
  - Alterar outras configs (ex.: compressão) **não** recalcula previews.
- Previews usam **resolução reduzida** (thumbnails) para evitar estouro de memória em PDFs grandes.

---

## ⛳ Limites de Upload

- **50 MB por arquivo** (configuração do servidor).  
- **75 MB por lote** (soma dos arquivos enviados de uma vez; checado no app).  
Se o total exceder 75 MB, o app **interrompe o fluxo do lote** e orienta a dividir o envio.

> **Streamlit Cloud / Local** — o limite por arquivo é definido em `.streamlit/config.toml`:
>
> ```toml
> [server]
> maxUploadSize = 50
> ```

---

## ▶️ Como rodar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```