#!/usr/bin/env python3
"""
SMTP Tunnel Client

Version: 1.5.0

Protocol:
1. SMTP handshake (EHLO, STARTTLS, AUTH) - looks like real SMTP
2. After AUTH, send "BINARY" to switch to streaming mode
3. Full-duplex binary protocol - data flows as fast as TCP allows

Features:
- Multi-user support (username + secret authentication)
- Port forwarding mode: forwards local connections to a fixed remote target
- SOCKS5 mode: acts as a SOCKS5 proxy for dynamic target selection
"""

import asyncio
import ssl
import logging
import argparse
import struct
import time
import os
import socket
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field

from common import TunnelCrypto, load_config, ClientConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('smtp-tunnel-client')


# ============================================================================
# Binary Protocol
# ============================================================================

FRAME_DATA = 0x01
FRAME_CONNECT = 0x02
FRAME_CONNECT_OK = 0x03
FRAME_CONNECT_FAIL = 0x04
FRAME_CLOSE = 0x05
FRAME_KEEPALIVE = 0x06
FRAME_KEEPALIVE_ACK = 0x07
FRAME_HEADER_SIZE = 5

def make_frame(frame_type: int, channel_id: int, payload: bytes = b'') -> bytes:
    return struct.pack('>BHH', frame_type, channel_id, len(payload)) + payload

def make_connect_payload(host: str, port: int) -> bytes:
    host_bytes = host.encode('utf-8')
    return struct.pack('>B', len(host_bytes)) + host_bytes + struct.pack('>H', port)


@dataclass
class Channel:
    channel_id: int
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    host: str
    port: int
    connected: bool = False


# ============================================================================
# Tunnel Client
# ============================================================================

