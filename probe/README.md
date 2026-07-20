# tls-reputation probe

A TLS server that answers with the reputation of the caller's own ClientHello.

A client connects over TLS; the server peeks the raw ClientHello off the socket
with `MSG_PEEK` — reading it without consuming it, so the same bytes still feed
the real handshake — then terminates TLS, base64-encodes the peeked ClientHello,
asks the reputation API (`POST /api/v1/reputation`) what it is, and writes the
answer back over the connection.

Standard library only.

```
tlsrep-probe --port 8443 --cert cert.pem --key key.pem \
             --reputation-url http://backend:8000/api/v1/reputation
```

Behind nginx `stream { ssl_preread }`, `probe.tls-reputation.com` on :443 is
routed here by SNI while the main site stays on its own server block.
