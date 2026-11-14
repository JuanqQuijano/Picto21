"""Agente orientador de Picto21: red neuronal que decide la ayuda a pedido.

El orientador se activa solo cuando el jugador lo solicita. Su red neuronal (MLP)
elige entre:
    - reconocer: pista | revelar | animo
    - decidir:   pedir | parar | usar_mejora

Para materializar la pista se reutiliza el baseline ID3 (`id3_pistas.mejor_pista`),
que ya evita repetir atributos y elige el de mayor ganancia de informacion. Para las
decisiones de juego la red se entrena imitando la politica tabular (Q-Learning /
value iteration) o, si no existe, la heuristica explicable.

El entrenamiento es por imitacion de un experto:
    - pistas: escalado pedagogico (pista -> revelar -> animo) sobre sesiones reales
      generadas con el catalogo y los escenarios;
    - decisiones: accion recomendada por la politica entrenada del Hito 2.

La red nunca puede elegir una accion invalida: en inferencia se enmascaran las clases
que no aplican al estado y, si la confianza es baja, se responde con el experto.

La ayuda no tiene tope: se puede pedir en cualquier turno y tantas veces como se quiera.
Cuando se agotan los atributos de la carta, la respuesta deja de ser una pista nueva y
pasa a ser el repaso de las ya entregadas junto con la silaba inicial.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

from catalogo import Carta, Catalogo, cargar_escenarios
from consejero import ConsejeroHeuristico, ConsejeroTabular
from id3_pistas import ATRIBUTOS_RESPALDO, Pista, _picto_de, mejor_pista, valor_atributo
from juego import EstadoJuego, Fase
from mdp import MEJORAS
from red_neuronal import MLP, division_estratificada, metricas_clasificacion

RUTA_POLITICA = Path(__file__).resolve().parents[2] / "datos" / "politica_q.json"
RUTA_MODELO = Path(__file__).resolve().parent / "modelos" / "orientador.npz"
RUTA_METRICAS = Path(__file__).resolve().parent / "modelos" / "metricas_orientador.json"

CLASES = ("pista", "revelar", "animo", "pedir", "parar", "usar_mejora")
FASES = ("reconocer", "decidir")
UMBRAL_CONFIANZA = 0.40

# La pista siempre se acompaña de la silaba inicial de la palabra.
ATRIBUTO_SILABA = "silaba_inicial"
NOMBRE_MEJORA = {"mas_uno": "el +1", "menos_uno": "el -1", "escudo": "el escudo"}

VOCALES = "aeiouáéíóúü"
FUERTES = "aeoáéó"
DEBILES = "iu"
DESFONEMAS = ("ch", "ll", "rr")
ATAQUES = ("bl", "br", "cl", "cr", "ch", "dr", "fl", "fr", "gl", "gr", "ll", "pl", "pr", "rr", "tr")


def silaba_inicial(palabra: str) -> str:
    """Primera silaba por heuristica del espanol: ataque + nucleo (+ diptongo) + coda.

    Reglas aplicadas: VCV corta en la vocal; VCCV deja la segunda consonante en la
    silaba siguiente solo si puede atacar sola (pr, bl, ch...); las consonantes finales
    cierran la silaba; i/u atonas forman diptongo, con tilde forman hiato.
    """
    w = (palabra or "").strip().lower()
    if not w:
        return ""
    i = 0
    while i < len(w) and w[i] not in VOCALES:
        i += 1
    if i == len(w):
        return w.upper()

    def diptongo(a: str, b: str) -> bool:
        return (a in FUERTES and b in DEBILES) or (a in DEBILES and b in FUERTES) or (
            a in DEBILES and b in DEBILES
        )

    fin = i + 1
    while fin < len(w) and diptongo(w[fin - 1], w[fin]):
        fin += 1
    j = fin
    while j < len(w) and w[j] not in VOCALES:
        j += 1
    grupo = w[fin:j]
    if j == len(w):
        fin = len(w)
    elif len(grupo) >= 2 and grupo[:2] not in DESFONEMAS and grupo[:2] not in ATAQUES:
        fin += 1
    return w[:fin].upper()


def picto_silaba(palabra: str) -> Optional[dict]:
    """Pictograma de respaldo (texto grande) con la silaba inicial de la palabra."""
    silaba = silaba_inicial(palabra)
    if not silaba:
        return None
    return {
        "atributo": ATRIBUTO_SILABA,
        "texto": f"sílaba {silaba}",
        "emoji": f"🔤{silaba}",
        "arasaac_id": None,
    }


@dataclass
class SolicitudAyuda:
    fase: str
    suma: int = 0
    visible: int = 3
    mejora: Optional[str] = None
    mejora_activa: Optional[str] = None
    puede_pedir: bool = True
    intentos: int = 0
    nivel: int = 2
    carta_id: Optional[str] = None
    candidatos: List[str] = field(default_factory=list)
    pistas_usadas: List[str] = field(default_factory=list)


@dataclass
class RespuestaAyuda:
    accion: str
    texto: str
    razon: str
    pictos: str
    pista: Optional[dict] = None
    confianza: float = 0.0
    origen: str = "red_neuronal"
    prediccion: str = ""
    silaba: Optional[dict] = None

    def a_dict(self) -> dict:
        return {
            "accion": self.accion,
            "texto": self.texto,
            "razon": self.razon,
            "pictos": self.pictos,
            "pista": self.pista,
            "silaba": self.silaba,
            "confianza": round(float(self.confianza), 4),
            "origen": self.origen,
            "prediccion": self.prediccion,
        }


def _indice_mejora(nombre: Optional[str]) -> int:
    try:
        return MEJORAS.index(nombre) if nombre in MEJORAS else 0
    except ValueError:
        return 0


class Orientador:
    def __init__(
        self,
        catalogo: Catalogo,
        ruta_modelo: Path = RUTA_MODELO,
        ruta_metricas: Path = RUTA_METRICAS,
        semilla: int = 7,
        forzar_entrenamiento: bool = False,
    ):
        self.catalogo = catalogo
        self.ruta_modelo = Path(ruta_modelo)
        self.ruta_metricas = Path(ruta_metricas)
        self.semilla = int(semilla)
        self.consejero = self._cargar_consejero()
        self.metricas: dict = self._cargar_metricas()
        self.red: Optional[MLP] = None

        if not forzar_entrenamiento:
            try:
                self.red = MLP.cargar(self.ruta_modelo)
            except Exception:
                self.red = None

        if self.red is None:
            self.metricas = self.entrenar(verbose=False)

    # ------------------------------------------------------------------ setup

    def _cargar_consejero(self):
        try:
            if RUTA_POLITICA.exists():
                return ConsejeroTabular.desde_archivo(RUTA_POLITICA, origen="q")
        except Exception:
            pass
        return ConsejeroHeuristico()

    @property
    def origen_etiquetas(self) -> str:
        return "politica_q" if isinstance(self.consejero, ConsejeroTabular) else "heuristica"

    def _cargar_metricas(self) -> dict:
        try:
            return json.loads(self.ruta_metricas.read_text(encoding="utf-8"))
        except Exception:
            return {}

    # --------------------------------------------------------------- dataset

    def entrenar(self, verbose: bool = False, n_contextos: int = 4) -> dict:
        """Genera el dataset por imitacion, entrena la red y guarda modelo + metricas."""
        X, y, resumen = self._dataset(n_contextos=n_contextos)
        idx_train, idx_val = division_estratificada(y, 0.2, self.semilla)

        red = MLP(
            n_in=X.shape[1],
            n_hidden=(64, 32),
            n_out=len(CLASES),
            clases=CLASES,
            semilla=self.semilla,
        )
        historial = red.entrenar(
            X[idx_train], y[idx_train], X[idx_val], y[idx_val],
            epocas=300, lote=64, lr=1e-3, l2=1e-4, paciencia=40, verbose=verbose,
        )
        pred = red.predecir(X[idx_val])
        metricas = metricas_clasificacion(y[idx_val], pred, CLASES)
        metricas.update({
            "muestras": resumen,
            "historial": historial,
            "origen_etiquetas": self.origen_etiquetas,
            "semilla": self.semilla,
            "arquitectura": "20-64-32-6",
        })

        red.guardar(self.ruta_modelo)
        self.ruta_metricas.parent.mkdir(parents=True, exist_ok=True)
        self.ruta_metricas.write_text(
            json.dumps(metricas, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.red = red
        self.metricas = metricas
        return metricas

    def _dataset(self, n_contextos: int = 4):
        X: List[np.ndarray] = []
        y: List[int] = []
        resumen = {
            "total": 0,
            "reconocer": 0,
            "decidir": 0,
            "por_clase": {c: 0 for c in CLASES},
        }

        # Reconocer: se recorren las sesiones de pistas reales de cada escenario.
        escenarios = cargar_escenarios()
        for esc in escenarios["escenarios"].values():
            candidatos = [self.catalogo.cartas[i] for i in dict.fromkeys(esc["mazo"])]
            for objetivo in candidatos:
                usadas: List[str] = []
                while True:
                    pista = self._elegir_pista(objetivo, candidatos, usadas)
                    for intentos in (0, 1, 2):
                        for _ in range(n_contextos):
                            sol = self._solicitud_reconocer(objetivo, usadas, intentos)
                            revelar = (
                                pista is None
                                and intentos >= 2
                                and len(usadas) >= 2
                            )
                            clase = "pista" if pista is not None else (
                                "revelar" if revelar else "animo"
                            )
                            X.append(self._vector(
                                sol,
                                self._semanticas_restantes(objetivo, usadas),
                                len(usadas),
                                revelar,
                                "primera_letra" in usadas,
                                "num_letras" in usadas,
                            ))
                            y.append(CLASES.index(clase))
                            resumen["reconocer"] += 1
                            resumen["por_clase"][clase] += 1
                    if pista is None:
                        break
                    usadas.append(pista.atributo)

        # Decidir: se etiqueta con la politica tabular o la heuristica.
        for suma in range(0, 22):
            for visible in range(3, 9):
                for md in range(4):
                    for ma in range(4):
                        for puede in (False, True):
                            sol = SolicitudAyuda(
                                fase="decidir",
                                suma=suma,
                                visible=visible,
                                mejora=MEJORAS[md],
                                mejora_activa=MEJORAS[ma],
                                puede_pedir=puede,
                                intentos=0,
                                nivel=2,
                            )
                            clase, _, _ = self._decision_experta(sol)
                            if clase not in CLASES:
                                continue
                            X.append(self._vector(sol, 0, 0, False, False, False))
                            y.append(CLASES.index(clase))
                            resumen["decidir"] += 1
                            resumen["por_clase"][clase] += 1

        resumen["total"] = len(y)
        return (
            np.asarray(X, dtype=np.float64),
            np.asarray(y, dtype=np.int64),
            resumen,
        )

    def _solicitud_reconocer(self, objetivo: Carta, usadas: Sequence[str], intentos: int) -> SolicitudAyuda:
        # El puntaje y las mejoras no influyen en la eleccion de pista; se fijan
        # para que la red aprenda la politica de ayuda y no ruido del estado.
        return SolicitudAyuda(
            fase="reconocer",
            suma=0,
            visible=5,
            mejora=None,
            mejora_activa=None,
            puede_pedir=False,
            intentos=int(intentos),
            nivel=2,
            carta_id=objetivo.id,
            candidatos=[],
            pistas_usadas=list(usadas),
        )

    # -------------------------------------------------------------- features

    def _objetivo(self, sol: SolicitudAyuda) -> Optional[Carta]:
        return self.catalogo.cartas.get(sol.carta_id) if sol.carta_id else None

    def _candidatos(self, sol: SolicitudAyuda) -> List[Carta]:
        vistos = dict.fromkeys(sol.candidatos or [])
        cands = [self.catalogo.cartas[i] for i in vistos if i in self.catalogo.cartas]
        return cands or list(self.catalogo.cartas.values())

    def _elegir_pista(
        self, objetivo: Carta, candidatos: Sequence[Carta], usadas: Sequence[str]
    ) -> Optional[Pista]:
        """Primero la ganancia ID3 y, agotada, los atributos descriptivos que faltan.

        El baseline corta en cuanto la carta queda identificada, pero un jugador que
        vuelve a pedir ayuda todavia puede aprovechar el resto de los atributos.
        """
        pista = mejor_pista(objetivo, candidatos, usadas, self.catalogo)
        if pista is not None:
            return pista
        for atributo in [*self.catalogo.atributos, *ATRIBUTOS_RESPALDO]:
            if atributo in usadas:
                continue
            v = valor_atributo(objetivo, atributo)
            if not v:
                continue
            picto = _picto_de(atributo, str(v), self.catalogo)
            return Pista(
                atributo=atributo,
                valor=str(v),
                texto=picto["texto"],
                emoji=picto.get("emoji", ""),
                arasaac_id=picto.get("arasaac_id"),
                ganancia=0.0,
                candidatos_antes=len(candidatos),
                candidatos_despues=len(candidatos),
            )
        return None

    def _pistas_usadas(self, sol: SolicitudAyuda) -> List[str]:
        vistas = set()
        salida: List[str] = []
        for atributo in sol.pistas_usadas or []:
            # La silaba inicial acompana a la pista, no es un atributo ID3.
            if atributo and atributo != ATRIBUTO_SILABA and atributo not in vistas:
                vistas.add(atributo)
                salida.append(atributo)
        return salida

    def _semanticas_restantes(self, objetivo: Optional[Carta], usadas: Sequence[str]) -> int:
        if objetivo is None:
            return 0
        return sum(
            1 for a in self.catalogo.atributos
            if objetivo.atributos.get(a) and a not in usadas
        )

    def _vector(
        self,
        sol: SolicitudAyuda,
        semanticas: int,
        n_pistas: int,
        revelar: bool,
        letra_usada: bool,
        num_usada: bool,
    ) -> np.ndarray:
        md = _indice_mejora(sol.mejora)
        ma = _indice_mejora(sol.mejora_activa)
        suma = min(21, max(0, int(sol.suma)))
        visible = min(8, max(3, int(sol.visible)))
        nivel = min(3, max(1, int(sol.nivel)))
        faltan = max(0, 21 - suma)
        fase = 1.0 if sol.fase == "decidir" else 0.0
        puede = 1.0 if (sol.puede_pedir and sol.fase == "decidir" and suma < 21) else 0.0
        one_md = [1.0 if md == i else 0.0 for i in range(4)]
        one_ma = [1.0 if ma == i else 0.0 for i in range(4)]
        return np.asarray([
            fase,
            min(2, max(0, int(sol.intentos))) / 2.0,
            min(7, max(0, int(n_pistas))) / 7.0,
            (nivel - 1) / 2.0,
            suma / 21.0,
            (visible - 3) / 5.0,
            faltan / 21.0,
            *one_md,
            *one_ma,
            puede,
            1.0 if revelar else 0.0,
            min(5, max(0, int(semanticas))) / 5.0,
            1.0 if letra_usada else 0.0,
            1.0 if num_usada else 0.0,
        ], dtype=np.float64)

    # ------------------------------------------------------------- inferencia

    def sugerir(self, sol: SolicitudAyuda) -> Optional[RespuestaAyuda]:
        fase = (sol.fase or "").strip().lower()
        if fase not in FASES:
            return None
        sol = replace(sol, fase=fase)

        objetivo = self._objetivo(sol)
        usadas = self._pistas_usadas(sol)
        semanticas = self._semanticas_restantes(objetivo, usadas)
        letra = "primera_letra" in usadas
        num = "num_letras" in usadas

        pista = None
        if fase == "reconocer" and objetivo is not None:
            pista = self._elegir_pista(objetivo, self._candidatos(sol), usadas)

        revelar = (
            fase == "reconocer"
            and pista is None
            and int(sol.intentos) >= 2
            and len(usadas) >= 2
        )

        x = self._vector(sol, semanticas, len(usadas), revelar, letra, num)
        proba = self.red.predecir_proba(x)[0]
        valida = self._mascara(sol, pista, revelar)
        masked = np.where(valida, proba, 0.0)
        total = float(masked.sum())
        if total <= 0.0:
            return None
        masked = masked / total
        idx = int(np.argmax(masked))
        confianza = float(masked[idx])
        clase = CLASES[idx]

        if confianza < UMBRAL_CONFIANZA:
            return self._respaldo(sol, objetivo, usadas, pista, revelar, confianza)

        return self._ejecutar(
            clase, sol, objetivo, usadas, pista, revelar,
            confianza, "red_neuronal", clase,
        )

    def _mascara(self, sol: SolicitudAyuda, pista, revelar: bool) -> np.ndarray:
        m = np.zeros(len(CLASES), dtype=bool)
        if sol.fase == "decidir":
            suma = int(sol.suma)
            if suma <= 21:
                m[CLASES.index("parar")] = True
            if sol.puede_pedir and suma < 21:
                m[CLASES.index("pedir")] = True
            if suma < 21 and sol.mejora and not sol.mejora_activa:
                m[CLASES.index("usar_mejora")] = True
        else:
            if pista is not None:
                m[CLASES.index("pista")] = True
            m[CLASES.index("animo")] = True
            if revelar:
                m[CLASES.index("revelar")] = True
        return m

    def _respaldo(
        self,
        sol: SolicitudAyuda,
        objetivo: Optional[Carta],
        usadas: Sequence[str],
        pista,
        revelar: bool,
        confianza: float,
    ) -> RespuestaAyuda:
        if sol.fase == "decidir":
            clase, razon, pictos = self._decision_experta(sol)
            return self._respuesta_decision(
                clase, sol, confianza, "respaldo_experto", "experto", razon, pictos
            )
        if pista is not None:
            return self._respuesta_pista(
                sol, objetivo, pista, confianza, "respaldo_experto", "experto"
            )
        if revelar:
            return self._respuesta_revelar(
                sol, objetivo, usadas, confianza, "respaldo_experto", "experto"
            )
        return self._respuesta_animo(
            sol, objetivo, usadas, confianza, "respaldo_experto", "experto"
        )

    def _ejecutar(
        self,
        clase: str,
        sol: SolicitudAyuda,
        objetivo: Optional[Carta],
        usadas: Sequence[str],
        pista,
        revelar: bool,
        confianza: float,
        origen: str,
        prediccion: str,
    ) -> RespuestaAyuda:
        if clase in ("pedir", "parar", "usar_mejora"):
            return self._respuesta_decision(
                clase, sol, confianza, origen, prediccion
            )
        if clase == "pista":
            if pista is not None:
                return self._respuesta_pista(
                    sol, objetivo, pista, confianza, origen, prediccion
                )
            return self._respaldo(sol, objetivo, usadas, pista, revelar, confianza)
        if clase == "revelar":
            if revelar:
                return self._respuesta_revelar(
                    sol, objetivo, usadas, confianza, origen, prediccion
                )
            return self._respuesta_animo(sol, objetivo, usadas, confianza, origen, prediccion)
        return self._respuesta_animo(sol, objetivo, usadas, confianza, origen, prediccion)

    # ----------------------------------------------------------- respuestas

    def _respuesta_pista(
        self,
        sol: SolicitudAyuda,
        objetivo: Optional[Carta],
        pista,
        confianza: float,
        origen: str,
        prediccion: str,
    ) -> RespuestaAyuda:
        pictos = f"[{pista.emoji} {pista.texto.upper()}]" if pista.emoji else f"[{pista.texto.upper()}]"
        silaba = picto_silaba(objetivo.palabra) if objetivo is not None else None
        texto = f"Pista: {pista.texto}."
        if silaba:
            pictos = f"{pictos} + [{silaba['emoji']}]"
            texto = f"Pista: {pista.texto}, {silaba['texto']}."
        datos = {
            "atributo": pista.atributo,
            "texto": pista.texto,
            "emoji": pista.emoji,
            "arasaac_id": pista.arasaac_id,
            "ganancia": round(float(pista.ganancia), 4),
            "candidatos_antes": int(pista.candidatos_antes),
            "candidatos_despues": int(pista.candidatos_despues),
        }
        return RespuestaAyuda(
            "pista",
            texto,
            pista.texto,
            pictos,
            datos,
            confianza,
            origen,
            prediccion,
            silaba,
        )

    def _respuesta_revelar(
        self,
        sol: SolicitudAyuda,
        objetivo: Optional[Carta],
        usadas: Sequence[str],
        confianza: float,
        origen: str,
        prediccion: str,
    ) -> RespuestaAyuda:
        if objetivo is None:
            return self._respuesta_animo(sol, objetivo, usadas, confianza, origen, prediccion)
        texto = f"La palabra es {objetivo.palabra.upper()}."
        return RespuestaAyuda(
            "revelar",
            texto,
            "Ya viste todas las pistas.",
            f"[{objetivo.emoji} {objetivo.palabra.upper()}]",
            None,
            confianza,
            origen,
            prediccion,
        )

    def _respuesta_animo(
        self,
        sol: SolicitudAyuda,
        objetivo: Optional[Carta],
        usadas: Sequence[str],
        confianza: float,
        origen: str,
        prediccion: str,
    ) -> RespuestaAyuda:
        """No hay tope de ayudas: si se agotaron los atributos, se vuelven a mostrar.

        La clase seguida es "animo", asi la red no necesita reentrenarse; lo unico que
        cambia es el contenido, que pasa a ser el repaso de las pistas ya entregadas
        mas la silaba inicial.
        """
        pictos: List[str] = []
        textos: List[str] = []
        if sol.fase == "reconocer" and objetivo is not None:
            for atributo in usadas:
                v = valor_atributo(objetivo, atributo)
                if not v:
                    continue
                p = _picto_de(atributo, str(v), self.catalogo)
                textos.append(p["texto"])
                pictos.append(f"[{p['emoji']} {p['texto'].upper()}]" if p["emoji"] else f"[{p['texto'].upper()}]")
        if not textos:
            texto = "Repasa las pistas que ya tienes. Tú puedes."
            return RespuestaAyuda(
                "animo", texto, texto, "[💪 TÚ PUEDES]", None, confianza, origen, prediccion
            )
        silaba = picto_silaba(objetivo.palabra)
        if silaba:
            pictos.append(f"[{silaba['emoji']}]")
            textos.append(silaba["texto"])
        texto = "Repasa: " + ", ".join(textos) + "."
        return RespuestaAyuda(
            "animo", texto, texto, " + ".join(pictos), None, confianza, origen, prediccion, silaba
        )

    def _respuesta_decision(
        self,
        clase: str,
        sol: SolicitudAyuda,
        confianza: float,
        origen: str,
        prediccion: str,
        razon: Optional[str] = None,
        pictos: Optional[str] = None,
    ) -> RespuestaAyuda:
        if clase not in ("pedir", "parar", "usar_mejora"):
            clase = "parar"
        suma = int(sol.suma)
        faltan = max(0, 21 - suma)
        if clase == "pedir":
            razon = razon or f"Te faltan {faltan}. Pide otra carta."
            pictos = pictos or "[👍 PEDIR] + [🃏 CARTA]"
        elif clase == "parar":
            razon = razon or f"Tienes {suma}. Mejor para."
            pictos = pictos or "[✋ PARAR]"
        else:
            nombre = NOMBRE_MEJORA.get(sol.mejora or "", "la mejora")
            razon = razon or f"Usa {nombre} ahora, te puede ayudar."
            pictos = pictos or "[⭐ MEJORA]"
        accion = "mejora" if clase == "usar_mejora" else clase
        return RespuestaAyuda(
            accion, razon, razon, pictos, None, confianza, origen, prediccion
        )

    # ------------------------------------------------------------- experto

    def _decision_experta(self, sol: SolicitudAyuda) -> Tuple[str, str, str]:
        estado = self._estado_para_consejero(sol)
        sug = self.consejero.sugerir(estado, self.catalogo)
        if sug is None:
            return "parar", f"Tienes {sol.suma}. Mejor para.", "[✋ PARAR]"
        tipo = sug.accion.tipo
        if tipo == "usar_mejora":
            clase = "usar_mejora"
        elif tipo == "plantarse":
            clase = "parar"
        else:
            clase = "pedir"
        return clase, sug.razon, sug.pictos

    def _estado_para_consejero(self, sol: SolicitudAyuda) -> EstadoJuego:
        visible = min(8, max(3, int(sol.visible)))
        carta_visible = next(
            (c.id for c in self.catalogo.cartas.values() if c.valor == visible),
            next(iter(self.catalogo.cartas)),
        )
        primera = next(iter(self.catalogo.cartas))
        return EstadoJuego(
            escenario_id="orientador",
            objetivo=21,
            crupier_se_planta=17,
            mazo=[primera] if sol.puede_pedir else [],
            carta_visible_crupier=carta_visible,
            suma_crupier=visible,
            mano_crupier=[carta_visible],
            nivel_ayuda=min(3, max(1, int(sol.nivel))),
            mejora_disponible=sol.mejora,
            mejora_activa=sol.mejora_activa,
            suma_jugador=min(21, max(0, int(sol.suma))),
            fase=Fase.DECIDIR,
        )
