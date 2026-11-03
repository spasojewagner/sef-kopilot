-- Executed by the postgres image on the first start of an empty data volume.
-- Application migrations (Alembic) also create these extensions idempotently, so that
-- managed databases without an init hook (Neon) end up in the same state.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
