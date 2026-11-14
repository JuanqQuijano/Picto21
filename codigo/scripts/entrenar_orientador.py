"""Entrena la red neuronal del agente orientador y guarda modelo + metricas.

Uso:
    cd codigo/ia_models
    python entrenar_orientador.py

Genera:
    codigo/ia_models/modelos/orientador.npz
    codigo/ia_models/modelos/metricas_orientador.json

El dataset se construye por imitacion de experto (ver `orientador.Orientador._dataset`):
las pistas siguen las ramas reales del baseline ID3 sobre los escenarios del juego y las
decisiones de pedir/parar/mejora siguen la politica tabular del Hito 2 (datos/politica_q.json).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ia_models"))

from catalogo import cargar_catalogo
from orientador import CLASES, RUTA_METRICAS, RUTA_MODELO, Orientador


def _tabla_matriz(matriz, clases) -> str:
    ancho = max(len(c) for c in clases) + 2
    encabezado = " " * ancho + "".join(f"{c:>10}" for c in clases)
    filas = [encabezado]
    for nombre, fila in zip(clases, matriz):
        filas.append(f"{nombre:>{ancho}}" + "".join(f"{v:>10d}" for v in fila))
    return "\n".join(filas)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    catalogo = cargar_catalogo()
    orientador = Orientador(catalogo, forzar_entrenamiento=True)
    m = orientador.metricas
    historial = m.get("historial", {})
    epocas = historial.get("epoca", [])
    mejor = (
        max(range(len(epocas)), key=lambda i: historial["exactitud_val"][i])
        if epocas else None
    )

    print("=== Orientador neuronal de Picto21 ===")
    print(f"Etiquetas del experto     : {m.get('origen_etiquetas')}")
    print(f"Arquitectura              : {m.get('arquitectura')} (entrada-ocultas-salida)")
    print(f"Clases                    : {', '.join(CLASES)}")
    print(f"Muestras totales          : {m['muestras']['total']} "
          f"(reconocer {m['muestras']['reconocer']}, decidir {m['muestras']['decidir']})")
    print("Muestras por clase        : " + ", ".join(
        f"{c}={m['muestras']['por_clase'][c]}" for c in CLASES
    ))
    print(f"Validacion                : {m['n_validacion']} muestras estratificadas")
    print(f"Exactitud de validacion   : {m['exactitud']:.2%}")
    print(f"Macro-F1                  : {m['macro_f1']:.4f}")
    if mejor is not None:
        print(f"Mejor epoca               : {epocas[mejor]} de {epocas[-1]} "
              f"(acc_val={historial['exactitud_val'][mejor]:.4f})")
    print("\nMatriz de confusion (fila = real, columna = predicha)")
    print(_tabla_matriz(m["matriz"], CLASES))
    print("\nMetricas por clase")
    print(f"  {'clase':<12}{'precision':>10}{'recall':>10}{'f1':>10}{'soporte':>10}")
    for clase, v in m["por_clase"].items():
        print(f"  {clase:<12}{v['precision']:>10.4f}{v['recall']:>10.4f}"
              f"{v['f1']:>10.4f}{v['soporte']:>10d}")
    print(f"\nModelo guardado en        : {RUTA_MODELO}")
    print(f"Metricas guardadas en     : {RUTA_METRICAS}")


if __name__ == "__main__":
    main()
