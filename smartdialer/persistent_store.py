"""
Minimal cross-process persistence layer for SmartDialer.

Why this file exists: two problems the in-memory design can't answer --
"two separate worker processes race for the same agent, who wins?" and
"a worker crashes mid-call, what happens when the system comes back?" --
both come down to the same root cause: AgentManager/BorrowerManager/
CallManager only live in one process's memory, so a second process can't
see or coordinate with them, and a crash loses everything.

The fix here is deliberately small: a JSON file per resource type,
guarded by an OS-level file lock (via the `filelock` library, not a
database engine), plus three manager classes that expose the exact same
public methods as their in-memory counterparts -- so they're drop-in
replacements (Python duck-typing) for CallAllocator/ProgressiveDialer/
PredictiveDialer, which don't need to change at all to use them -- and a
recovery function that reconciles anything a dead process left claiming
resources.

Not built here on purpose: SafetyController's counters stay in-memory
per-process. A fully distributed deployment would derive them from a
live count of non-terminal persisted calls instead of incrementing/
decrementing counters that reset on crash; that's a reasonable next
step, not done here to keep this one file focused on the specific
failure mode the assignment calls out (leaked agent/borrower/call
state), not a full distributed-systems rewrite.

Not a database: no query engine, no indexes. Every operation reads the
whole JSON blob, mutates it, writes it all back atomically under one
lock. Fine at this prototype's scale (hundreds to low-thousands of
records); the "what breaks first at scale" answer for this file
specifically is the same "rewrite the whole file every write" cost that
makes it simple in the first place -- past a few thousand records, a
real embedded KV store or database is the right next step, not a
bigger JSON file.
"""

import json
import os
import tempfile

from filelock import FileLock

from smartdialer.models import Agent, AgentStatus, Borrower, BorrowerStatus, Call, CallStatus
from smartdialer.agent_lifecycle import AGENT_VALID_TRANSITIONS
from smartdialer.call_manager import CALL_VALID_TRANSITIONS


# ---------------------------------------------------------------------
# Storage primitive
# ---------------------------------------------------------------------

class JSONFileStore:
    """
    Cross-process-safe key-value store: a JSON file plus a FileLock.

    Why this actually solves cross-process races and threading.Lock
    does not: threading.Lock only coordinates threads inside one Python
    process -- two separate `python` processes each get their own
    independent Lock and can't see each other's. FileLock instead asks
    the operating system to arbitrate (fcntl on POSIX, LockFileEx on
    Windows) over a real file on disk, so every process pointed at the
    same lock path is coordinated by the OS kernel, whether or not they
    know about each other.
    """

    def __init__(self, path, lock_timeout=30):
        self.path = path
        self._lock = FileLock(path + ".lock", timeout=lock_timeout)

        if not os.path.exists(self.path):
            self._write_raw({})

    def _read_raw(self):
        if not os.path.exists(self.path):
            return {}
        with open(self.path, "r") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}

    def _write_raw(self, data):
        # Atomic write: temp file in the same dir, then os.replace() --
        # atomic on POSIX and Windows, so a crash mid-write can never
        # leave a half-written store; readers see the old complete file
        # or the new complete file, never a partial one.
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def with_lock(self, fn):
        """
        Runs fn(data) -> (result, new_data_or_None) under the exclusive
        cross-process lock. Non-None new_data is written back before the
        lock releases; None means read-only, don't write. This is the
        ONLY way callers should read-modify-write the store -- it's what
        makes e.g. "reserve the first AVAILABLE agent" atomic across
        every process pointed at the same file.
        """
        with self._lock:
            data = self._read_raw()
            result, new_data = fn(data)
            if new_data is not None:
                self._write_raw(new_data)
            return result

    def read_all(self):
        with self._lock:
            return self._read_raw()


# ---------------------------------------------------------------------
# Persistent managers -- same public interface as AgentManager /
# BorrowerManager / CallManager, backed by a JSONFileStore instead of an
# in-memory dict, so CallAllocator/dialers work unchanged with either.
# ---------------------------------------------------------------------

