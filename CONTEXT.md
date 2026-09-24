# Colophon

Colophon corrects an ebook's metadata from the records that book sources keep, before the book reaches the library. This glossary covers the language of the completed build tickets (CBO-34 to CBO-42, CBO-58, CBO-59, CBO-73, CBO-74) and the drafted terms from CBO-65, CBO-68 and CBO-90.

## Language

### Works and Editions

**Work**:
A text as its author wrote it, independent of any printing, format or publisher. An omnibus is a Work of its own, not an Edition of the Works it collects. Two Works can share a title and an author; a differing Series Placement is what tells them apart.
_Avoid_: book (it names the file in Colophon's code and the Work in Hardcover's schema), title

**Edition**:
One published form of a Work, as a source lists it, with its own date, publisher, ISBN and cover. Every format is an Edition: ebook, paperback, hardback and audiobook alike. Every Edition of a Work shares the Work's Series Placement.
_Avoid_: printing, volume, release

**Standard Edition**:
The Edition chosen to represent a Work when a source returns several: the earliest listed, which is not necessarily the first published.
_Avoid_: first edition, canonical edition, survivor

**Reading Format**:
The kind of thing an Edition is (physical, audio or ebook), as the source states it.
_Avoid_: edition format, format, medium

**Audio Edition**:
An Edition that the source states has an audio Reading Format. It is still an Edition of its Work.
_Avoid_: audiobook edition, non-ebook edition

### Series

**Series Placement**:
The series a source names for a Work together with the Work's position in it, taken as one pair. Two placements conflict when either the series or the position differs. A Work in several series has one Series Placement in Colophon: the one its source features.
_Avoid_: series number, series index, position (on its own)

**Claimed Placement**:
The Series Placement a file's own title asserts, as in `Cragside (The DCI Ryan Mysteries Book 6)`. It is the file's evidence of which Work it is, and is distinct from the series metadata the file records and Colophon writes.
_Avoid_: file series, series_index, bracket number

### The Relay

**Relay**:
Colophon's place in the stack: one stage between an Ingest Folder and an Output Folder, independent of whichever library app reads the output.
_Avoid_: plugin, importer, library

**Ingest Folder**:
The folder Colophon watches. A file dropped here is waiting to be corrected.
_Avoid_: input, inbox, drop folder

**Output Folder**:
The folder Colophon delivers to and the library app imports from. A file arrives there whole or not at all, and never replaces another.
_Avoid_: digest folder, library folder

**Backups Folder**:
Where an original is kept before Colophon changes it, and where an identical copy of an already-delivered file goes. Kept for a limited time.
_Avoid_: trash, archive

**Dry Run**:
A mode in which Colophon reports every change it would make and makes none.
_Avoid_: preview, test mode

### Sources and Candidates

