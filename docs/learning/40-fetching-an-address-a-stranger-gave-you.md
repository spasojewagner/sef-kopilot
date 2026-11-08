# 40. Fetching an address a stranger gave you

A client of the authorization server may introduce itself by a URL: its `client_id` is
`https://assistant.example/oauth/client.json`, and the server fetches that document to learn the
client's name and where it may send people back (ADR-0045). The server now makes a request to an
address anyone could have typed. That is **server-side request forgery** (SSRF) waiting to happen:
the server sits inside a network the stranger cannot reach, and will happily ask it for them.

```text
stranger ──client_id=https://evil.example/x──▶ API ──GET──▶ ?
                                                  │
           what evil.example could resolve to:    ├─ 169.254.169.254   the cloud's metadata service
                                                  ├─ 10.0.0.7          a database's admin page
                                                  └─ 127.0.0.1:6379    the API's own Redis
```

**The defences, and why each is there.**

- **Check every address the name resolves to.** Only addresses of the public internet will do:
  none on the loopback interface, a private or link-local network, or a reserved block. One bad
  address among good ones is enough to refuse, since the connection could use any of them.
- **Connect to the address you checked.** Resolving again to connect lets the name answer
  differently the second time (*DNS rebinding*: a public address for the check, `10.0.0.7` for
  the request). So the request goes to the checked IP, with the host's name sent for TLS (SNI)
  and checked against its certificate, so the right site is still proven.
- **Follow no redirect.** A public page can answer `302 Location: http://10.0.0.7/`.
- **Bound everything.** Five seconds, 5 KiB, asked for without compression: a small gzip can
  inflate to gigabytes, and a slow host can hold a worker forever.
- **Count the requests that cause a fetch**, so that no one can make the server fetch at will.
- **Read the answer as hostile data**: it must be JSON, name itself by the same URL, and pass the
  same checks a registration does.

**And the question before all of these: should the server fetch at all?** A self-hosted SEF
Kopilot promises to call out to nothing but its language model's provider, so fetching is off
unless the operator turns it on (`SEF_CLIENT_METADATA_DOCUMENTS`). The safest request is the
one a deployment never makes.
