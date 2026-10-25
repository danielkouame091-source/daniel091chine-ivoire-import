# SNDGIR & Transit ERP

Plateforme SaaS **multi-tenant** d'ERP comptable, transit douanier et fiscalité pour
les cabinets d'expertise comptable, directions financières, PME/SARL/SA et
institutions financières de **Côte d'Ivoire** et de la zone **UEMOA**.

Conçue en concurrence directe ou en intégration avec les écosystèmes de type
**Sage** et les solutions bancaires ivoiriennes (SGBCI, Ecobank…).

---

## 🚀 Démarrage rapide

```bash
# 1. Dépendances (Streamlit, pandas, reportlab, groq)
pip install -r requirements.txt

# 2. Lancer l'application (base SQLite auto-créée et peuplée au 1er démarrage)
streamlit run sndgir_erp.py

# 3. Valider le cœur métier (sans Streamlit)
python3 valider_sndgir.py
```

### Comptes de démonstration (tenant `Cabinet Excellence Comptable CI`)

| Identifiant | Mot de passe | Rôle |
|---|---|---|
| `admin` | `admin123` | Administrateur Système |
| `expert` | `expert123` | Expert-Comptable signataire |
| `collab` | `collab123` | Collaborateur |
| `auditeur` | `audit123` | Auditeur externe |

> ⚠️ **Changez ces mots de passe avant tout déploiement en production.**
> L'application vous le rappelle (bandeau dans la barre latérale) tant qu'un compte de
> démonstration est actif. Changement : barre latérale → « Changer mon mot de passe » ;
> réinitialisation d'un autre compte : Administration → Utilisateurs.
> L'écran de connexion n'affiche ces identifiants que si la variable d'environnement
> `SNDGIR_DEMO=1` est définie (`SNDGIR_DEMO=1 streamlit run sndgir_erp.py`).

### Ouvrir sans mot de passe (usage personnel, sur votre ordinateur)

```bash
SNDGIR_ACCES_DIRECT=1 streamlit run sndgir_erp.py
```
L'application s'ouvre directement avec le compte administrateur. **Ne jamais utiliser ce mode
sur internet** : sans cette option, la connexion reste obligatoire.

---

## 🧩 Périmètre fonctionnel

Le cœur applicatif tient dans un **bloc Python unique et exécutable** :
`sndgir_erp.py`.

### 1. Multi-tenant & sécurité de niveau bancaire (RegTech)
- Isolation stricte des données par entreprise cliente : **chaque requête métier
  est filtrée par `tenant_id`**.
- **5 rôles granulaires** avec permissions `<module>.<action>` :
  Administrateur Système, Expert-Comptable signataire, Collaborateur,
  Auditeur externe, Client final.
- **Piste d'audit immuable** : chaîne de hachage append-only. Chaque entrée
  embarque l'empreinte de la précédente ; toute modification ou suppression
  rétroactive est **détectée** par `verifier_audit()`.
