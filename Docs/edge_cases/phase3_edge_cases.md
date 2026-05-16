# Phase 3 — Analysis & Clustering Engine: Edge Cases

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §7

---

## EC3.1 — Embedding Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC3.1.1 | Review body is empty string (`""`) | Model produces a valid embedding (zero-meaning vector); will likely become HDBSCAN noise | 🟢 Low |
| EC3.1.2 | Review body is a single word ("terrible") | Valid embedding; may form micro-cluster or noise | 🟢 Low |
| EC3.1.3 | Review body exceeds model's max token length (256 tokens for MiniLM) | Truncated by tokeniser; first 256 tokens embedded; log warning | 🟡 Medium |
| EC3.1.4 | Review body contains only `[EMAIL]` and `[PHONE]` tags (post-PII scrub) | Valid but semantically empty embedding; will be noise | 🟢 Low |
| EC3.1.5 | Mixed-language review (English + Hindi in same body) | MiniLM handles mixed scripts but may reduce embedding quality; accepted as-is | 🟡 Medium |
| EC3.1.6 | Sentence-Transformers model not found locally | Auto-download from HuggingFace; fail if offline with clear error | 🔴 Critical |
| EC3.1.7 | GPU available but CUDA not configured | Fall back to CPU; log info "Using CPU for embeddings" | 🟢 Low |
| EC3.1.8 | Extremely large batch (5000+ reviews) | Batch into chunks of 512; embed sequentially to avoid OOM | 🟡 Medium |

## EC3.2 — UMAP Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC3.2.1 | Input has fewer samples than `n_neighbors` (e.g. 3 reviews, n_neighbors=20) | Auto-adjust `n_neighbors = min(n_reviews - 1, config_value)`; log warning | 🟡 Medium |
| EC3.2.2 | All embeddings are identical (all reviews have same text) | UMAP may produce degenerate output; all points collapse to same location; 1 cluster or all noise | 🟡 Medium |
| EC3.2.3 | Very high-dimensional noise in embeddings | UMAP should still find structure; if not, results degrade gracefully in clustering phase | 🟢 Low |
| EC3.2.4 | `n_components` set higher than input dimensions | Raise `ConfigError`: "UMAP n_components (X) cannot exceed embedding dimension (384)" — though practically never set >50 | 🟢 Low |
| EC3.2.5 | UMAP runs out of memory on large dataset | Catch `MemoryError`; suggest reducing `max_reviews_per_source` in config | 🔴 Critical |
| EC3.2.6 | Non-deterministic results across runs (no fixed `random_state`) | Always set `random_state=42` in config; document that results may vary without it | 🟢 Low |

## EC3.3 — HDBSCAN Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC3.3.1 | All points labeled as noise (-1) | Trigger TF-IDF fallback; report flagged as "low-confidence clustering" | 🟡 Medium |
| EC3.3.2 | Single massive cluster containing 90%+ of reviews | Accept but log warning "dominant cluster detected"; LLM summariser may produce overly broad theme | 🟡 Medium |
| EC3.3.3 | Too many clusters (>20) for a small review set | Rank by cluster size; keep top `max_themes`; aggregate rest as "other" | 🟡 Medium |
| EC3.3.4 | `min_cluster_size` > number of reviews | All points become noise; trigger fallback | 🟡 Medium |
| EC3.3.5 | Cluster with only `min_cluster_size` reviews (e.g. exactly 5) | Valid cluster; LLM summariser works on 5 reviews | 🟢 Low |
| EC3.3.6 | Two distinct sentiment clusters on same topic (e.g. "support great" vs "support terrible") | HDBSCAN should separate them; LLM names them as distinct themes | 🟢 Low |

## EC3.4 — LLM Summariser Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC3.4.1 | LLM API returns HTTP 429 (rate limited) | Retry with exponential backoff (2s, 4s, 8s); max 3 retries | 🟡 Medium |
| EC3.4.2 | LLM API returns HTTP 500 (server error) | Retry once; if persistent, skip cluster with warning | 🟡 Medium |
| EC3.4.3 | LLM returns theme name > 6 words | Truncate to first 6 words; log warning | 🟢 Low |
| EC3.4.4 | LLM returns 0 quotes | Trigger re-prompt; if still 0 after 2 retries, use first review sentence as fallback quote | 🟡 Medium |
| EC3.4.5 | LLM returns quotes that are paraphrased (not verbatim) | Quote validator catches; triggers re-prompt with stronger instruction | 🟡 Medium |
| EC3.4.6 | LLM response is not valid JSON | Catch `JSONDecodeError`; retry once with "respond in valid JSON only" suffix | 🟡 Medium |
| EC3.4.7 | LLM follows malicious instructions embedded in review text | System prompt forbids instruction-following; monitor output for anomalies | 🔴 Critical |
| EC3.4.8 | Cluster reviews are in a language the LLM handles poorly | LLM may produce English themes from non-English reviews; accept if coherent | 🟡 Medium |
| EC3.4.9 | Token budget exhausted mid-cluster-processing | Stop processing remaining clusters; include completed themes only; log "partial analysis" | 🟡 Medium |
| EC3.4.10 | LLM model specified in config doesn't exist | Catch API error; raise `ConfigError` with suggestion to check model name | 🔴 Critical |

## EC3.5 — Quote Validation Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC3.5.1 | Quote is a substring but spans across PII-scrubbed text | e.g., original: "call 9876543210 now" → scrubbed: "call [PHONE] now" → quote "call [PHONE] now" is valid | 🟡 Medium |
| EC3.5.2 | Quote contains Unicode normalisation differences (e.g., curly vs straight quotes) | Normalise both to NFC before comparison | 🟡 Medium |
| EC3.5.3 | Quote matches a review from a different cluster | Valid — quote exists in source data regardless of cluster assignment | 🟢 Low |
| EC3.5.4 | Quote is the entire review body (100% match) | Valid; accepted | 🟢 Low |
| EC3.5.5 | Quote is a single word | Valid if it's a real substring; but likely not useful — warn if < 10 chars | 🟢 Low |
| EC3.5.6 | All LLM-returned quotes fail validation for all clusters | Run completes but report section has "No validated quotes available" notice | 🟡 Medium |