class PersistentAgentManager:

    def __init__(self, store_path):
        self.store = JSONFileStore(store_path)

    def add_agent(self, agent: Agent):
        def op(data):
            data[agent.id] = {"id": agent.id, "name": agent.name, "status": agent.status.value}
            return None, data
        self.store.with_lock(op)

    @property
    def agents(self):
        return {aid: _record_to_agent(r) for aid, r in self.store.read_all().items()}

    def get_available_agents(self):
        return [
            _record_to_agent(r) for r in self.store.read_all().values()
            if r["status"] == AgentStatus.AVAILABLE.value
        ]

    def reserve_agent(self):
        def op(data):
            for record in data.values():
                if record["status"] == AgentStatus.AVAILABLE.value:
                    record["status"] = AgentStatus.RESERVED.value
                    return _record_to_agent(record), data
            return None, None
        return self.store.with_lock(op)

    def release_agent(self, agent_id):
        # Unconditional -> AVAILABLE, matching AgentManager's permissive
        # release_agent() semantics (see agent_lifecycle.py).
        def op(data):
            record = data.get(agent_id)
            if record is None:
                return False, None
            record["status"] = AgentStatus.AVAILABLE.value
            return True, data
        return self.store.with_lock(op)

    def _transition(self, agent_id, new_status):
        def op(data):
            record = data.get(agent_id)
            if record is None:
                return False, None
            current = AgentStatus(record["status"])
            if new_status not in AGENT_VALID_TRANSITIONS.get(current, set()):
                return False, None
            record["status"] = new_status.value
            return True, data
        return self.store.with_lock(op)

    def mark_dialing(self, agent_id):
        return self._transition(agent_id, AgentStatus.DIALING)

    def mark_connected(self, agent_id):
        return self._transition(agent_id, AgentStatus.CONNECTED)

    def mark_wrap_up(self, agent_id):
        return self._transition(agent_id, AgentStatus.WRAP_UP)

    def pause_agent(self, agent_id):
        return self._transition(agent_id, AgentStatus.PAUSED)

    def resume_agent(self, agent_id):
        return self._transition(agent_id, AgentStatus.AVAILABLE)

    def bring_online(self, agent_id):
        return self._transition(agent_id, AgentStatus.AVAILABLE)

    def set_offline(self, agent_id):
        """Returns (success, was_mid_call) -- see AgentManager.set_offline()."""
        def op(data):
            record = data.get(agent_id)
            if record is None:
                return (False, False), None
            was_mid_call = record["status"] in (
                AgentStatus.RESERVED.value, AgentStatus.DIALING.value, AgentStatus.CONNECTED.value
            )
            record["status"] = AgentStatus.OFFLINE.value
            return (True, was_mid_call), data
        return self.store.with_lock(op)


class PersistentBorrowerManager:

    def __init__(self, store_path):
        self.store = JSONFileStore(store_path)

    def add_borrower(self, borrower: Borrower):
        def op(data):
            data[borrower.id] = {
                "id": borrower.id, "name": borrower.name,
                "phone_number": borrower.phone_number,
                "priority": borrower.priority, "status": borrower.status.value
            }
            return None, data
        self.store.with_lock(op)

    @property
    def borrowers(self):
        return {bid: _record_to_borrower(r) for bid, r in self.store.read_all().items()}

    def get_waiting_borrowers(self):
        return [
            _record_to_borrower(r) for r in self.store.read_all().values()
            if r["status"] == BorrowerStatus.WAITING.value
        ]

    def reserve_borrower(self):
        def op(data):
            waiting = [r for r in data.values() if r["status"] == BorrowerStatus.WAITING.value]
            if not waiting:
                return None, None
            waiting.sort(key=lambda r: r["priority"], reverse=True)
            chosen = waiting[0]
            chosen["status"] = BorrowerStatus.RESERVED.value
            return _record_to_borrower(chosen), data
        return self.store.with_lock(op)

    def release_borrower(self, borrower_id):
        def op(data):
            record = data.get(borrower_id)
            if record is None:
                return False, None
            record["status"] = BorrowerStatus.WAITING.value
            return True, data
        return self.store.with_lock(op)

    def complete_borrower(self, borrower_id):
        def op(data):
            record = data.get(borrower_id)
            if record is None:
                return False, None
            record["status"] = BorrowerStatus.COMPLETED.value
            return True, data
        return self.store.with_lock(op)

    def mark_borrower_failed(self, borrower_id):
        def op(data):
            record = data.get(borrower_id)
            if record is None:
                return False, None
            record["status"] = BorrowerStatus.FAILED.value
            return True, data
        return self.store.with_lock(op)


