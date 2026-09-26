-- Kişisel Sabah Bülteni: ilk şema.
-- Tüm zaman damgaları ISO-8601 UTC ("2026-09-26T05:00:00+00:00") olarak saklanır.

CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Genel amaçlı anahtar/değer: Telegram offset, worker nabzı, ilk çalıştırma işaretleri.
CREATE TABLE kv (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL
);

-- Kaynaklar -----------------------------------------------------------------

CREATE TABLE sources (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  module TEXT NOT NULL,            -- windows|intune|configmgr|community|news|content|search
  adapter TEXT NOT NULL,           -- adaptör adı (bulten/sources/registry.py)
  url TEXT NOT NULL,               -- kullanıcıya gösterilen kanonik adres
  fetch_url TEXT,                  -- birincil okuma adresi (ör. GitHub markdown kaynağı)
  fallback_url TEXT,               -- birincil başarısızsa denenecek adres
  trust TEXT NOT NULL,             -- official|press|community|user
  category TEXT,                   -- haberler: turkiye|dunya|genel|teknoloji
  product_ids TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  builtin INTEGER NOT NULL DEFAULT 0,
  critical INTEGER NOT NULL DEFAULT 0,   -- kritik alarm kontrollerine dahil mi
  config_json TEXT NOT NULL DEFAULT '{}',
  validation_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE source_checks (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  run_id TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,            -- running|ok|not_modified|error|parse_warning|skipped
  http_status INTEGER,
  fetched_url TEXT,
  error TEXT,
  items_found INTEGER NOT NULL DEFAULT 0,
  items_changed INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER
);
CREATE INDEX ix_source_checks_source ON source_checks(source_id, started_at DESC);

CREATE TABLE http_cache (
  url TEXT PRIMARY KEY,
  etag TEXT,
  last_modified TEXT,
  content_hash TEXT,
  content_type TEXT,
  body TEXT,
  fetched_at TEXT NOT NULL
);

-- Gözlemler (normalleştirilmiş kaynak kayıtları) ve kanıt geçmişi ------------

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  module TEXT NOT NULL,            -- windows|intune|configmgr|community|news|content
  category TEXT,                   -- haber kategorisi (tek birincil kategori)
  kind TEXT NOT NULL,              -- issue|release|feature|notice|version|hotfix|news|content
  title TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  published_at TEXT,               -- kaynağın yayın tarihi
  meaningful_update_at TEXT,       -- son maddi değişiklik
  last_checked_at TEXT,            -- son başarılı kontrol
  current_version INTEGER NOT NULL DEFAULT 0,
  status TEXT,
  evidence_level TEXT,
  risk_level TEXT,
  relevance REAL NOT NULL DEFAULT 0,
  products_json TEXT NOT NULL DEFAULT '[]',
  kbs_json TEXT NOT NULL DEFAULT '[]',
  tags_json TEXT NOT NULL DEFAULT '[]',
  signature TEXT,                  -- eşleştirme için normalleştirilmiş başlık/belirti imzası
  state_json TEXT,                 -- son hesaplanan maddi durum (sürümler arasında da güncellenir)
  field_sources INTEGER NOT NULL DEFAULT 0,  -- bağımsız saha kaynağı sayısı
  needs_analysis INTEGER NOT NULL DEFAULT 1,
  is_baseline INTEGER NOT NULL DEFAULT 0,
  is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_events_module ON events(module, meaningful_update_at DESC);

CREATE TABLE event_aliases (
  alias TEXT PRIMARY KEY,
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE
);
CREATE INDEX ix_event_aliases_event ON event_aliases(event_id);

CREATE TABLE observations (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  external_key TEXT NOT NULL,
  kind TEXT NOT NULL,              -- known_issue|kb_release|feature|notice|cm_version|cm_hotfix|cm_known_issue|article|field_report|content|announcement
  url TEXT,
  title TEXT NOT NULL,
  body TEXT,
  lang TEXT,
  published_at TEXT,
  source_updated_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  fields_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL,
  semantic_hash TEXT NOT NULL,
  event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
  match_method TEXT,
  match_score REAL,
  needs_analysis INTEGER NOT NULL DEFAULT 1,
  from_first_run INTEGER NOT NULL DEFAULT 0,   -- kaynağın ilk başarılı taramasında görüldü (başlangıç arşivi)
  is_demo INTEGER NOT NULL DEFAULT 0,
  UNIQUE(source_id, external_key)
);
CREATE INDEX ix_observations_event ON observations(event_id);
CREATE INDEX ix_observations_pending ON observations(needs_analysis);

CREATE TABLE observation_snapshots (
  id INTEGER PRIMARY KEY,
  observation_id INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
  captured_at TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  title TEXT,
  body TEXT,
  fields_json TEXT
);
CREATE INDEX ix_snapshots_obs ON observation_snapshots(observation_id, captured_at DESC);

-- Olay sürümleri (yalnızca maddi değişiklikte yeni sürüm) ---------------------

CREATE TABLE event_versions (
  id INTEGER PRIMARY KEY,
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  state_json TEXT NOT NULL,
  state_hash TEXT NOT NULL,
  change_types_json TEXT NOT NULL DEFAULT '[]',
  change_note TEXT,                -- deterministik "Ne değişti?" metni
  is_major INTEGER NOT NULL DEFAULT 1,
  summary_status TEXT NOT NULL DEFAULT 'pending',   -- pending|llm|template|failed
  title_tr TEXT,
  summary_tr TEXT,
  why_tr TEXT,
  what_changed_tr TEXT,
  details_tr TEXT,
  actions_json TEXT,
  summary_source TEXT,
  summary_note TEXT,
  summarized_at TEXT,
  UNIQUE(event_id, version)
);
CREATE INDEX ix_event_versions_created ON event_versions(created_at DESC);

CREATE TABLE event_version_evidence (
  event_version_id INTEGER NOT NULL REFERENCES event_versions(id) ON DELETE CASCADE,
  observation_id INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
  snapshot_id INTEGER REFERENCES observation_snapshots(id) ON DELETE SET NULL,
  PRIMARY KEY (event_version_id, observation_id)
);

-- Kullanıcı durumları: gönderildi (deliveries) ile görüntülendi/okundu/susturuldu ayrı.
CREATE TABLE user_event_state (
  event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
  viewed_at TEXT,
  viewed_version INTEGER,
  read_at TEXT,
  read_version INTEGER,
  followed INTEGER NOT NULL DEFAULT 0,
  followed_at TEXT,
  muted_at TEXT,
  muted_version INTEGER,
  updated_at TEXT NOT NULL
);

CREATE TABLE user_actions (
  id INTEGER PRIMARY KEY,
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  action TEXT NOT NULL,            -- view|read|unread|follow|unfollow|mute|unmute
  via TEXT NOT NULL,               -- web|telegram|email
  version INTEGER,
  at TEXT NOT NULL
);

-- Bültenler ve gönderimler --------------------------------------------------

CREATE TABLE bulletins (
  id INTEGER PRIMARY KEY,
  bulletin_date TEXT NOT NULL,     -- kullanıcı saat dilimindeki gün (YYYY-MM-DD)
  kind TEXT NOT NULL,              -- daily|baseline|manual|alert
  slot TEXT NOT NULL UNIQUE,       -- idempotency: "daily:2026-09-26", "alert:2026-09-26T03", "manual:<ts>"
  created_at TEXT NOT NULL,
  window_start TEXT,
  window_end TEXT,
  content_json TEXT NOT NULL,
  is_demo INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE bulletin_items (
  bulletin_id INTEGER NOT NULL REFERENCES bulletins(id) ON DELETE CASCADE,
  event_version_id INTEGER NOT NULL REFERENCES event_versions(id) ON DELETE CASCADE,
  event_id INTEGER NOT NULL,
  section TEXT NOT NULL,
  position INTEGER NOT NULL,
  render_mode TEXT NOT NULL DEFAULT 'full',   -- full|reference
  PRIMARY KEY (bulletin_id, event_version_id)
);

CREATE TABLE deliveries (
  id INTEGER PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  channel TEXT NOT NULL,           -- telegram|email
  kind TEXT NOT NULL,              -- bulletin|alert|test
  bulletin_id INTEGER REFERENCES bulletins(id) ON DELETE SET NULL,
  recipient TEXT NOT NULL,
  status TEXT NOT NULL,            -- pending|sending|sent|partial|failed|uncertain|cancelled
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  sent_at TEXT
);
CREATE INDEX ix_deliveries_status ON deliveries(status, next_attempt_at);

CREATE TABLE delivery_parts (
  id INTEGER PRIMARY KEY,
  delivery_id INTEGER NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,            -- pending|sending|sent|failed|uncertain
  attempts INTEGER NOT NULL DEFAULT 0,
  provider_message_id TEXT,
  last_error TEXT,
  sent_at TEXT,
  UNIQUE(delivery_id, seq)
);

CREATE TABLE delivery_items (
  delivery_id INTEGER NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
  event_version_id INTEGER NOT NULL REFERENCES event_versions(id) ON DELETE CASCADE,
  event_id INTEGER NOT NULL,
  render_mode TEXT NOT NULL,       -- full|reference
  PRIMARY KEY (delivery_id, event_version_id)
);
CREATE INDEX ix_delivery_items_event ON delivery_items(event_id);

CREATE TABLE delivery_attempts (
  id INTEGER PRIMARY KEY,
  delivery_id INTEGER NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
  part_id INTEGER REFERENCES delivery_parts(id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  ok INTEGER NOT NULL,
  classification TEXT,             -- sent|retryable|permanent|uncertain
  error TEXT
);

-- Günlük veriler (hava, piyasa, takvim) olay hafızasından ayrı ------------------

CREATE TABLE daily_data (
  id INTEGER PRIMARY KEY,
  module TEXT NOT NULL,            -- weather|market|calendar
  provider TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  data_time TEXT,                  -- kaynağın kendi veri zamanı
  status TEXT NOT NULL,            -- ok|partial|error
  payload_json TEXT NOT NULL,
  error TEXT,
  is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_daily_data_module ON daily_data(module, fetched_at DESC);

-- Zamanlayıcı ---------------------------------------------------------------

CREATE TABLE job_runs (
  id INTEGER PRIMARY KEY,
  job TEXT NOT NULL,
  slot TEXT NOT NULL,
  status TEXT NOT NULL,            -- running|ok|error|skipped
  attempt INTEGER NOT NULL DEFAULT 1,
  started_at TEXT NOT NULL,
  heartbeat_at TEXT,
  finished_at TEXT,
  detail TEXT,
  UNIQUE(job, slot)
);

CREATE TABLE job_requests (
  id INTEGER PRIMARY KEY,
  job TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  requested_by TEXT,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending|running|done|error
  started_at TEXT,
  finished_at TEXT,
  detail TEXT
);

-- Kullanım, bütçe ve önbellek -----------------------------------------------

CREATE TABLE usage_log (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  day TEXT NOT NULL,
  provider TEXT NOT NULL,
  kind TEXT NOT NULL,              -- llm|search
  units INTEGER NOT NULL DEFAULT 1,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd REAL,
  ok INTEGER NOT NULL DEFAULT 1,
  note TEXT
);
CREATE INDEX ix_usage_day ON usage_log(day, kind);

CREATE TABLE llm_cache (
  cache_key TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  model TEXT,
  response_json TEXT NOT NULL
);
