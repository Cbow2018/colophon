# Recorded LLM replies

Real replies from DeepSeek's OpenAI-compatible API, recorded on 2026-09-19 with
the DeepSeek key, so the suite never needs a key and never touches the network.
They are the **only** provider that was probed: Ollama, OpenAI, Anthropic,
Gemini, Groq and OpenRouter were not called, and nothing here should be read as
evidence about them. See `docs/research/cbo-40-llm-fallback-chooser.md`.

Each file is a reply body exactly as it came back, with the per-call fields
removed — `id`, `created`, `system_fingerprint` and `usage` differ on every
request and would make a diff unreadable. Nothing else was changed, and no file
carries a request header or any key material.

| File | The request | The reply | How |
| --- | --- | --- | --- |
| `belsay-picked.json` | Belsay present among four candidates | `{"pick": 1, "confidence": 1.0, …}` | recorded |
| `belsay-absent.json` | Belsay removed, Berwick #24 as a lookalike | `{"pick": null, "confidence": 0.95, …}` | recorded |
| `null-pick-confident.json` | Belsay absent, a later asking of the same question | `{"pick": null, "confidence": 1.0, …}` | recorded |
| `prose-not-json.json` | The same question with a **neutral** system prompt | prose, not JSON | recorded |

`belsay-picked.json` and `belsay-absent.json` are the two cases CBO-40's
acceptance criteria name.

`null-pick-confident.json` is the one that keeps the gate honest, and that is why
it is a separate recording from `belsay-absent.json` rather than a duplicate of it.
The model answers `null` **with total confidence** — `1.0` — because it is certain
that none of the candidates is the book. So "the confidence clears the threshold"
must never be read as "there is something to write": a null pick is never applied,
whatever its confidence says, and this fixture is what a test asserts that with. A
confidence of `1.0` and a `pick` of `null` together are the whole point, so do not
"fix" one of them.

`belsay-absent.json` reaches the same conclusion at a lower confidence (`0.95`) and
is the recording that carries fewer candidate fields. One shows the conclusion, the
other pins the confidence the gate has to ignore.

`prose-not-json.json` is a **neutral** system prompt's answer, so it is *not* what
the shipped client would produce — the shipped prompt carries the JSON contract and
answered with the contract object even when `response_format` was left out. It is
here because the parsing rule needs a real prose reply to reject. A reply like this
one counts as `null`.

The candidates in the three contract recordings are the real Hardcover records from
`tests/fixtures/hardcover/by-title-*.json`, named the way the shipped prompt
numbers them. The prompt carries each candidate's title, authors, series, series
position, year, publisher, ISBN and language, and deliberately does **not** carry
the source the record came from.

## CBO-42: genre mapping

CBO-42 asks the same endpoint a different question — which of the user's allowed
genres this one source genre is, or none of them — and these are its recordings.
Unlike the four above, **these are read by tests.**

Two prompt shapes were recorded, and which is which matters:

| File | The request | The reply | How |
| --- | --- | --- | --- |
| `genre-mapping-murder.json` | `Murder`, allowed list holding `Crime` too | `{"genre": "Crime", …}` | recorded |
| `genre-mapping-case.json` | `crime`, lower-cased | `{"genre": "Crime", …}` | recorded |
| `genre-mapping-packed.json` | `Fantasy:Humour`, a packed BISAC path | `{"genre": "Fantasy", …}` | recorded |
| `genre-mapping-fiction.json` | `Fiction` | `{"genre": null, …}` | recorded |
| `genre-mapping-synagogues.json` | `Synagogues` | `{"genre": null, …}` | recorded |
| `genre-mapping-unmappable.json` | `Finlay-Ryan, Maxwell (Fictitious character)` | `{"genre": null, …}` | recorded |
| `genre-mapping-empty-allowed.json` | `Murder`, allowed list empty | `{"genre": null, …}` | recorded |
| `genre-mapping-batch.json` | four genres in one object (**rejected shape**) | partial JSON, `finish_reason: length` | recorded |
| `genre-mapping-truncated.json` | four genres, no shared vocabulary (**rejected shape**) | `finish_reason: length`, empty body | recorded |

The first seven are the shape the shipped `Llm.map_genre` sends: **one genre per
call**. The last two are the shape it does **not** send, kept as the evidence
against it — the batch object straddled the 256-token cap in two runs out of five
at only four genres, and a truncated reply is a `null` under CBO-40's rule, so a
book would silently get no genres. `genre-mapping-batch.json` is one of those
truncated replies: it carries **partial JSON with `finish_reason: length`**, which
is exactly why the parser must not read it. Do not "fix" it into a complete
answer.

`usage` **is** kept in these nine, unlike the four above. The completion and
reasoning token counts are the whole reason the batch shape was rejected and
CBO-42's note quotes them; `id`, `created` and `system_fingerprint` are still
removed, as they differ on every request.

The allowed list in every recording but `genre-mapping-empty-allowed.json` is
`["Crime", "Mystery", "Thriller", "Historical Fiction", "Science Fiction",
"Fantasy"]`, and `genre-mapping-murder.json` is the one that shows the model's
judgement rather than an echo: `Murder` is on that list too, and it answers
`Crime` as the nearer allowed word.

`genre-mapping-fiction.json` is the one to read before changing the drop rule.
`Fiction` is *Berwick*'s only source genre, and the model answers `null` — a
correct answer that leaves the book with no genres at all. A null is a success,
not a failure, and the two must not be made to look alike in the log.
