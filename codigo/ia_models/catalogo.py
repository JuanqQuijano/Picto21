"""Carga del catalogo de pictogramas y reglas de validacion de palabras de Picto21."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

RUTA_DATOS = Path(__file__).resolve().parents[2] / "datos"


@dataclass(frozen=True)
class Carta:
    id: str
    palabra: str
    sinonimos: tuple
    arasaac_id: int
    emoji: str
    atributos: Dict[str, Optional[str]] = field(hash=False, compare=False)

    @property
    def palabras_validas(self) -> List[str]:
        return [self.palabra, *self.sinonimos]

    @property
    def valor(self) -> int:
        """Valor base de la carta: letras de la palabra principal."""
        return valor(self.palabra)

    @property
    def url_imagen(self) -> str:
        return f"https://static.arasaac.org/pictograms/{self.arasaac_id}/{self.arasaac_id}_500.png"


@dataclass(frozen=True)
class Catalogo:
    cartas: Dict[str, Carta]
    atributos: List[str]
    pictos_pista: Dict[str, dict]

    def picto(self, clave: str) -> dict:
        return self.pictos_pista.get(clave, {"texto": clave, "emoji": "", "arasaac_id": None})


def normalizar(texto: str) -> str:
    """Minusculas, sin tildes ni espacios ni signos; la ene se conserva como una letra."""
    texto = texto.strip().lower().replace("ñ", "\0")
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return "".join(c for c in sin_tildes if c.isalpha() or c == "\0").replace("\0", "ñ")


def valor(palabra: str) -> int:
    return len(normalizar(palabra))


def letras_elegibles(carta: Carta) -> List[str]:
    """Maximo de cada letra necesario para armar cualquiera de las palabras validas."""
    maximo: Dict[str, int] = {}
    for palabra in carta.palabras_validas:
        cuenta: Dict[str, int] = {}
        for letra in normalizar(palabra):
            cuenta[letra] = cuenta.get(letra, 0) + 1
        for letra, n in cuenta.items():
            maximo[letra] = max(maximo.get(letra, 0), n)
    letras: List[str] = []
    for letra, n in maximo.items():
        letras.extend([letra.upper()] * n)
    return letras


def es_valida(carta: Carta, respuesta: str) -> Optional[str]:
    """Devuelve la palabra valida (normalizada) que coincide con la respuesta, o None."""
    r = normalizar(respuesta)
    for p in carta.palabras_validas:
        if normalizar(p) == r:
            return normalizar(p)
    return None


def cargar_catalogo(ruta: Path = RUTA_DATOS / "catalogo.json") -> Catalogo:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    cartas = {
        c["id"]: Carta(
            id=c["id"],
            palabra=c["palabra"],
            sinonimos=tuple(c.get("sinonimos", [])),
            arasaac_id=c["arasaac_id"],
            emoji=c.get("emoji", ""),
            atributos=c["atributos"],
        )
        for c in datos["cartas"]
    }
    return Catalogo(cartas=cartas, atributos=datos["atributos"], pictos_pista=datos["pictos_pista"])


def cargar_escenarios(ruta: Path = RUTA_DATOS / "escenarios.json") -> dict:
    """Devuelve {"mejoras": {...}, "escenarios": {id: escenario}}."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return {
        "mejoras": datos["mejoras"],
        "escenarios": {e["id"]: e for e in datos["escenarios"]},
    }
