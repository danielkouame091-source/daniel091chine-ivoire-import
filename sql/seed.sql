-- ============================================================================
-- MTECH SaaS SYSCOHADA — SCHÉMA POSTGRESQL 16 (CÔTE D'IVOIRE)
-- Multi-tenant RLS + SYSCOHADA révisé + Abonnements + Gel en cascade
-- Auteur : Architecte Logiciel Senior — Version 1.0
-- ============================================================================

-- ============================================================================
-- 0. EXTENSIONS & TYPES
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Enums métier (figés, jamais modifiés à chaud)
CREATE TYPE user_role AS ENUM (
  'SUPER_ADMIN',      -- fondateur unique (cockpit)
  'ADMIN_TENANT',     -- patron de l'entreprise
  'COMPTABLE',
  'LECTEUR',
  'AUDITEUR'
);

CREATE TYPE tenant_statut AS ENUM ('actif', 'suspendu', 'gele', 'archive');
CREATE TYPE user_statut   AS ENUM ('actif', 'gele', 'revoque', 'invite');
CREATE TYPE sub_statut    AS ENUM ('trial', 'actif', 'impaye', 'expire', 'suspendu', 'resilie');
CREATE TYPE sub_plan      AS ENUM ('starter', 'pro', 'business', 'enterprise');

CREATE TYPE compte_type AS ENUM (
  'actif', 'passif', 'charge', 'produit',
  'tresorerie', 'analytique', 'engagement'
);

CREATE TYPE journal_type AS ENUM (
  'vente', 'achat', 'banque', 'caisse',
  'od', 'an', 'mobile_money', 'paie', 'impot'
);

CREATE TYPE ecriture_source AS ENUM (
  'manuel', 'import', 'mobile_money', 'ia_nlp', 'api', 'systeme'
);

CREATE TYPE ecriture_statut AS ENUM (
  'brouillon', 'validee', 'gelee', 'annulee', 'extournee'
);

CREATE TYPE mm_provider AS ENUM ('wave', 'orange_money', 'mtn_momo', 'moov_money');
CREATE TYPE mm_sens     AS ENUM ('credit', 'debit');
CREATE TYPE mm_statut   AS ENUM ('non_rapproche', 'rapproche', 'ecart', 'gele');

CREATE TYPE freeze_cible AS ENUM (
  'tenant', 'user', 'compte', 'journal',
  'ecriture', 'mm_transaction', 'exercice'
);
CREATE TYPE freeze_statut AS ENUM ('actif', 'leve', 'partiel');

-- ============================================================================
-- 1. SOCLE MULTI-TENANT (isolation stricte)
-- ============================================================================

CREATE TABLE tenants (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  slug                  CITEXT UNIQUE NOT NULL,
  raison_sociale        TEXT NOT NULL,
  forme_juridique       TEXT,                                -- SARL, SA, SAS, EI...
  rccm                  TEXT,                                -- Registre Commerce CI
  compte_contribuable   TEXT,                                -- Identifiant DGI
  numero_cnps           TEXT,
  regime_fiscal         TEXT CHECK (regime_fiscal IN ('RME','RNI','RSI','TPU','ZONE_FRANCHE')),
  centre_impots         TEXT,                                -- DGE, CME, etc.
  pays                  CHAR(2) NOT NULL DEFAULT 'CI',
  devise                CHAR(3) NOT NULL DEFAULT 'XOF',
  fuseau                TEXT NOT NULL DEFAULT 'Africa/Abidjan',
  adresse               JSONB,                               -- adresse structurée
  telephone             TEXT,
  email                 CITEXT,
  logo_url              TEXT,
  statut                tenant_statut NOT NULL DEFAULT 'actif',
  metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at            TIMESTAMPTZ
);
CREATE INDEX idx_tenants_statut ON tenants(statut) WHERE deleted_at IS NULL;

CREATE TABLE users (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id             UUID REFERENCES tenants(id) ON DELETE CASCADE, -- NULL pour le fondateur
  email                 CITEXT UNIQUE NOT NULL,
  password_hash         TEXT NOT NULL,                       -- argon2id
  nom_complet           TEXT NOT NULL,
  telephone             TEXT,
  role                  user_role NOT NULL DEFAULT 'LECTEUR',
  statut                user_statut NOT NULL DEFAULT 'invite',
  is_founder            BOOLEAN NOT NULL DEFAULT false,
  mfa_enabled           BOOLEAN NOT NULL DEFAULT false,
  mfa_secret_enc        BYTEA,                               -- AES-256-GCM chiffré
  mfa_backup_codes_enc  BYTEA,
  derniere_connexion    TIMESTAMPTZ,
  derniere_ip           INET,
  tentatives_echec      SMALLINT NOT NULL DEFAULT 0,
  verrouille_jusqu_a    TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at            TIMESTAMPTZ,

  CONSTRAINT founder_must_be_alone CHECK (
    (is_founder = true AND tenant_id IS NULL AND role = 'SUPER_ADMIN')
    OR (is_founder = false AND tenant_id IS NOT NULL)
  )
);
-- Un SEUL fondateur dans toute la table
CREATE UNIQUE INDEX uniq_founder ON users(is_founder) WHERE is_founder = true;
CREATE INDEX idx_users_tenant ON users(tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_email_active ON users(email) WHERE deleted_at IS NULL;

-- Sessions (JWT refresh rotatif, révocation par jti)
CREATE TABLE sessions (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id               UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tenant_id             UUID REFERENCES tenants(id) ON DELETE CASCADE,
  jti                   UUID UNIQUE NOT NULL,
  refresh_hash          TEXT NOT NULL,
  ip                    INET,
  user_agent            TEXT,
  expires_at            TIMESTAMPTZ NOT NULL,
  revoquee_at           TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sessions_user ON sessions(user_id) WHERE revoquee_at IS NULL;

-- ============================================================================
-- 2. ABONNEMENTS SaaS (bascule lecture seule)
-- ============================================================================

CREATE TABLE plans (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  code                  sub_plan UNIQUE NOT NULL,
  libelle               TEXT NOT NULL,
  prix_mensuel_xof      BIGINT NOT NULL,
  prix_annuel_xof       BIGINT NOT NULL,
  max_users             INTEGER NOT NULL DEFAULT 3,
  max_ecritures_mois    INTEGER NOT NULL DEFAULT 1000,
  max_mm_transactions   INTEGER NOT NULL DEFAULT 500,
  features              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE subscriptions (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  plan_id               UUID NOT NULL REFERENCES plans(id),
  statut                sub_statut NOT NULL DEFAULT 'trial',
  periode_debut         TIMESTAMPTZ NOT NULL DEFAULT now(),
  periode_fin           TIMESTAMPTZ NOT NULL,                -- ⚠️ clé de la bascule read-only
  grace_jours           SMALLINT NOT NULL DEFAULT 7,
  montant_xof           BIGINT NOT NULL,
  devise                CHAR(3) NOT NULL DEFAULT 'XOF',
  mode_paiement         TEXT CHECK (mode_paiement IN ('wave','orange_money','mtn_momo','moov_money','virement','espece','carte')),
  reference_paiement    TEXT,
  auto_renouvellement   BOOLEAN NOT NULL DEFAULT false,
  metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sub_tenant_actif ON subscriptions(tenant_id, periode_fin DESC)
  WHERE statut IN ('trial','actif','impaye');
CREATE INDEX idx_sub_expiration ON subscriptions(periode_fin)
  WHERE statut IN ('trial','actif');

-- Historique paiements (audit facturation)
CREATE TABLE subscription_payments (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  subscription_id       UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  montant_xof           BIGINT NOT NULL,
  mode_paiement         TEXT NOT NULL,
  reference_externe     TEXT,
  provider              mm_provider,
  statut                TEXT NOT NULL CHECK (statut IN ('en_attente','confirme','echoue','rembourse')),
  payload               JSONB,
  confirme_at           TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_subpay_tenant ON subscription_payments(tenant_id, created_at DESC);

-- ============================================================================
-- 3. SYSCOHADA — EXERCICES, PLAN COMPTABLE, JOURNAUX
-- ============================================================================

CREATE TABLE exercices (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  libelle               TEXT NOT NULL,                       -- "Exercice 2025"
  date_debut            DATE NOT NULL,
  date_fin              DATE NOT NULL,
  cloture               BOOLEAN NOT NULL DEFAULT false,
  cloture_at            TIMESTAMPTZ,
  report_solde          JSONB,                               -- soldes reportés N+1
  UNIQUE (tenant_id, date_debut, date_fin),
  CONSTRAINT exercice_dates_coherentes CHECK (date_fin > date_debut)
);

CREATE TABLE plan_comptable (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  compte                VARCHAR(10) NOT NULL,                -- '401100', '521000'...
  libelle               TEXT NOT NULL,
  classe                SMALLINT NOT NULL CHECK (classe BETWEEN 1 AND 9),
  type_compte           compte_type NOT NULL,
  collectif             BOOLEAN NOT NULL DEFAULT false,
  lettrable             BOOLEAN NOT NULL DEFAULT true,       -- rapprochement bancaire
  auxiliaire           BOOLEAN NOT NULL DEFAULT false,       -- 401xxx client/fournisseur
  actif                 BOOLEAN NOT NULL DEFAULT true,
  metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, compte)
);
CREATE INDEX idx_pc_tenant_classe ON plan_comptable(tenant_id, classe);
CREATE INDEX idx_pc_tenant_actif  ON plan_comptable(tenant_id) WHERE actif = true;

CREATE TABLE journaux (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  code                  VARCHAR(5) NOT NULL,                 -- VE, AC, BQ, CA, OD, AN, MM
  libelle               TEXT NOT NULL,
  type_journal          journal_type NOT NULL,
  compte_contrepartie   VARCHAR(10),                         -- compte trésorerie par défaut
  actif                 BOOLEAN NOT NULL DEFAULT true,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code)
);

-- ============================================================================
-- 4. SYSCOHADA — ÉCRITURES EN PARTIE DOUBLE (avec hash-chain)
-- ============================================================================

CREATE TABLE ecritures (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  exercice_id           UUID NOT NULL REFERENCES exercices(id),
  journal_id            UUID NOT NULL REFERENCES journaux(id),
  numero_piece          TEXT NOT NULL,                       -- VE-2025-0001
  date_ecriture         DATE NOT NULL,
  date_saisie           TIMESTAMPTZ NOT NULL DEFAULT now(),
  libelle               TEXT NOT NULL,
  reference_ext         TEXT,                                -- ID transaction MM, facture...
  source                ecriture_source NOT NULL DEFAULT 'manuel',
  statut                ecriture_statut NOT NULL DEFAULT 'brouillon',
  validee_at            TIMESTAMPTZ,
  validee_par           UUID REFERENCES users(id),
  -- Chaînage cryptographique (traçabilité bancaire)
  hash_chain            TEXT NOT NULL,                       -- SHA-256(courant)
  hash_precedent        TEXT,                                -- SHA-256(N-1) du tenant
  created_by            UUID REFERENCES users(id),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, numero_piece)
);
CREATE INDEX idx_ecr_tenant_date   ON ecritures(tenant_id, date_ecriture DESC);
CREATE INDEX idx_ecr_tenant_statut ON ecritures(tenant_id, statut);
CREATE INDEX idx_ecr_journal_date  ON ecritures(journal_id, date_ecriture);
CREATE INDEX idx_ecr_reference     ON ecritures(tenant_id, reference_ext) WHERE reference_ext IS NOT NULL;
CREATE INDEX idx_ecr_hash          ON ecritures(tenant_id, hash_chain);

CREATE TABLE ecriture_lignes (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  ecriture_id           UUID NOT NULL REFERENCES ecritures(id) ON DELETE CASCADE,
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  compte_id             UUID NOT NULL REFERENCES plan_comptable(id),
  libelle               TEXT,
  debit_xof             BIGINT NOT NULL DEFAULT 0 CHECK (debit_xof  >= 0),
  credit_xof            BIGINT NOT NULL DEFAULT 0 CHECK (credit_xof >= 0),
  lettrage_code         TEXT,                                -- rapprochement bancaire
  lettrage_at           TIMESTAMPTZ,
  ordre                 SMALLINT NOT NULL DEFAULT 1,
  -- Jamais débit ET crédit sur la même ligne
  CONSTRAINT ligne_non_mixte CHECK (NOT (debit_xof > 0 AND credit_xof > 0)),
  CONSTRAINT ligne_non_nulle CHECK (debit_xof > 0 OR credit_xof > 0)
);
CREATE INDEX idx_lignes_ecriture ON ecriture_lignes(ecriture_id);
CREATE INDEX idx_lignes_compte   ON ecriture_lignes(tenant_id, compte_id);
CREATE INDEX idx_lignes_lettrage ON ecriture_lignes(tenant_id, lettrage_code) WHERE lettrage_code IS NOT NULL;

-- Contrainte différée : vérification équilibre débit/crédit à la validation
CREATE OR REPLACE FUNCTION check_ecriture_equilibre() RETURNS TRIGGER AS $$
DECLARE
  v_ecriture_id UUID;
  v_debit BIGINT;
  v_credit BIGINT;
BEGIN
  v_ecriture_id := COALESCE(NEW.ecriture_id, OLD.ecriture_id);
  SELECT COALESCE(SUM(debit_xof),0), COALESCE(SUM(credit_xof),0)
    INTO v_debit, v_credit
    FROM ecriture_lignes WHERE ecriture_id = v_ecriture_id;
  IF v_debit <> v_credit THEN
    RAISE EXCEPTION 'Écriture déséquilibrée SYSCOHADA : débit=% crédit=%', v_debit, v_credit;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_ecriture_equilibre
  AFTER INSERT OR UPDATE OR DELETE ON ecriture_lignes
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION check_ecriture_equilibre();

-- ============================================================================
-- 5. MOBILE MONEY (flux associés au gel)
-- ============================================================================

CREATE TABLE mm_transactions (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider              mm_provider NOT NULL,
  external_id           TEXT NOT NULL,                       -- ID côté Wave/OM/MTN
  montant_xof           BIGINT NOT NULL,
  frais_xof             BIGINT NOT NULL DEFAULT 0,
  sens                  mm_sens NOT NULL,
  numero_tiers          TEXT,
  libelle               TEXT,
  horodatage            TIMESTAMPTZ NOT NULL,
  raw_payload           JSONB NOT NULL,
  statut_rappro         mm_statut NOT NULL DEFAULT 'non_rapproche',
  ecriture_id           UUID REFERENCES ecritures(id),
  rapproche_at          TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, provider, external_id)
);
CREATE INDEX idx_mm_tenant_date   ON mm_transactions(tenant_id, horodatage DESC);
CREATE INDEX idx_mm_tenant_statut ON mm_transactions(tenant_id, statut_rappro);

-- ============================================================================
-- 6. PROTOCOLE DE GEL EN CASCADE
-- ============================================================================

-- Événement racine de gel (déclencheur unique)
CREATE TABLE freeze_events (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  cible_type            freeze_cible NOT NULL,
  cible_id              UUID NOT NULL,
  motif                 TEXT NOT NULL,
  details               JSONB NOT NULL DEFAULT '{}'::jsonb,
  declencheur_user_id   UUID REFERENCES users(id),           -- NULL = système
  declencheur_ip        INET,
  cascade_profondeur    SMALLINT NOT NULL DEFAULT 0,
  statut                freeze_statut NOT NULL DEFAULT 'actif',
  leve_at               TIMESTAMPTZ,
  leve_par              UUID REFERENCES users(id),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_freeze_tenant_actif ON freeze_events(tenant_id) WHERE statut = 'actif';
CREATE INDEX idx_freeze_cible        ON freeze_events(cible_type, cible_id);

-- Chaque ressource effectivement atteinte par un gel (cascade matérialisée)
CREATE TABLE freeze_targets (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  freeze_event_id       UUID NOT NULL REFERENCES freeze_events(id) ON DELETE CASCADE,
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  cible_type            freeze_cible NOT NULL,
  cible_id              UUID NOT NULL,
  niveau_profondeur     SMALLINT NOT NULL DEFAULT 0,         -- 0=racine, 1=enfant direct...
  raison                TEXT NOT NULL,                       -- 'cascade_user', 'cascade_ecriture'...
  statut                freeze_statut NOT NULL DEFAULT 'actif',
  gele_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  leve_at               TIMESTAMPTZ,
  UNIQUE (freeze_event_id, cible_type, cible_id)
);
CREATE INDEX idx_ft_tenant   ON freeze_targets(tenant_id, statut);
CREATE INDEX idx_ft_cible    ON freeze_targets(cible_type, cible_id);
CREATE INDEX idx_ft_event    ON freeze_targets(freeze_event_id);

-- Règles de cascade déclaratives (graphe de propagation)
CREATE TABLE freeze_cascade_rules (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source_type           freeze_cible NOT NULL,
  cible_type            freeze_cible NOT NULL,
  propagation           TEXT NOT NULL DEFAULT 'immediate',   -- immediate | differee
  blocage_ecriture      BOOLEAN NOT NULL DEFAULT true,       -- empêche toute nouvelle écriture
  description           TEXT,
  UNIQUE (source_type, cible_type)
);

-- Journal immuable (hash-chain) pour toute action sensible
CREATE TABLE audit_logs (
  id                    BIGSERIAL PRIMARY KEY,
  tenant_id             UUID,
  user_id               UUID,
  action                TEXT NOT NULL,
  ressource             TEXT NOT NULL,
  ressource_id          UUID,
  ip                    INET,
  user_agent            TEXT,
  payload               JSONB,
  hash_precedent        TEXT,
  hash_courant          TEXT NOT NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_tenant_date ON audit_logs(tenant_id, created_at DESC);
CREATE INDEX idx_audit_action      ON audit_logs(action);

-- Verrou global consultable en temps réel par l'API (cache chaud)
CREATE TABLE tenant_freeze_state (
  tenant_id             UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  gele                  BOOLEAN NOT NULL DEFAULT false,
  freeze_event_id       UUID REFERENCES freeze_events(id),
  motif                 TEXT,
  gele_at               TIMESTAMPTZ,
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- 7. ROW LEVEL SECURITY (isolation stricte multi-tenant)
-- ============================================================================
-- Convention : l'application pose, à chaque requête :
--   SELECT set_config('app.tenant_id', '<uuid>', true);
--   SELECT set_config('app.read_only', 'true'|'false', true);
--   SELECT set_config('app.frozen',    'true'|'false', true);

-- 7.1 Tables tenant-scoped : isolation par tenant_id
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'users','sessions','subscriptions','subscription_payments',
    'exercices','plan_comptable','journaux','ecritures','ecriture_lignes',
    'mm_transactions','freeze_events','freeze_targets','audit_logs'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', t);
  END LOOP;
END $$;

-- 7.2 Policy de lecture : ne voir QUE son tenant
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'users','sessions','subscriptions','subscription_payments',
    'exercices','plan_comptable','journaux','ecritures','ecriture_lignes',
    'mm_transactions','freeze_events','freeze_targets','audit_logs'
  ] LOOP
    EXECUTE format($f$
      CREATE POLICY tenant_read ON %I FOR SELECT
      USING (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        OR current_setting('app.tenant_id', true) IS NULL  -- fondateur
      );
    $f$, t);
  END LOOP;
END $$;

-- 7.3 Policy d'écriture : bloquée si read_only OU frozen
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'users','subscriptions','exercices','plan_comptable','journaux',
    'ecritures','ecriture_lignes','mm_transactions'
  ] LOOP
    EXECUTE format($f$
      CREATE POLICY tenant_write ON %I FOR INSERT
      WITH CHECK (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        AND current_setting('app.read_only', true) <> 'true'
        AND current_setting('app.frozen',    true) <> 'true'
      );
    $f$, t);

    EXECUTE format($f$
      CREATE POLICY tenant_update ON %I FOR UPDATE
      USING (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        AND current_setting('app.read_only', true) <> 'true'
        AND current_setting('app.frozen',    true) <> 'true'
      );
    $f$, t);

    EXECUTE format($f$
      CREATE POLICY tenant_delete ON %I FOR DELETE
      USING (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        AND current_setting('app.read_only', true) <> 'true'
        AND current_setting('app.frozen',    true) <> 'true'
      );
    $f$, t);
  END LOOP;
END $$;

-- 7.4 exceptions : tables toujours lisibles (paiement, audit) — pas d'écriture bloquée
DROP POLICY IF EXISTS tenant_write ON subscription_payments;
CREATE POLICY tenant_write ON subscription_payments FOR INSERT
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- (paiement autorisé même en read-only pour permettre le renouvellement)

DROP POLICY IF EXISTS tenant_write ON audit_logs;
CREATE POLICY tenant_write ON audit_logs FOR INSERT
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- (audit toujours écrit, même en read-only)

-- 7.5 Tables globales (plans, freeze_cascade_rules) : lecture seule
ALTER TABLE plans                ENABLE ROW LEVEL SECURITY;
ALTER TABLE freeze_cascade_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY plans_read_all                ON plans                FOR SELECT USING (true);
CREATE POLICY freeze_cascade_rules_read_all ON freeze_cascade_rules FOR SELECT USING (true);

-- 7.6 tenant_freeze_state : lecture par tenant
ALTER TABLE tenant_freeze_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY tfs_read ON tenant_freeze_state FOR SELECT
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid
         OR current_setting('app.tenant_id', true) IS NULL);

-- 7.7 Table tenants : un tenant ne voit que son propre enregistrement
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenants_self ON tenants
  USING (
    id = current_setting('app.tenant_id', true)::uuid
    OR current_setting('app.tenant_id', true) IS NULL  -- fondateur
  );

-- ============================================================================
-- 8. TRIGGERS UTILITAIRES
-- ============================================================================

-- 8.1 updated_at automatique
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['tenants','users','subscriptions','ecritures','tenant_freeze_state'] LOOP
    EXECUTE format('CREATE TRIGGER trg_touch_%s BEFORE UPDATE ON %I
                    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();', t, t);
  END LOOP;
END $$;

-- 8.2 Synchronisation du flag frozen (cache chaud)
CREATE OR REPLACE FUNCTION sync_freeze_state() RETURNS TRIGGER AS $$
BEGIN
  IF NEW.statut = 'actif' THEN
    INSERT INTO tenant_freeze_state(tenant_id, gele, freeze_event_id, motif, gele_at, updated_at)
    VALUES (NEW.tenant_id, true, NEW.id, NEW.motif, now(), now())
    ON CONFLICT (tenant_id) DO UPDATE
      SET gele=true, freeze_event_id=NEW.id, motif=NEW.motif,
          gele_at=now(), updated_at=now();
  ELSIF NEW.statut = 'leve' THEN
    UPDATE tenant_freeze_state
      SET gele=false, freeze_event_id=NULL, motif=NULL,
          gele_at=NULL, updated_at=now()
      WHERE tenant_id = NEW.tenant_id AND freeze_event_id = NEW.id;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_freeze_state
  AFTER INSERT OR UPDATE OF statut ON freeze_events
  FOR EACH ROW EXECUTE FUNCTION sync_freeze_state();

-- 8.3 Interdiction absolue de modification d'une écriture gelée
CREATE OR REPLACE FUNCTION block_frozen_ecriture() RETURNS TRIGGER AS $$
BEGIN
  IF OLD.statut = 'gelee' AND NEW.statut <> 'gelee' THEN
    RAISE EXCEPTION 'Écriture % gelée — modification interdite', OLD.id;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_block_frozen_ecriture
  BEFORE UPDATE ON ecritures
  FOR EACH ROW EXECUTE FUNCTION block_frozen_ecriture();

-- ============================================================================
-- 9. SEED INITIAL : PLANS SaaS + RÈGLES DE CASCADE
-- ============================================================================

INSERT INTO plans (code, libelle, prix_mensuel_xof, prix_annuel_xof,
                   max_users, max_ecritures_mois, max_mm_transactions, features)
VALUES
  ('starter',    'Starter',    15000,  150000,  3,   1000,   500,
   '{"whatsapp":false,"nlp":true,"multiuser":false}'),
  ('pro',        'Pro',        45000,  450000,  10,  10000,  5000,
   '{"whatsapp":true,"nlp":true,"multiuser":true}'),
  ('business',   'Business',   120000, 1200000, 50,  100000, 50000,
   '{"whatsapp":true,"nlp":true,"multiuser":true,"api":true}'),
  ('enterprise', 'Enterprise', 350000, 3500000, 500, 1000000,500000,
   '{"whatsapp":true,"nlp":true,"multiuser":true,"api":true,"sla":true}');

INSERT INTO freeze_cascade_rules (source_type, cible_type, propagation, blocage_ecriture, description)
VALUES
  ('tenant',        'user',           'immediate', true,  'Geler tous les utilisateurs du tenant'),
  ('tenant',        'ecriture',       'immediate', true,  'Geler toutes les écritures non clôturées'),
  ('tenant',        'mm_transaction', 'immediate', true,  'Geler tous les flux Mobile Money'),
  ('tenant',        'exercice',       'immediate', true,  'Bloquer la saisie sur tous les exercices ouverts'),
  ('user',          'ecriture',       'immediate', true,  'Geler les écritures créées par cet utilisateur'),
  ('ecriture',      'mm_transaction', 'immediate', false, 'Geler les transactions MM liées à l''écriture'),
  ('mm_transaction','ecriture',       'immediate', false, 'Geler l''écriture de rapprochement associée'),
  ('compte',        'ecriture',       'immediate', false, 'Geler toutes les écritures mouvementant ce compte');

-- ============================================================================
-- 10. VUES DE CONTRÔLE (cockpit fondateur)
-- ============================================================================

CREATE OR REPLACE VIEW v_subscriptions_a_expirer AS
SELECT s.id, s.tenant_id, t.raison_sociale, s.statut, s.periode_fin,
       EXTRACT(DAY FROM (s.periode_fin - now()))::int AS jours_restants
FROM subscriptions s
JOIN tenants t ON t.id = s.tenant_id
WHERE s.statut IN ('trial','actif','impaye')
  AND s.periode_fin <= now() + INTERVAL '7 days'
  AND t.deleted_at IS NULL
ORDER BY s.periode_fin ASC;

CREATE OR REPLACE VIEW v_tenants_geles AS
SELECT t.id, t.raison_sociale, tfs.motif, tfs.gele_at, fe.cible_type
FROM tenant_freeze_state tfs
JOIN tenants t ON t.id = tfs.tenant_id
LEFT JOIN freeze_events fe ON fe.id = tfs.freeze_event_id
WHERE tfs.gele = true;

-- ============================================================================
-- FIN DU SCHÉMA — prêt pour Alembic migration 0001
-- ============================================================================
