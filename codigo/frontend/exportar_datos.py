"""Genera datos.js a partir de datos/catalogo.json y datos/escenarios.json.

El frontend se abre como archivo local (file://), donde fetch() no puede leer JSON,
por eso los datos se embeben como variables globales de JavaScript.

Uso: python exportar_datos.py
"""

import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DATOS = AQUI.parents[1] / "datos"

catalogo = json.loads((DATOS / "catalogo.json").read_text(encoding="utf-8"))
escenarios = json.loads((DATOS / "escenarios.json").read_text(encoding="utf-8"))

contenido = (
    "// Archivo generado por exportar_datos.py. No editar a mano.\n"
    f"const CATALOGO = {json.dumps(catalogo, ensure_ascii=False, indent=1)};\n"
    f"const ESCENARIOS = {json.dumps(escenarios, ensure_ascii=False, indent=1)};\n"
)
(AQUI / "datos.js").write_text(contenido, encoding="utf-8")
print(f"datos.js generado con {len(catalogo['cartas'])} cartas y "
      f"{len(escenarios['escenarios'])} escenarios.")
