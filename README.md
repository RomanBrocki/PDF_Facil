# 📄 PDF Fàcil

Aplicação feita em **Python/Streamlit** para lidar com PDFs e imagens (JPG/PNG), com foco em simplicidade e eficiência.  
A ideia é centralizar em uma só interface tudo que eu realmente preciso no dia a dia: **unir arquivos, dividir, girar páginas, reordenar e comprimir** — sem complicação.

Criado por **Roman Brocki** em Python, com suporte do **ChatGPT-5** no desenvolvimento.

---

## 🚀 Funcionalidades

- **Unir PDFs e imagens** em um único PDF.
- **Converter JPG/PNG para PDF** (com ou sem compressão).
- **Comprimir PDFs** em diferentes níveis:
  - Nenhuma
  - Mínima (só rasteriza páginas imagem-only)
  - Média
  - Máxima (downscale forte, ainda preservando usabilidade)
- **Reordenar páginas**: manual ou por critérios (nome, tipo, ordem original).
- **Girar páginas**: 90/180/270°.
- **Dividir**: selecionar páginas específicas para gerar um novo PDF.
- **Estimativa de tamanho**: antes de gerar, já mostra o “antes e depois” esperado.
- **Guard-rails**: se a compressão não trouxer ganho real, a página (ou PDF inteiro) é mantida sem alteração.

---

## 🔒 Proteção de Dados

- **Nenhum dado enviado é armazenado**.  
- Todos os arquivos ficam apenas na sessão ativa do navegador/servidor enquanto o app está rodando.  
- Ao fechar a aba ou encerrar a sessão, os arquivos são descartados.  
- Não existe persistência em banco de dados ou envio para terceiros.  
- Ou seja: você mantém controle total dos seus documentos.

---

## ⚙️ Estrutura do Projeto

- **`app.py`** — a interface no **Streamlit**. É o coração do app: renderiza a UI, organiza uploads, previews, botões e chama as funções dos outros módulos.
- **`app_helpers.py`** — utilitários para a interface.  
  Inclui presets de compressão, formatação de tamanhos, helpers de upload, notificações e manipulação de estado de páginas (ordenar, mover, thumbnails, etc).
- **`pdf_ops.py`** — o “motor” por trás de tudo.  
  Aqui ficam as funções pesadas: estimativas de tamanho, compressão real, rasterização de páginas, união, divisão e rotação. Tudo puro em bytes, sem Streamlit.
- **`requirements.txt`** — dependências mínimas necessárias para rodar no Streamlit Cloud (streamlit, PyMuPDF, pypdf, img2pdf, Pillow).

---

## ▶️ Como rodar localmente

```bash
pip install -r requirements.txt
streamlit run app.py

