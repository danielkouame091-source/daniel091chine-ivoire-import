"""Prévision de trésorerie (flux net hebdomadaire) à court (4 sem.) et moyen terme (13 sem.).

Modèles :
- Références : naïf saisonnier, moyenne mobile.
- ML : Gradient Boosting sur retards et variables calendaires (prévision multi-horizons « directe »).
- Réseau de neurones : MLP scikit-learn (toujours disponible).
- Deep learning : LSTM / GRU PyTorch (si `torch` installé) — voir `PrevisionneurRNN`.
Évaluation : validation à origine glissante (rolling-origin), MAE / RMSE / MASE, et intervalle de
prévision empirique par quantiles des résidus.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from ..ml.metrics import metriques_regression

try:
    import torch
    from torch import nn
    TORCH_OK = True
except Exception:                                      # pragma: no cover
    torch, nn, TORCH_OK = None, None, False


def naif_saisonnier(y: np.ndarray, horizon: int, periode: int = 52) -> np.ndarray:
    y = np.asarray(y, float)
    if len(y) < periode:
        return np.full(horizon, y[-min(len(y), 4):].mean())
    return np.array([y[-periode + (h % periode)] for h in range(horizon)])


def moyenne_mobile(y: np.ndarray, horizon: int, fenetre: int = 8) -> np.ndarray:
    return np.full(horizon, np.asarray(y, float)[-fenetre:].mean())


def _variables_retard(y: np.ndarray, t_cible: int, nb_retards: int, dates: pd.DatetimeIndex) -> list[float]:
    retards = [y[t_cible - k] for k in range(1, nb_retards + 1)]
    d = dates[t_cible]
    sem = int(d.isocalendar().week)
    saison = [y[t_cible - 52 + j] if t_cible - 52 + j < t_cible and t_cible - 52 + j >= 0 else 0.0 for j in (-1, 0, 1)]
    return retards + saison + [np.mean(y[t_cible - 4:t_cible]), np.mean(y[t_cible - 13:t_cible]), sem / 52.0,
                               (sem % 4 == 0) * 1.0, (sem % 13 == 0) * 1.0]


class PrevisionneurDirect:
    """Un modèle par horizon h (stratégie directe) : y_{t+h} = f(retards à t). `modele` = 'gb' ou 'mlp'."""

    def __init__(self, horizon: int = 13, nb_retards: int = 26, modele: str = "gb", seed: int = 0):
        self.h, self.p, self.nom, self.seed = horizon, nb_retards, modele, seed
        self.modeles: list = []
        self.scaler = StandardScaler()
        self.residus_: np.ndarray = np.array([0.0])

    def _fabrique(self):
        if self.nom == "gb":
            return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.06, max_iter=200, random_state=self.seed)
        return MLPRegressor(hidden_layer_sizes=(32, 16), alpha=1e-2, max_iter=1500, early_stopping=False,
                            random_state=self.seed)

    def fit(self, serie: pd.Series) -> "PrevisionneurDirect":
        y, dates = serie.to_numpy(float), pd.DatetimeIndex(serie.index)
        self.mu, self.sd = y.mean(), y.std() or 1.0
        yn = (y - self.mu) / self.sd
        self.modeles, res = [], []
        for h in range(1, self.h + 1):
            lignes, cibles = [], []
            for t in range(max(self.p, 53), len(y) - h + 1):
                lignes.append(_variables_retard(yn, t, self.p, dates))
                cibles.append(yn[t + h - 1])
            X, c = np.array(lignes), np.array(cibles)
            ok = ~np.isnan(c)
            X, c = X[ok], c[ok]
            if self.nom == "mlp":
                sc = StandardScaler().fit(X)
                m = self._fabrique().fit(sc.transform(X), c)
                m._sc = sc
            else:
                m = self._fabrique().fit(X, c)
            self.modeles.append(m)
            pred = m.predict(m._sc.transform(X) if self.nom == "mlp" else X)
            res.append((c - pred) * self.sd)
        self.residus_ = np.concatenate(res) if res else np.array([0.0])
        self.serie_ = serie
        return self

    def predict(self, alpha: float = 0.1) -> pd.DataFrame:
        """Prévision + intervalle empirique [alpha/2, 1−alpha/2] à partir des résidus d'entraînement
        (sous-estime l'incertitude hors échantillon : à documenter)."""
        y, dates = self.serie_.to_numpy(float), pd.DatetimeIndex(self.serie_.index)
        yn = (y - self.mu) / self.sd
        t = len(y)
        # la dernière ligne de variables utilise des retards jusqu'à t-1 : on prolonge d'un pas fictif
        yn_ext = np.append(yn, yn[-1])
        dates_ext = dates.append(pd.DatetimeIndex([dates[-1] + pd.Timedelta(weeks=1)]))
        x = np.array([_variables_retard(yn_ext, t, self.p, dates_ext)])
        preds = []
        for m in self.modeles:
            xx = m._sc.transform(x) if self.nom == "mlp" else x
            preds.append(float(m.predict(xx)[0]) * self.sd + self.mu)
        futur = pd.date_range(dates[-1] + pd.Timedelta(weeks=1), periods=len(preds), freq="W-MON")
        lo, hi = np.quantile(self.residus_, [alpha / 2, 1 - alpha / 2])
        return pd.DataFrame({"prevision": preds, "bas": np.array(preds) + lo, "haut": np.array(preds) + hi}, index=futur)


def evaluer_previsions(serie: pd.Series, horizon: int = 13, origines: int = 4, pas: int = 13,
                       modeles: tuple[str, ...] = ("naif", "moyenne_mobile", "gb", "mlp")) -> pd.DataFrame:
    """Rolling-origin : pour chaque origine, on ajuste sur le passé et on prédit les `horizon` semaines suivantes."""
    lignes = []
    n = len(serie)
    debuts = [n - horizon - k * pas for k in range(origines)][::-1]
    for d in debuts:
        train, test = serie.iloc[:d], serie.iloc[d:d + horizon].to_numpy()
        for nom in modeles:
            if nom == "naif":
                p = naif_saisonnier(train.to_numpy(), horizon)
            elif nom == "moyenne_mobile":
                p = moyenne_mobile(train.to_numpy(), horizon)
            elif nom in ("gb", "mlp"):
                p = PrevisionneurDirect(horizon, modele=nom).fit(train).predict()["prevision"].to_numpy()
            elif nom in ("lstm", "gru") and TORCH_OK:
                p = PrevisionneurRNN(horizon, cellule=nom).fit(train).predict()["prevision"].to_numpy()
            else:
                continue
            for h_cible in ("court_terme", "moyen_terme"):
                k = 4 if h_cible == "court_terme" else horizon
                m = metriques_regression(test[:k], p[:k], train.to_numpy())
                lignes.append({"modele": nom, "horizon": h_cible, "origine": d, **m})
    df = pd.DataFrame(lignes)
    return df.groupby(["modele", "horizon"])[["mae", "rmse", "mase"]].mean().reset_index()


if TORCH_OK:                                           # pragma: no cover - dépend de PyTorch (non testé ici)
    class _ReseauRNN(nn.Module):
        def __init__(self, cellule: str = "lstm", entree: int = 1, cache: int = 48, couches: int = 2,
                     sortie: int = 13, dropout: float = 0.1):
            super().__init__()
            rnn = nn.LSTM if cellule == "lstm" else nn.GRU
            self.rnn = rnn(entree, cache, num_layers=couches, batch_first=True,
                           dropout=dropout if couches > 1 else 0.0)
            self.tete = nn.Sequential(nn.Linear(cache, cache), nn.ReLU(), nn.Linear(cache, sortie))

        def forward(self, x):
            sortie, _ = self.rnn(x)
            return self.tete(sortie[:, -1, :])

    class PrevisionneurRNN:
        """LSTM / GRU « séquence → vecteur » (multi-horizons) avec fenêtre glissante, arrêt précoce et
        graine fixe. Entrées normalisées (moyenne/écart-type du train). ATTENTION : cette classe n'a pas
        été exécutée dans l'environnement de rédaction (PyTorch indisponible) ; lancez
        `python scripts/run_pipeline.py --avec-dl` pour la valider chez vous."""

        def __init__(self, horizon: int = 13, fenetre: int = 52, cellule: str = "lstm", epochs: int = 150,
                     lr: float = 5e-3, seed: int = 0, patience: int = 15):
            self.h, self.w, self.cellule, self.epochs, self.lr, self.seed, self.patience = horizon, fenetre, cellule, epochs, lr, seed, patience

        def fit(self, serie: pd.Series) -> "PrevisionneurRNN":
            torch.manual_seed(self.seed)
            np.random.seed(self.seed)
            y = serie.to_numpy(float)
            self.mu, self.sd = y.mean(), y.std() or 1.0
            yn = (y - self.mu) / self.sd
            X = np.array([yn[i:i + self.w] for i in range(len(yn) - self.w - self.h + 1)])[:, :, None]
            Y = np.array([yn[i + self.w:i + self.w + self.h] for i in range(len(yn) - self.w - self.h + 1)])
            coupe = max(1, int(len(X) * 0.85))
            Xt, Yt = torch.tensor(X[:coupe], dtype=torch.float32), torch.tensor(Y[:coupe], dtype=torch.float32)
            Xv, Yv = torch.tensor(X[coupe:], dtype=torch.float32), torch.tensor(Y[coupe:], dtype=torch.float32)
            self.net = _ReseauRNN(self.cellule, sortie=self.h)
            opt = torch.optim.Adam(self.net.parameters(), lr=self.lr, weight_decay=1e-5)
            perte = nn.HuberLoss()
            meilleur, sans_progres, etat = float("inf"), 0, None
            for _ in range(self.epochs):
                self.net.train()
                opt.zero_grad()
                l = perte(self.net(Xt), Yt)
                l.backward()
                nn.utils.clip_grad_norm_(self.net.parameters(), 1.0)
                opt.step()
                self.net.eval()
                with torch.no_grad():
                    lv = perte(self.net(Xv), Yv).item() if len(Xv) else l.item()
                if lv < meilleur - 1e-5:
                    meilleur, sans_progres = lv, 0
                    etat = {k: v.clone() for k, v in self.net.state_dict().items()}
                else:
                    sans_progres += 1
                    if sans_progres >= self.patience:
                        break
            if etat:
                self.net.load_state_dict(etat)
            self.serie_ = serie
            self.residu_sd_ = float(np.sqrt(meilleur)) * self.sd if meilleur < float("inf") else self.sd
            return self

        def predict(self, alpha: float = 0.1) -> pd.DataFrame:
            y = (self.serie_.to_numpy(float) - self.mu) / self.sd
            x = torch.tensor(y[-self.w:][None, :, None], dtype=torch.float32)
            self.net.eval()
            with torch.no_grad():
                p = self.net(x).numpy()[0] * self.sd + self.mu
            futur = pd.date_range(self.serie_.index[-1] + pd.Timedelta(weeks=1), periods=self.h, freq="W-MON")
            z = 1.645 if alpha == 0.1 else 1.96
            return pd.DataFrame({"prevision": p, "bas": p - z * self.residu_sd_, "haut": p + z * self.residu_sd_}, index=futur)
else:
    class PrevisionneurRNN:                            # pragma: no cover
        def __init__(self, *a, **k):
            raise RuntimeError("PyTorch n'est pas installé : pip install torch (voir requirements-dl.txt).")
