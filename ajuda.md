```markdown
# 📄 PDF Fácil — Guia de Uso

Este app foi feito para ser simples e direto: você sobe arquivos e define o que quer fazer.  
Aqui vai o passo a passo das principais funções:

---

## 🗂 Upload de Arquivos
- Suporta **PDF, JPG e PNG**.  
- Pode enviar múltiplos arquivos de uma vez.  
- Cada página (ou imagem) vira um “card” no grid, onde você controla individualmente.

---

## 🔀 Reordenar
- **Manual**: digite a ordem (ex.: `3,1,2`).  
- **Automático**: ordenar por *Nome* ou *Tipo*.  
- Também dá pra mover páginas com os botões ↑ e ↓.

---

## 🔄 Rotação
- Cada página pode ser girada em 90/180/270°.  
- O preview já mostra a rotação antes de gerar o PDF final.

---

## 📉 Compressão
- **Global (todas as páginas)** ou **individual (cada página)**.  
- Perfis disponíveis:
  - Nenhuma: mantém como está.
  - Mínima: só rasteriza páginas puramente imagem.
  - Média: rasteriza todas as páginas com qualidade intermediária.
  - Máxima: redução mais agressiva, mantendo leitura confortável.

---

## 📊 Estimativa de Tamanho
- Antes de gerar o PDF final, você pode pedir uma **estimativa de tamanho total**.  
- O app calcula o “antes e depois” e já mostra o percentual de economia esperado.  

---

## 🛡 Guard-rails / Fallbacks
- Se uma compressão não trouxer ganho real, o app **mantém o arquivo ou página original**.  
- Ou seja, **nunca vai sair um PDF maior** do que o fornecido.  
- Na união de arquivos, cada item passa pela compressão pedida, mas é garantido que não vai ficar maior.  
- Esse cuidado evita perder tempo e garante que o resultado sempre é igual ou menor.

---

## ✂️ Dividir
- Use as caixas “Manter” para escolher quais páginas entram no PDF final.  
- Dá pra criar rapidamente versões menores de um arquivo grande.

---

## 🧩 Unir
- Se você mandar múltiplos arquivos (PDFs e imagens), tudo é convertido e unido em um único PDF.  
- A ordem segue o grid — ou seja, você tem controle total.

---

## 📥 Download
- Quando estiver satisfeito, clique em **Gerar PDF**.  
- O app monta o arquivo final, mostra aviso de sucesso e libera o botão de download.

---

## 💡 Dicas
- Limite atual: ~200MB por arquivo no upload.  
- Imagens PNG com fundo transparente são preservadas como tal nas miniaturas.  
- Use compressão mínima/média para relatórios; máxima quando quiser só reduzir peso para envio.
- Código aberto disponível em: [GitHub - Roman Brocki](https://github.com/romanbrocki/converte_une_pdf)  

---
