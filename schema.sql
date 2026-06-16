CREATE TABLE campaign_queue (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  niche TEXT NOT NULL,
  city TEXT NOT NULL,
  niche_target TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'scraping', 'done')),
  batch INTEGER DEFAULT 1,
  smartlead_campaign_id BIGINT,
  include_keywords TEXT,
  exclude_keywords TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_campaign_queue_status ON campaign_queue(status);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_campaign_queue_updated_at
  BEFORE UPDATE ON campaign_queue
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at();

CREATE TABLE leads (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  place_id TEXT NOT NULL UNIQUE,
  campaign_queue_id UUID REFERENCES campaign_queue(id) ON DELETE SET NULL,
  email TEXT NOT NULL,
  first_name TEXT,
  company_name TEXT,
  domain TEXT,
  phone TEXT,
  location TEXT,
  niche TEXT,
  city TEXT,
  status TEXT NOT NULL DEFAULT 'raw'
    CHECK (status IN ('raw', 'cleaned', 'excluded', 'imported_smartlead')),
  valid BOOLEAN DEFAULT NULL,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_leads_status ON leads(status);
CREATE INDEX idx_leads_campaign ON leads(campaign_queue_id);

CREATE TABLE niche_variable (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  niche TEXT NOT NULL UNIQUE,
  niche_keyword_1 TEXT,
  niche_keyword_2 TEXT,
  niche_keyword_3 TEXT,
  niche_member TEXT,
  objectif TEXT,
  pain_point TEXT,
  methode TEXT,
  offre TEXT,
  timeline TEXT DEFAULT '60 jours',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TRIGGER trg_niche_variable_updated_at
  BEFORE UPDATE ON niche_variable
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at();

CREATE TABLE campaign_settings (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  smartlead_campaign_id INT NOT NULL UNIQUE,
  schedule JSONB,
  settings JSONB,
  email_account_ids INT[],
  raw JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TRIGGER trg_campaign_settings_updated_at
  BEFORE UPDATE ON campaign_settings
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at();
