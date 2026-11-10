# Measuring a model offline: cassettes

A language model cannot be measured in CI the way a function is tested. It is slow, it costs a
request (and on a free tier, a share of a daily limit), it needs a key that CI should not hold,
and it may answer differently each time. Yet the measure must run on every pull request.

The answer is borrowed from HTTP testing (VCR, "cassettes"): **record each answer once, replay
it ever after.**

```
record:  request ──► real model ──► answer ──► cassette[sha256(request)] = answer
replay:  request ──► cassette[sha256(request)] ──► answer        (no network, no key)
```

Three choices make it trustworthy:

1. **Name a request by everything sent.** The key is the SHA-256 of the messages, the schema
   and the limits, in canonical JSON. Change one word of the prompt, one passage, one value of
   the invoice, and the key changes: there is no recorded answer, and the measure drops. Old
   answers can never stand in for a new question.
2. **Replay only.** A request the cassette does not hold is an error, as a model that does not
   answer would be. Nothing quietly falls back to the network.
3. **Record only what is missing, and keep only what was used.** A recording continues where a
   daily limit stopped it; a finished one drops the answers no question asks for any more, so
   the cassette is exactly the run.

What a cassette is not: a promise that the model will always answer so. It is one sample of a
model with variance, recorded on a day. Recording again may move the measures, and the
report's diff shows by how much, which is itself worth knowing before changing a model.

What it buys: the code around the model — retrieval, the prompt, the checks, the retries, the
citations held to the passages — is measured on real answers, on every change, for nothing.
