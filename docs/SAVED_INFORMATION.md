# Saved information: database foundation

Status: local implementation and isolated SQL tests only. Not applied to an
operating/shared database; no HTTP API, UI, authentication flow or deployment.
Base: main `28cdbd682587df11b4cfc53dff0d3ecad94938e5`.

## Storage and permissions

`machimoa_saved.information` stores only account UUID, original curation UUID,
nullable current curation reference, and creation time. Its primary key is
`(user_id, original_curation_id)`; language, URL and title are not identity keys.
No content, title, profile, email, provider token or source URL snapshot is stored.

`user_id` references `auth.users` with account-deletion cascade. A curation's
physical deletion sets its current reference to NULL and preserves its original
UUID, so the owner can still remove the bookmark. Unpublish does not delete it.
The existing curation table definition, published-read policy, ingest/review
functions and administrator policy are unchanged. Adding this relationship
causes only saved references to be cleared when content is deleted; it does not
block deletion or change publication behavior.

The private schema is not added to Supabase's exposed schema configuration.
Authenticated users have SELECT/DELETE on their own rows through RLS, no direct
INSERT/UPDATE. `save_information` is the sole security-definer entry point: it
derives the owner from `auth.uid()` and validates current database content. Other
functions use invoker permissions and RLS. All four public functions explicitly
deny PUBLIC, anon and service_role execution; authenticated has the minimum
function privileges. Future web handlers must use the existing session-authenticated
client, not a service-role client or a caller-supplied account ID.

The application category is `curations.user_category`, not legacy `category`.
Saving requires `is_published=true`, confirmed category policy/program and all six
nonempty reviewed bilingual fields, matching the public app display gate.
Closed/expired application dates do not prevent bookmarking published content.
The target content row is locked FOR SHARE until the save commits, serializing
against unpublish/update/delete. Duplicate save requests retain creation time.

## Database functions / next-step contract

Functions receive UUIDs, not route slugs. A web handler must resolve a visible
detail route to its stable curation ID. No locale is persisted in a save.

| Function | Parameters | Successful result |
| --- | --- | --- |
| `save_information` | `p_curation_id: uuid` | `{id, saved:true, savedAt}`; repeat is idempotent |
| `remove_saved_information` | `p_curation_id: uuid` (original ID) | `{id, saved:false}`; absent/already removed also succeeds |
| `saved_information_state` | `p_curation_id: uuid` | `{id, saved:boolean}` for this account only |
| `list_saved_information` | `p_locale: ko/ja` default ko; `p_limit: 1..100` default25; `p_offset: 0..100000` default0 | `{items, hasMore}` |

Each list item is `{id, savedAt, availability, information}`. Available information
contains the current public `slug`, category, localized title/summary and deadline
kind/date. It contains no body. Unavailable information is NULL and availability
is `unavailable`; never substitute cached titles or expose private content. This
also covers a changed category or missing reviewed translation. The owner still
removes the record using `id`. Do not claim that the item was deleted specifically:
the contract intentionally does not distinguish missing/nonpublic/non-displayable.

Order is savedAt descending with original ID descending as the tie-breaker.
Offset pages can shift while the user changes the list; the UI should refresh the
first page after removal. A database exception propagates and must render a retry
state, never an empty-list success or unavailable item.

Proposed HTTP mapping for the next implementation stage (not an implemented API):

| Database outcome | Web handling |
| --- | --- |
| `22023` / UUID parse `22P02` | 400 invalid request |
| `PT404` | 404 information unavailable; never report saved |
| No verified session | 401 / login flow, before RPC |
| `42501` with verified session | inspect permission/configuration failure; do not assume every denial is expiry |
| Other DB/network failure | generic failure/retry; no success or private error details |

Mutation requests must retain existing same-origin POST checks and private,
no-store responses. Extend service-worker network-only coverage for future save
APIs. Verify the session before every request and use explicit save/remove
operations, not a toggle, when resuming a pending login action. Consume/cancel a
pending intention so refresh/back navigation cannot re-save after removal. Notify
success only after a successful DB result. All these HTTP/auth/UI items are next
stage work, not delivered by this migration.

## Isolated validation

Run with bundled Node and an existing PGlite installation:

```powershell
$env:MACHIMOA_PGLITE_MODULE = 'absolute/path/to/@electric-sql/pglite/dist/index.js'
node scripts/test_saved_information_sql.mjs
```

The test creates a NEW in-memory PGlite instance with no host, connection string,
data directory, network or .env access. The module path is a temporary process
variable only. Synthetic auth users and `auth.uid()` stand in for Supabase's auth
schema and trusted JWT-sub extraction. Because the original curation CREATE is
absent from the repository, a documented minimal synthetic pre-P0 table is used,
then 21 existing canonical content/review/ingest migrations are applied unchanged.
No Production rows or complete original DB schema are copied.

The suite checks anon and missing identity, two users, raw-row permissions,
ownership forgery, provider-independent/language-independent identity, duplicate
saves, repeat removal, public eligibility, pagination, masked nonpublic/deleted
rows, account cascade, errors vs empty lists, statement rollback after injected
write failure, and non-destructive feature rollback. It compares existing content,
public-read permissions and review function definitions/ACLs before/after the new
migration. It does not verify real JWT/OAuth, Supabase/PostgREST schema exposure,
network failures, independent-connection lock contention, HTTP or browser flows.

## Rollback and later operating application

`supabase/rollback/20261001000100_saved_information_down.sql` drops only the new
public entry points and revokes feature access. The private schema/table/helper and
all saved rows are retained; existing content and its permissions remain intact.
Do not re-run the creation migration after this rollback: preserved objects will
conflict. Re-enable access only through a separately reviewed forward migration.

Before any separately authorized operating application, inspect actual auth and
curation schema/types, grants/default privileges, applied migration history and
name collisions. This local suite is not proof of the operating schema. Check
schema-cache visibility and two-account permissions through authenticated
Supabase/PostgREST after application. Existing shared DB access, migration apply,
commit/push/merge/deploy are outside this stage.

Official references checked 2026-10-01:
- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://www.postgresql.org/docs/current/sql-createfunction.html
