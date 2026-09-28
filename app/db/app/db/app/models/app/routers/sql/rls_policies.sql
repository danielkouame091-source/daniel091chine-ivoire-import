-- ⚠️ À exécuter dans migration 0007_rls_policies.py via op.execute()
ALTER TABLE ecritures          ENABLE ROW LEVEL SECURITY;
ALTER TABLE ecriture_lignes    ENABLE ROW LEVEL SECURITY;
ALTER TABLE mm_transactions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_comptable     ENABLE ROW LEVEL SECURITY;
ALTER TABLE journaux           ENABLE ROW LEVEL SECURITY;
ALTER TABLE nlp_suggestions    ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON ecritures
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE POLICY tenant_write_only_if_active ON ecritures
  FOR INSERT
  WITH CHECK (
    tenant_id = current_setting('app.tenant_id', true)::uuid
    AND current_setting('app.read_only', true) <> 'true'
  );

-- Répéter pour chaque table via un DO $$ loop
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['ecriture_lignes','mm_transactions','plan_comptable','journaux','nlp_suggestions'] LOOP
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid)', t);
    EXECUTE format('CREATE POLICY tenant_write_only_if_active ON %I FOR INSERT WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid AND current_setting(''app.read_only'', true) <> ''true'')', t);
  END LOOP;
END $$;
