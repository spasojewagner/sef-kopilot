# A secret at rest: sealing a tenant's key so that a copy of the database opens nothing

The API must keep each organization's SEF API key: it sends invoices in the organization's
name, and asks SEF about them later, in the background. A key stored as it came would be in
every backup, every replica and every dump. So it is *sealed*: encrypted and authenticated
under a second key that lives somewhere else.

```
   PUT /organization/sef-key  {"api_key": "…"}
             │
             ▼
   message = {"organization": "<id>", "key": "…"}
             │   Fernet: AES-128-CBC, random IV, HMAC-SHA256, timestamp
             ▼   under SEF_FERNET_KEY  ←── the environment (Render), never the database
   token  = "gAAAAAB…"  ──►  sef_keys.token   (a CHECK refuses anything else)
```

**Two halves, two places.** The database holds the token; the environment holds the key that
opens it. A stolen dump is useless without the environment, and the environment alone holds
nothing to open. The running API holds both, so this protects copies of the data, not a
compromised server: that is what it is for.

**Authenticated, not only encrypted.** Fernet's HMAC means a token that was changed by one bit
does not open at all, rather than opening to something else. Never use encryption without
authentication for data at rest.

**Bound to its row.** Fernet authenticates nothing beside its message (no *associated data*).
A token copied from one organization's row to another's would open there, and that
organization would send with the first one's key. Putting the organization's id *inside* the
message and checking it on opening binds the token to its row. AES-GCM would do it with
associated data; with Fernet, the message carries it.

**Rotation without a gap.** `MultiFernet([new, old])` seals with the first key and opens with
any. Deploy both, seal every token again under the new key (`make rotate-sef-keys`, in one
transaction), then drop the old one. At no moment is a stored key unreadable.

**What is never done:** the key in a log, an answer, an audit event, or a 422 that repeats the
body it refused; the secret in SQL (`pgcrypto`), where the database's own logs would keep it;
a cipher or a mode chosen by hand.