- **Chiffrement authentifié** des données sensibles (nonce + flux HMAC-SHA256 +
  étiquette d'intégrité, encodage base64).
- **Hachage des mots de passe** : Argon2 en priorité, repli PBKDF2-HMAC-SHA256
  (200 000 itérations).
- **Politique de mots de passe** (10 caractères minimum, lettres et chiffres) et
  **blocage temporaire** du compte après 5 échecs de connexion en 15 minutes.
- **Masquage automatique des secrets** (clés API, tokens) avant journalisation.
- **Empreintes SHA-256** pour sceller les documents officiels.

### 2. Moteur comptable SYSCOHADA révisé (standards Sage)
- **Partie double stricte** : une écriture déséquilibrée ou portant un compte
  hors plan comptable est **refusée** (`ErreurComptable`).
- **Journaux auxiliaires et centraux** : Achats `ACQ`, Ventes `VTE`,
  Banque/Trésorerie `BAN`, Opérations Diverses `OD`.
- **Automatisation native des flux** — chaque opération génère ses écritures
  croisées :
  - `ecritures_frais_transit()` → débours douaniers (hors taxes), fret,
    surestaries, honoraires soumis à TVA ;
  - `ecritures_depuis_debours()` → droits et taxes (État 447100 / banque 521000) ;
  - `ecritures_surestaries()` → charge 628000 / banque ;
  - `ecritures_quittance_caisse()` → encaissement caisse 571000 / client 411000 ;
  - `ecritures_achat_import()` → entrée en stock 311000 + droits.
- **États en temps réel** : Balance Générale, Grand Livre, Journaux,
  Compte de résultat et Bilan synthétique (SYSCOHADA).

### 3. Transit, import-export & douanes (contexte ivoirien)
- **Manifestes** maritimes/aériens et **apurement des connaissements (B/L)**,
  unitaire ou automatique à l'échelle du manifeste.
- **Calcul des droits** par régime — `C100` (mise à la consommation),
  `E100` (exportation), `AT` (admission temporaire), `TR` (transit) :
  - droits de douane (DD) ;
  - **Redevance statistique** (1 %) ;
  - **Prélèvement Communautaire UEMOA** (0,8 %) ;
  - **Prélèvement Communautaire CEDEAO** (0,5 %) ;
  - **TVA 18 %** assise sur (CAF + DD + RS + PC + PCC) ;
  - les régimes `E100`, `AT` et `TR` ne donnent lieu à **aucun droit ni TVA** à payer.
- **Tarif douanier à 10 chiffres** : importez votre tarif (fichier CSV `code_sh;designation;dd;unite`)
  depuis l'onglet **Transit → Tarif & taxes**. Dans un dossier, le code SH renseigné fournit
  automatiquement le taux de DD de référence. Aucun taux officiel n'est écrit dans le code.
- **Taxes spécifiques / accises** par produit : règles configurables par préfixe SH, soit en
  % de la CAF, soit en montant par unité (kg, litre…). Elles s'ajoutent aux droits et entrent
  dans la base de la TVA (selon les sources secondaires consultées ; à confirmer).
- **Parcours officiel de dédouanement** (onglet *Parcours officiel & FNE*) : suivi pas à pas selon la
  procédure publiée par la Douane ivoirienne — compte contribuable, code importateur, compte GUCE,
  FDI, BSC, RFCV, déclaration en détail par commissionnaire agréé, canal SYDAM World, avis de
  liquidation et quittance (comptant art. 94 ou crédit), BAE. Vous saisissez les numéros issus des
  systèmes officiels ; l'application **ne s'y connecte pas**.
- **Droit Unique de Sortie (export)** : règles par code SH (% du prix de référence CIF × quantité, ou
  montant par unité). Le Conseil des ministres fixe taux et prix avant chaque campagne : rien n'est
  préchargé, vous les saisissez.
- **Facture Normalisée Électronique (FNE)** : suivi du statut de certification et du numéro FNE
  reçu de la plateforme de la DGI (obligatoire par phases depuis juin 2025). Pas de transmission
  automatique : une connexion API exige les accès et la documentation officiels de la DGI.
- **Conformité documentaire du dossier** : pièces obligatoires selon le régime
  (facture, B/L, colisage, **FDI**, **BSC**, **Certificat de Conformité** dès 1 000 000 FCFA
  de FOB, déclaration en douane…). Le CdC peut être déclaré « Exempté » avec motif.
- **Cycle de vie du dossier contrôlé** : pas d'étape sautée, et **BAE refusé tant
  qu'une pièce obligatoire manque**. Les références FDI / BSC / CdC figurent sur le BAE
  scellé (le sceau change si une pièce change).
- **Moteur hybride de sélectivité des risques** (canaux **Vert / Bleu / Jaune /
  Rouge**) par scoring pondéré : écart entre le taux de DD déclaré et le taux de la base
  tarifaire, sous-évaluation, montant CAF, ancienneté du fournisseur, sensibilité de la
  marchandise.
- **Surestaries portuaires** : franchise armateur, jours de retard, pénalité
  journalière en **USD convertie en FCFA** au taux en direct
  (`actualiser_taux_api()` avec repli sur le dernier taux connu).
- **Documents officiels PDF** :
  - **Bon à Enlever (BAE)** scellé par empreinte **SHA-256** ;
  - **Facture transitaire** détaillée distinguant les débours douaniers
    (refacturés hors taxes), le fret, le transport et les honoraires soumis à TVA.

### 4. Intelligence artificielle & OCR (IDP)
- **Assistant expert** douane ivoirienne, import-export, fiscalité DGI et SYSCOHADA (API **Groq** ;
  modèle par défaut `llama-3.3-70b-versatile` avec repli sur `llama-3.1-8b-instant`, modifiable par
  `GROQ_MODEL`). Il s'appuie sur :
  - un **socle intégré** de fiches sourcées (procédure de dédouanement, DUS, FNE, Certificat de
    Conformité, calcul des droits, pièces, canaux) ;
  - une **base de connaissances du cabinet** (Administration de l'IA : collez ou chargez vos décrets,
    arrêtés, circulaires, notes) — recherche par pertinence, isolée par tenant ;
  - les **données du dossier choisi** (chiffres, pièces manquantes, étapes du parcours) et les
    taux / taxes configurés pour les codes SH cités dans la question.
- **Garde-fous** : l'assistant cite ses sources [S1], [S2]…, dit « je n'ai pas cette précision »
  plutôt que d'inventer un numéro de décret, un article ou un taux, ignore les instructions
  cachées dans les textes, et refuse poliment les sujets hors domaine.
- **Sans clé IA**, il affiche les extraits les plus proches de la base de connaissances.
- **Extraction OCR/IDP** de factures fournisseurs (fournisseur, n° de facture,
  date, montants, désignation) — fonctionne hors-ligne, une sortie OCR externe
  peut alimenter la même interface.
- **Cross-checking automatique** : détection des discordances déclaré/extrait et
  de la **sous-évaluation douanière** par comparaison au prix de référence.
- **Générateur de communications** (relances, demandes de pièces, courriers
  administratifs) avec **validation humaine obligatoire** avant toute diffusion.

### 5. Expérience utilisateur & interopérabilité
- **Dark mode** épuré (glassmorphism, palette iOS), KPI financiers dynamiques,
  **graphiques Plotly interactifs** avec **repli automatique** sur `st.bar_chart`
  si Plotly est absent.
- **Robustesse** : dépendances optionnelles (`plotly`, `groq`, `requests`,
  `reportlab`, `passlib`) protégées par `try/except` — aucune ImportError ne
  bloque l'application.
- **Initialisation automatique** de la base au premier lancement avec un jeu de
  données professionnel cohérent (plan comptable, journaux, tenant, utilisateurs,
  articles SH, dossiers).

---

## 🗂️ Architecture

```
sndgir_erp.py        Application complète (bloc unique exécutable, ~2 440 lignes)
valider_sndgir.py    Harnais de validation fonctionnelle (101 contrôles)
requirements.txt     Dépendances Python
sndgir_erp.db        Base SQLite (créée automatiquement, ignorée par Git)
```

Déploiement : `Dockerfile`, `docker-compose*.yml`, `Caddyfile`, `fly.toml`,
`railway.json`. Le point d'entrée FastAPI (`app/main.py`) peut être porté vers
PostgreSQL ; le moteur métier de `sndgir_erp.py` est transposable via SQLAlchemy.

---

## ⚖️ Mentions & limites (honnêteté)

- Les **taux par défaut** (TVA 18 %, redevance statistique 1 %, IS/BIC 25 %,
  PC UEMOA 0,8 %, PCC CEDEAO 0,5 %) reflètent le régime général le plus courant en
  Côte d'Ivoire mais sont **indicatifs** : à confirmer avec le tarif de la Douane en
  vigueur (le taux du PC UEMOA n'a pas été revérifié). Les accises et taxes spécifiques
  sont **à configurer par vous** (aucun taux n'est préchargé), tout comme le tarif douanier.
- Les **régimes E100 / AT / TR** sont modélisés par suspension / exonération totale
  (droits et TVA) ; les cas particuliers (contingents, garanties, destinations
  privilégiées) doivent être affinés selon le tarif douanier en vigueur.
- La **liste des pièces obligatoires** (FDI, BSC, CdC…) est une liste de référence
  à adapter par le transitaire : les exigences évoluent (le programme de contrôle avec
  Certificat de Conformité est en vigueur depuis le 1er juillet 2025 selon SGS).
- Cet outil **ne remplace pas** la validation d'un **expert-comptable agréé** ni
  d'un **commissionnaire en douane agréé** avant toute déclaration officielle
  auprès de la DGI ou des Douanes ivoiriennes.
- Le chiffrement embarqué est une construction portable (HMAC-SHA256 + MAC).
  Pour une production bancaire, remplacez-la par **AES-256-GCM**
  (`cryptography`).

---

## ✅ État de validation

```
131 validations · 0 échec   (python3 valider_sndgir.py)
Sécurité ✓  Audit immuable ✓  Partie double ✓  Douanes ✓  Surestaries ✓
OCR/IDP ✓  Transit & B/L ✓  Multi-tenant & RBAC ✓  PDF scellés ✓
Conformité documentaire ✓  Cycle de vie du dossier ✓  Comptes & blocage ✓
```

## Analyse financière & IA (nouvelle tuile 🧠)
Dossier `finai/` + fichier `sndgir_finai.py`. Depuis votre grand livre : SIG, ratios, comparaison de normes,
scénarios « Et si ? », anomalies (Benford + Isolation Forest), prévision de trésorerie, textes (NLP), score de
solvabilité. Le bilan est reconstitué par approximation et les modèles apprennent sur des données simulées :
résultats indicatifs, à valider par l'expert-comptable. Paquets : voir `requirements.txt`.
