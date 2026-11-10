# M7 — `fix/evals-empty-database-url`

## Three questions a senior engineer would ask

**1. "Why is an empty value not simply a value?"**

Because `.env.example` writes the variable empty, and every developer starts from a copy of it.
The API's tests already read empty as not set and skip; the evaluations read it as a URL and
failed deep in SQLAlchemy. Two readers of one setting must agree on what empty means, or the
same `.env` works for one command and breaks the other.

**2. "Why not print the value that failed to parse? It would help debugging."**

A database URL holds a password. The message names the variable and shows the form to write it
in, with placeholders; the value is never repeated, in an error or a log, as the runner already
did for a server it could not reach.

**3. "How was it found, and how do you keep it found?"**

On the maintainer's machine, shipping 0.6.0: the terminal of the first recording had named the
server, the `.env` never had. The tests now write an empty value both ways, in the environment
and in `.env`, and a value that is no URL, and they failed before the fix.

## The one concept to explain unaided

**Empty is a value configuration readers must agree on**: decide once whether an empty setting
means "unset", apply it everywhere the setting is read, and make the error name the setting and
the fix, never the secret.
