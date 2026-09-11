/*
===============================================================================
SCRIPT NAME:
03_installed_extensions.sql

PURPOSE:
Lists extensions currently installed in the connected database, and
separately lists extensions that are available to install but are not yet
installed, so an operator can confirm prerequisites (e.g.
pg_stat_statements) before relying on a workflow that needs them.

AURORA POSTGRESQL VERSION:
17+

EXECUTION LOCATION:
Any instance (writer or reader) -- extensions are installed per database,
which is the same on every instance in the cluster since they share
storage.

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads pg_extension and pg_available_extensions only. Does not
run CREATE EXTENSION.

REQUIRED PRIVILEGES:
None beyond CONNECT on the target database.

PREREQUISITES:
None.

EXECUTION ORDER:
Step 03 of common/scripts

RELATED SCRIPTS:
01_postgres_and_aurora_version.sql

HOW TO INTERPRET RESULTS:
Section 1 shows what is installed right now in this database -- if
`pg_stat_statements` is missing here, workflows under performance/ and
query-optimization/ that depend on it will not return the expected rows.
Section 2 shows extensions Aurora makes available but that are not yet
installed in this database; an extension appearing here is not itself a
problem, it only means `CREATE EXTENSION` has not been run for this
specific database (this script intentionally does not run it -- see
docs/production-safety/README.md).
===============================================================================
*/

-- Section 1: extensions installed in the current database.
SELECT
    e.extname                                   AS extension_name,
    e.extversion                                AS installed_version,
    e.extnamespace::regnamespace::text          AS schema_name,
    e.extrelocatable                            AS is_relocatable
FROM pg_extension e
ORDER BY e.extname;

-- Section 2: extensions available to Aurora but not yet installed here.
SELECT
    a.name                                       AS extension_name,
    a.default_version                            AS default_version,
    a.comment                                    AS description
FROM pg_available_extensions a
WHERE a.installed_version IS NULL
ORDER BY a.name;