class PersistentCallManager:

    def __init__(self, store_path):
        self.store = JSONFileStore(store_path)

    def add_call(self, call: Call):
        def op(data):
            data[call.id] = {
                "id": call.id, "agent_id": call.agent_id,
                "borrower_id": call.borrower_id, "status": call.status.value
            }
            return None, data
        self.store.with_lock(op)

    @property
    def calls(self):
        return {cid: _record_to_call(r) for cid, r in self.store.read_all().items()}

    def get_call(self, call_id):
        record = self.store.read_all().get(call_id)
        return _record_to_call(record) if record else None

    def transition(self, call_id, new_status):
        def op(data):
            record = data.get(call_id)
            if record is None:
                return False, None
            current = CallStatus(record["status"])
            if current == new_status:
                return True, None  # duplicate event -- no-op, same as CallManager
            if new_status not in CALL_VALID_TRANSITIONS.get(current, set()):
                return False, None
            record["status"] = new_status.value
            return True, data
        return self.store.with_lock(op)

    def read_all(self):
        return self.store.read_all()


def _record_to_agent(r):
    return Agent(id=r["id"], name=r["name"], status=AgentStatus(r["status"]))


def _record_to_borrower(r):
    return Borrower(id=r["id"], name=r["name"], phone_number=r["phone_number"],
                    priority=r["priority"], status=BorrowerStatus(r["status"]))


def _record_to_call(r):
    return Call(id=r["id"], borrower_id=r["borrower_id"],
                agent_id=r.get("agent_id"), status=CallStatus(r["status"]))


# ---------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------

IN_FLIGHT_CALL_STATUSES = {
    CallStatus.RESERVED, CallStatus.INITIATED, CallStatus.RINGING,
    CallStatus.ANSWERED, CallStatus.CONNECTED
}


def recover_stale_calls(call_manager, agent_manager, borrower_manager):
    """
    Startup (or periodic) reconciliation pass: finds every persisted
    call still sitting in a non-terminal state and forces it to FAILED,
    releasing whatever agent/borrower it was holding.

    This is what "the system comes back after a worker crash" means
    here: there's no in-memory state to lose (it was already durable in
    these managers), so recovery is "reconcile anything a dead process
    left dangling" using the same agent->AVAILABLE / borrower->WAITING
    release a normal fail_call() would do -- not "replay a log".

    Call once at worker startup; optionally on a timer for long-running
    workers to catch a peer that died mid-call. Returns the recovered
    call ids.
    """
    recovered = []
    data = call_manager.read_all()

    for call_id, record in data.items():
        try:
            status = CallStatus(record["status"])
        except ValueError:
            continue

        if status not in IN_FLIGHT_CALL_STATUSES:
            continue

        call_manager.transition(call_id, CallStatus.FAILED)

        agent_id = record.get("agent_id")
        if agent_id:
            agent_manager.release_agent(agent_id)

        borrower_id = record.get("borrower_id")
        if borrower_id:
            borrower_manager.release_borrower(borrower_id)

        recovered.append(call_id)

    return recovered
