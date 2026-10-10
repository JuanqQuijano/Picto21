"""Consejero de juego y tutor de nivel de Picto21.

`Consejero` define la interfaz que usara el modelo principal del Hito 2 (MDP resuelto por
value iteration o politica aprendida con Q-Learning). En el Hito 1 se usan politicas
heuristicas explicables con la misma interfaz, de modo que el reemplazo no cambie el
resto del sistema.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from catalogo import Carta, Catalogo, normalizar, valor
from juego import (
    PEDIR,
    PLANTARSE,
    USAR_MEJORA,
    Accion,
    EstadoJuego,
    Fase,
    Resultado,
    acciones_validas,
    valor_con_mejora,
)


@dataclass(frozen=True)
class Sugerencia:
    accion: Accion
    razon: str
    pictos: str  # frase en pictogramas que la interfaz muestra y lee en voz alta


def leccion_sinonimo(carta: Carta, dicha: str, suma_antes: int, mejora, resultado: Resultado, suma_crupier: int, objetivo: int = 21):
    """Si otro nombre de la misma carta habria evitado la derrota, lo devuelve con la suma que daba.

    No modifica el resultado. Sirve para decirle al jugador que pudo elegir otra palabra.
    """
    if resultado not in (Resultado.SE_PASO, Resultado.PIERDE):
        return None
    dicha = normalizar(dicha)
    ajuste = mejora if mejora in ("mas_uno", "menos_uno") else None

    def suma_de(p: str) -> int:
        return suma_antes + valor_con_mejora(valor(p), ajuste)

    def sirve(suma: int) -> bool:
        if suma > objetivo:
            return False
        if resultado == Resultado.SE_PASO:
            return True
        return suma > suma_crupier

    utiles = [normalizar(p) for p in carta.palabras_validas if normalizar(p) != dicha and sirve(suma_de(p))]
    if not utiles:
        return None
    mejor = max(utiles, key=suma_de)
    return mejor, suma_de(mejor)


class Consejero(ABC):
    @abstractmethod
    def sugerir(self, estado: EstadoJuego, catalogo: Catalogo) -> Optional[Sugerencia]:
        """Sugiere una accion para la fase DECIDIR (None en otras fases)."""

    def sugerir_palabra(self, estado: EstadoJuego, carta: Carta, dicha: str) -> Optional[str]:
        """Ya no cambia la palabra dicha. La leccion se da al terminar, si perdio."""
        return None


class ConsejeroHeuristico(Consejero):
    """Reglas tipo 'estrategia basica' adaptadas a cartas con valores entre 3 y 9."""

    def __init__(self, pedir_hasta: int = 15, plantarse_desde: int = 18, crupier_alto: int = 6):
        self.pedir_hasta = pedir_hasta
        self.plantarse_desde = plantarse_desde
        self.crupier_alto = crupier_alto

    def sugerir(self, estado: EstadoJuego, catalogo: Catalogo) -> Optional[Sugerencia]:
        if estado.fase != Fase.DECIDIR:
            return None
        validas = acciones_validas(estado)
        suma = estado.suma_jugador
        visible = catalogo.cartas[estado.carta_visible_crupier].valor
        faltan = estado.objetivo - suma

        mejora = self._sugerir_mejora(estado, validas, faltan)
        if mejora:
            return mejora

        if PEDIR not in validas:
            return Sugerencia(PLANTARSE, "Ya no quedan cartas en el mazo.", "[✋ PARAR]")
        if estado.mejora_activa == "escudo":
            return Sugerencia(PEDIR, "El escudo te protege si te pasas.", "[🛡️ ESCUDO] + [👍 PEDIR]")
        if estado.mejora_activa == "menos_uno" and suma < self.plantarse_desde:
            return Sugerencia(PEDIR, "La proxima carta vale 1 menos.", "[➖ MENOS] + [👍 PEDIR]")
        if suma <= self.pedir_hasta:
            return Sugerencia(PEDIR, f"Te faltan {faltan} puntos; es seguro pedir.", "[👍 PEDIR] + [🃏 CARTA]")
        if suma >= self.plantarse_desde:
            return Sugerencia(PLANTARSE, f"Tienes {suma}; otra carta probablemente te pasa.", "[✋ PARAR]")
        if visible >= self.crupier_alto:
            return Sugerencia(
                PEDIR,
                f"El crupier muestra {visible}, va a llegar alto. Conviene arriesgar.",
                "[👍 PEDIR] + [🃏 CARTA]",
            )
        return Sugerencia(
            PLANTARSE,
            f"El crupier muestra {visible}, puede pasarse. Mejor parar con {suma}.",
            "[✋ PARAR]",
        )

    def _sugerir_mejora(self, estado: EstadoJuego, validas, faltan: int) -> Optional[Sugerencia]:
        if USAR_MEJORA not in validas or PEDIR not in validas:
            return None
        m = estado.mejora_disponible
        if m == "escudo" and self.pedir_hasta - 2 < estado.suma_jugador < self.plantarse_desde:
            return Sugerencia(USAR_MEJORA, "Activa el escudo antes de arriesgarte.", "[🛡️ ESCUDO]")
        if m == "menos_uno" and self.pedir_hasta < estado.suma_jugador < self.plantarse_desde:
            return Sugerencia(USAR_MEJORA, "Usa -1 para que la proxima carta reste.", "[➖ MENOS]")
        if m == "mas_uno" and faltan >= 10:
            return Sugerencia(USAR_MEJORA, "Usa +1 ahora que estas lejos de 21.", "[➕ MAS]")
        return None


class ConsejeroAleatorio(Consejero):
    """Politica de referencia para comparar en las metricas."""

    def __init__(self, rng):
        self.rng = rng

    def sugerir(self, estado: EstadoJuego, catalogo: Catalogo) -> Optional[Sugerencia]:
        if estado.fase != Fase.DECIDIR:
            return None
        accion = self.rng.choice(acciones_validas(estado))
        return Sugerencia(accion, "Eleccion al azar.", "")

    def sugerir_palabra(self, estado: EstadoJuego, carta: Carta, dicha: str) -> Optional[str]:
        return None


class TutorHeuristico:
    """Ajusta el nivel de ayuda (1: opciones, 2: fichas de letras, 3: teclado).

    Sube un nivel tras `racha_subir` aciertos al primer intento seguidos y baja uno cuando
    una carta se tuvo que revelar. En el Hito 2 se reemplaza por una politica Q-Learning.
    """

    def __init__(self, racha_subir: int = 3):
        self.racha_subir = racha_subir
        self.racha = 0

    def actualizar(self, acerto_primer_intento: bool, revelada: bool) -> int:
        if revelada:
            self.racha = 0
            return -1
        if acerto_primer_intento:
            self.racha += 1
            if self.racha >= self.racha_subir:
                self.racha = 0
                return +1
        else:
            self.racha = 0
        return 0
