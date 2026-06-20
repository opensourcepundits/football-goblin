# Data Schemas & Architecture Contract: Live Match Assistant

This document outlines the database schemas, collection structures, and vector relationship strategies for our live match commentator assistant PWA.

The core architectural goal is **Zero External Lookups During Play**. All static metadata, biographical entities, seasonal baselines, and historical trivia are stored internally and indexed before kickoff. The live third-party API stream is reserved exclusively for structural match-state updates (e.g., score changes, possession ticks, fouls).

---

## 1. Static Metadata Store (Google Cloud Firestore)

### Collection: `teams`

**Role:** Stores baseline club profiles, venue metrics, and pre-aggregated historical seasonal statistics. This prevents the need to calculate season goal averages or lookup stadium capacities mid-game.

```json
// Path: /teams/{team_id}
{
  "team_id": "tm_mun_01",
  "name": "Manchester United",
  "short_name": "MUN",
  "logo_url": "https://storage.googleapis.com/match-assistant-assets/logos/mun.png",
  "venue": {
    "name": "Old Trafford",
    "city": "Manchester",
    "capacity": 74310
  },
  "current_season_stats": {
    "played": 28,
    "won": 16,
    "drawn": 5,
    "lost": 7,
    "goals_scored": 52,
    "goals_conceded": 34,
    "clean_sheets": 9,
    "average_possession": 54.2
  },
  "historical_records": {
    "biggest_win_vs_liverpool": "7-1 (1997)",
    "unbeaten_run_record": 29
  }
}
```

### Collection: `players`

**Role:** Acts as the biographical and historical master record for every active squad member. When a live event reports a pass streak, card, or substitution involving an ID, this document provides the immediate background layer (e.g., preferred foot, milestone warnings, structural metrics).

```json
// Path: /players/{player_id}
{
  "player_id": "pl_bruno_08",
  "team_id": "tm_mun_01",
  "display_name": "Bruno Fernandes",
  "full_name": "Bruno Miguel Borges Fernandes",
  "jersey_number": 8,
  "position": "Midfielder",
  "nationality": "Portugal",
  "birth_date": "1994-09-08",
  "preferred_foot": "Right",
  "height_cm": 179,
  "current_season_metrics": {
    "appearances": 26,
    "minutes_played": 2340,
    "goals": 7,
    "assists": 11,
    "expected_goals_xG": 6.42,
    "expected_assists_xA": 9.81,
    "passing_accuracy_pct": 82.4,
    "yellow_cards": 5,
    "red_cards": 0
  },
  "milestone_alerts": {
    "next_club_appearance_milestone": 250,
    "current_club_appearances": 248,
    "goals_to_club_record": 3
  }
}
```

---

## 2. Dynamic Live Match Store (Google Cloud Firestore)

### Collection: `live_matches`

**Role:** This document represents the only entry point for real-time operational feeds. The Ingestion Service routinely overwrites this small, volatile payload. Because the PWA subscribes directly to this document path via Firestore's `onSnapshot()`, UI changes ripple instantly down to the client.

```json
// Path: /live_matches/{match_id}
{
  "match_id": "mtch_2026_06_01",
  "status": "LIVE", // UPCOMING, LIVE, FIRST_HALF, SECOND_HALF, FT
  "clock": {
    "minute": 64,
    "second": 12,
    "injury_time_added": 0
  },
  "score": {
    "home_team_id": "tm_mun_01",
    "away_team_id": "tm_liv_02",
    "home_score": 1,
    "away_score": 0
  },
  "live_telemetry": {
    "possession": {
      "home_pct": 52,
      "away_pct": 48
    },
    "shots": {
      "home_on_target": 4,
      "away_on_target": 2
    },
    "expected_goals_xG": {
      "home": 1.45,
      "away": 0.88
    },
    "current_dangerous_attacks_last_5min": "home"
  },
  "last_significant_event": {
    "type": "FOUL",
    "player_involved_id": "pl_bruno_08",
    "recipient_player_id": "pl_salah_11",
    "timestamp": "2026-06-20T12:20:00Z"
  }
}
```

---

## 3. The Vector Relationship Index (Vertex AI Vector Search / pgvector)

**Role:** Rather than managing brittle, complex relational database loops or writing thousands of nested if/else clauses to match players to historical milestones, narratives are parsed into unstructured text snippets, vectorized using text embedding models, and stored in a vector index.

### Index Document Structure

