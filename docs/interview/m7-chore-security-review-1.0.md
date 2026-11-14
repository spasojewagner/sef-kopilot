# M7 — `chore/security-review-1.0`

## Three questions a senior engineer would ask

**1. "Your content security policy allows inline scripts. Isn't that the one thing a CSP is
for?"**

It is the thing a CSP is best known for, not the only thing it does. A strict policy needs a
nonce on every script, and Next.js can put one there only if every page is rendered per request.
That would give up the static and partially prerendered pages for a defence React already
largely gives: it escapes what it renders, and a lint rule forbids setting HTML from data. The
risk the policy was owed against is narrower. The refresh token sits in the page's storage
(ADR-0027), and an injected script could send it away. `connect-src` stops that: a script can
reach the site and the API, and nowhere else, and it can load no image or font from elsewhere
to smuggle the token in an address. The review records the trade-off as accepted, with the
condition that would reopen it.

**2. "Why a list of common passwords shipped in the repository, rather than Have I Been Pwned's
range API?"**

Because a self-hosted deployment makes no call it was not told to (SECURITY.md, principle 7).
The range API would be an outside request on every registration, and the deployment would depend
on a service it never chose. ASVS asks for at least the top 3,000 passwords that meet the policy.
The list is the 10,000 most common of 12 to 128 characters from SecLists, in lower case: 72 KB
gzipped, with its MIT licence beside it. It catches the passphrases people actually reuse, like
`qwerty123456` and `1qaz2wsx3edc`. It does not catch a password from a breach no list has seen,
and the rate limits on sign-in are what slow down guessing against those.

**3. "You ticked key rotation without implementing key ids. Isn't that moving the goalposts?"**

It is stating the goal the item was for. Rotation with key ids and a grace period exists so that
tokens signed with the old key keep working while it is retired. Here nothing signed lives longer
than 15 minutes. Refresh tokens, the web's and the MCP clients', are opaque digests in the
database, not signed. So a new `SEF_JWT_SECRET` costs each session one refused request, after
which the client renews and retries; the web's session code is tested for exactly that. A grace
period would add code to protect tokens that expire on their own within a quarter of an hour.

## The one concept to explain unaided

**A security control is owed against a specific threat, and the review's job is to say which.**
A checklist item ticked without that reasoning is theatre, and one left open without it is
noise. Each item here was fixed, verified, or accepted with the threat it answers and the reason
written down, so the next review starts from that reasoning, not from the boxes.
