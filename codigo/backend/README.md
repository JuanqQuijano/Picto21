# Backend (Hito 2)

Expone el validador semantico, el consejero (value iteration / Q-Learning) y el
agente orientador neuronal al frontend. Sirve tambien la interfaz.

```bash
cd codigo
pip install -r requirements.txt
python ia_models/entrenar_hito2.py
python ia_models/entrenar_orientador.py
uvicorn backend.main:app --app-dir . --reload --port 8000
```

Abrir http://127.0.0.1:8000/

| Ruta | Uso |
| --- | --- |
| `GET /api/salud` | El API esta vivo, si hay politica y si cargo el orientador |
| `POST /api/validar` | `{texto, carta_id}` → ok, palabra, metodo |
| `POST /api/sugerir` | consejo pedir / parar / mejora |
| `POST /api/orientar` | ayuda a pedido: pista / repaso / revelar o pedir / parar / mejora |
