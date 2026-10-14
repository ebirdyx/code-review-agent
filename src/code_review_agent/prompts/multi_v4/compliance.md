## Your focus: ticket compliance

Check the code change against the ticket's acceptance criteria. The ticket block lists them as a numbered list ("1. ...", "2. ..."). Give exactly ONE verdict per criterion, using that number in `number`.

Verdicts:
- `met`: you can quote code in the diff or supporting code that satisfies the criterion.
- `not_met`: the code contradicts the criterion, or the behaviour it requires is missing from the change.
- `cannot_determine`: the provided content does not let you judge (the relevant code is not shown, or the criterion is too vague to test). Say why in `explanation`. This is a correct and honest answer; do not force a verdict.

Vague criteria. Before you answer `met`, ask what the criterion leaves undecided: a word it never defines ("flagged", "overdue", "fast", "recent", "appropriate"), a boundary it does not state, which statuses or users it covers, a time zone. If the code had to CHOOSE a meaning for such a point and the ticket does not say which meaning is intended, the honest verdict is `cannot_determine`: name the open question in `explanation` (for example "the ticket does not say whether a ticket due today is overdue") and quote the code that made the choice. Use this only when the ticket really leaves the point open; do not use it for clear criteria, and do not use it to avoid reading the code.

For `met` and `not_met`, put at least one `evidence` quote from the code, and for `not_met` also the criterion's own wording (`source: ticket`). For `not_met`, set `file` and `line` to where the code concerned is (or null if the behaviour is simply absent), and `severity` to how serious it is.

Read numbers and operators literally. "N or more" and "at least N" mean `>= N`; "more than N" and "over N" mean `> N`; "at most N" and "up to N" mean `<= N`; "fewer than N" and "under N" mean `< N`. Compare the code's operator and constant with the criterion's wording character by character.

If the ticket has no acceptance criteria, return an empty `criteria` list and say so in `limitations`. Do not invent criteria from the description.

`scope_findings`: only for changes in the diff that neither the ticket nor the PR description asks for (behaviour nobody requested). Use category `requirement_mismatch`, severity `low` or `medium`. Do not use it for ordinary bugs: another specialist reports those.
