# Passer des données simulées aux vraies données

Aujourd'hui l'IA apprend sur des données **inventées**. Avec les vraies données d'un transitaire, elle devient crédible.

## 1. Ce qu'il faut demander au transitaire (anonymisé)
- **Voyages** : modèle `donnees_reelles/modele_voyages.csv` (port de départ, compagnie, dates de départ / arrivée prévue / arrivée réelle, transbordements).
- **Dossiers** : modèle `donnees_reelles/modele_dossiers.csv` (code importateur, date, chapitre SH, valeur, pays, régime, voie douane obtenue).
- Idéal : **200 lignes ou plus** dans chaque fichier. Minimum absolu : 30.
- **Anonymisation** : ne jamais donner de noms. Remplacer chaque importateur par un code (IMP-001, IMP-002…).
- Faire signer un accord écrit : usage pour un projet d'école, aucune publication des données brutes.

## 2. Comment lancer (Terminal, dossier du projet)
```
cd ~/daniel091chine-ivoire-import
python3 donnees_reelles/entrainer_donnees_reelles.py voyages  donnees_reelles/mes_voyages.csv
python3 donnees_reelles/entrainer_donnees_reelles.py dossiers donnees_reelles/mes_dossiers.csv
```
Mettez les fichiers du transitaire dans le dossier `donnees_reelles/` (ils ne seront **jamais envoyés sur GitHub** : le fichier `.gitignore` les bloque).

## 3. Lire le résultat
Le script écrit un **VERDICT** : le modèle fait-il mieux qu'une méthode simple ? Si non, on le dit honnêtement dans la présentation. Un résultat décevant sur de vraies données vaut mieux qu'un beau résultat sur des données inventées.

## 4. Limites
- Les ports doivent être dans la liste du logiciel (message d'erreur clair sinon).
- Les critères de la douane sont confidentiels : le modèle prépare un dossier, il ne prédit jamais une décision officielle.
- Brancher ces modèles réentraînés dans l'ERP est une étape suivante (le script évalue, il ne remplace pas encore le modèle de l'application).
