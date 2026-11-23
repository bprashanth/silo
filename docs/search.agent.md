# How Search Works in Idli (plain-English guide)

Implementation guide for hybrid search across Drive `files`, chat `messages`, and (later) `mail`. See [proposals/architecture/whatsapp-search.md](../proposals/architecture/whatsapp-search.md) for the full design.

## The three retrieval building blocks

### 1. BM25 + Porter stemming (exact & near-exact words, fast, inside DuckDB)

- **What stemming is:** Stripping word endings back to a common root using the Porter stemmer (`birding`, `birders`, `birds` → `bird`; `rehearsals`, `rehearsing` → `rehears`). That way searching `"birding"` matches a caption containing `"Young Birders' Month"` without requiring an exact character match.
- **What Okapi BM25 is:** A classic keyword ranking formula built into DuckDB's `fts` (Full-Text Search) extension. Instead of naive `LIKE '%word1%' AND LIKE '%word2%'` (which fails if even one word is missing and treats `"the"` the same as `"DICE"`), BM25:
  1. Scores documents even if only *some* query words appear (OR-scored, not brittle AND).
  2. Weights **rare words much higher** than common words (IDF: `"Nadhi"` or `"IndusInd"` dominates over `"meeting"` or `"group"`).
  3. Accounts for document length so a 1-line chat message isn't drowned out by a 20-page PDF.
- **Where it shines:** Exact names, acronyms (`DICE`, `EFI`, `SESTA`), URLs, phone/project codes, and rare nouns (`bird`) — the exact places where embeddings alone are noisy or miss.
- **Where it falls short:** True paraphrases with zero shared words (e.g. searching `"what cars were discussed"` against `"Ford is a gas guzzler"`).

### 2. Bi-encoder / Embeddings (`Qwen3-Embedding-0.6B`, meaning search)

- **How it works:** A small neural model turns the **query** into a single 1,024-number vector, and turns each **stored passage** (a Drive chunk or a chat conversation episode) into a 1,024-number vector *independently* (at sync time). At search time, DuckDB computes the cosine similarity (angle) between the query vector and all stored vectors.
- **Why it's called a *bi*-encoder:** Two separate encodings — the query and the passage are encoded in isolation and only meet via a fast dot product.
- **Where it shines:** Speed and paraphrases. Comparing 1 query vector against 10,000 stored vectors takes milliseconds, and it bridges vocabulary gaps (`"what cars were discussed"` ↔ `"Ford is a gas guzzler"`, `"women entrepreneurs"` ↔ `"female_entrepreneurship.pdf"`, `"who should attend"` ↔ `"include Rinj and Vidya"`).
- **Where it falls short:** Because the query and passage never read each other word-by-word, fine distinctions blur: a passage talking *generally* about meetings can score almost as high as the *specific* message with the agreed time, and rare proper nouns often sit in the noise band.

### 3. Cross-encoder / Reranker (`Qwen3-Reranker-0.6B` or `bge-reranker-v2-m3`, precision filter)

- **How it works:** Instead of encoding query and passage separately, a cross-encoder takes **both together in one input** — `[Query] + [Candidate passage]` — lets full attention compare every word of the query against every word of the passage, and outputs a single relevance score (`0.0` to `1.0`).
- **Why it's a *second stage* (not run on the whole database):** Running a neural forward pass over 10,000 rows would take minutes. Running it over only the **top ~30 candidates** already shortlisted by BM25 + Bi-encoder takes ~50–100 ms total.
- **Where it shines:** Sharpening top-5 precision (so decisive messages like a later confirmation aren't pushed past `LIMIT 5`) and abstaining cleanly when none of the 30 candidates actually answer the question.

---

## How we combine them (worked examples)

When you run an unquoted search like `idli list messages --in "Jam Buns" --search "who should attend the CC meeting"`:

```text
Stage 1 — Candidate generation (high recall, fast, inside DuckDB)
  ├─ Path A: BM25 (DuckDB fts) on individual messages
  │          → catches exact words, stemmed forms, names, URLs, acronyms
  └─ Path B: Bi-encoder (Qwen3-Embedding-0.6B) on contextualized conversation episodes
             → catches paraphrases, reply chains, multi-message exchanges

Stage 2 — Merge (Reciprocal Rank Fusion / RRF)
  └─ Combine top ~20 from Path A + top ~20 from Path B → deduplicated shortlist of ~30 candidates

Stage 3 — Cross-encoder rerank (high precision, optional local endpoint)
  └─ Send ONLY those ~30 (query, candidate_episode) pairs through Qwen3-Reranker-0.6B (~50–100 ms)
     → re-sort by true relevance score → return top K with stable refs & excerpts
```

> **Note on quoted phrases:** If the query is in double quotes (`--search '"border effects"'`), Idli skips semantic search and runs **literal phrase matching only**, matching Google/Gmail conventions.

### Concrete examples

1. **Paraphrase ("what cars were discussed" vs `"Ford is a gas guzzler"`):**
   - **BM25 (Path A)** finds 0 hits (no shared words).
   - **Bi-encoder (Path B)** embeds the episode containing `"Ford is a gas guzzler"` close to `"what cars were discussed"`, putting it in the top 20.
   - **RRF** includes it in the ~30-candidate shortlist.
   - **Cross-encoder (Stage 3)** reads `("what cars were discussed", "Chat: Roadtrip | Arun: Ford is a gas guzzler")` together, scores it `0.91`, and puts it at rank #1 — while pushing down noisy bi-encoder hits like `"we need to discuss our travel budget"` (`0.14`).
2. **Exact rare word / typo ("young birding month" or `"young borders month"` vs image caption `"Young Birders' Month — sign up at ..."`):**
   - **BM25 + Porter stemming (Path A)** stems `birding` → `bird` and `Birders` → `bird`, ranking the captioned image #1 directly (with fuzzy fallback catching `borders` → `birders`).
   - **Bi-encoder (Path B)** also places the caption near the top for `"young borders month"`.
   - **Cross-encoder (Stage 3)** sees both the caption text and the query together and confirms it as #1.
3. **Multi-message reply chain ("Abhi's DICE doc"):**
   - Message 1 (Nov 18): *"DICE invitation..."*
   - Message 2 (Nov 20 13:12, quoting Message 1): *"Won't be able to make it"*
   - Message 3 (Nov 20 13:13, Abhiram): *"https://docs.google.com/..."*
   - Because Path B indexes **contextualized conversation episodes** (stitching `parent_id` reply links + 10–15 min bursts with speaker and chat headers), the episode contains all three messages together. BM25 hits `"DICE"` + `"Abhiram"`, Bi-encoder hits the whole stitched episode, and the Cross-encoder ranks the full episode #1 with every supporting `ref`.

## Telemetry & safety

Every `--search` logs to `<sandbox>/log.jsonl`:
- `bm25_hits`, `semantic_hits`, `fused_candidates`
- `reranker_used` (boolean), `reranker_ms`, pre/post rank shifts and top scores
- `fallback_reason` if the reranker or embedder is unreachable (falls back cleanly to RRF or BM25).
