"""Barras apiladas acierta / se equivoca / no sabe por modo y corrida, a partir de los CSV de evaluar.py.

    uv run grafico.py

Lee resultados_base.csv, resultados_sin_null.csv y resultados_web.csv (omite el que falte) y escribe grafico.png.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

AQUI = Path(__file__).parent
CORRIDAS = [("base", "resultados_base.csv"), ("sin null", "resultados_sin_null.csv"), ("base", "resultados_web.csv")]
COLORES = {"acierta": "#2e7d32", "se equivoca": "#c62828", "no sabe": "#9e9e9e"}

if __name__ == "__main__":
    filas = []
    for corrida, archivo in CORRIDAS:
        if not (AQUI / archivo).exists():
            continue
        d = pd.read_csv(AQUI / archivo)
        for modo, g in d.groupby("modo", sort=False):
            conteo = g.resultado.value_counts()
            filas.append({"barra": f"{modo}\n({corrida})", **{k: int(conteo.get(k, 0)) for k in COLORES}})
    t = pd.DataFrame(filas).set_index("barra")
    t = t.loc[sorted(t.index, key=lambda b: (["memoria", "web", "mcp"].index(b.split("\n")[0]), "sin null" in b))]

    fig, ax = plt.subplots(figsize=(8, 5))
    abajo = [0] * len(t)
    for cat, color in COLORES.items():
        barras = ax.bar(t.index, t[cat], bottom=abajo, color=color, label=cat, edgecolor="white")
        for b, v, a in zip(barras, t[cat], abajo):
            if v:
                ax.text(b.get_x() + b.get_width() / 2, a + v / 2, str(v), ha="center", va="center",
                        color="white", fontweight="bold")
        abajo = [a + v for a, v in zip(abajo, t[cat])]
    ax.set_ylabel("Número de preguntas (de 10)")
    ax.set_xlabel("Modo (corrida)")
    ax.set_ylim(0, 10.5)
    ax.set_title("¿Acierta Claude Haiku cifras oficiales del BCRP?\nResultados por modo y corrida, 10 preguntas")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, frameon=False)
    fig.tight_layout()
    fig.savefig(AQUI / "grafico.png", dpi=150)
    print(t.to_string())
