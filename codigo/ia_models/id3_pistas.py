"""Baseline del tutor: seleccion de pistas por ganancia de informacion (ID3).

El agente conoce la carta objetivo; el jugador no. El conjunto de candidatos son las cartas
del escenario que el jugador podria estar confundiendo. En cada fallo el agente elige el
atributo con mayor ganancia de informacion sobre los candidatos (como al construir un nodo
de un arbol ID3), muestra el valor de ese atributo para la carta objetivo como pictograma y
filtra los candidatos consistentes. Asi cada pista recorre una rama del arbol de decision.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from catalogo import Carta, Catalogo, normalizar

# Atributos de respaldo, solo se usan cuando los semanticos ya no aportan informacion:
# se prefieren pistas por significado antes que pistas ortograficas.
ATRIBUTOS_RESPALDO: Dict[str, Callable[[Carta], str]] = {
    "primera_letra": lambda c: normalizar(c.palabra)[0].upper(),
    "num_letras": lambda c: str(len(normalizar(c.palabra))),
}


@dataclass(frozen=True)
class Pista:
    atributo: str
    valor: str
    texto: str
    emoji: str
    arasaac_id: Optional[int]
    ganancia: float
    candidatos_antes: int
    candidatos_despues: int


def valor_atributo(carta: Carta, atributo: str) -> Optional[str]:
    if atributo in ATRIBUTOS_RESPALDO:
        return ATRIBUTOS_RESPALDO[atributo](carta)
    return carta.atributos.get(atributo)


def entropia(candidatos: Sequence[Carta]) -> float:
    """H(C) con distribucion uniforme sobre la identidad de la carta objetivo."""
    n = len(candidatos)
    return math.log2(n) if n > 0 else 0.0


def ganancia(candidatos: Sequence[Carta], atributo: str) -> float:
    """IG(C, A) = H(C) - sum_v |C_v|/|C| * H(C_v)."""
    n = len(candidatos)
    if n == 0:
        return 0.0
    grupos = Counter(valor_atributo(c, atributo) or "ninguno" for c in candidatos)
    resto = sum(k / n * math.log2(k) for k in grupos.values())
    return entropia(candidatos) - resto


def filtrar(candidatos: Sequence[Carta], atributo: str, valor: str) -> List[Carta]:
    return [c for c in candidatos if valor_atributo(c, atributo) == valor]


def candidatos_consistentes(
    objetivo: Carta, candidatos: Sequence[Carta], pistas_usadas: Sequence[str]
) -> List[Carta]:
    """Candidatos que siguen siendo posibles despues de las pistas ya mostradas."""
    restantes = list(candidatos)
    for atributo in pistas_usadas:
        restantes = filtrar(restantes, atributo, valor_atributo(objetivo, atributo))
    return restantes


def mejor_pista(
    objetivo: Carta,
    candidatos: Sequence[Carta],
    pistas_usadas: Sequence[str],
    catalogo: Catalogo,
) -> Optional[Pista]:
    """Elige el atributo no usado con maxima ganancia de informacion."""
    restantes = candidatos_consistentes(objetivo, candidatos, pistas_usadas)

    def evaluar(atributos: Sequence[str]) -> List[tuple]:
        opciones = []
        for a in atributos:
            if a in pistas_usadas or valor_atributo(objetivo, a) is None:
                continue
            opciones.append((ganancia(restantes, a), a))
        return opciones

    opciones = [o for o in evaluar(catalogo.atributos) if o[0] > 0]
    if not opciones:
        opciones = evaluar(list(ATRIBUTOS_RESPALDO))
    if not opciones:
        return None

    # Desempate estable por el orden de los atributos en el catalogo.
    orden = {a: i for i, a in enumerate([*catalogo.atributos, *ATRIBUTOS_RESPALDO])}
    g, atributo = max(opciones, key=lambda o: (round(o[0], 9), -orden[o[1]]))
    v = valor_atributo(objetivo, atributo)
    picto = _picto_de(atributo, v, catalogo)
    return Pista(
        atributo=atributo,
        valor=v,
        texto=picto["texto"],
        emoji=picto.get("emoji", ""),
        arasaac_id=picto.get("arasaac_id"),
        ganancia=g,
        candidatos_antes=len(restantes),
        candidatos_despues=len(filtrar(restantes, atributo, v)),
    )


def _picto_de(atributo: str, valor: str, catalogo: Catalogo) -> dict:
    if atributo == "primera_letra":
        return {"texto": f"empieza con {valor}", "emoji": f"🔤{valor}", "arasaac_id": None}
    if atributo == "num_letras":
        return {"texto": f"{valor} letras", "emoji": f"🔢{valor}", "arasaac_id": None}
    return catalogo.picto(valor)


def frase_pictos(pistas: Sequence[Pista]) -> str:
    """Frase acumulada de pistas, p. ej. [ANIMAL] + [CASA] + [LADRA]."""
    return " + ".join(f"[{p.emoji} {p.texto.upper()}]" for p in pistas)


def arbol_id3(candidatos: Sequence[Carta], atributos: Sequence[str], profundidad: int = 0) -> str:
    """Arbol ID3 completo en texto, util para documentar el baseline en el informe."""
    sangria = "  " * profundidad
    if len(candidatos) <= 1 or not atributos:
        return f"{sangria}-> {', '.join(c.palabra for c in candidatos)}\n"
    ganancias = [(ganancia(candidatos, a), a) for a in atributos]
    g, mejor = max(ganancias)
    if g <= 0:
        return f"{sangria}-> {', '.join(c.palabra for c in candidatos)}\n"
    texto = ""
    restantes = [a for a in atributos if a != mejor]
    for v in sorted({valor_atributo(c, mejor) or "ninguno" for c in candidatos}):
        rama = [c for c in candidatos if (valor_atributo(c, mejor) or "ninguno") == v]
        texto += f"{sangria}{mejor} = {v}  (IG={g:.2f})\n"
        texto += arbol_id3(rama, restantes, profundidad + 1)
    return texto
