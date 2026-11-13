"""MDP reducido del consejero de Picto21: value iteration y Q-Learning.

Estado S' = (suma, visible, mejora_disp, mejora_act)
Acciones = pedir | plantarse | usar_mejora
Recompensa terminal: +1 gana, 0 empate, -1 pierde o se pasa.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from catalogo import Catalogo, cargar_catalogo
from juego import EstadoJuego, valor_con_mejora

MEJORAS = (None, "mas_uno", "menos_uno", "escudo")
MEJ_I = {m: i for i, m in enumerate(MEJORAS)}
ACCIONES = ("pedir", "plantarse", "usar_mejora")
EstadoRed = Tuple[int, int, int, int]  # suma, visible, md, ma


def valores_cartas(catalogo: Catalogo) -> List[int]:
    return [c.valor for c in catalogo.cartas.values()]


def dist_valores(catalogo: Catalogo) -> Dict[int, float]:
    vs = valores_cartas(catalogo)
    n = len(vs)
    d: Dict[int, float] = defaultdict(float)
    for v in vs:
        d[v] += 1.0 / n
    return dict(d)


def clamp_suma(s: int) -> int:
    return max(0, min(22, s))


def clamp_vis(v: int) -> int:
    return max(3, min(12, v))


def estado_reducido(e: EstadoJuego, catalogo: Catalogo) -> EstadoRed:
    vis = catalogo.cartas[e.carta_visible_crupier].valor
    return (
        clamp_suma(e.suma_jugador),
        clamp_vis(vis),
        MEJ_I.get(e.mejora_disponible, 0),
        MEJ_I.get(e.mejora_activa, 0),
    )


def acciones_red(s: EstadoRed) -> List[str]:
    suma, _vis, md, ma = s
    if suma > 21:
        return []
    out = ["plantarse"]
    if suma < 21:
        out.insert(0, "pedir")
    if md != 0 and ma == 0:
        out.append("usar_mejora")
    return out


def _dp_crupier(visible: int, dist: Dict[int, float], se_planta: int = 17, objetivo: int = 21) -> Dict[int, float]:
    """P(suma final del crupier | carta visible). 22 representa 'se paso'."""
    actual = {visible: 1.0}
    terminal: Dict[int, float] = defaultdict(float)
    for _ in range(12):
        nxt: Dict[int, float] = defaultdict(float)
        progreso = False
        for suma, p in actual.items():
            if suma >= se_planta:
                clave = 22 if suma > objetivo else suma
                terminal[clave] += p
                continue
            progreso = True
            for v, pv in dist.items():
                ns = suma + v
                nxt[ns] += p * pv
        actual = nxt
        if not progreso:
            break
    for suma, p in actual.items():
        clave = 22 if suma > objetivo else suma
        terminal[clave] += p
    return dict(terminal)


def recompensa_plantarse(suma: int, visible: int, dist: Dict[int, float]) -> float:
    if suma > 21:
        return -1.0
    esperada = 0.0
    for cs, p in _dp_crupier(visible, dist).items():
        if cs == 22 or suma > cs:
            r = 1.0
        elif suma == cs:
            r = 0.0
        else:
            r = -1.0
        esperada += p * r
    return esperada


class ModeloMDP:
    def __init__(self, catalogo: Catalogo, gamma: float = 0.97):
        self.catalogo = catalogo
        self.gamma = gamma
        self.dist = dist_valores(catalogo)
        self._r_stand: Dict[Tuple[int, int], float] = {}

    def r_stand(self, suma: int, visible: int) -> float:
        k = (suma, visible)
        if k not in self._r_stand:
            self._r_stand[k] = recompensa_plantarse(suma, visible, self.dist)
        return self._r_stand[k]

    def transiciones(self, s: EstadoRed, accion: str) -> List[Tuple[float, EstadoRed, float, bool]]:
        """Lista de (prob, s', recompensa, terminal)."""
        suma, vis, md, ma = s
        if accion == "plantarse":
            return [(1.0, s, self.r_stand(suma, vis), True)]
        if accion == "usar_mejora":
            if md == 0 or ma != 0:
                return [(1.0, s, 0.0, False)]
            return [(1.0, (suma, vis, 0, md), 0.0, False)]
        # pedir
        out: List[Tuple[float, EstadoRed, float, bool]] = []
        for v, p in self.dist.items():
            extra = MEJORAS[ma] if ma in (1, 2) else None
            nv = valor_con_mejora(v, extra)
            ma2 = 0 if extra else ma
            ns = suma + nv
            if ns > 21:
                if ma == 3:  # escudo
                    out.append((p, (suma, vis, md, 0), 0.0, False))
                else:
                    out.append((p, (22, vis, md, ma2), -1.0, True))
            elif ns == 21:
                out.append((p, (21, vis, md, ma2), self.r_stand(21, vis), True))
            else:
                out.append((p, (ns, vis, md, ma2), 0.0, False))
        return _agrupar(out)


def _agrupar(filas):
    acc: Dict[Tuple, float] = defaultdict(float)
    extra = {}
    for p, sp, r, term in filas:
        key = (sp, r, term)
        acc[key] += p
        extra[key] = (sp, r, term)
    return [(acc[k], *extra[k]) for k in acc]


def todos_estados() -> List[EstadoRed]:
    vis_vals = range(3, 13)
    return [
        (suma, vis, md, ma)
        for suma in range(0, 22)
        for vis in vis_vals
        for md in range(4)
        for ma in range(4)
    ]


def value_iteration(modelo: ModeloMDP, theta: float = 1e-4, max_it: int = 80) -> Tuple[dict, dict]:
    estados = todos_estados()
    V = {s: 0.0 for s in estados}
    for s in estados:
        if s[0] > 21:
            V[s] = -1.0
    for _ in range(max_it):
        delta = 0.0
        for s in estados:
            acts = acciones_red(s)
            if not acts:
                continue
            mejor = max(_q_sa(modelo, V, s, a) for a in acts)
            delta = max(delta, abs(mejor - V[s]))
            V[s] = mejor
        if delta < theta:
            break
    pi = {}
    for s in estados:
        acts = acciones_red(s)
        if not acts:
            continue
        pi[s] = max(acts, key=lambda a: _q_sa(modelo, V, s, a))
    return V, pi


def _q_sa(modelo: ModeloMDP, V: dict, s: EstadoRed, a: str) -> float:
    q = 0.0
    for p, sp, r, term in modelo.transiciones(s, a):
        q += p * (r if term else r + modelo.gamma * V.get(sp, 0.0))
    return q


def q_learning(
    modelo: ModeloMDP,
    episodios: int = 40000,
    alpha: float = 0.15,
    eps_0: float = 0.35,
    semilla: int = 7,
) -> Tuple[dict, List[float]]:
    rng = random.Random(semilla)
    Q: Dict[EstadoRed, Dict[str, float]] = defaultdict(lambda: {a: 0.0 for a in ACCIONES})
    curva: List[float] = []
    ventana = 0.0
    vis_ops = list(range(3, 13))

    for ep in range(1, episodios + 1):
        s: EstadoRed = (0, rng.choice(vis_ops), rng.choice(range(4)), 0)
        G = 0.0
        for _ in range(24):
            acts = acciones_red(s)
            if not acts:
                break
            eps = eps_0 * (1 - ep / episodios)
            if rng.random() < eps:
                a = rng.choice(acts)
            else:
                a = max(acts, key=lambda x: Q[s][x])
            trans = modelo.transiciones(s, a)
            p_acum, u = 0.0, rng.random()
            sp, r, term = trans[-1][1], trans[-1][2], trans[-1][3]
            for p, nsp, nr, nterm in trans:
                p_acum += p
                if u <= p_acum:
                    sp, r, term = nsp, nr, nterm
                    break
            acts2 = acciones_red(sp)
            max_next = max((Q[sp][x] for x in acts2), default=0.0) if not term else 0.0
            Q[s][a] += alpha * (r + modelo.gamma * max_next - Q[s][a])
            G += r
            s = sp
            if term:
                break
        ventana = 0.99 * ventana + 0.01 * G if ep > 1 else G
        if ep % 2000 == 0:
            curva.append(round(ventana, 4))
    return {k: dict(v) for k, v in Q.items()}, curva


def politica_q(Q: dict) -> dict:
    pi = {}
    for s, qs in Q.items():
        acts = acciones_red(s)
        if acts:
            pi[s] = max(acts, key=lambda a: qs.get(a, 0.0))
    return pi


def clave(s: EstadoRed) -> str:
    return ",".join(map(str, s))


def parse_clave(k: str) -> EstadoRed:
    a, b, c, d = (int(x) for x in k.split(","))
    return (a, b, c, d)


def serializar(V, pi_vi, Q, pi_q, curva, metricas) -> dict:
    return {
        "pi_vi": {clave(s): a for s, a in pi_vi.items()},
        "pi_q": {clave(s): a for s, a in pi_q.items()},
        "q": {clave(s): qs for s, qs in Q.items()},
        "curva_q": curva,
        "metricas": metricas,
    }


def cargar_politica(ruta: Path) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))
