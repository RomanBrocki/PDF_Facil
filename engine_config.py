"""
engine_config.py

Define presets de compressão alinhados ao app original.
`LEVELS` mapeia: 'none'|'min'|'med'|'max' -> {mode, dpi, jpg_q}
"""

# engine/engine_config.py
from __future__ import annotations
from typing import Dict

# Mesmos níveis do app original (sem depender de Streamlit)
LEVELS: Dict[str, dict] = {
    "none": {"mode": "none",  "dpi": None, "jpg_q": None},
    # "smart": rasteriza só páginas imagem-only (ganho sem perder vetores/texto)
    "min":  {"mode": "smart", "dpi": 200,  "jpg_q": 85},
    # "all": rasteriza todas as páginas (maior redução em PDFs “pesados”)
    "med":  {"mode": "all",   "dpi": 150,  "jpg_q": 70},
    "max":  {"mode": "all",   "dpi": 110,  "jpg_q": 50},
}
