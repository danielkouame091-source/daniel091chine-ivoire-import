# Protection des données personnelles — modèles de travail

> ⚠️ **À FAIRE VALIDER PAR UN JURISTE** avant tout usage réel.
> Ce document est un modèle de départ, pas un avis juridique. Le texte de référence en Côte d'Ivoire est la
> **loi n°2013-450 du 19 juin 2013** relative à la protection des données à caractère personnel, contrôlée par
> l'**ARTCI** (à vérifier : formalités de déclaration/autorisation, durées de conservation, transferts hors du pays).

## 1. Registre des traitements (à compléter)

| Traitement | Données | Qui y accède | Pourquoi | Combien de temps | Où |
|---|---|---|---|---|---|
| Dossiers de transit | nom du client, e-mail, téléphone, observations | collaborateurs, expert, admin | réaliser le transit, facturer | **à fixer avec le juriste** (pièces comptables : durée légale OHADA/DGI à vérifier) | base SQLite de l'application |
| Messages au client | nom, e-mail, texte | collaborateurs, admin | informer le client | à fixer | base SQLite |
| Comptes utilisateurs | identifiant, e-mail, téléphone, empreinte du mot de passe, secret 2FA | admin | se connecter | tant que le compte est actif | base SQLite |
| Journal d'audit | identifiant, action, date | admin, auditeur | preuve et sécurité | à fixer | base SQLite |
| Avis des testeurs | identifiant, note, message | admin | améliorer le logiciel | durée de l'essai | base SQLite |

## 2. Texte d'information à donner au client (modèle)

> **Vos données personnelles.** [Nom de l'entreprise], [adresse], utilise votre nom, votre e-mail et votre numéro de
> téléphone pour réaliser votre opération de transit, vous tenir informé de l'avancement de votre marchandise et établir
> vos factures. Ces données ne sont pas vendues. Elles sont accessibles uniquement à notre personnel habilité et
> conservées [durée à fixer]. Vous pouvez demander à tout moment à voir vos données, à les corriger ou à les faire
> effacer (dans la limite de nos obligations comptables et douanières) en écrivant à [adresse e-mail du responsable].
> Vous pouvez aussi saisir l'ARTCI.

## 3. Procédure interne (ce que fait l'administrateur)

1. Recevoir la demande **par écrit** et vérifier l'identité du demandeur.
2. *Administration → 👤 Données personnelles* : choisir le client.
3. **Accès** : bouton « Exporter tout ce que nous savons (Excel) » → envoyer au client.
4. **Effacement** : noter le motif, retaper le nom exact, cliquer « Anonymiser ».
   - Effacés : nom, e-mail, téléphone, observations, contenu des messages, NCC du client sur la facture FNE.
   - Gardés : références de dossier, dates, montants (pièces comptables à conserver).
   - Le journal d'audit garde la trace de l'opération **sans le nom** (un code de remplacement seulement).
5. Répondre au demandeur dans le délai prévu (à vérifier avec le juriste) et classer la demande.

## 4. Limites connues de l'outil (honnêtes)

- L'anonymisation couvre : dossiers, connaissements, messages, factures FNE. Le **nom écrit à la main dans un libellé
  d'écriture comptable, une pièce PDF jointe ou un document OCR** n'est PAS effacé automatiquement.
- Les **anciennes sauvegardes** de la base contiennent encore les données : supprimez-les ou conservez-les à l'abri.
- Aucune purge automatique après X années : à décider avec le juriste, puis à programmer.
- La recherche du client est exacte (au caractère près, sans tenir compte des majuscules) : « SARL IvoirTech » et
  « Ivoirtech SARL » sont deux clients différents pour l'outil.
