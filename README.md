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

## 3. The Vector Relationship Index (Vertex AI Vector Search / pgvector/ elasticsearch)

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

## 4. Live Interaction Runtime Loop example

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
              │       Push "goblin" text instantly to PWA
              │
              └─► NO ───► Discard/Log event quietly
```
