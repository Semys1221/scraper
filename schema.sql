CREATE TABLE campaign_queue (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  niche TEXT NOT NULL,
  city TEXT NOT NULL,
  niche_target TEXT,
  objective TEXT,
  timeframe TEXT,
  constraint_ TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'scraping', 'done')),
  batch INTEGER DEFAULT 1,
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
  status TEXT NOT NULL DEFAULT 'raw'
    CHECK (status IN ('raw', 'cleaned', 'excluded', 'imported_smartlead')),
  valid BOOLEAN DEFAULT NULL,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_leads_status ON leads(status);
CREATE INDEX idx_leads_campaign ON leads(campaign_queue_id);
