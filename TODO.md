# Performance TODOs

- [ ] Increase read buffer 32 KB → 128 KB in `client.py` channel forward loop
- [ ] Increase receiver buffer 64 KB → 256 KB in `client.py` receiver loop
- [ ] Increase server channel reader 32 KB → 128 KB in `server.py`
- [ ] Add TCP_NODELAY on tunnel socket in `client.py` after connect
- [ ] Add TCP_NODELAY on destination connections in `server.py` after open_connection
