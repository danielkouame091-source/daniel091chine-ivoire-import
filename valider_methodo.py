from finai.logistique import voyages, douane
import sndgir_methodo as M
mv, mc = voyages.entrainer().metriques, douane.entrainer().metriques
p = M.phrases_bilan(mv, mc)
assert len(p) >= 3 and "d'erreur en moins" in p[0] and "F1 moyen" in p[-1] + p[-2]
# les phrases suivent les chiffres : on truque un cas où le boosting rate des rouges
mc2 = {k: dict(v) if isinstance(v, dict) else v for k, v in mc.items()}
mc2["Gradient boosting"].update(exactitude=0.99, rappel_rouge=0.0); mc2["Régression logistique"].update(exactitude=0.5, rappel_rouge=0.9)
assert any("rate plus de dossiers rouges" in x for x in M.phrases_bilan(mv, mc2))
mc3 = {k: dict(v) if isinstance(v, dict) else v for k, v in mc.items()}
mc3["Gradient boosting"].update(exactitude=0.1)
assert not any("rate plus" in x for x in M.phrases_bilan(mv, mc3))
print("METHODO OK")
