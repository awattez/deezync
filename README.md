# deezync

Sync the Deezer listening history of one or more users into an Elasticsearch index.

The Deezer API only exposes the **last 100 plays** of a user, with no date filter and no
webhook. `deezync` therefore polls that sliding window periodically and indexes only the
plays it has not seen yet.

Two authentication methods are supported per account:

- **ARL cookie** (practical default): the session cookie of the Deezer web player, used
  against the private `gw-light.php` API. Since Deezer closed its developer portal, this is
  the only way in for most people. Read the warning below before choosing it.
- **OAuth access token**: the official REST API. The sanctioned interface, and the only one
  Deezer documents. In practice it is reserved to whoever already holds credentials, since
  the developer portal stopped issuing new ones (see below).

> [!WARNING]
> **Using the ARL is at your own risk and your own responsibility.**
>
> The private `gw-light.php` API is undocumented and unsupported, and the ARL cookie is not
> mentioned anywhere in [Deezer's terms of use](https://www.deezer.com/legal/cgu). Not being
> mentioned is not the same as being allowed, and several clauses cut against this usage:
>
> - **Article 6** states that Deezer *"strictly forbids all operations of harvesting and
>   mining of texts and data and any other Content accessible on the Site"*, explicitly
>   including *"automated data collection devices"*, absent a formal agreement from Deezer.
>   Polling a history endpoint on a schedule and storing the result is hard to argue out of
>   that wording.
> - **Article 4 (iv)** makes each user *"solely responsible for keeping his/her password safe
>   and confidential"* and forbids using *"the account, name or password of any other user"*.
>   An ARL is a password equivalent: it grants full account access without one. Putting a
>   sibling family profile's ARL in your `users.toml` means holding another user's
>   credential, even inside your own household.
> - **Article 7** lets Deezer suspend access or cancel a subscription *"without notice or
>   compensation"*.
> - **Article 5** is explicit that the user *"is solely liable for his/her use of the Deezer
>   Service"*.
>
> This project takes no position on whether your particular use is permitted. That reading
> is yours to make, and the terms can change. What it does do is stay narrow: it reads your
> own listening history, downloads no audio, bypasses no protection measure, and trains
> nothing. The realistic worst case is account suspension.
>
> **And there is no sanctioned alternative to fall back on.** `developers.deezer.com` has
> refused new application registrations since 2024 (*"We're not accepting new application
> creation at this time"*), and a Deezer community manager confirmed in October 2025 that
> abuse and terms-of-service violations by third parties forced the shutdown, with no
> reopening date announced since. Deezer never announced the closure either, which is why
> even the start date is only ever cited as "early" or "mid" 2024. Applications registered
> before then still work, so the OAuth mode here remains usable for whoever already holds
> credentials. There is no longer a way to obtain new ones.
>
> So the abuse of a few third parties closed the documented route for everyone else. That
> explains the situation without authorising anything. Decide knowingly, or do not run this.

## How it works

```
users.toml ──> for each account ──> fetch the last 100 plays
                   (ARL: gw-light.php deezer.pageProfile, one call
                    OAuth: GET /user/{id}/history, two pages of 50)
                                              │
                                              v
                          Listen (deterministic id user:track:timestamp)
                                              │
                                              v
                         bulk `create` ──> Elasticsearch index (idempotent)
```

Every play gets a deterministic identifier `{user_id}:{track_id}:{timestamp}`. Two runs
that see the same play produce the same `_id`: writes use `create`, and documents that
already exist return a 409 which is counted then ignored. No duplicates, no rewrites.
Both auth methods yield the same track ids and timestamps, so an account can switch from
OAuth to ARL (or back) without creating duplicates.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Requires Python 3.11 or later (`tomllib` is used to read `users.toml`).

### Elasticsearch client version

The project pins `elasticsearch>=9.5,<10`, which requires a **9.x or 10.x** cluster. Per the
[official compatibility rules](https://www.elastic.co/docs/reference/elasticsearch/clients/python),
an 8.x client reaches **8.x and 9.x** and would therefore cover more servers, which is what
this project used to do. That line has shipped nothing since 8.19.3 in December 2025 though,
and running a frozen client to keep a compatibility window open is the worse trade.

If your cluster is still on 8.x, pin back to `elasticsearch>=8.19.3,<9`. Nothing else needs
to change: the repository only calls `indices.exists`, `indices.create` and `helpers.bulk`,
which behave the same on both lines.

## Configuration

### 1. Elasticsearch connection (`.env`)

```bash
cp .env.example .env
```

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ES_URL` | yes | — | Cluster URL |
| `ES_API_KEY` | yes* | — | Elasticsearch API key |
| `ES_USERNAME` / `ES_PASSWORD` | yes* | — | Alternative to the API key |
| `ES_INDEX` | no | `deezer-history` | Destination index |
| `DEEZYNC_USERS_FILE` | no | `users.toml` | Accounts file |

\* Either `ES_API_KEY` **or** the `ES_USERNAME` + `ES_PASSWORD` pair.

Nothing about the listeners lives in `.env`: that all belongs to `users.toml` below.

The `.env` file is read from the current working directory only, without walking up the
tree, hence the `cd` in the crontab example below. Real environment variables take
precedence over the file.

### 2. Deezer accounts (`users.toml`)

```bash
cp users.example.toml users.toml
```

```toml
[[accounts]]
name = "adrien"                 # value of the `user` field in the documents
arl = "xxxxxxxx..."             # Deezer web-player session cookie
timezone = "Europe/Paris"       # where this listener is

[[accounts]]
name = "alice"
access_token = "frYYYYYY"       # OAuth variant, legacy credentials only
timezone = "America/Montreal"
```

An account has exactly those three keys. Everything Deezer already knows about a profile
(its id, its subscription country) is read from the login call that every run makes anyway,
rather than declared here where it could drift out of sync with reality.

`timezone` is the exception, and the reason it is **required**: no API can tell where a
listener sits, and a silent default would yield local hours that look plausible and are
wrong. It drives `dayOfWeek` and `hourOfDay` only: `@timestamp` and `played_at` always stay
in UTC, since Deezer timestamps are absolute instants. Use `"UTC"` if you do not care.

Each account needs exactly one of `arl` or `access_token`. Adding a user means adding an
`[[accounts]]` block. Accounts are processed sequentially; if one fails (expired
credential...) it is logged and the others still run.

### 3. Getting your ARL

Read the [warning](#deezync) above first: this route is undocumented and unsupported, and
whether it is allowed is a call you make for yourself.

1. Sign in on [deezer.com](https://www.deezer.com) with the account to synchronise.
2. Open the browser developer tools (`F12`) > **Application** (Chrome) or **Storage**
   (Firefox) > **Cookies** > `https://www.deezer.com`.
3. Copy the value of the `arl` cookie (a long hexadecimal string) into `users.toml`.

Do not click "log out" afterwards: signing out of the website invalidates the ARL you just
copied. Close the tab instead. Treat the value like a password. It grants full access to the
account without one, which is why `users.toml` is in `.gitignore` and should never be
shared or committed.

An ARL also expires on its own after a few months. `deezync` then reports
`invalid or expired ARL`, and you copy a fresh one. `gw-light.php` is unversioned as well
as undocumented, so it can change without notice.

**Family subscriptions**: each profile has its own ARL. Switch to the profile in the web
player, copy its `arl` cookie, and add one `[[accounts]]` block per profile. Another
profile's ARL is another person's credential, even within your own household, so get their
agreement first. There is no in-session way to pivot between profiles: a given ARL only ever
returns the history of the profile it was created for, and asking for a sibling profile
answers an empty history rather than an error. `deezync` therefore always trusts the profile
the ARL resolves to at login, so a mix-up cannot pass for a successful run that synced
nothing.

### 4. Getting an OAuth access token (legacy)

The official route requires an application created on the
[Deezer developer portal](https://developers.deezer.com), which has been closed to new
registrations since 2024 and answers *"We're not accepting new application creation at this
time"*. This section is therefore only actionable if you registered an application before
then; existing ones keep working. If you already own one:

1. Open the following URL in a browser, signed in as the account to synchronise:

```
https://connect.deezer.com/oauth/auth.php?app_id=APP_ID&redirect_uri=http://localhost/&perms=basic_access,listening_history,offline_access
```

2. Deezer redirects to `http://localhost/?code=XXXX`. Exchange that code for a token:

```
https://connect.deezer.com/oauth/access_token.php?app_id=APP_ID&secret=SECRET&code=XXXX&output=json
```

3. Copy the `access_token` into `users.toml`.

The `listening_history` permission is mandatory, and `offline_access` prevents the token
from expiring; without it the token has to be renewed regularly.

## Usage

```bash
.venv/bin/deezync                    # one cycle over every account in users.toml
.venv/bin/deezync --users prod.toml  # a different accounts file
.venv/bin/deezync -v                 # verbose logging
```

Output:

```
2026-08-07 12:30:01 INFO    adrien           100 listens read,   7 new,  93 already indexed
2026-08-07 12:30:02 INFO    alice             42 listens read,   0 new,  42 already indexed
2026-08-07 12:30:02 INFO    7 new listen(s) indexed into deezer-history
```

Exit codes: `0` success, `1` at least one account failed, `2` invalid configuration.

The index is created with its mapping on the first run if it does not exist yet.

### Scheduling

No embedded scheduler: one run equals one cycle. Periodicity is handled by cron.

```cron
*/30 * * * * cd /path/to/deezer-es-sync && .venv/bin/deezync >> deezync.log 2>&1
```

**Which frequency?** The 100-track window represents roughly 5 to 6 hours of continuous
listening. Running every 30 minutes leaves a comfortable margin: even a heavy listener
cannot push 100 tracks through that interval. One to two hours is still safe for normal use.

### Cloud Run

[`ops/`](ops/) is a Terraform stack for Google Cloud: Cloud Build packs this
repository with buildpacks, Elasticsearch and Deezer credentials go in Secret
Manager, and a Cloud Run Job runs every 30 minutes via Cloud Scheduler. Copy
the directory into a private repository, or apply it from this clone —
`secrets.auto.tfvars` is gitignored. See [`ops/README.md`](ops/README.md).

## Document schema

| Field | Type | Deezer source |
|---|---|---|
| `id` | keyword | `{user_id}:{track_id}:{timestamp}` |
| `user` | keyword | `name` of the account in `users.toml` |
| `@timestamp` | date | play `timestamp`, in UTC |
| `played_at` | date | same as `@timestamp` |
| `title` | keyword | `title` |
| `artist` | keyword | every billed artist, primary first (see below) |
| `album` | keyword | `album.title` |
| `duration` | integer | `duration`, converted to **milliseconds** |
| `explicit` | boolean | `explicit_lyrics` |
| `url` | keyword | `link` |
| `country` | keyword | subscription market, read at login |
| `dayOfWeek` | keyword | derived from `played_at`, in the account timezone (`Monday`...) |
| `hourOfDay` | long | derived from `played_at`, in the account timezone (0-23) |
| `deezer_metadata` | object | the track record carried by the history entry (see below) |

Two fields are normalised rather than copied as they arrive:

- `duration` is stored in **milliseconds**, whereas Deezer counts in seconds. The untouched
  value remains available in `deezer_metadata.duration`.
- `artist` is a list rather than a single name, holding the primary artist followed by the
  co-artists (`contributors.main_artist`, or its `mainartist` spelling) and the featurings
  (`contributors.featuring`), deduplicated case-insensitively. The gateway also exposes an
  `artist` contributor role, which is left out: it lists band members and session players
  rather than billed artists.

`country` is the subscription market Deezer reports at login (`COUNTRY` for the gateway,
`country` on `/user/me`), not a geolocation of the play: a French account streaming from
abroad still reports `FR`. Deezer does expose a geo-IP guess under `SETTING.location`, but
it describes the machine making the request and goes stale, so it is ignored.

`deezer_metadata` is the history entry itself, normalised to the official REST API shape.
In ARL mode the `deezer.pageProfile` response is rich enough to need no follow-up call:
the track `isrc`, `contributors` broken down by role, `track_position`, `disk_number`,
`rank`, `gain`, and artist and album objects with their artwork hashes. `isrc` is indexed
and queryable; playback plumbing (`track_token`, per-format file sizes, `rights`) is
dropped before indexing.

The gateway also exposes `DATE_START`, which is **not** used: it is a rights start date,
frequently a `2000-01-01` placeholder, not a release date.

The full definition lives in
[src/deezync/infrastructure/index_mapping.json](src/deezync/infrastructure/index_mapping.json)
and can be applied manually with `PUT deezer-history` in the Kibana Dev Tools.

### Storage tuning

The index definition is tuned for this workload, which cuts the footprint roughly in half
(measured on 50 000 synthetic listens, single shard, force-merged: 26.3 MB down to
11.3 MB, about 553 to 238 bytes per document):

- `index.codec: best_compression` on the index settings. On its own this accounts for most
  of the gain (26.3 to 16.1 MB), because `_source` dominates the footprint here.
- Everything in `deezer_metadata` that is a URL, an image, a preview or a hash is mapped
  with `index: false, doc_values: false`. It stays in `_source` and remains readable, it is
  simply not searchable or aggregatable.
- Same treatment for the raw fields already promoted to the top level (`title`, `duration`,
  `link`, `explicit_lyrics`, `timestamp`, `artist.name`, `album.title`): they were indexed
  twice.
- `deezer_metadata.artist.id`, `deezer_metadata.album.id` and `deezer_metadata.rank` stay
  indexed: they are the stable catalogue identifiers, more reliable than names for
  aggregations.
- `deezer_metadata` is `dynamic: false`, so a new field appearing in the Deezer payload is
  kept in `_source` without silently growing the mapping.
- Narrower numeric types (`hourOfDay` as `byte`, `duration` as `integer`) and
  `doc_values: false` on `id`, which is unique per document and never aggregated.

Index sorting on `@timestamp` was measured and **rejected**: it made the index slightly
larger (16.5 versus 16.1 MB) for no query benefit, since listens are already ingested in
chronological order.

## Known limitations

- **100-track window.** A long cron outage during a long listening session means a
  permanent loss: the Deezer API exposes nothing beyond that window. This is a
  server-side cap rather than a paging limit; `deezer.pageProfile` answers with exactly 100
  entries and `"total": 100` however large the requested `nb`. The alternatives were
  checked and none carries track-level plays with timestamps: `pipe.deezer.com`'s
  `RecentlyPlayed` returns containers (albums, playlists) rather than individual plays,
  and `PrivateUserPodcastRaw` only covers favourited podcasts.
- **No back catalogue.** To build a retroactive base, request a GDPR export of your data
  from Deezer, bulk load it, then let `deezync` take over.
- **No playback context.** A history entry says what was played and when, never how, which
  is the frustrating part of what Deezer exposes. There is no `ip`, no `platform`, no
  `skipped`, `shuffle` or `offline` flag, no `reason_start` or `reason_end`, and no
  `listened_to_ms` or `listened_to_pct`: only the length of the track, never how much of it
  you actually heard. Those fields stay declared in the mapping and always empty, ready for
  the day a source can fill them.
- **Occasional near-duplicates in ARL mode.** The private history endpoint sometimes
  reports the same play twice with timestamps a few seconds apart (also observed by the
  multi-scrobbler project). The timestamps differ, so the deterministic ids differ and
  both entries are indexed. Not deduplicated in v1.

## Project layout

```
src/deezync/
├── domain/            # Listen, DeezerAccount: business rules, no dependencies
├── application/       # SyncHistory: use case orchestration
├── infrastructure/    # DeezerClient (OAuth), DeezerGwClient (ARL),
│                      # ListenRepository (Elasticsearch)
├── config.py          # reads the environment and users.toml
└── cli.py             # entry point, wires the dependencies together
```

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pre-commit install
.venv/bin/pytest
```

Tests hit neither the Deezer API nor Elasticsearch: the client and the repository are
replaced by in-memory doubles.

`pre-commit install` is done once per clone. The hook runs `ruff check --fix` and
`ruff format`, then the credential guards. Those refuse `users.toml` and `.env` outright,
including behind a `git add -f`, and reject any staged file carrying a private key, a
192-character hex ARL, a Deezer OAuth token, or an `ES_API_KEY` with a value in it.
`.gitignore` already keeps the two credential files out of the repository, so the guards
exist for what it cannot catch, namely a secret pasted into a file that is tracked. Run
`.venv/bin/pre-commit run --all-files` to sweep the whole tree.
