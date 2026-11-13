# Backend (Hito 2)

Expone el validador semantico y el consejero (value iteration / Q-Learning)
al frontend. Sirve tambien la interfaz.

```bash
cd codigo
pip install -r requirements.txt
python ia_models/entrenar_hito2.py
uvicorn backend.main:app --app-dir . --reload --port 8000
```

Abrir http://127.0.0.1:8000/

| Ruta | Uso |
| --- | --- |
| `GET /api/salud` | El API esta vivo y si hay politica entrenada |
| `POST /api/validar` | `{texto, carta_id}` → ok, palabra, metodo |
| `POST /api/sugerir` | consejo pedir / parar / mejora |
