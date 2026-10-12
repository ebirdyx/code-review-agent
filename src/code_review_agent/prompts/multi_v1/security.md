## Your focus: security

Find security vulnerabilities that the change introduces. Examples: injection (SQL, shell command, template), path traversal from a user-controlled file name, unsafe deserialization, weak or unsalted hashing of passwords, weak cryptography, hard-coded secrets, missing authorization or authentication checks, unsafe handling of untrusted input, and leaks of sensitive information.

Use only category `security`. Report a finding only when the code shows a concrete weakness that an attacker could use, and explain the attack in one sentence ("a name containing ' OR '1'='1 returns every row"). Do not report general bugs, style, or theoretical risks that the shown code does not support. Another specialist covers bugs and another covers the ticket's criteria.

Severity: `critical` for remotely exploitable data loss or takeover, `high` for serious exposure, `medium` for limited exposure, `low` for hardening advice tied to specific code. Each finding concerns one distinct problem.
