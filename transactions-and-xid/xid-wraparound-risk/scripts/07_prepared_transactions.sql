/*
===============================================================================
SCRIPT NAME:
07_prepared_transactions.sql

PURPOSE:
Checks for orphaned two-phase-commit (PREPARE TRANSACTION) entries, which behave like an indefinitely long-running transaction until resolved.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 07 of workflow 'transactions-and-xid/xid-wraparound-risk'

RELATED SCRIPTS:
../prepared-transactions/README.md

HOW TO INTERPRET RESULTS:
Any row here older than a few minutes is almost certainly a bug in a distributed transaction coordinator, not intentional application behavior -- coordinate with the owning team to COMMIT PREPARED or ROLLBACK PREPARED it.
===============================================================================
*/

-- Outstanding two-phase-commit (PREPARE TRANSACTION) entries. These hold
-- locks and prevent vacuum from advancing past their snapshot until they
-- are COMMIT PREPARED / ROLLBACK PREPARED. Aurora PostgreSQL supports
-- two-phase commit, but very few application frameworks intentionally use
-- it -- an unexpected non-empty result here is almost always a bug in a
-- distributed-transaction coordinator (e.g. XA-style ORM configuration)
-- rather than expected behavior.
SELECT
    gid,
    prepared,
    owner,
    database,
    now() - prepared                                            AS prepared_age
FROM pg_prepared_xacts
ORDER BY prepared ASC;
