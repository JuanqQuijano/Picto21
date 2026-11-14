"""Red neuronal (MLP) del agente orientador de Picto21.

Implementacion minima en NumPy: una red fully-connected con dos capas ocultas ReLU,
salida softmax y entrenamiento por descenso de gradiente con Adam. Se usa para
clasificar la accion de ayuda del orientador. No depende de frameworks externos
ademas de NumPy, de modo que el entrenamiento es reproducible con una semilla fija.

Uso:
    red = MLP(n_in=20, n_hidden=(64, 32), n_out=6, clases=CLASES, semilla=7)
    historial = red.entrenar(X_train, y_train, X_val, y_val)
    proba = red.predecir_proba(X_nuevo)
    red.guardar("modelos/orientador.npz")
    red = MLP.cargar("modelos/orientador.npz")
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def division_estratificada(y: np.ndarray, fraccion_val: float = 0.2, semilla: int = 7):
    """Divide indices manteniendo la proporcion de cada clase en validacion."""
    rng = np.random.default_rng(semilla)
    idx_train: List[int] = []
    idx_val: List[int] = []
    for clase in np.unique(y):
        idx = np.where(y == clase)[0]
        rng.shuffle(idx)
        if len(idx) < 2:
            idx_train.extend(idx.tolist())
            continue
        n_val = max(1, int(round(len(idx) * fraccion_val)))
        idx_val.extend(idx[:n_val].tolist())
        idx_train.extend(idx[n_val:].tolist())
    rng.shuffle(idx_train)
    rng.shuffle(idx_val)
    return np.asarray(idx_train, dtype=np.int64), np.asarray(idx_val, dtype=np.int64)


def matriz_confusion(y: np.ndarray, pred: np.ndarray, n_clases: int) -> np.ndarray:
    m = np.zeros((n_clases, n_clases), dtype=np.int64)
    for t, p in zip(y, pred):
        m[int(t), int(p)] += 1
    return m


def metricas_clasificacion(y: np.ndarray, pred: np.ndarray, clases: Sequence[str]) -> dict:
    n = len(clases)
    m = matriz_confusion(y, pred, n)
    por_clase: Dict[str, dict] = {}
    for i, nombre in enumerate(clases):
        tp = int(m[i, i])
        fp = int(m[:, i].sum() - tp)
        fn = int(m[i, :].sum() - tp)
        soporte = int(m[i, :].sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        por_clase[nombre] = {
            "precision": round(float(precision), 4),
            "recall": round(float(recall), 4),
            "f1": round(float(f1), 4),
            "soporte": soporte,
        }
    con_soporte = [v["f1"] for v in por_clase.values() if v["soporte"] > 0]
    macro_f1 = float(np.mean(con_soporte)) if con_soporte else 0.0
    return {
        "exactitud": round(float(np.mean(y == pred)), 4),
        "macro_f1": round(macro_f1, 4),
        "matriz": m.tolist(),
        "por_clase": por_clase,
        "n_validacion": int(len(y)),
    }


class MLP:
    """Perceptron multicapa  n_in -> hidden[0] -> hidden[1] -> n_out."""

    def __init__(
        self,
        n_in: int,
        n_hidden: Tuple[int, int] = (64, 32),
        n_out: int = 6,
        clases: Optional[Sequence[str]] = None,
        semilla: int = 7,
    ):
        if len(n_hidden) != 2:
            raise ValueError("n_hidden debe tener exactamente dos capas")
        self.n_in = int(n_in)
        self.n_hidden = (int(n_hidden[0]), int(n_hidden[1]))
        self.n_out = int(n_out)
        self.clases = list(clases) if clases is not None else [str(i) for i in range(n_out)]
        self.semilla = int(semilla)

        rng = np.random.default_rng(self.semilla)
        h1, h2 = self.n_hidden
        self.W1 = rng.normal(0.0, np.sqrt(2.0 / self.n_in), (self.n_in, h1))
        self.b1 = np.zeros(h1)
        self.W2 = rng.normal(0.0, np.sqrt(2.0 / h1), (h1, h2))
        self.b2 = np.zeros(h2)
        self.W3 = rng.normal(0.0, np.sqrt(2.0 / h2), (h2, self.n_out))
        self.b3 = np.zeros(self.n_out)

        self.media = np.zeros(self.n_in)
        self.desv = np.ones(self.n_in)
        self.historial: Dict[str, List[float]] = {}

    # --------------------------------------------------------------- forward

    def _forward(self, X: np.ndarray) -> np.ndarray:
        z1 = X @ self.W1 + self.b1
        a1 = np.maximum(0.0, z1)
        z2 = a1 @ self.W2 + self.b2
        a2 = np.maximum(0.0, z2)
        z3 = a2 @ self.W3 + self.b3
        return _softmax(z3)

    def predecir_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        Xn = (X - self.media) / self.desv
        return self._forward(Xn)

    def predecir(self, X: np.ndarray) -> np.ndarray:
        return np.argmax(self.predecir_proba(X), axis=1)

    # ------------------------------------------------------------- training

    def entrenar(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        epocas: int = 300,
        lote: int = 64,
        lr: float = 1e-3,
        l2: float = 1e-4,
        paciencia: int = 40,
        verbose: bool = False,
    ) -> dict:
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.int64)
        X_val = np.asarray(X_val, dtype=np.float64)
        y_val = np.asarray(y_val, dtype=np.int64)

        self.media = X.mean(axis=0)
        desv = X.std(axis=0)
        self.desv = np.where(desv < 1e-9, 1.0, desv)
        Xn = (X - self.media) / self.desv
        Xv = (X_val - self.media) / self.desv

        params = [self.W1, self.b1, self.W2, self.b2, self.W3, self.b3]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        rng = np.random.default_rng(self.semilla + 1)

        mejor_acc = -1.0
        mejor_pesos = None
        sin_mejora = 0
        paso = 0
        historial: Dict[str, List[float]] = {
            "epoca": [],
            "perdida_train": [],
            "perdida_val": [],
            "exactitud_val": [],
        }

        n = len(Xn)
        for epoca in range(1, epocas + 1):
            perm = rng.permutation(n)
            for inicio in range(0, n, lote):
                idx = perm[inicio:inicio + lote]
                xb, yb = Xn[idx], y[idx]
                nb = len(yb)

                z1 = xb @ self.W1 + self.b1
                a1 = np.maximum(0.0, z1)
                z2 = a1 @ self.W2 + self.b2
                a2 = np.maximum(0.0, z2)
                z3 = a2 @ self.W3 + self.b3
                p = _softmax(z3)

                dz3 = p.copy()
                dz3[np.arange(nb), yb] -= 1.0
                dz3 /= nb
                dW3 = a2.T @ dz3 + l2 * self.W3
                db3 = dz3.sum(axis=0)
                da2 = dz3 @ self.W3.T
                dz2 = da2 * (z2 > 0)
                dW2 = a1.T @ dz2 + l2 * self.W2
                db2 = dz2.sum(axis=0)
                da1 = dz2 @ self.W2.T
                dz1 = da1 * (z1 > 0)
                dW1 = xb.T @ dz1 + l2 * self.W1
                db1 = dz1.sum(axis=0)

                grados = [dW1, db1, dW2, db2, dW3, db3]
                paso += 1
                for j in range(len(params)):
                    m[j] = beta1 * m[j] + (1 - beta1) * grados[j]
                    v[j] = beta2 * v[j] + (1 - beta2) * (grados[j] ** 2)
                    mhat = m[j] / (1 - beta1 ** paso)
                    vhat = v[j] / (1 - beta2 ** paso)
                    params[j] -= lr * mhat / (np.sqrt(vhat) + eps)

            p_train = self._forward(Xn)
            p_val = self._forward(Xv)
            perdida_train = float(-np.mean(np.log(np.clip(p_train[np.arange(n), y], 1e-12, 1.0))))
            perdida_val = float(-np.mean(np.log(np.clip(p_val[np.arange(len(y_val)), y_val], 1e-12, 1.0))))
            acc_val = float(np.mean(np.argmax(p_val, axis=1) == y_val))

            historial["epoca"].append(epoca)
            historial["perdida_train"].append(round(perdida_train, 6))
            historial["perdida_val"].append(round(perdida_val, 6))
            historial["exactitud_val"].append(round(acc_val, 6))

            if acc_val > mejor_acc + 1e-9:
                mejor_acc = acc_val
                mejor_pesos = [p.copy() for p in params]
                sin_mejora = 0
            else:
                sin_mejora += 1

            if verbose and (epoca == 1 or epoca % 50 == 0):
                print(f"  epoca {epoca:3d}  perdida={perdida_train:.4f}  "
                      f"val={perdida_val:.4f}  acc_val={acc_val:.3f}")

            if sin_mejora >= paciencia:
                if verbose:
                    print(f"  parada temprana en la epoca {epoca} (mejor acc_val={mejor_acc:.3f})")
                break

        if mejor_pesos is not None:
            self.W1, self.b1, self.W2, self.b2, self.W3, self.b3 = mejor_pesos

        self.historial = historial
        return historial

    # ------------------------------------------------------------ persistencia

    def guardar(self, ruta: str | Path) -> None:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            ruta,
            W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2, W3=self.W3, b3=self.b3,
            media=self.media, desv=self.desv,
            clases=np.asarray(self.clases), hidden=np.asarray(self.n_hidden),
            n_in=np.asarray(self.n_in), semilla=np.asarray(self.semilla),
        )

    @classmethod
    def cargar(cls, ruta: str | Path) -> "MLP":
        datos = np.load(Path(ruta), allow_pickle=False)
        red = cls(
            n_in=int(datos["n_in"]),
            n_hidden=tuple(int(x) for x in datos["hidden"]),
            n_out=len(datos["clases"]),
            clases=[str(c) for c in datos["clases"]],
            semilla=int(datos["semilla"]),
        )
        red.W1 = datos["W1"]
        red.b1 = datos["b1"]
        red.W2 = datos["W2"]
        red.b2 = datos["b2"]
        red.W3 = datos["W3"]
        red.b3 = datos["b3"]
        red.media = datos["media"]
        red.desv = datos["desv"]
        return red
