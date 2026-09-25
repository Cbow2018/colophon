# Hand-made fixtures: the cases a ticket rests on

> A **live** recording is re-recordable at will; nothing asserts its values, only
> its shape. A **hand-made** fixture exists to freeze one case a ticket rests on;
> it is never re-recorded, and it says which ticket and which case in this
> directory README.

The rule is stated in full at `fixtures/hardcover/hand-made/README.md`, where the
directory form was decided (CBO-74). This directory follows it, and there is no
recorded reply either file could have been copied from:

| File | Status | Reads it | The case, and why no recording can carry it |
| --- | --- | --- | --- |
| `error-key-rejected.json` | 401 | `FailureKindTests.test_a_rejected_key_is_held_and_named_as_the_key` | DeepSeek's wrong-key reply. **No 401 body was ever committed**: the measured one echoes four characters of the key back (CBO-40 §4), which is why CBO-40 kept it out of the corpus. The message here is the measured one with those four characters left as `****0000`. |
| `error-out-of-balance.json` | 402 | `FailureKindTests.test_an_account_out_of_balance_is_temporary` | `Insufficient Balance`: the one LLM status that is temporary, because topping up fixes it and a restart does not (CBO-43). Asking for one means spending the account's balance. |

Both bodies are the OpenAI-compatible error envelope DeepSeek answers with, and
the two messages are the ones its error-code table and the CBO-40 probe record.
The `type`, `param` and `code` values are Colophon's own reading of the names in
that table - DeepSeek documents the codes, not the field values - so nothing here
is quoted as measured.
