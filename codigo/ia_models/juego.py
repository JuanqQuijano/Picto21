"""Motor de reglas de Picto21: espacio de estados S, acciones A y funcion de transicion.

Una ronda enfrenta al jugador contra un crupier automatico. Cada carta vale el numero de
letras de la palabra con la que el jugador la nombra. La transicion es determinista dado
el estado (el mazo ya esta barajado al iniciar), lo que permite reutilizarla como modelo
del entorno para el MDP / Q-Learning del Hito 2.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from catalogo import Catalogo, es_valida, valor

MAX_INTENTOS = 3
NIVEL_MIN, NIVEL_MAX = 1, 3


class Fase(str, Enum):
    RECONOCER = "reconocer"  # hay una carta nueva que el jugador debe nombrar
    DECIDIR = "decidir"      # el jugador elige pedir, plantarse o usar su mejora
    FIN = "fin"


class Resultado(str, Enum):
    GANA = "gana"
    EMPATE = "empate"
    PIERDE = "pierde"
    SE_PASO = "se_paso"


@dataclass(frozen=True)
class Accion:
    tipo: str                      # "responder" | "pedir" | "plantarse" | "usar_mejora"
    palabra: Optional[str] = None  # solo para "responder"

    def __str__(self) -> str:
        return f"responder({self.palabra})" if self.tipo == "responder" else self.tipo


PEDIR = Accion("pedir")
PLANTARSE = Accion("plantarse")
USAR_MEJORA = Accion("usar_mejora")


def responder(palabra: str) -> Accion:
    return Accion("responder", palabra)


@dataclass
class EstadoJuego:
    escenario_id: str
    objetivo: int
    crupier_se_planta: int
    mazo: List[str]
    carta_visible_crupier: str
    suma_crupier: int
    mano_crupier: List[str]
    nivel_ayuda: int
    mejora_disponible: Optional[str]
    mano: List[Tuple[str, int]] = field(default_factory=list)  # (id_carta, valor obtenido)
    suma_jugador: int = 0
    mejora_activa: Optional[str] = None
    carta_actual: Optional[str] = None
    intentos: int = 0
    pistas_usadas: List[str] = field(default_factory=list)
    fase: Fase = Fase.RECONOCER
    resultado: Optional[Resultado] = None
    turnos: int = 0
    pistas_totales: int = 0
    cartas_reveladas: int = 0
    aciertos_primer_intento: int = 0
    escudo_usado: bool = False

    @property
    def cartas_reconocidas(self) -> int:
        return len(self.mano)


def nueva_partida(
    escenario: dict,
    catalogo: Catalogo,
    semilla: Optional[int] = None,
    nivel: Optional[int] = None,
) -> EstadoJuego:
    rng = random.Random(escenario["semilla"] if semilla is None else semilla)
    mazo = list(escenario["mazo"]) * escenario.get("copias", 1)
    rng.shuffle(mazo)

    visible = mazo.pop(0)
    mejoras = escenario.get("mejoras_disponibles", [])
    estado = EstadoJuego(
        escenario_id=escenario["id"],
        objetivo=escenario.get("objetivo", 21),
        crupier_se_planta=escenario.get("crupier_se_planta", 17),
        mazo=mazo,
        carta_visible_crupier=visible,
        suma_crupier=catalogo.cartas[visible].valor,
        mano_crupier=[visible],
        nivel_ayuda=escenario.get("nivel_inicial", 1) if nivel is None else nivel,
        mejora_disponible=rng.choice(mejoras) if mejoras else None,
    )
    estado.carta_actual = estado.mazo.pop(0)
    return estado


def acciones_validas(e: EstadoJuego) -> List[Accion]:
    if e.fase == Fase.RECONOCER:
        return [Accion("responder")]
    if e.fase == Fase.DECIDIR:
        acciones = [PLANTARSE]
        if e.mazo:
            acciones.insert(0, PEDIR)
        if e.mejora_disponible and e.mejora_activa is None:
            acciones.append(USAR_MEJORA)
        return acciones
    return []


def valor_con_mejora(base: int, mejora: Optional[str]) -> int:
    if mejora == "mas_uno":
        return base + 1
    if mejora == "menos_uno":
        return max(1, base - 1)
    return base


def transicion(e: EstadoJuego, accion: Accion, catalogo: Catalogo) -> EstadoJuego:
    tipos_validos = {a.tipo for a in acciones_validas(e)}
    if accion.tipo not in tipos_validos:
        raise ValueError(f"Accion {accion} no valida en fase {e.fase.value}")

    s = copy.deepcopy(e)
    s.turnos += 1

    if accion.tipo == "responder":
        carta = catalogo.cartas[s.carta_actual]
        coincide = es_valida(carta, accion.palabra or "")
        if coincide:
            if s.intentos == 0:
                s.aciertos_primer_intento += 1
            _agregar_carta(s, carta.id, valor(coincide))
        else:
            s.intentos += 1
            if s.intentos >= MAX_INTENTOS:
                s.cartas_reveladas += 1
                _agregar_carta(s, carta.id, carta.valor)
    elif accion.tipo == "pedir":
        s.carta_actual = s.mazo.pop(0)
        s.intentos = 0
        s.pistas_usadas = []
        s.fase = Fase.RECONOCER
    elif accion.tipo == "plantarse":
        _jugar_crupier(s, catalogo)
    elif accion.tipo == "usar_mejora":
        s.mejora_activa, s.mejora_disponible = s.mejora_disponible, None

    if s.fase == Fase.DECIDIR and s.suma_jugador == s.objetivo:
        _jugar_crupier(s, catalogo)
    return s


def registrar_pista(e: EstadoJuego, atributo: str) -> EstadoJuego:
    s = copy.deepcopy(e)
    s.pistas_usadas.append(atributo)
    s.pistas_totales += 1
    return s


def cambiar_nivel(e: EstadoJuego, delta: int) -> EstadoJuego:
    s = copy.deepcopy(e)
    s.nivel_ayuda = min(NIVEL_MAX, max(NIVEL_MIN, s.nivel_ayuda + delta))
    return s


def _agregar_carta(s: EstadoJuego, carta_id: str, base: int) -> None:
    v = base
    if s.mejora_activa in ("mas_uno", "menos_uno"):
        v = valor_con_mejora(base, s.mejora_activa)
        s.mejora_activa = None

    s.mano.append((carta_id, v))
    s.suma_jugador += v
    s.carta_actual = None
    s.intentos = 0
    s.pistas_usadas = []
    s.fase = Fase.DECIDIR

    if s.suma_jugador > s.objetivo:
        if s.mejora_activa == "escudo":
            s.mano.pop()
            s.suma_jugador -= v
            s.mejora_activa = None
            s.escudo_usado = True
        else:
            s.fase = Fase.FIN
            s.resultado = Resultado.SE_PASO


def _jugar_crupier(s: EstadoJuego, catalogo: Catalogo) -> None:
    while s.suma_crupier < s.crupier_se_planta and s.mazo:
        c = s.mazo.pop(0)
        s.mano_crupier.append(c)
        s.suma_crupier += catalogo.cartas[c].valor

    if s.suma_crupier > s.objetivo or s.suma_jugador > s.suma_crupier:
        s.resultado = Resultado.GANA
    elif s.suma_jugador == s.suma_crupier:
        s.resultado = Resultado.EMPATE
    else:
        s.resultado = Resultado.PIERDE
    s.fase = Fase.FIN
