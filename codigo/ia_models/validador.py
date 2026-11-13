"""Validador semantico para los niveles 2 y 3 de Picto21.

No sustituye la lista de sinonimos: primero busca coincidencia exacta (con
normalizacion y palabras vacias), luego un typo leve (Levenshtein) y por
ultimo un embedding lexico de n-gramas de caracteres construido con la
palabra, los sinonimos y los atributos de cada carta.

La palabra con la que se puntua:
- si coincidio con un nombre del catalogo (exacto o typo), esa palabra;
- si solo coincidio por embedding (parafrasis), la palabra principal.
Nunca se cambia despues para "salvar" al jugador.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from catalogo import Carta, Catalogo, es_valida, normalizar

STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al",
    "es", "un", "que", "se", "mi", "tu", "su", "este", "esta", "ese", "esa",
    "y", "o", "en", "con", "por", "para", "como", "muy", "esun",
}

# Documentos extra para el embedding: no suman puntos, solo ayudan a reconocer.
PARAFRASES = {
    "gato": ["felino", "gatito", "miau", "animal que maulla"],
    "perro": ["canino", "perrito", "guau", "animal que ladra"],
    "oso": ["osito", "animal del bosque"],
    "pato": ["patito", "ave que nada"],
    "vaca": ["vaquita", "animal que muge"],
    "pez": ["pececito", "animal que nada"],
    "conejo": ["conejito", "animal que salta"],
    "elefante": ["elefantito", "animal grande"],
    "pan": ["pancito", "hogaza de pan"],
    "leche": ["vasito de leche"],
    "manzana": ["manzanita", "fruta roja"],
    "huevo": ["huevito"],
    "queso": ["quesito"],
    "banana": ["bananita", "platano"],
    "arroz": ["arrocito"],
    "mesa": ["mesita"],
    "silla": ["sillita", "asiento"],
    "pelota": ["pelotita", "balon"],
    "zapato": ["zapatito", "calzado"],
    "auto": ["carrito", "coche", "automovil"],
    "cama": ["camita", "lecho"],
    "comer": ["alimentarse", "comer comida"],
    "dormir": ["descansar", "ir a dormir"],
    "saltar": ["brincar", "dar un salto"],
}


@dataclass(frozen=True)
class Veredicto:
    ok: bool
    palabra: Optional[str]  # forma con la que se puntua (normalizada)
    metodo: str             # exacto | vacias | typo | embedding | ninguno
    similitud: float
    carta_id: Optional[str] = None


def _sin_vacias(texto: str) -> str:
    n = normalizar(texto)
    partes = []
    for cruda in texto.lower().replace("¿", " ").replace("?", " ").split():
        p = normalizar(cruda)
        if p and p not in STOPWORDS:
            partes.append(p)
    return "".join(partes) if partes else n


def _para_embedding(texto: str) -> str:
    """Minusculas sin tildes, pero conserva espacios para los n-gramas."""
    texto = texto.strip().lower().replace("ñ", "\0").replace("¿", " ").replace("?", " ")
    sin = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return " ".join("".join(c for c in w if c.isalpha() or c == "\0").replace("\0", "ñ") for w in sin.split() if w)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _typo_ok(a: str, b: str) -> bool:
    d = _levenshtein(a, b)
    if d == 0:
        return True
    if d == 1:
        return True
    return d == 2 and min(len(a), len(b)) >= 6


def _ngrams(texto: str, n: int = 3) -> Counter:
    s = f"  {texto}  "
    return Counter(s[i:i + n] for i in range(max(0, len(s) - n + 1)))


def _coseno(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    claves = set(a) | set(b)
    dot = sum(a[k] * b[k] for k in claves)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class ValidadorSemantico:
    """Reconoce la carta nombrada en los niveles 2 y 3."""

    def __init__(self, catalogo: Catalogo, umbral: float = 0.34, margen: float = 0.06):
        self.catalogo = catalogo
        self.umbral = umbral
        self.margen = margen
        self._docs: Dict[str, List[Counter]] = {}
        self._nombres: Dict[str, List[str]] = {}
        for carta in catalogo.cartas.values():
            self._nombres[carta.id] = [normalizar(p) for p in carta.palabras_validas]
            partes = list(carta.palabras_validas)
            partes.extend(PARAFRASES.get(carta.id, []))
            for v in carta.atributos.values():
                if v:
                    partes.append(str(v))
            diminutivo = carta.palabra + ("ita" if carta.palabra.endswith("a") else "ito")
            partes.append(diminutivo)
            self._docs[carta.id] = [_ngrams(_para_embedding(p)) for p in partes if p]

    def validar(self, carta: Carta, texto: str) -> Veredicto:
        exacto = es_valida(carta, texto)
        if exacto:
            return Veredicto(True, exacto, "exacto", 1.0, carta.id)

        limpio = _sin_vacias(texto)
        if limpio:
            exacto = es_valida(carta, limpio)
            if exacto:
                return Veredicto(True, exacto, "vacias", 1.0, carta.id)
            for p in self._nombres[carta.id]:
                if _typo_ok(limpio, p):
                    return Veredicto(True, p, "typo", 1.0 - _levenshtein(limpio, p) / max(len(p), 1), carta.id)

        n = normalizar(texto)
        for p in self._nombres[carta.id]:
            if n and _typo_ok(n, p):
                return Veredicto(True, p, "typo", 1.0 - _levenshtein(n, p) / max(len(p), 1), carta.id)

        consulta = _ngrams(_para_embedding(texto) or limpio or n)

        def sim_carta(cid: str) -> float:
            return max((_coseno(consulta, doc) for doc in self._docs[cid]), default=0.0)

        sims: List[Tuple[float, str]] = [(sim_carta(cid), cid) for cid in self._docs]
        sims.sort(reverse=True)
        if not sims:
            return Veredicto(False, None, "ninguno", 0.0)

        mejor_sim, mejor_id = sims[0]
        segunda = sims[1][0] if len(sims) > 1 else 0.0
        sim_objetivo = next(s for s, cid in sims if cid == carta.id)

        if (
            mejor_id == carta.id
            and sim_objetivo >= self.umbral
            and sim_objetivo >= segunda + self.margen
        ):
            return Veredicto(True, normalizar(carta.palabra), "embedding", sim_objetivo, carta.id)

        return Veredicto(False, None, "ninguno", sim_objetivo, carta.id)


def palabra_para_puntuar(veredicto: Veredicto, texto: str) -> Optional[str]:
    if not veredicto.ok:
        return None
    return veredicto.palabra
