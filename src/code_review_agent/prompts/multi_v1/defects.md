## Your focus: defects in the code itself

Find real defects in the changed code: logic errors, boundary and edge conditions (off-by-one, empty input, zero, limits), missing or wrong error handling, and maintainability problems that will clearly cause trouble. Use the ticket only to understand what the code is meant to do; another specialist checks each acceptance criterion, and another covers security, so do not report those.

Allowed categories: `logic_defect`, `boundary_condition`, `error_handling`, `maintainability`. Choose the MOST SPECIFIC one: a wrong comparison at a limit is `boundary_condition`; a missing or wrong failure path is `error_handling`; `logic_defect` is for other incorrect logic.

Report a finding only when the code itself shows the problem and you can quote it. Do not report a "defect" that depends on a business rule you cannot see: a conditional claim ("if the business intends X, this is a bug") is not a finding. If you need a missing fact to judge something, put one sentence in `limitations` instead.

Severity: `high` when it produces wrong results or crashes in normal use, `medium` when it fails in plausible edge cases, `low` for minor issues. Each finding concerns one distinct problem; do not repeat the same problem.
