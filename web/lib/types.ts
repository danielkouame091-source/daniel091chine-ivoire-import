// ⚠️ Miroir des schémas Pydantic backend — à maintenir synchronisé.

export type UserRole = "SUPER_ADMIN" | "ADMIN_TENANT" | "COMPTABLE" | "LECTEUR" | "AUDITEUR";
export type TenantStatut = "actif" | "suspendu" | "gele" | "archive";
export type UserStatut = "actif" | "gele" | "revoque" | "invite";
export type SubStatut = "trial" | "actif" | "impaye" | "expire" | "suspendu" | "resilie";
export type SubPlan = "starter" | "pro" | "business" | "enterprise";
export type CompteType = "actif" | "passif" | "charge" | "produit" | "tresorerie" | "analytique" | "engagement";
export type JournalType = "vente" | "achat" | "banque" | "caisse" | "od" | "an" | "mobile_money" | "paie" | "impot";
export type EcritureSource = "manuel" | "import" | "mobile_money" | "ia_nlp" | "api" | "systeme";
export type EcritureStatut = "brouillon" | "validee" | "gelee" | "annulee" | "extournee";
export type MMProvider = "wave" | "orange_money" | "mtn_momo" | "moov_money";
export type MMSens = "credit" | "debit";
export type MMStatut = "non_rapproche" | "rapproche" | "ecart" | "gele";
export type FreezeCible = "tenant" | "user" | "compte" | "journal" | "ecriture" | "mm_transaction" | "exercice";
export type FreezeStatut = "actif" | "leve" | "partiel";

export interface CurrentUser {
  id: string;
  email: string;
  nom_complet: string;
  role: UserRole;
  is_founder: boolean;
  tenant_id: string | null;
  mfa_enabled: boolean;
  derniere_connexion: string | null;
}

export interface TokenOut {
  access_token: string;
  refresh_token: string | null;
  token_type: string;
  expires_in: number;
  mfa_required: boolean;
  session_token: string | null;
}

export interface Tenant {
  id: string;
  slug: string;
  raison_sociale: string;
  forme_juridique: string | null;
  rccm: string | null;
  compte_contribuable: string | null;
  regime_fiscal: string | null;
  pays: string;
  devise: string;
  fuseau: string;
  telephone: string | null;
  email: string | null;
  logo_url: string | null;
  statut: TenantStatut;
  created_at: string;
}

export interface PlanComptable {
  id: string;
  tenant_id: string;
  compte: string;
  libelle: string;
  classe: number;
  type_compte: CompteType;
  collectif: boolean;
  lettrable: boolean;
  auxiliaire: boolean;
  actif: boolean;
  created_at: string;
}

export interface Journal {
  id: string;
  tenant_id: string;
  code: string;
  libelle: string;
  type_journal: JournalType;
  compte_contrepartie: string | null;
  actif: boolean;
  created_at: string;
}

export interface LigneIn {
  compte: string;
  libelle?: string | null;
  debit: number;
  credit: number;
}

export interface LigneOut {
  id: string;
  compte_id: string;
  libelle: string | null;
  debit_xof: number;
  credit_xof: number;
  lettrage_code: string | null;
  ordre: number;
}

export interface EcritureCreate {
  numero_piece?: string | null;
  date_ecriture: string;
  code_journal: string;
  libelle: string;
  reference_ext?: string | null;
  source?: EcritureSource;
  lignes: LigneIn[];
}

export interface Ecriture {
  id: string;
  tenant_id: string;
  exercice_id: string;
  journal_id: string;
  numero_piece: string;
  date_ecriture: string;
  date_saisie: string;
  libelle: string;
  reference_ext: string | null;
  source: EcritureSource;
  statut: EcritureStatut;
  validee_at: string | null;
  validee_par: string | null;
  hash_chain: string;
  hash_precedent: string | null;
  created_by: string | null;
  created_at: string;
  lignes: LigneOut[];
}

export interface MmTransaction {
  id: string;
  tenant_id: string;
  provider: MMProvider;
  external_id: string;
  montant_xof: number;
  frais_xof: number;
  sens: MMSens;
  numero_tiers: string | null;
  libelle: string | null;
  horodatage: string;
  statut_rappro: MMStatut;
  ecriture_id: string | null;
  rapproche_at: string | null;
  created_at: string;
}

export interface SubscriptionStatus {
  statut: SubStatut;
  periode_fin: string;
  jours_restants: number;
  est_expiree: boolean;
  est_en_grace: boolean;
  force_read_only: boolean;
  plan_code: SubPlan | null;
}

export interface Subscription {
  id: string;
  tenant_id: string;
  plan_id: string;
  statut: SubStatut;
  periode_debut: string;
  periode_fin: string;
  grace_jours: number;
  montant_xof: number;
  devise: string;
  mode_paiement: string | null;
  reference_paiement: string | null;
  auto_renouvellement: boolean;
  created_at: string;
}

export interface FreezeEvent {
  id: string;
  tenant_id: string;
  cible_type: FreezeCible;
  cible_id: string;
  motif: string;
  details: Record<string, unknown>;
  declencheur_user_id: string | null;
  cascade_profondeur: number;
  statut: FreezeStatut;
  leve_at: string | null;
  leve_par: string | null;
  created_at: string;
  targets: FreezeTarget[];
}

export interface FreezeTarget {
  id: string;
  cible_type: FreezeCible;
  cible_id: string;
  niveau_profondeur: number;
  raison: string;
  statut: FreezeStatut;
  gele_at: string;
  leve_at: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}