class TunnelClient:
    def __init__(self, config: ClientConfig, ca_cert: str = None):
        self.config = config
        self.ca_cert = ca_cert

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False

        self.channels: Dict[int, Channel] = {}
        self.next_channel_id = 1
        self.channel_lock = asyncio.Lock()

        self.connect_events: Dict[int, asyncio.Event] = {}
        self.connect_results: Dict[int, bool] = {}

        self.write_lock = asyncio.Lock()

        # Keepalive
        self.last_recv_time: float = time.time()
        self.keepalive_task: Optional[asyncio.Task] = None

        # Channel migration: track active channel info for reconnect
        # {channel_id: (host, port, local_reader, local_writer)}
        self.active_channel_info: Dict[int, Tuple[str, int, asyncio.StreamReader, asyncio.StreamWriter]] = {}
        self.migration_lock = asyncio.Lock()

    async def connect(self) -> bool:
        """Connect and do SMTP handshake, then switch to binary mode."""
        try:
            logger.info(f"Connecting to {self.config.server_host}:{self.config.server_port}")

            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.config.server_host, self.config.server_port),
                timeout=30.0
            )

            sock = self.writer.transport.get_extra_info('socket')
            if sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # Detect dead tunnel fast (default Linux is 2+ hours)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 120)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)

            # SMTP Handshake
            if not await self._smtp_handshake():
                return False

            self.connected = True
            self.last_recv_time = time.time()
            self.keepalive_task = asyncio.create_task(self._keepalive_loop())
            logger.info("Connected - binary mode active")
            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def _smtp_handshake(self) -> bool:
        """Do SMTP handshake then switch to binary."""
        try:
            # Wait for greeting
            line = await self._read_line()
            if not line or not line.startswith('220'):
                return False

            # EHLO
            await self._send_line("EHLO tunnel-client.local")
            if not await self._expect_250():
                return False

            # STARTTLS
            await self._send_line("STARTTLS")
            line = await self._read_line()
            if not line or not line.startswith('220'):
                return False

            # Upgrade TLS
            await self._upgrade_tls()

            # EHLO again
            await self._send_line("EHLO tunnel-client.local")
            if not await self._expect_250():
                return False

            # AUTH
            timestamp = int(time.time())
            crypto = TunnelCrypto(self.config.secret, is_server=False)
            token = crypto.generate_auth_token(timestamp, self.config.username)

            await self._send_line(f"AUTH PLAIN {token}")
            line = await self._read_line()
            if not line or not line.startswith('235'):
                logger.error(f"Auth failed: {line}")
                return False

            # Switch to binary mode
            await self._send_line("BINARY")
            line = await self._read_line()
            if not line or not line.startswith('299'):
                logger.error(f"Binary mode failed: {line}")
                return False

            return True

        except Exception as e:
            logger.error(f"Handshake error: {e}")
            return False

    async def _upgrade_tls(self):
        """Upgrade to TLS."""
        ssl_context = ssl.create_default_context()
        if self.ca_cert and os.path.exists(self.ca_cert):
            ssl_context.load_verify_locations(self.ca_cert)
        else:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        transport = self.writer.transport
        protocol = self.writer._protocol
        loop = asyncio.get_event_loop()

        new_transport = await loop.start_tls(
            transport, protocol, ssl_context,
            server_hostname=self.config.server_host
        )

        self.writer._transport = new_transport
        self.reader._transport = new_transport
        logger.debug("TLS established")

    async def _send_line(self, line: str):
        self.writer.write(f"{line}\r\n".encode())
        await self.writer.drain()

    async def _read_line(self) -> Optional[str]:
        try:
            data = await asyncio.wait_for(self.reader.readline(), timeout=60.0)
            if not data:
                return None
            return data.decode('utf-8', errors='replace').strip()
        except:
            return None

    async def _expect_250(self) -> bool:
        while True:
            line = await self._read_line()
            if not line:
                return False
            if line.startswith('250 '):
                return True
            if line.startswith('250-'):
                continue
            return False

    async def _receiver_loop(self):
        """Receive and dispatch frames from server."""
        buffer = bytearray()

        while self.connected:
            try:
                chunk = await asyncio.wait_for(self.reader.read(65536), timeout=60.0)
                if not chunk:
                    break
                self.last_recv_time = time.time()
                buffer.extend(chunk)

                # Process frames
                while len(buffer) >= FRAME_HEADER_SIZE:
                    frame_type, channel_id, payload_len = struct.unpack('>BHH', bytes(buffer[:5]))
                    total_len = FRAME_HEADER_SIZE + payload_len

                    if len(buffer) < total_len:
                        break

                    payload = bytes(buffer[FRAME_HEADER_SIZE:total_len])
                    del buffer[:total_len]

                    await self._handle_frame(frame_type, channel_id, payload)

            except asyncio.TimeoutError:
                # Check keepalive timeout
                elapsed = time.time() - self.last_recv_time
                if elapsed > self.config.keepalive_timeout:
                    logger.warning(f"Keepalive timeout ({elapsed:.0f}s), reconnecting")
                    break
                continue
            except Exception as e:
                logger.error(f"Receiver error: {e}")
                break

        self.connected = False
        # Close all channels immediately to prevent CLOSE-WAIT pileup
        for channel in list(self.channels.values()):
            await self._close_channel(channel)

    async def _handle_frame(self, frame_type: int, channel_id: int, payload: bytes):
        """Handle received frame."""
        if frame_type == FRAME_CONNECT_OK:
            if channel_id in self.connect_events:
                self.connect_results[channel_id] = True
                self.connect_events[channel_id].set()

        elif frame_type == FRAME_CONNECT_FAIL:
            if channel_id in self.connect_events:
                self.connect_results[channel_id] = False
                self.connect_events[channel_id].set()

        elif frame_type == FRAME_DATA:
            channel = self.channels.get(channel_id)
            if channel and channel.connected:
                try:
                    channel.writer.write(payload)
                    await channel.writer.drain()
                except:
                    await self._close_channel(channel)

        elif frame_type == FRAME_CLOSE:
            channel = self.channels.get(channel_id)
            if channel:
                await self._close_channel(channel)

        elif frame_type == FRAME_KEEPALIVE:
            await self.send_frame(FRAME_KEEPALIVE_ACK, 0)

    async def send_frame(self, frame_type: int, channel_id: int, payload: bytes = b''):
        """Send frame to server."""
        if not self.connected or not self.writer:
            return
        frame = make_frame(frame_type, channel_id, payload)
        async with self.write_lock:
            if not self.connected:
                return
            try:
                self.writer.write(frame)
            except Exception:
                self.connected = False
                return
        # drain outside the lock so one slow channel doesn't block all others
        try:
            await asyncio.wait_for(self.writer.drain(), timeout=10.0)
        except (asyncio.TimeoutError, Exception):
            self.connected = False

    async def open_channel(self, host: str, port: int) -> Tuple[int, bool]:
        """Open a tunnel channel."""
        if not self.connected:
            return 0, False

        # Check channel limit
        if len(self.channels) >= self.config.max_channels:
            logger.warning(f"Channel limit reached ({self.config.max_channels})")
            return 0, False

        async with self.channel_lock:
            channel_id = self.next_channel_id
            self.next_channel_id += 1

        event = asyncio.Event()
        self.connect_events[channel_id] = event
        self.connect_results[channel_id] = False

        # Send CONNECT
        try:
            payload = make_connect_payload(host, port)
            await self.send_frame(FRAME_CONNECT, channel_id, payload)
        except Exception:
            self.connect_events.pop(channel_id, None)
            self.connect_results.pop(channel_id, None)
            return channel_id, False

        # Wait for response
        try:
            await asyncio.wait_for(event.wait(), timeout=30.0)
            success = self.connect_results.get(channel_id, False)
        except asyncio.TimeoutError:
            success = False

        self.connect_events.pop(channel_id, None)
        self.connect_results.pop(channel_id, None)

        return channel_id, success

    async def send_data(self, channel_id: int, data: bytes):
        """Send data on channel."""
        await self.send_frame(FRAME_DATA, channel_id, data)

    async def close_channel_remote(self, channel_id: int):
        """Tell server to close channel."""
        await self.send_frame(FRAME_CLOSE, channel_id)

    async def _close_channel(self, channel: Channel):
        """Close local channel and cleanup."""
        if not channel.connected:
            return
        channel.connected = False

        # Close writer
        try:
            channel.writer.close()
            await channel.writer.wait_closed()
        except:
            pass

        # Close reader
        try:
            channel.reader.feed_eof()
        except:
            pass

        # Remove from active channel info
        self.active_channel_info.pop(channel.channel_id, None)
        self.channels.pop(channel.channel_id, None)

    async def disconnect(self):
        """Disconnect and cleanup."""
        self.connected = False

        # Cancel keepalive
        if self.keepalive_task:
            self.keepalive_task.cancel()
            try:
                await self.keepalive_task
            except asyncio.CancelledError:
                pass

        for channel in list(self.channels.values()):
            await self._close_channel(channel)
        if self.writer:
            try:
                self.writer.close()
                await asyncio.wait_for(self.writer.wait_closed(), timeout=2.0)
            except:
                pass
        self.reader = None
        self.writer = None
        self.channels.clear()
        self.connect_events.clear()
        self.connect_results.clear()

    async def _keepalive_loop(self):
        """Periodically send keepalive probes."""
        try:
            while True:
                await asyncio.sleep(self.config.keepalive_interval)
                if not self.connected:
                    break
                await self.send_frame(FRAME_KEEPALIVE, 0)
        except asyncio.CancelledError:
            pass

    async def migrate_channels(self):
        """Re-establish active channels after reconnect."""
        async with self.migration_lock:
            if not self.active_channel_info:
                return

            logger.info(f"Migrating {len(self.active_channel_info)} channels...")
            to_migrate = dict(self.active_channel_info)
            self.active_channel_info.clear()

            for old_id, (host, port, local_reader, local_writer) in to_migrate.items():
                try:
                    new_id, success = await self.open_channel(host, port)
                    if success:
                        # Create new channel with the local connection
                        channel = Channel(
                            channel_id=new_id,
                            reader=local_reader,
                            writer=local_writer,
                            host=host,
                            port=port,
                            connected=True,
                        )
                        self.channels[new_id] = channel
                        self.active_channel_info[new_id] = (host, port, local_reader, local_writer)
                        asyncio.create_task(self._migrated_forward_loop(channel))
                        logger.info(f"Migrated channel {old_id} -> {new_id} ({host}:{port})")
                    else:
                        # Failed to re-establish, close local connection
                        logger.warning(f"Failed to migrate channel {old_id} ({host}:{port})")
                        local_writer.close()
                except Exception as e:
                    logger.error(f"Migration error for channel {old_id}: {e}")
                    try:
                        local_writer.close()
                    except:
                        pass

    async def _migrated_forward_loop(self, channel: Channel):
        """Forward loop for migrated channels."""
        try:
            while channel.connected and self.connected:
                try:
                    data = await asyncio.wait_for(channel.reader.read(32768), timeout=0.1)
                    if data:
                        await self.send_data(channel.channel_id, data)
                    elif data == b'':
                        break
                except asyncio.TimeoutError:
                    continue
        except:
            pass
        finally:
            await self.close_channel_remote(channel.channel_id)
            await self._close_channel(channel)


