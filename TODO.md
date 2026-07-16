# Performance TODOs

- [ ] Increase read buffer 32 KB → 128 KB in `client.py` channel forward loop
- [ ] Increase receiver buffer 64 KB → 256 KB in `client.py` receiver loop
- [ ] Increase server channel reader 32 KB → 128 KB in `server.py`

# Completed

- [x] Add TCP_NODELAY on tunnel socket in `client.py` after connect
- [x] Add TCP_NODELAY on destination connections in `server.py` after open_connection
- [x] Add keepalive mechanism (client + server)
- [x] Add backpressure to channel data forwarding (1 MB buffer limit)
- [x] Add max channel limit (256 default, configurable)
- [x] Persistent listen server across tunnel reconnects
- [x] Fix reader leak on channel close (close reader + cancel task)
