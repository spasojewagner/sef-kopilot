# M3 — `docs/infra-first-deploy`

## Three questions a senior engineer would ask

**1. "What did the first deploy find that the runbook did not say?"**

Four things. The image did not build from a clone, since its build fetched rule sets with git,
which its stage lacked: a fix of its own, with CI changed to build as the platform does. Neither
Vercel nor Render could see the repository, because their GitHub apps had access to some
repositories only, and GitHub asks for a code by e-mail before it changes that. Neon's Connect
dialog offered the pooled host, which the API's driver must not use. And the corpus's step had
the database's URL typed into the command line. Each is now in the step where it was met.

**2. "Why read the database's URL with `Read-Host -AsSecureString`?"**

Because a secret typed into a command stays where the command goes: in the shell's history
file, on the screen, and in the screenshot someone sends to ask for help. Read as a secure
string, it is shown as asterisks and never written to the history; it lives in the process's
environment for the one command that needs it, and is removed after.

**3. "How do you know that the deploy works, end to end?"**

From outside, at three levels. `/ready` answers `ready` with the database and the validator
`ok`: the API runs, has migrated Neon, and has its rule sets. The web application's footer
reads the API's version from the browser, which proves the address it was built with and the
API's CORS for its origin. And an explanation that cites passages proves the corpus was loaded.
The path between them, upload to approval, is what the end-to-end test walks on every change.

## The one concept to explain unaided

**A runbook is tested by its first use.** Each surprise of the first deploy goes back into the
step where it happened, so that the second deploy meets none of them.

## Supporting facts worth remembering

- Live on 2026-11-07: <https://sef-kopilot.vercel.app> and
  <https://sef-kopilot-api.onrender.com>.
- Neon's pooled host ends in `-pooler`; the direct one does not.
- Vercel's default Node.js version for a new project was newer than 22; `engines.node` in
  `package.json` decides.
- The team's default Deployment Protection covers previews and each deployment's own address;
  the production domain stays public.
