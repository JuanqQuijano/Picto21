"""Entrena value iteration y Q-Learning, compara contra la heuristica y prueba el validador.

Uso (desde codigo/ia_models):
    python entrenar_hito2.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from catalogo import cargar_catalogo, cargar_escenarios
from consejero import ConsejeroAleatorio, ConsejeroHeuristico, ConsejeroTabular
from experimento_a import imprimir_metricas, simular
from mdp import ModeloMDP, politica_q, q_learning, serializar, value_iteration
from validador import ValidadorSemantico

RUTA_POLITICA = Path(__file__).resolve().parents[2] / "datos" / "politica_q.json"


def evaluar_validador(catalogo) -> dict:
    v = ValidadorSemantico(catalogo)
    gato = catalogo.cartas["gato"]
    perro = catalogo.cartas["perro"]
    casos = [
        ("gato", gato, True, "exacto"),
        ("MININO", gato, True, "exacto"),
        ("el gato", gato, True, "vacias"),
        ("cato", gato, True, "typo"),
        ("gatito", gato, True, "embedding"),
        ("perro", gato, False, "ninguno"),
        ("el que maulla", gato, True, "embedding"),
        ("chucho", perro, True, "exacto"),
        ("perrito", perro, True, "embedding"),
        ("gato", perro, False, "ninguno"),
    ]
    ok = 0
    detalle = []
    for texto, carta, esperado, _metodo in casos:
        ver = v.validar(carta, texto)
        bien = ver.ok == esperado
        ok += int(bien)
        detalle.append(
            f"  [{'ok' if bien else 'FAIL'}] '{texto}' vs {carta.palabra}: "
            f"ok={ver.ok} metodo={ver.metodo} sim={ver.similitud:.2f} palabra={ver.palabra}"
        )
    return {"aciertos": ok, "total": len(casos), "detalle": detalle}


def comparar(catalogo, escenarios, politica, n=400, semilla=7):
    ruta_tmp = Path(__file__).resolve().parents[2] / "datos" / "_tmp_politica.json"
    ruta_tmp.write_text(json.dumps(politica), encoding="utf-8")
    q = ConsejeroTabular.desde_archivo(ruta_tmp, "q")
    vi = ConsejeroTabular.desde_archivo(ruta_tmp, "vi")
    ruta_tmp.unlink(missing_ok=True)

    def run(nombre, consejero):
        # simular() construye el consejero internamente; aqui replicamos con el objeto dado
        from experimento_a import JugadorSimulado, TutorHeuristico, jugar_ronda
        from juego import Resultado, nueva_partida

        esc = escenarios["escenarios"]["mixto"]
        rng = random.Random(semilla)
        jugador = JugadorSimulado(0.6, 0.9, rng)
        tutor = TutorHeuristico()
        res = {r: 0 for r in Resultado}
        for i in range(n):
            estado = nueva_partida(esc, catalogo, semilla=semilla * 1000 + i, nivel=2)
            reg = jugar_ronda(estado, catalogo, esc, consejero, tutor, jugador, rng)
            res[reg.estado.resultado] += 1
        return {
            "victoria": res[Resultado.GANA] / n,
            "empate": res[Resultado.EMPATE] / n,
            "derrota": res[Resultado.PIERDE] / n,
            "se_paso": res[Resultado.SE_PASO] / n,
        }

    return {
        "heuristico": run("h", ConsejeroHeuristico()),
        "value_iteration": run("vi", vi),
        "q_learning": run("q", q),
        "aleatorio": run("a", ConsejeroAleatorio(random.Random(semilla))),
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    catalogo = cargar_catalogo()
    escenarios = cargar_escenarios()
    modelo = ModeloMDP(catalogo)

    print("=== Value iteration ===")
    V, pi_vi = value_iteration(modelo)
    print(f"  Estados con politica: {len(pi_vi)}")

    print("=== Q-Learning (40k episodios) ===")
    Q, curva = q_learning(modelo, episodios=40000)
    pi_q = politica_q(Q)
    print(f"  Curva (recompensa media suavizada): {curva}")

    print("=== Validador semantico ===")
    val = evaluar_validador(catalogo)
    print(f"  {val['aciertos']}/{val['total']} casos")
    print("\n".join(val["detalle"]))

    payload = serializar(V, pi_vi, Q, pi_q, curva, {})
    print("=== Comparacion en partidas simuladas (mixto, 400) ===")
    metricas = comparar(catalogo, escenarios, payload, n=400)
    payload["metricas"] = metricas
    for nombre, m in metricas.items():
        print(f"  {nombre:16} victoria={m['victoria']:.1%}  empate={m['empate']:.1%}  "
              f"derrota={m['derrota']:.1%}  se_paso={m['se_paso']:.1%}")

    RUTA_POLITICA.parent.mkdir(parents=True, exist_ok=True)
    RUTA_POLITICA.write_text(json.dumps(payload), encoding="utf-8")
    print(f"\nPolitica guardada en {RUTA_POLITICA}")


if __name__ == "__main__":
    main()
