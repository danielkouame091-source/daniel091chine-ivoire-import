# Guide de Déploiement — MTech SaaS SYSCOHADA

## Vue d'ensemble

| Composant | Fly.io | Railway |
|---|---|---|
| **API** | `mtech-saas-api.fly.dev` | `api.mtech.ci` |
| **Worker** | `mtech-saas-worker` | service `worker` |
| **PostgreSQL** | Fly Managed Postgres | Plugin Postgres |
| **Redis** | Upstash Redis | Plugin Redis |
| **Région** | `cdg` (Paris) | Europe West |

**Recommandation** : Fly.io pour la production (meilleur contrôle, coût prévisible). Railway pour le staging / MVP rapide.

---

## Prérequis

### Fly.io
```bash
curl -L https://fly.io/install.sh | sh
flyctl auth login