```json
{
  "vector_id": "vec_trivia_8943",
  "entities": ["pl_bruno_08", "tm_liv_02"],
  "context_tags": ["penalty", "anfield", "rivalry"],
  "text_content": "Bruno Fernandes has converted 4 crucial penalties against Liverpool at Anfield, representing the highest success rate of any visiting midfielder since 2020.",
  "embedding": [0.0125, -0.0843, 0.3122, "...", 0.0091]
}
```

---

## 4. The Live Interaction Runtime Loop

```text
[ Live Match Event Ingestion ]
              │
              ▼
    Is event significant? (e.g., Penalty / Yellow Card / Sub)
              │
              ├─► YES ──► Extract `player_id` + `opponent_team_id`
              │           │
              │           ▼
              │       Generate Query Vector: "Bruno Fernandes record vs Liverpool"
              │           │
              │           ▼
              │       Query Vertex AI Vector Search Index
              │           │
              │           ▼
              │       Extract top match: "vec_trivia_8943"
              │           │
              │           ▼
              │       Push "Commentator Sprinkle" text instantly to PWA
              │
              └─► NO ───► Discard/Log event quietly
```

---

## 5. Summary of Architectural Separation

| Data Category | Target Host Component | Dynamic Lifecycle | Role in App |
|---|---|---|---|
| Team Profiles | Firestore `/teams` | Pre-calculated every 24 hrs | Structural layouts, base statistics, and UI logos |
| Player Bio/Stats | Firestore `/players` | Pre-calculated every 24 hrs | Career tallies, physical metrics, milestone watches |
| Live Telemetry | Firestore `/live_matches` | Mutated every 15 seconds | Core dashboard stream (clocks, possession bars, live xG) |
| Relationship Trivia | Vertex AI Vector Search | Generated pre-season/pre-match | Semi-structured semantic triggers for narrative commentator notifications |

---

## 6. Architecture Review Notes

### Strengths

- **Read/write separation is correct.** Splitting slow-changing biographical/seasonal data (`teams`, `players`) from the fast-mutating `live_matches` doc avoids re-fetching or recalculating static data every 15 seconds.
- **`onSnapshot()` on a single small live doc** is a sensible way to get instant propagation without overengineering a pub/sub layer.
- **Vector search for trivia instead of if/else trees** is a good fit. Milestone/rivalry narratives are inherently fuzzy (e.g., "biggest win vs Liverpool," "penalty record at Anfield") — that's semantic retrieval, not relational lookup, so pgvector/Vertex AI is the right tool.

### Open Questions / Risks

1. **Write contention on `live_matches`.** A single mutable document updated every 15 seconds (clock, score, possession) alongside low-frequency narrative writes (`last_significant_event`) risks field overwrite ordering issues and unnecessary full-document re-renders on the client unless field-level diffing is used. Consider splitting high-frequency fields (`clock`, `score`, `live_telemetry`) from low-frequency narrative-triggering fields (`last_significant_event`) into separate documents or subcollections so the PWA can subscribe selectively.

2. **No mid-match freshness mechanism for the vector index.** The index is described as "generated pre-season/pre-match" with no described path for incremental embedding updates as new milestones become live-relevant (e.g., a player ties a record mid-match). Worth confirming whether this is an intentional scope limit or a gap.

3. **No de-duplication/cooldown logic in the runtime loop.** As written, the same trivia snippet could fire repeatedly if the same player triggers the same event type more than once in a match (e.g., two fouls in 10 minutes). A short-term per-match cache of already-surfaced `vector_id`s would prevent repetitive commentary.

4. **Top-1 vector match only.** Pulling only the single top result risks repetitive or low-quality narratives over a 90-minute match. A top-3 retrieval with a lightweight relevance/freshness re-ranker would diversify commentary.

5. **Milestone fields need a mid-match patch path.** `players.milestone_alerts` (e.g., `goals_to_club_record`) is tied to the 24-hour batch recompute, but these fields can go stale the instant a relevant event happens live (e.g., a goal is scored). Consider a narrow, fast patch path for milestone-relevant fields that's decoupled from the full nightly recompute.

---

## 7. Build Roadmap

Build the data layer fully before touching the PWA — get the knowledge base solid and validated first, UI last.

### Phase 1: Static metadata store (`teams` + `players`) — scoped to 48 World Cup 2026 teams