# ============================================================================
# Port Forwarding
# ============================================================================

class PortForward:
    def __init__(self, tunnel: TunnelClient, listen_host: str = '127.0.0.1',
                 listen_port: int = 1080, forward_host: str = '',
                 forward_port: int = 0):
        self.tunnel = tunnel
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.forward_host = forward_host
        self.forward_port = forward_port

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming connection by forwarding through tunnel."""
        channel = None
        try:
            if not self.tunnel.connected:
                writer.close()
                return

            logger.info(f"Forwarding {writer.get_extra_info('peername')} -> {self.forward_host}:{self.forward_port}")

            channel_id, success = await self.tunnel.open_channel(
                self.forward_host, self.forward_port
            )

            if success:
                channel = Channel(
                    channel_id=channel_id,
                    reader=reader,
                    writer=writer,
                    host=self.forward_host,
                    port=self.forward_port,
                    connected=True,
                )
                self.tunnel.channels[channel_id] = channel
                self.tunnel.active_channel_info[channel_id] = (
                    self.forward_host, self.forward_port, reader, writer
                )
                await self._forward_loop(channel)
            else:
                writer.close()

        except Exception as e:
            logger.debug(f"Forward error: {e}")
        finally:
            # Close local socket first (don't wait for dead tunnel)
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
            if channel:
                # Best-effort notify server (may fail if tunnel is dead)
                try:
                    await asyncio.wait_for(
                        self.tunnel.close_channel_remote(channel.channel_id),
                        timeout=2.0
                    )
                except:
                    pass
                await self.tunnel._close_channel(channel)

    async def _forward_loop(self, channel: Channel):
        """Forward data from local client to tunnel."""
        try:
            while channel.connected and self.tunnel.connected:
                try:
                    data = await asyncio.wait_for(channel.reader.read(32768), timeout=0.1)
                    if data:
                        await self.tunnel.send_data(channel.channel_id, data)
                    elif data == b'':
                        break
                except asyncio.TimeoutError:
                    continue
        except:
            pass


# ============================================================================
# SOCKS5
# ============================================================================

class SOCKS5:
    VERSION = 0x05
    AUTH_NONE = 0x00
    CMD_CONNECT = 0x01
    ATYP_IPV4 = 0x01
    ATYP_DOMAIN = 0x03
    ATYP_IPV6 = 0x04
    REP_SUCCESS = 0x00
    REP_FAILURE = 0x01


class SOCKS5Server:
    def __init__(self, tunnel: TunnelClient, host: str = '127.0.0.1', port: int = 1080):
        self.tunnel = tunnel
        self.host = host
        self.port = port

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        channel = None
        try:
            if not self.tunnel.connected:
                writer.close()
                return

            data = await reader.read(2)
            if len(data) < 2 or data[0] != SOCKS5.VERSION:
                return

            nmethods = data[1]
            await reader.read(nmethods)

            writer.write(bytes([SOCKS5.VERSION, SOCKS5.AUTH_NONE]))
            await writer.drain()

            data = await reader.read(4)
            if len(data) < 4:
                return

            version, cmd, _, atyp = data

            if cmd != SOCKS5.CMD_CONNECT:
                writer.write(bytes([SOCKS5.VERSION, 0x07, 0, 1, 0, 0, 0, 0, 0, 0]))
                await writer.drain()
                return

            if atyp == SOCKS5.ATYP_IPV4:
                addr_data = await reader.read(4)
                host = socket.inet_ntoa(addr_data)
            elif atyp == SOCKS5.ATYP_DOMAIN:
                length = (await reader.read(1))[0]
                host = (await reader.read(length)).decode()
            elif atyp == SOCKS5.ATYP_IPV6:
                addr_data = await reader.read(16)
                host = socket.inet_ntop(socket.AF_INET6, addr_data)
            else:
                return

            port_data = await reader.read(2)
            port = struct.unpack('>H', port_data)[0]

            logger.info(f"CONNECT {host}:{port}")

            channel_id, success = await self.tunnel.open_channel(host, port)

            if success:
                writer.write(bytes([SOCKS5.VERSION, SOCKS5.REP_SUCCESS, 0, 1, 0, 0, 0, 0, 0, 0]))
                await writer.drain()

                channel = Channel(
                    channel_id=channel_id,
                    reader=reader,
                    writer=writer,
                    host=host,
                    port=port,
                    connected=True,
                )
                self.tunnel.channels[channel_id] = channel
                self.tunnel.active_channel_info[channel_id] = (host, port, reader, writer)
                await self._forward_loop(channel)
            else:
                writer.write(bytes([SOCKS5.VERSION, SOCKS5.REP_FAILURE, 0, 1, 0, 0, 0, 0, 0, 0]))
                await writer.drain()

        except Exception as e:
            logger.debug(f"SOCKS error: {e}")
        finally:
            # Close local socket first (don't wait for dead tunnel)
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
            if channel:
                try:
                    await asyncio.wait_for(
                        self.tunnel.close_channel_remote(channel.channel_id),
                        timeout=2.0
                    )
                except:
                    pass
                await self.tunnel._close_channel(channel)

    async def _forward_loop(self, channel: Channel):
        """Forward data from local client to tunnel."""
        try:
            while channel.connected and self.tunnel.connected:
                try:
                    data = await asyncio.wait_for(channel.reader.read(32768), timeout=0.1)
                    if data:
                        await self.tunnel.send_data(channel.channel_id, data)
                    elif data == b'':
                        break
                except asyncio.TimeoutError:
                    continue
        except:
            pass


# ============================================================================
# Main
# ============================================================================

async def run_client(config: ClientConfig, ca_cert: str):
    """Run client with auto-reconnect and channel migration."""
    reconnect_delays = [0, 0.5, 1, 2, 3, 5]  # instant for first 2, then backoff
    max_reconnect_delay = 5
    retry_count = 0

    # Persistent listen server - survives tunnel reconnects
    tunnel = TunnelClient(config, ca_cert)
    handler = None
    srv = None

    if config.mode == 'socks':
        handler = SOCKS5Server(tunnel, config.listen_host, config.listen_port)
    else:
        handler = PortForward(tunnel, config.listen_host, config.listen_port,
                              config.forward_host, config.forward_port)

    # Start persistent listen server
    srv = await asyncio.start_server(
        handler.handle_client, handler.listen_host if handler else config.listen_host,
        handler.listen_port if handler else config.listen_port,
        reuse_address=True
    )
    addr = srv.sockets[0].getsockname()
    if config.mode == 'socks':
        logger.info(f"SOCKS5 proxy on {addr[0]}:{addr[1]}")
    else:
        logger.info(f"Listening on {addr[0]}:{addr[1]} -> {config.forward_host}:{config.forward_port}")

    async with srv:
        while True:
            # Preserve active channels from old tunnel for migration
            old_active = tunnel.active_channel_info if tunnel else {}
            tunnel = TunnelClient(config, ca_cert)
            tunnel.active_channel_info = old_active

            # Re-point handler to new tunnel instance
            if isinstance(handler, SOCKS5Server):
                handler.tunnel = tunnel
            elif isinstance(handler, PortForward):
                handler.tunnel = tunnel

            if not await tunnel.connect():
                delay = reconnect_delays[min(retry_count, len(reconnect_delays) - 1)]
                logger.warning(f"Connection failed, retrying in {delay}s...")
                await asyncio.sleep(delay)
                retry_count += 1
                continue

            retry_count = 0

            # Migrate channels from previous connection
            if old_active:
                await tunnel.migrate_channels()

            receiver_task = asyncio.create_task(tunnel._receiver_loop())

            try:
                logger.info("Tunnel connected")
                await receiver_task

            except asyncio.CancelledError:
                pass
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                await tunnel.disconnect()
                return 0
            except OSError as e:
                if "Address already in use" in str(e):
                    logger.error(f"Port {config.listen_port} already in use, waiting...")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"Server error: {e}")
            finally:
                await tunnel.disconnect()
                receiver_task.cancel()
                try:
                    await receiver_task
                except asyncio.CancelledError:
                    pass

            logger.warning("Connection lost, reconnecting...")
            current_delay = reconnect_delay


def main():
    parser = argparse.ArgumentParser(description='SMTP Tunnel Client')
    parser.add_argument('--config', '-c', default='config.yaml')
    parser.add_argument('--server', default=None, help='Server domain name (FQDN required for TLS)')
    parser.add_argument('--server-port', type=int, default=None)
    parser.add_argument('--mode', default=None, choices=['forward', 'socks'],
                        help='Client mode: forward (port forward) or socks (SOCKS5 proxy)')
    parser.add_argument('--listen-port', '-p', type=int, default=None,
                        help='Local port to listen on')
    parser.add_argument('--listen-host', default=None,
                        help='Local address to bind to')
    parser.add_argument('--forward-host', default=None,
                        help='Target host to forward connections to (forward mode)')
    parser.add_argument('--forward-port', type=int, default=None,
                        help='Target port to forward connections to (forward mode)')
    parser.add_argument('--username', '-u', default=None, help='Username for authentication')
    parser.add_argument('--secret', '-s', default=None)
    parser.add_argument('--ca-cert', default=None)
    parser.add_argument('--debug', '-d', action='store_true')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        config_data = load_config(args.config)
    except FileNotFoundError:
        config_data = {}

    client_conf = config_data.get('client', {})

    mode = args.mode or client_conf.get('mode', 'forward')

    # Backward compat: map old socks_port/socks_host to listen_port/listen_host
    listen_port = args.listen_port or client_conf.get('listen_port') or \
                  client_conf.get('socks_port', 1080)
    listen_host = args.listen_host or client_conf.get('listen_host') or \
                  client_conf.get('socks_host', '127.0.0.1')

    config = ClientConfig(
        server_host=args.server or client_conf.get('server_host', 'localhost'),
        server_port=args.server_port or client_conf.get('server_port', 587),
        mode=mode,
        listen_host=listen_host,
        listen_port=listen_port,
        forward_host=args.forward_host or client_conf.get('forward_host', ''),
        forward_port=args.forward_port or client_conf.get('forward_port', 0),
        username=args.username or client_conf.get('username', ''),
        secret=args.secret or client_conf.get('secret', ''),
        max_channels=client_conf.get('max_channels', 256),
        keepalive_interval=client_conf.get('keepalive_interval', 30),
        keepalive_timeout=client_conf.get('keepalive_timeout', 90),
    )

    ca_cert = args.ca_cert or client_conf.get('ca_cert')

    if not config.username:
        logger.error("No username configured!")
        return 1

    if not config.secret:
        logger.error("No secret configured!")
        return 1

    if config.mode == 'forward' and (not config.forward_host or not config.forward_port):
        logger.error("Forward target not configured! Use --forward-host and --forward-port")
        return 1

    try:
        return asyncio.run(run_client(config, ca_cert))
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    exit(main())
