# Database ownership

No database files should be committed or manually placed in this directory.

- FluidPanel uses the persistent MariaDB Docker volume `fluidpanel_mariadb_data`.
- FluxWeb uses its configured external PostgreSQL/Supabase database through `DATABASE_URL` and `DIRECT_URL` in `FluxWeb/.env`.

Back up those real data stores, not this directory.