1. **Lock the team list.** All 48 are already finalized (hosts Canada/Mexico/USA + 45 qualifiers across UEFA, CONMEBOL, CAF, AFC, Concacaf, OFC). Hardcode this list rather than discovering it dynamically — it won't change mid-tournament.
2. **Seed `teams` (48 documents)** using the V1 schema in Section 9. Source: FIFA.com for group/ranking data, Wikipedia/Wikidata for historical World Cup records per country.
3. **Seed `players` (48 × 26 ≈ 1,248 documents)** using the V1 schema in Section 9. Source: ESPN's finalized squad lists (locked June 2) for the base roster; Transfermarkt for `club_context.pre_tournament_form` and `injury_status.injury_history`.
4. **One-time pre-tournament form + injury pull.** Since `pre_tournament_form` is a snapshot (not live), this is a single batch pull per player, not a recurring job — run it once, close to kickoff, and you're done for V1.
5. **Validation pass.** Spot-check 2-3 teams, including a debutant nation (e.g., Cape Verde, Curaçao, Jordan, or Uzbekistan), since smaller federations are more likely to have data gaps in third-party sources than established teams.

### Phase 2: Vector relationship index ("the knowledge base")
- Pick an embedding model, build the ingestion pipeline: raw trivia/narrative text → embeddings → stored vectors with `entities` and `context_tags`.
- Manually write 15–20 trivia snippets for the seed teams/players and validate end-to-end retrieval quality (query → top match → sanity-check relevance) before building anything on top of it.
- Decide on top-1 vs. top-k re-ranking here, since changing it later means touching the query layer, not just the data.

### Phase 3: Live match store + runtime loop
- Build `live_matches` and the ingestion service that writes to it from the third-party live API.
- Wire up the "is event significant → query vector index" loop as a standalone backend service, testable independently of any UI (e.g., log output to console). Resolve the write-contention and dedup/cooldown questions from Section 6 here.

### Phase 4: PWA (last)
- Once Phases 1–3 are stable and a manually triggered live event correctly resolves trivia, the PWA becomes a thin `onSnapshot()` listener + renderer — much lower risk built this way.

---

## 8. Data Source Suggestions

### For the static metadata store (`teams`, `players`, historical records)

- **Wikipedia / Wikidata** — solid for club founding dates, venue capacities, historical records (e.g., biggest wins, unbeaten runs), and player biographical data (birthdate, nationality). Wikidata's structured query service (SPARQL) is easier to bulk-pull from than scraping prose pages.
- **Transfermarkt** — strong for squad lists, player market values, contract/injury history, and transfer records. No official API, but community-maintained scrapers exist (e.g., `transfermarkt-scraper`, `worldfootballR` for R users). This is also the most reliable single source for `injury_status.injury_history` — it maintains a per-player injury log with dates and matches missed.
- **ESPN's World Cup injury tracker** — a curated, tournament-specific source for which players are managing fitness concerns heading into or during the World Cup; useful as a cross-check against Transfermarkt's more granular club-level injury log.
- **Official club/league sites** — most top-flight clubs and leagues (Premier League, La Liga, etc.) publish official squad and fixture data; useful as a ground-truth cross-check against third-party providers.
- **football-data.org** — free tier covering ~12 major leagues, good for bootstrapping seasonal stats without a paid plan.
- **Understat** — free xG/xA data, but limited to six leagues; useful if your `current_season_metrics.expected_goals_xG` fields need a free historical baseline.

### For historical trivia / narrative snippets (to seed the vector index)

- News archives and football journalism sites (BBC Sport, The Athletic, ESPN) for rivalry storylines and milestone write-ups — good raw material to rewrite into your own `text_content` snippets.
- Club official histories/archives pages, often the most reliable source for "record vs. opponent" type stats.
- Wikipedia match/rivalry pages (e.g., "Manchester United–Liverpool rivalry") for structured historical context.

### For the live match feed

- **API-Football (API-SPORTS)** — broad coverage (1,200+ leagues), live scores updated roughly every 15 seconds, free tier available (~100 requests/day), straightforward REST API authenticated via an API key. A good default for live `score`/`clock`/event data.
- **Sportmonks** — broader paid feature set including proprietary xG and a "Pressure Index," sub-15-second live updates, transparent self-serve pricing; worth it if you need advanced live telemetry (matches the `live_telemetry.expected_goals_xG` fields in your schema) beyond what API-Football's free tier offers.
- **FotMob** — has no official public API; access is via undocumented/reverse-engineered endpoints (community wrappers exist, e.g. a `fotmob-api` PyPI package and unofficial Ruby/JS wrappers). It's free and has strong xG/shot-map data, but being unofficial means it can break without notice — fine for prototyping, risky as a sole production dependency.
- **Sportradar / Opta** — enterprise-grade, official league partnerships, most reliable for production-scale apps, but priced and contracted accordingly — worth evaluating once the prototype proves out the architecture.

