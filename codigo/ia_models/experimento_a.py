"""Experimento A (Hito 1): simulacion en consola del agente guiando una partida de Picto21.

Uso:
    python experimento_a.py --interactivo --escenario animales
    python experimento_a.py --simular 1000 --p 0.6 --escenario mixto
    python experimento_a.py --barrido 500 --escenario mixto
    python experimento_a.py --arbol --escenario animales
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from catalogo import (
    Carta,
    Catalogo,
    cargar_catalogo,
    cargar_escenarios,
    es_valida,
    letras_elegibles,
    normalizar,
    valor,
)
from consejero import (
    Consejero,
    ConsejeroAleatorio,
    ConsejeroHeuristico,
    Sugerencia,
    TutorHeuristico,
    leccion_sinonimo,
)
from id3_pistas import Pista, arbol_id3, frase_pictos, mejor_pista
from juego import (
    PEDIR,
    PLANTARSE,
    USAR_MEJORA,
    Accion,
    EstadoJuego,
    Fase,
    Resultado,
    acciones_validas,
    cambiar_nivel,
    nueva_partida,
    registrar_pista,
    responder,
    transicion,
)

NOMBRE_NIVEL = {1: "elegir entre 3 opciones", 2: "ordenar letras", 3: "escribir en teclado"}


# --------------------------------------------------------------------------- jugadores

class Jugador:
    def responder(self, carta: Carta, nivel: int, opciones: List[str], pistas: List[Pista]) -> str:
        raise NotImplementedError

    def aceptar_sinonimo(self, palabra: str) -> bool:
        raise NotImplementedError

    def decidir(self, estado: EstadoJuego, sugerencia: Optional[Sugerencia]) -> Accion:
        raise NotImplementedError


class JugadorConsola(Jugador):
    def responder(self, carta, nivel, opciones, pistas):
        if nivel == 1:
            for i, o in enumerate(opciones, 1):
                print(f"     {i}) {o.upper()}")
            r = input("  Tu respuesta (numero o palabra): ").strip()
            if r.isdigit() and 1 <= int(r) <= len(opciones):
                return opciones[int(r) - 1]
            return r
        if nivel == 2:
            letras = letras_elegibles(carta)
            random.shuffle(letras)
            print(f"  Fichas: {'  '.join(letras)}")
        return input("  Escribe la palabra: ")

    def aceptar_sinonimo(self, palabra):
        return input(f"  Usar {palabra.upper()}? (s/n): ").strip().lower().startswith("s")

    def decidir(self, estado, sugerencia):
        validas = acciones_validas(estado)
        menu = {"1": PEDIR, "2": PLANTARSE, "3": USAR_MEJORA}
        texto = {"1": "Pedir carta", "2": "Plantarse", "3": f"Usar mejora ({estado.mejora_disponible})"}
        for k, a in menu.items():
            if a in validas:
                print(f"     {k}) {texto[k]}")
        while True:
            r = input("  Que haces?: ").strip()
            if r in menu and menu[r] in validas:
                return menu[r]


class JugadorSimulado(Jugador):
    """Jugador con probabilidad base `p` de reconocer la carta en cada intento.

    La probabilidad sube con las ayudas: niveles mas faciles y cada pista mostrada.
    `sigue` es la probabilidad de aceptar el consejo del agente.
    """

    BONUS_NIVEL = {1: 0.25, 2: 0.10, 3: 0.0}
    BONUS_PISTA = 0.15

    def __init__(self, p: float, sigue: float, rng: random.Random):
        self.p, self.sigue, self.rng = p, sigue, rng

    def responder(self, carta, nivel, opciones, pistas):
        prob = min(0.98, self.p + self.BONUS_NIVEL[nivel] + self.BONUS_PISTA * len(pistas))
        if self.rng.random() < prob:
            return self.rng.choice(carta.palabras_validas)
        return "???"

    def aceptar_sinonimo(self, palabra):
        return self.rng.random() < self.sigue

    def decidir(self, estado, sugerencia):
        if sugerencia and self.rng.random() < self.sigue:
            return sugerencia.accion
        return self.rng.choice(acciones_validas(estado))


# --------------------------------------------------------------------------- partida

@dataclass
class Registro:
    estado: EstadoJuego
    sinonimos_sugeridos: int = 0
    sinonimos_aceptados: int = 0
    log: List[str] = field(default_factory=list)


def opciones_nivel1(carta: Carta, candidatos: List[Carta], rng: random.Random) -> List[str]:
    distractores = [c.palabra for c in candidatos if c.id != carta.id]
    rng.shuffle(distractores)
    opciones = [carta.palabra, *distractores[:2]]
    rng.shuffle(opciones)
    return opciones


def jugar_ronda(
    estado: EstadoJuego,
    catalogo: Catalogo,
    escenario: dict,
    consejero: Consejero,
    tutor: TutorHeuristico,
    jugador: Jugador,
    rng: random.Random,
    verbose: bool = False,
) -> Registro:
    reg = Registro(estado)
    candidatos = [catalogo.cartas[i] for i in dict.fromkeys(escenario["mazo"])]
    say = print if verbose else (lambda *a, **k: None)

    say(f"\n  Crupier muestra: {catalogo.cartas[estado.carta_visible_crupier].emoji} "
        f"{catalogo.cartas[estado.carta_visible_crupier].palabra.upper()} "
        f"({catalogo.cartas[estado.carta_visible_crupier].valor})")
    if estado.mejora_disponible:
        say(f"  Tu carta de mejora: {estado.mejora_disponible}")

    pistas: List[Pista] = []
    opciones: List[str] = []
    ultima = None
    while estado.fase != Fase.FIN:
        if estado.fase == Fase.RECONOCER:
            carta = catalogo.cartas[estado.carta_actual]
            if estado.intentos == 0:
                pistas = []
                opciones = opciones_nivel1(carta, candidatos, rng)
                say(f"\n  Agente: [❓ QUE] + [ES] + [{carta.emoji}]   "
                    f"(nivel {estado.nivel_ayuda}: {NOMBRE_NIVEL[estado.nivel_ayuda]})")
            r = jugador.responder(carta, estado.nivel_ayuda, opciones, pistas)
            coincide = es_valida(carta, r)
            primer_intento = estado.intentos == 0
            reveladas_antes = estado.cartas_reveladas

            if coincide:
                dicha = normalizar(coincide)
                ultima = (carta, dicha, estado.suma_jugador, estado.mejora_activa)
                estado = transicion(estado, responder(dicha), catalogo)
                say(f"  Agente: [⭐ MUY BIEN] {dicha.upper()} vale {valor(dicha)}. "
                    f"Suma: {estado.suma_jugador}")
            else:
                suma_antes = estado.suma_jugador
                mejora = estado.mejora_activa
                estado = transicion(estado, responder(r), catalogo)
                if estado.cartas_reveladas > reveladas_antes:
                    ultima = (carta, normalizar(carta.palabra), suma_antes, mejora)
                    say(f"  Agente: [🤝 AYUDA] Es {carta.palabra.upper()} ({carta.valor}). "
                        f"Suma: {estado.suma_jugador}")
                else:
                    pista = mejor_pista(carta, candidatos, estado.pistas_usadas, catalogo)
                    if pista:
                        estado = registrar_pista(estado, pista.atributo)
                        pistas.append(pista)
                        say(f"  Agente: [🔁 OTRA VEZ] Pista: {frase_pictos(pistas)}  "
                            f"(IG={pista.ganancia:.2f} bits, candidatos {pista.candidatos_antes}"
                            f"->{pista.candidatos_despues})")

            if estado.fase != Fase.RECONOCER:
                revelada = estado.cartas_reveladas > reveladas_antes
                delta = tutor.actualizar(primer_intento and coincide is not None, revelada)
                nivel_antes = estado.nivel_ayuda
                estado = cambiar_nivel(estado, delta)
                if estado.nivel_ayuda != nivel_antes:
                    say(f"  Tutor: nivel de ayuda -> {estado.nivel_ayuda} "
                        f"({NOMBRE_NIVEL[estado.nivel_ayuda]})")
                if estado.escudo_usado and not reg.estado.escudo_usado:
                    say("  Agente: [🛡️ ESCUDO] Te salvo el escudo, se descarto la ultima carta.")
                if estado.resultado == Resultado.SE_PASO:
                    say(f"  Te pasaste de {estado.objetivo}.")

        elif estado.fase == Fase.DECIDIR:
            sug = consejero.sugerir(estado, catalogo)
            if sug and sug.pictos:
                say(f"\n  Suma {estado.suma_jugador}. Consejero: {sug.pictos}  ({sug.razon})")
            accion = jugador.decidir(estado, sug)
            estado = transicion(estado, accion, catalogo)
        reg.estado = estado

    if estado.resultado != Resultado.SE_PASO:
        mano_c = ", ".join(catalogo.cartas[c].palabra for c in estado.mano_crupier)
        say(f"\n  Crupier: {mano_c} = {estado.suma_crupier}")
    say(f"  Resultado: {estado.resultado.value.upper()}  (tu {estado.suma_jugador} vs "
        f"crupier {estado.suma_crupier})")
    if ultima and estado.resultado in (Resultado.SE_PASO, Resultado.PIERDE):
        carta, dicha, suma_antes, mejora = ultima
        alt = leccion_sinonimo(
            carta, dicha, suma_antes, mejora, estado.resultado, estado.suma_crupier, estado.objetivo
        )
        if alt:
            reg.sinonimos_sugeridos += 1
            say(f"  Agente: Pudiste decir {alt[0].upper()} y quedar en {alt[1]}. La proxima vez.")
    return reg


# --------------------------------------------------------------------------- modos

def modo_interactivo(catalogo, escenarios, escenario_id, semilla):
    esc = escenarios["escenarios"][escenario_id]
    rng = random.Random(semilla)
    tutor, consejero = TutorHeuristico(), ConsejeroHeuristico()
    nivel = esc["nivel_inicial"]
    print(f"=== PICTO21 - escenario {esc['nombre']} ===")
    print("Cada carta vale las letras de su nombre. Llega a 21 sin pasarte.")
    ronda = 0
    while True:
        ronda += 1
        print(f"\n------ Ronda {ronda} ------")
        estado = nueva_partida(esc, catalogo, semilla=rng.randrange(10**6), nivel=nivel)
        reg = jugar_ronda(estado, catalogo, esc, consejero, tutor, JugadorConsola(), rng, verbose=True)
        nivel = reg.estado.nivel_ayuda
        if not input("\nOtra ronda? (s/n): ").strip().lower().startswith("s"):
            break


def simular(catalogo, escenarios, escenario_id, n, p, sigue, consejero_nombre, semilla):
    esc = escenarios["escenarios"][escenario_id]
    rng = random.Random(semilla)
    consejero = ConsejeroHeuristico() if consejero_nombre == "heuristico" else ConsejeroAleatorio(rng)
    jugador = JugadorSimulado(p, sigue, rng)
    tutor = TutorHeuristico()
    nivel = esc["nivel_inicial"]

    res = {r: 0 for r in Resultado}
    cartas = pistas = reveladas = primer = turnos = sug = acep = 0
    niveles = []
    for i in range(n):
        estado = nueva_partida(esc, catalogo, semilla=semilla * 100_000 + i, nivel=nivel)
        reg = jugar_ronda(estado, catalogo, esc, consejero, tutor, jugador, rng)
        e = reg.estado
        res[e.resultado] += 1
        cartas += e.cartas_reconocidas + (1 if e.escudo_usado else 0)
        pistas += e.pistas_totales
        reveladas += e.cartas_reveladas
        primer += e.aciertos_primer_intento
        turnos += e.turnos
        sug += reg.sinonimos_sugeridos
        acep += reg.sinonimos_aceptados
        nivel = e.nivel_ayuda
        niveles.append(nivel)

    cartas = max(cartas, 1)
    return {
        "partidas": n,
        "victoria": res[Resultado.GANA] / n,
        "empate": res[Resultado.EMPATE] / n,
        "derrota": res[Resultado.PIERDE] / n,
        "se_paso": res[Resultado.SE_PASO] / n,
        "reconocidas_sin_revelar": 1 - reveladas / cartas,
        "acierto_primer_intento": primer / cartas,
        "pistas_por_carta": pistas / cartas,
        "turnos_promedio": turnos / n,
        "cartas_por_partida": cartas / n,
        "sinonimos_sugeridos": sug,
        "nivel_promedio": sum(niveles) / n,
    }


def imprimir_metricas(nombre, m):
    print(f"\n  Consejero {nombre}")
    print(f"    Victoria / empate / derrota / se paso : {m['victoria']:.1%} / {m['empate']:.1%} / "
          f"{m['derrota']:.1%} / {m['se_paso']:.1%}")
    print(f"    Cartas reconocidas sin revelar       : {m['reconocidas_sin_revelar']:.1%}")
    print(f"    Acierto al primer intento            : {m['acierto_primer_intento']:.1%}")
    print(f"    Pistas por carta                     : {m['pistas_por_carta']:.2f}")
    print(f"    Turnos promedio por partida          : {m['turnos_promedio']:.2f}")
    print(f"    Cartas por partida                   : {m['cartas_por_partida']:.2f}")
    print(f"    Nivel de ayuda promedio              : {m['nivel_promedio']:.2f}")
    print(f"    Sinonimos sugeridos (total)          : {m['sinonimos_sugeridos']}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Experimento A - Picto21")
    modo = ap.add_mutually_exclusive_group(required=True)
    modo.add_argument("--interactivo", action="store_true", help="jugar en consola")
    modo.add_argument("--simular", type=int, metavar="N", help="simular N partidas")
    modo.add_argument("--barrido", type=int, metavar="N", help="simular N partidas para varios p")
    modo.add_argument("--arbol", action="store_true", help="imprimir el arbol ID3 del escenario")
    ap.add_argument("--escenario", default="animales")
    ap.add_argument("--p", type=float, default=0.6, help="prob. base de acierto del jugador simulado")
    ap.add_argument("--sigue", type=float, default=0.9, help="prob. de seguir el consejo")
    ap.add_argument("--semilla", type=int, default=7)
    args = ap.parse_args(argv)

    catalogo = cargar_catalogo()
    escenarios = cargar_escenarios()
    if args.escenario not in escenarios["escenarios"]:
        ap.error(f"escenario desconocido; opciones: {', '.join(escenarios['escenarios'])}")

    if args.interactivo:
        modo_interactivo(catalogo, escenarios, args.escenario, args.semilla)
    elif args.arbol:
        esc = escenarios["escenarios"][args.escenario]
        cand = [catalogo.cartas[i] for i in dict.fromkeys(esc["mazo"])]
        print(arbol_id3(cand, catalogo.atributos))
    elif args.simular:
        print(f"=== Simulacion: {args.simular} partidas, escenario {args.escenario}, "
              f"p={args.p}, sigue={args.sigue} ===")
        for nombre in ("heuristico", "aleatorio"):
            m = simular(catalogo, escenarios, args.escenario, args.simular, args.p, args.sigue,
                        nombre, args.semilla)
            imprimir_metricas(nombre, m)
    else:
        print(f"=== Barrido de p: {args.barrido} partidas por punto, escenario {args.escenario} ===")
        print(f"  {'p':>4} | {'victoria heur.':>14} | {'victoria azar':>13} | {'pistas/carta':>12} | "
              f"{'sin revelar':>11} | {'nivel prom.':>11}")
        for p in (0.2, 0.4, 0.6, 0.8):
            h = simular(catalogo, escenarios, args.escenario, args.barrido, p, args.sigue,
                        "heuristico", args.semilla)
            a = simular(catalogo, escenarios, args.escenario, args.barrido, p, args.sigue,
                        "aleatorio", args.semilla)
            print(f"  {p:>4.1f} | {h['victoria']:>14.1%} | {a['victoria']:>13.1%} | "
                  f"{h['pistas_por_carta']:>12.2f} | {h['reconocidas_sin_revelar']:>11.1%} | "
                  f"{h['nivel_promedio']:>11.2f}")


if __name__ == "__main__":
    main()
