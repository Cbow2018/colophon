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
