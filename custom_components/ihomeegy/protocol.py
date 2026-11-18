"""The iHomeegy unit's local protocol, the same one the iHomeegy app speaks.

TCP to the unit (port 8890), secured with Noise_NNpsk0_25519_ChaChaPoly_SHA256 (prologue "iHome/noise/v1"):
  frame = [2-byte big-endian length][payload]
  frames 1 and 2 are the 48-byte handshake messages, every later frame is one encrypted JSON message.
The pre-shared key is this Home Assistant's own member key: a successful handshake IS the authentication.

This module has no Home Assistant imports, so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from noise.connection import NoiseConnection

from .const import (
    INVITE_PREFIX,
    MAX_PLAIN_TO_UNIT,
    NOISE_PROLOGUE,
    NOISE_PROTOCOL,
    SILENCE_LIMIT,
)

_LOGGER = logging.getLogger(__name__)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UNIT_ID = re.compile(r"^[0-9a-f]{16}$")


class IhError(Exception):
    """Something went wrong talking to a unit."""


class IhUnreachable(IhError):
    """The unit could not be reached."""


class IhRefused(IhError):
    """The unit does not know this key (removed member, factory reset, wrong unit)."""


class IhTimeout(IhError):
    """The unit did not answer in time."""


class IhCommandError(IhError):
    """The unit refused a command ("forbidden", "license", ...)."""

    def __init__(self, err: str) -> None:
        super().__init__(err)
        self.err = err


# ---------------------------------------------------------------------------------------------------------------------
#  Invite code (the app's "Invite" screen: ihome://join?d=<base64url JSON>)
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class InviteUnit:
    id: str
    name: str
    host: str
    port: int


@dataclass
class Invite:
    key: bytes
    mid: str
    name: str
    by: str
    units: list[InviteUnit] = field(default_factory=list)


def parse_invite(text: str) -> Invite | None:
    """Parse an invite code copied from the iHomeegy app. None when it is not one."""
    s = (text or "").strip()
    if not s.startswith(INVITE_PREFIX):
        return None
    raw = s[len(INVITE_PREFIX) :]
    try:
        j = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(j, dict) or j.get("v") != 1:
        return None
    k = str(j.get("k", ""))
    if not _HEX64.match(k):
        return None
    units: list[InviteUnit] = []
    for u in j.get("u") or []:
        if not isinstance(u, dict):
            continue
        uid = str(u.get("i", "")).lower()
        if not _UNIT_ID.match(uid):
            continue
        port = u.get("p")
        units.append(
            InviteUnit(
                id=uid,
                name=str(u.get("n") or uid),
                host=str(u.get("h") or ""),
                port=int(port) if isinstance(port, (int, float)) else 8890,
            )
        )
    if not units:
        return None
    return Invite(
        key=bytes.fromhex(k),
        mid=str(j.get("m", "")),
        name=str(j.get("n", "")),
        by=str(j.get("b", "")),
        units=units,
    )


def new_key() -> bytes:
    """A fresh 32-byte member key."""
    return secrets.token_bytes(32)


# ---------------------------------------------------------------------------------------------------------------------
#  One Noise connection
# ---------------------------------------------------------------------------------------------------------------------
class NoiseLink:
    """One TCP connection to a unit with the Noise session on top of it."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, noise: NoiseConnection) -> None:
        self._reader = reader
        self._writer = writer
        self._noise = noise
        self.last_rx = time.monotonic()
        self.bye_code: int | None = None

    @classmethod
    async def open(cls, host: str, port: int, psk: bytes, timeout: float = 10.0) -> NoiseLink:
        """Connect and complete the handshake. Raises IhUnreachable / IhTimeout / IhRefused."""
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        except asyncio.TimeoutError as err:
            raise IhTimeout(f"no answer from {host}:{port}") from err
        except OSError as err:
            raise IhUnreachable(f"cannot reach {host}:{port}: {err}") from err
        noise = NoiseConnection.from_name(NOISE_PROTOCOL)
        noise.set_as_initiator()
        noise.set_psks(psk=psk)
        noise.set_prologue(NOISE_PROLOGUE)
        noise.start_handshake()
        link = cls(reader, writer, noise)
        try:
            link._write_frame(noise.write_message())
            try:
                msg2 = await asyncio.wait_for(link._read_frame(), timeout)
            except asyncio.IncompleteReadError as err:
                # the unit closes the socket when message 1 matches none of its keys
                raise IhRefused("the unit refused the key") from err
            try:
                noise.read_message(msg2)
            except Exception as err:  # noqa: BLE001 - the library raises several kinds
                raise IhRefused("the unit refused the key") from err
            if not noise.handshake_finished:
                raise IhRefused("handshake did not finish")
        except asyncio.TimeoutError as err:
            await link.close()
            raise IhTimeout("the unit did not answer the handshake") from err
        except (IhError, OSError) as err:
            await link.close()
            if isinstance(err, IhError):
                raise
            raise IhUnreachable(str(err)) from err
        return link

    def _write_frame(self, payload: bytes) -> None:
        self._writer.write(len(payload).to_bytes(2, "big") + payload)

    async def _read_frame(self) -> bytes:
        hdr = await self._reader.readexactly(2)
        n = int.from_bytes(hdr, "big")
        data = await self._reader.readexactly(n)
        self.last_rx = time.monotonic()
        return data

    async def recv(self) -> dict[str, Any] | None:
        """Next JSON message (keep-alive answered here). None for a frame that is not JSON. Raises on close/tamper."""
        while True:
            frame = await self._read_frame()
            try:
                plain = self._noise.decrypt(frame)
            except Exception as err:  # noqa: BLE001
                raise IhError("a message from the unit failed authentication") from err
            try:
                msg = json.loads(plain.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get("t")
            if t == "ping":
                self.send({"t": "pong"})
                await self.drain()
                continue
            if t == "pong":
                continue
            if t == "bye":
                code = msg.get("code")
                self.bye_code = int(code) if isinstance(code, (int, float)) else 0
                raise IhError(f"the unit closed the session (code {self.bye_code})")
            return msg

    def send(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_PLAIN_TO_UNIT:
            raise IhError("message too big for the unit")
        self._write_frame(self._noise.encrypt(data))

    async def drain(self) -> None:
        await self._writer.drain()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            self._writer.close()
            await asyncio.wait_for(self._writer.wait_closed(), 2)


async def claim(host: str, port: int, unit_id: str, invite_key: bytes, my_key: bytes, timeout: float = 8.0) -> None:
    """Accept an invite on one unit: open it with the one-time invite key and swap it for [my_key] (mem_claim).

    Raises IhRefused when the invite is used / expired / for another unit, IhError("full"/"license"/"storage") when
    the unit said no, IhUnreachable / IhTimeout when it could not be reached.
    """
    link = await NoiseLink.open(host, port, invite_key, timeout)
    try:
        hello = await asyncio.wait_for(link.recv(), 6)
        if not hello or hello.get("t") != "hello" or hello.get("id") != unit_id:
            raise IhRefused("another unit answered")
        if hello.get("claim") is not True:
            raise IhRefused("not an invite for this unit")
        link.send({"t": "mem_claim", "key": my_key.hex()})
        await link.drain()
        for _ in range(8):
            m = await asyncio.wait_for(link.recv(), 8)
            if not m:
                continue
            if m.get("t") == "claim_ok":
                return
            if m.get("t") == "claim_fail":
                raise IhError(str(m.get("err") or "failed"))
        raise IhTimeout("no answer to the claim")
    except asyncio.TimeoutError as err:
        raise IhTimeout("the unit did not answer") from err
    except asyncio.IncompleteReadError as err:
        raise IhRefused("the unit closed the connection") from err
    finally:
        await link.close()


async def probe(host: str, port: int, unit_id: str, key: bytes, timeout: float = 5.0) -> bool:
    """True when [host] is this unit and it accepts [key]."""
    try:
        link = await NoiseLink.open(host, port, key, timeout)
    except IhError:
        return False
    try:
        hello = await asyncio.wait_for(link.recv(), timeout)
        return bool(hello) and hello.get("t") == "hello" and hello.get("id") == unit_id
    except (IhError, asyncio.TimeoutError, asyncio.IncompleteReadError, OSError):
        return False
    finally:
        await link.close()


# ---------------------------------------------------------------------------------------------------------------------
#  A unit kept connected (local push), with reconnects
# ---------------------------------------------------------------------------------------------------------------------
class UnitClient:
    """Keeps one connection to a unit open and holds what it said: hello ("you"), descriptor, state."""

    def __init__(
        self,
        unit_id: str,
        host: str,
        port: int,
        key: bytes,
        on_update: Callable[[], None],
        on_removed: Callable[[int], None],
        find_host: Callable[[], Any] | None = None,
    ) -> None:
        self.unit_id = unit_id
        self.host = host
        self.port = port
        self._key = key
        self._on_update = on_update
        self._on_removed = on_removed
        self._find_host = find_host  # async () -> (host, port) | None : look for the unit (mDNS) when it moved
        self.hello: dict[str, Any] = {}
        self.desc: dict[str, Any] = {}
        self.state: dict[str, Any] = {}
        self.connected = False
        self._link: NoiseLink | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._seq = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._first = asyncio.Event()  # the first descriptor + state arrived
        self.refusals = 0  # handshakes refused in a row

    # -------- lifecycle --------
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run(), name=f"ihomeegy {self.unit_id}")

    async def stop(self) -> None:
        self._stop.set()
        if self._link:
            await self._link.close()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def wait_ready(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._first.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def set_host(self, host: str, port: int) -> None:
        """A new address for the unit (mDNS): used at the next (re)connect."""
        self.host, self.port = host, port

    # -------- what the unit allows this member --------
    @property
    def you(self) -> dict[str, Any]:
        y = self.hello.get("you")
        return y if isinstance(y, dict) else {}

    def allowed(self, entity: dict[str, Any]) -> bool:
        """The unit lets this member use that card (the unit checks it again on every command)."""
        cards = self.you.get("cards")
        if cards == "*":
            return True
        if not isinstance(cards, list):
            return False
        eid = entity.get("id")
        if eid in cards:
            return True
        parent = entity.get("parent")  # e.g. the humidity half of the temperature card
        return bool(parent) and parent in cards

    def entities(self) -> list[dict[str, Any]]:
        ents = self.desc.get("entities")
        if not isinstance(ents, list):
            return []
        return [e for e in ents if isinstance(e, dict) and isinstance(e.get("id"), str) and self.allowed(e)]

    # -------- commands --------
    async def command(self, values: dict[str, Any], timeout: float = 6.0) -> None:
        """Send {"t":"cmd","set":{...}} and wait for the unit's ack. Raises IhCommandError / IhError."""
        reply = await self.request({"t": "cmd", "set": values}, timeout)
        if reply.get("ok") is False:
            raise IhCommandError(str(reply.get("err") or "failed"))

    async def request(self, message: dict[str, Any], timeout: float = 6.0) -> dict[str, Any]:
        link = self._link
        if not self.connected or link is None:
            raise IhUnreachable("not connected to the unit")
        seq = self._seq
        self._seq += 1
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[seq] = fut
        try:
            link.send({**message, "seq": seq})
            await link.drain()
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as err:
            raise IhTimeout("the unit did not answer the command") from err
        except (OSError, ConnectionError) as err:
            raise IhUnreachable(str(err)) from err
        finally:
            self._pending.pop(seq, None)

    # -------- the connection loop --------
    async def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                await self._session()
                delay = 1.0
            except IhRefused as err:
                self.refusals += 1
                _LOGGER.debug("%s: refused (%s), %d in a row", self.unit_id, err, self.refusals)
            except (IhError, OSError, asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError) as err:
                _LOGGER.debug("%s: connection ended: %s", self.unit_id, err)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never let the loop die
                _LOGGER.exception("%s: unexpected error", self.unit_id)
            was = self.connected
            self.connected = False
            self._fail_pending()
            if was:
                self._on_update()
            link = self._link
            self._link = None
            if link:
                if link.bye_code in (4001, 4002):
                    self._on_removed(link.bye_code)
                    return
                await link.close()
            if self._stop.is_set():
                return
            # the unit moved to another address? look for it on the network
            if self._find_host is not None and delay >= 4:
                with contextlib.suppress(Exception):
                    found = await self._find_host()
                    if found:
                        self.host, self.port = found
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), delay)
            delay = min(delay * 2, 60.0)

    async def _session(self) -> None:
        link = await NoiseLink.open(self.host, self.port, self._key, 10.0)
        self._link = link
        self.refusals = 0
        hello = await asyncio.wait_for(link.recv(), 8)
        if not hello or hello.get("t") != "hello" or hello.get("id") != self.unit_id:
            raise IhRefused("another unit answered")
        if hello.get("paired") is not True or hello.get("claim"):
            raise IhRefused("not a member session")
        self.hello = hello
        # the descriptor's hash we hold: the unit sends the descriptor only when it changed
        link.send({"t": "sync", "dh": self.desc.get("_dh", "") if self.desc else ""})
        await link.drain()
        self.connected = True
        self._on_update()
        watchdog = asyncio.get_running_loop().create_task(self._watch(link))
        try:
            while True:
                msg = await link.recv()
                if msg:
                    self._handle(msg)
        finally:
            watchdog.cancel()

    async def _watch(self, link: NoiseLink) -> None:
        while True:
            await asyncio.sleep(5)
            if time.monotonic() - link.last_rx > SILENCE_LIMIT:
                _LOGGER.debug("%s: no sign of life", self.unit_id)
                await link.close()
                return

    def _handle(self, m: dict[str, Any]) -> None:
        seq = m.get("seq")
        if isinstance(seq, int) and seq in self._pending:
            fut = self._pending.pop(seq)
            if not fut.done():
                fut.set_result(m)
            return
        t = m.get("t")
        d = m.get("d")
        if t == "desc" and isinstance(d, dict) and isinstance(d.get("entities"), list):
            d["_dh"] = self.hello.get("dh", "")
            self.desc = d
            self._maybe_ready()
            self._on_update()
        elif t == "state" and isinstance(d, dict):
            self.state = d
            self._maybe_ready()
            self._on_update()
        elif t == "you" and isinstance(d, dict):
            self.hello = {**self.hello, "you": d}
            self._on_update()

    def _maybe_ready(self) -> None:
        if self.desc and self.state:
            self._first.set()

    def _fail_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(IhUnreachable("connection to the unit ended"))
        self._pending.clear()