**Practical note:** since most of this data (standings, season stats, historical records) doesn't change minute to minute, cache aggressively and only hit the live endpoint for the truly live fields (`clock`, `score`, in-match events) — this keeps you within free-tier rate limits during development.

---

## 9. V1 Schema: World Cup 2026 (National Team Scope)

V1 is scoped to only the 48 teams currently competing in the 2026 FIFA World Cup. This changes the `teams` and `players` shapes from the original club-oriented examples in Section 1, since national teams don't have a club "season," a home venue in the same sense, or club-only milestone tracking. Use the schemas below as the V1 source of truth in place of Section 1's examples.

### Collection: `teams` (V1 — national teams)

```json
// Path: /teams/{team_id}
{
  "team_id": "tm_por",
  "name": "Portugal",
  "short_name": "POR",
  "confederation": "UEFA",
  "group": "F",
  "fifa_ranking": 6,
  "logo_url": "https://storage.googleapis.com/match-assistant-assets/flags/por.png",
  "tournament_stats": {
    "played": 1,
    "won": 1,
    "drawn": 0,
    "lost": 0,
    "goals_scored": 2,
    "goals_conceded": 0,
    "clean_sheets": 1
  },
  "historical_records": {
    "best_world_cup_finish": "3rd place (1966, 2006)",
    "appearances_total": 8,
    "biggest_world_cup_win": "7-0 vs North Korea (1966)"
  }
}
```

### Collection: `players` (V1 — national team squad, with club form + injury tracking)

**Role addition:** beyond biographical and tournament data, each player document now carries (1) **pre-tournament club form** — what they were doing for their club in the weeks/months leading into the World Cup, used to talk about a player's form heading into a match — and (2) **injury status**, both current and historical, so commentary can reference fitness concerns or recent return-from-injury context.

```json
// Path: /players/{player_id}
{
  "player_id": "pl_bruno_08",
  "team_id": "tm_por",
  "display_name": "Bruno Fernandes",
  "full_name": "Bruno Miguel Borges Fernandes",
  "squad_number": 8,
  "position": "Midfielder",
  "birth_date": "1994-09-08",
  "preferred_foot": "Right",
  "height_cm": 179,

  "club_context": {
    "current_club": "Manchester United",
    "league": "Premier League",
    "pre_tournament_form": {
      "period_covered": "2025-26 season, through 2026-05-25",
      "appearances": 34,
      "goals": 9,
      "assists": 13,
      "minutes_played": 2890,
      "passing_accuracy_pct": 83.1,
      "form_note": "Started Man United's final 12 league matches before the World Cup break"
    }
  },

  "injury_status": {
    "is_currently_injured": false,
    "current_injury": null,
    "fitness_note": "Returned to full training 2026-05-30, no minutes restriction",
    "injury_history": [
      {
        "injury_type": "Hamstring strain",
        "date_occurred": "2026-03-10",
        "date_returned": "2026-04-02",
        "days_out": 23,
        "club_matches_missed": 5
      },
      {
        "injury_type": "Ankle knock",
        "date_occurred": "2025-11-18",
        "date_returned": "2025-11-25",
        "days_out": 7,
        "club_matches_missed": 1
      }
    ]
  },

  "tournament_metrics": {
    "appearances": 1,
    "minutes_played": 90,
    "goals": 1,
    "assists": 0,
    "yellow_cards": 0,
    "red_cards": 0
  },

  "milestone_alerts": {
    "world_cup_caps_total": 1,
    "world_cup_goals_total": 1,
    "country_world_cup_goals_record": 9,
    "international_caps_total": 92
  }
}
```

**Field notes:**
- `injury_status.current_injury` is `null` when fit; when injured, populate with the same shape as an `injury_history` entry plus an `expected_return_date`. This lets the commentator layer flag "playing through fitness concerns" if a player took the pitch shortly after `date_returned`.
- `club_context.pre_tournament_form` is a snapshot, not a live feed — refresh it once before the tournament starts (it doesn't need in-tournament updates, since club seasons are over once the World Cup begins for most leagues).
- `injury_history` should be capped (e.g., last 3-5 entries) rather than a full career log, to keep documents small and queries fast.
