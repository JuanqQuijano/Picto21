"""API FastAPI del Hito 2: validador semantico, consejero MDP/Q-Learning y UI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ia_models"))

from catalogo import cargar_catalogo, cargar_escenarios  # noqa: E402
from consejero import ConsejeroHeuristico, ConsejeroTabular  # noqa: E402
from juego import PEDIR, PLANTARSE, USAR_MEJORA, EstadoJuego, Fase  # noqa: E402
from validador import ValidadorSemantico  # noqa: E402

RUTA_POLITICA = ROOT.parent / "datos" / "politica_q.json"
FRONTEND = ROOT / "frontend"

catalogo = cargar_catalogo()
escenarios = cargar_escenarios()
validador = ValidadorSemantico(catalogo)
heuristico = ConsejeroHeuristico()
try:
    consejero_q = ConsejeroTabular.desde_archivo(RUTA_POLITICA, origen="q")
    consejero_vi = ConsejeroTabular.desde_archivo(RUTA_POLITICA, origen="vi")
except FileNotFoundError:
    consejero_q = None
    consejero_vi = None

app = FastAPI(title="Picto21 Hito 2", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ValidarIn(BaseModel):
    texto: str
    carta_id: str


class SugerirIn(BaseModel):
    suma: int
    visible: int
    mejora: Optional[str] = None
    mejora_activa: Optional[str] = None
    puede_pedir: bool = True
    origen: str = Field("q", description="q | vi | heuristico")


@app.get("/api/salud")
def salud():
    return {
        "ok": True,
        "hito": 2,
        "politica": consejero_q is not None,
        "cartas": len(catalogo.cartas),
    }


@app.post("/api/validar")
def validar(body: ValidarIn):
    carta = catalogo.cartas.get(body.carta_id)
    if not carta:
        raise HTTPException(404, "carta desconocida")
    v = validador.validar(carta, body.texto)
    return {
        "ok": v.ok,
        "palabra": v.palabra,
        "metodo": v.metodo,
        "similitud": round(v.similitud, 3),
        "valor": None if not v.palabra else len(v.palabra),
    }


@app.post("/api/sugerir")
def sugerir(body: SugerirIn):
    estado = EstadoJuego(
        escenario_id="mixto",
        objetivo=21,
        crupier_se_planta=17,
        mazo=["gato"] if body.puede_pedir else [],
        carta_visible_crupier=_carta_con_valor(body.visible),
        suma_crupier=body.visible,
        mano_crupier=[],
        nivel_ayuda=2,
        mejora_disponible=body.mejora,
        mejora_activa=body.mejora_activa,
        suma_jugador=body.suma,
        fase=Fase.DECIDIR,
    )
    origen = body.origen
    if origen == "vi" and consejero_vi is not None:
        sug = consejero_vi.sugerir(estado, catalogo)
    elif origen != "heuristico" and consejero_q is not None:
        sug = consejero_q.sugerir(estado, catalogo)
        origen = "q"
    else:
        sug = heuristico.sugerir(estado, catalogo)
        origen = "heuristico"
    if sug is None:
        return {"accion": None, "razon": "", "origen": origen}
    nombre = {PEDIR: "pedir", PLANTARSE: "parar", USAR_MEJORA: "mejora"}[sug.accion]
    return {"accion": nombre, "razon": sug.razon, "origen": origen}


def _carta_con_valor(visible: int) -> str:
    for c in catalogo.cartas.values():
        if c.valor == visible:
            return c.id
    return next(iter(catalogo.cartas))


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="ui")