**Source**:
An outside catalogue Colophon asks about a book, such as Hardcover or Google Books. Every value Colophon writes comes from a Source's record.
_Avoid_: provider (that is the LLM's endpoint), API, database

**Source Priority**:
The user's ordering of Sources. It decides which Source is asked first and so which wins an Early Exit; it carries no weight in any Score.
_Avoid_: source weight, preference

**Candidate**:
One record a Source returned for a query: a possible answer to which Edition a file is.
_Avoid_: result, hit, match (until it is accepted)

**Scored Candidate**:
A Candidate together with its Score against the file and the reasons for it. Every Candidate in a Pool is scored; only one becomes the Match.
_Avoid_: match, result

**Match**:
The Candidate Colophon accepted for a file, whether by the rules or by the LLM Chooser. Every value written comes from it.
_Avoid_: candidate, pick, result

**Cleaned Title**:
The file's title with its Claimed Placement and any generic subtitle removed: what a Source would call the Work. Used to search, never written.
_Avoid_: search title, stripped title

**Written Value**:
A value exactly as the Source spells it, apostrophes and accents kept. Every normalisation Colophon does is for comparison only and never reaches a Written Value.
_Avoid_: normalised value, cleaned value

### Grading

**Walk**:
One file's pass through the Sources in Source Priority order, gathering their Candidates into one Pool.
_Avoid_: search, lookup, fall-through

**Pool**:
Every Candidate a Walk gathered, across all Sources, with Duplicates collapsed, graded together as one.
_Avoid_: result set, candidate list

**Duplicate**:
Two Candidates from different Sources for the same Edition, collapsed into one before grading. Collapsing is strict: a wrong merge writes the wrong record confidently, a missed merge only costs a lower Band.
_Avoid_: repeat, copy

**Score**:
How well one Candidate agrees with the file, from 0 to 1. Title counts most, then author, then series and year. A Candidate in a different language is refused rather than scored lower.
_Avoid_: confidence (that is the LLM's own number, or the Match's), similarity

**Band**:
The confidence grade of a whole Pool: strong, medium, low or none. Strong is written; medium goes to the LLM Chooser if one is configured, otherwise Unverified; low and none are Unverified. Neither strong nor medium is reached unless the leader's author agrees with the file.
_Avoid_: tier, level, confidence

**Gap**:
How far the leading Candidate's Score is ahead of the runner-up's. A high Score with a small Gap is not a confident match.
_Avoid_: margin, lead

**Singleton**:
A Pool of one Candidate. With no runner-up to corroborate it, it must clear a higher bar to be strong.
_Avoid_: single result, lone match

**Early Exit**:
A Walk stopping before every Source was asked, because the Pool already grades strong.
_Avoid_: short-circuit, first match wins

**Half-asked**:
A Walk that ran to the end with a configured Source erroring. Its Pool is missing a Source the user asked for, so a weak grade cannot be trusted as a refusal: the book waits instead of being marked Unverified.
_Avoid_: partial walk, degraded

**LLM Chooser**:
The model Colophon asks to pick one Candidate from a numbered list, or none. It judges; it never supplies a value.
_Avoid_: AI matcher, AI metadata

### Outcomes

**Correction**:
The values written into a file from its Match, each according to its Field Rule.
_Avoid_: fix, update, enrichment

**Field Rule**:
The user's choice, per field, of skip, fill if empty, or overwrite.
_Avoid_: field policy, merge rule

**Unverified**:
The final state of a book with no confident Match: it keeps its own metadata, is tagged `colophon:unverified`, and says so at the end of its description. It is not retried.
_Avoid_: unmatched, failed, skipped

**Waiting**:
A book left untouched in the Ingest Folder and asked again later, because the LLM Chooser or a configured Source could not be asked. It lasts no longer than the configured retry window, usually a day; after that the book is delivered with its own metadata, tagged `colophon:source-unavailable`.
_Avoid_: queued, pending, held

**Held**:
Books kept back because a Source or the LLM refused Colophon itself (a rejected key, a configuration problem), not because it was briefly unreachable. Nothing is tagged and nothing is retried; it ends only when the user fixes the cause and restarts.
_Avoid_: waiting, blocked, paused

### Colophon's Record

**Record**:
Colophon's own memory of the books it has delivered: name spellings, series names, genre mappings and previous Matches. Used for consistency only: never to work out a series position, and never to bias a Score.
_Avoid_: database, cache, history

**Standard Spelling**:
The spelling of an author or series name the Record has settled on, reused for every later book. A new name takes the spelling of the Source that matched it.
_Avoid_: canonical name, preferred name

**Author Override**:
A user's own spelling for an author, set in the config. It always beats the Standard Spelling, and removing it restores the spelling the library had before.
_Avoid_: alias, correction

**Allowed Genres**:
The user's list of the tags a genre may become. Nothing outside it is written.
_Avoid_: tag whitelist, genre list

**Genre Mapping**:
The LLM's judgement of which Allowed Genre, if any, a Source's genre means. A genre that fits none is dropped.
_Avoid_: genre translation, tagging

### Fixtures

**Live Recording**:
A stored Source reply that can be re-recorded at any time. Tests may rely on its shape, never its values.
_Avoid_: snapshot, cassette

**Hand-made Fixture**:
A stored reply frozen to keep one case a ticket depends on. It is never re-recorded.
_Avoid_: mock, synthetic fixture
