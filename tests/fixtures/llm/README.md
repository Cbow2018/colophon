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
| `prose-not-json.json` | The same question asked with no JSON instruction | prose, not JSON | recorded |

`belsay-picked.json` and `belsay-absent.json` are the two cases CBO-40's
acceptance criteria name. Between them they also settle a design point: the
absent case answers `null` **with a high confidence** — the model is certain that
none of the candidates is the book — so a null pick is never applied, whatever
its confidence says. A reply of `{"pick": null, "confidence": 1.0}` is recorded
in the probe's raw replies for that test and should be promoted here when the
ticket is built.

`prose-not-json.json` is what a client with no JSON mode produces. Answered with
a neutral system prompt, the model writes prose rather than the contract object,
which is why the shipped request always sends
`response_format: {"type": "json_object"}`. A reply like this one counts as
`null`.

The candidates in these recordings are the real Hardcover records from
`tests/fixtures/hardcover/by-title-*.json`, named the way the shipped prompt
numbers them. The prompt carries each candidate's title, authors, series,
series position, year, publisher, ISBN and language, and deliberately does **not**
carry the source the record came from.
