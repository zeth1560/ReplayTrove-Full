-- ReplayTrove: poster thumbnails for clips (run once on your Supabase/Postgres database).
-- Objects live in S3 under thumbnails/{slug}.jpg; worker fills these columns after upload.

ALTER TABLE clips
  ADD COLUMN IF NOT EXISTS thumbnail_s3_key text;

ALTER TABLE clips
  ADD COLUMN IF NOT EXISTS thumbnail_created_at timestamptz;
