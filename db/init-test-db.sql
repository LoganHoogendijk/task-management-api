-- Runs automatically on first container init (empty volume only).
-- POSTGRES_DB in docker-compose.yml creates `taskmanager`; this adds
-- the separate `taskmanager_test` database the test suite points at,
-- so `docker compose exec app pytest` has somewhere to run against
-- without touching dev/seed data.
CREATE DATABASE taskmanager_test;
GRANT ALL PRIVILEGES ON DATABASE taskmanager_test TO taskmanager_user;