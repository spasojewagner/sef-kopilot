# 65. A waking API is told in the footer only, not above every page

- Status: accepted
- Date: 2026-11-15
- Deciders: Marko Spasojević
- Technical story: branch `fix/web-api-waking-in-footer`; amends ADR-0036

## Context and problem statement

ADR-0036 has the pages wait for an API that Render's free plan has put to sleep, and say so twice
once a wait has gone three seconds: in the footer, and in a notice above every page. The notice
sits between the header and the page, so the first visitor after a pause sees a box appear under
the header and push the home page down by its height, on a page that sends nothing and waits for
nothing but the footer's check. Should the pages still say it above everything?

## Decision drivers

- The home page, which most visitors see first, opens without anything moving it.
- A visitor who sends something while the API wakes still learns that it waits, rather than that
  it failed.
- A screen reader still hears that the API is waking up.

## Considered options

1. **The footer alone says it.** Chosen.
2. A notice that floats in a corner, over the page, while a wait lasts.
3. The notice above the page, as ADR-0036 has it.

## Decision outcome

**The notice above every page goes; the footer's status stays**, as ADR-0036 has it otherwise:
once a wait has gone three seconds, the footer says that the API is waking up, in a polite status
region that a screen reader announces, until it answers. Everything else in ADR-0036 holds: a
request waits for the API and is sent once, and a button that sends says that it is sending while
it waits.

### Consequences

Good:

- No page moves under the visitor while the API wakes.
- One less status region on every page.

Bad / accepted:

- A sighted visitor who sends something while the API wakes sees the button say that it is
  sending, and the reason only in the footer, which may be out of view: about a minute of
  waiting, once after a pause, in a free demo.

## Pros and cons of the options

### A notice that floats in a corner

- Good: in view wherever the visitor is, without moving the page.
- Bad: it still appears over the home page, which waits for nothing; and it covers what is
  under it, on a phone a good part of the screen.

### The notice above the page

- Good: nobody misses it.
- Bad: it pushes the page down under the visitor, on every page, including those that send
  nothing.
