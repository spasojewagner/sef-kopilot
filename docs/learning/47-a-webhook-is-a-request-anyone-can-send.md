# A webhook is a request anyone can send

A payment provider tells you a customer paid by calling a URL of yours. That URL is public: the
provider has no session with you, so anyone who learns the address can call it with a body that
says "organization X paid for 100 000 credits". Three things make such a request trustworthy.

**1. A signature only the provider can make.** You and Stripe share a secret, the endpoint's
signing secret. Stripe sends

```
Stripe-Signature: t=1794250000,v1=5257a869…
v1 = hex(HMAC-SHA256(secret, "1794250000" + "." + raw_body))
```

and you compute the same HMAC over the body *exactly as it arrived* (not a re-serialised JSON,
whose key order or spacing may differ) and compare in constant time, so the comparison does not
leak how many characters matched. Several `v1` signatures may come while a secret is rolled;
any one may match. Ignore every other scheme (`v0`): accepting a weaker one would let an
attacker choose it.

**2. A time inside the signature.** The timestamp is part of what is signed, so it cannot be
changed; refuse a signature older than five minutes. A captured, genuine event cannot then be
sent again tomorrow.

**3. Counting once.** Even genuine events arrive more than once: the provider retries until it
gets a 2xx, and two different events (paid now, paid later) may report the same payment. Write
the payment under the provider's reference in a column with a unique constraint, and insert
with `ON CONFLICT DO NOTHING`: the second delivery inserts nothing and changes no balance, in
one statement, without a lock or a read first.

```
event ──► signature valid? ──no──► 400, nothing read
              │yes
              ▼
          a paid checkout? ──no──► 200, ignored
              │yes
              ▼
          INSERT purchase(reference) ON CONFLICT DO NOTHING ──conflict──► 200, counted before
              │inserted
              ▼
          balance += credits            (same transaction)
```

Answer 2xx quickly for anything you have handled or chosen to ignore; answer 4xx only when the
request is not the provider's, so that a genuine event is never retried forever.
