"""Hardware-free simulator core. Demo settings are not hardware allocations."""
from collections import deque
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
import uuid

SCHEMA = "dsn-simulator-v1"
DEMO_INTERVAL_MS = 50
DEMO_BUFFER_SIZE = 128
STALE_NS = 100_000_000  # Owner-selected software test target, not hardware evidence.
MAX_LINE_BYTES = 1_048_576


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class Sample:
    code: int
    validity: str
    timestamp_ns: int
    sequence: int
    session_id: str
    timing_quality: str = "simulated"
    source: str = "simulator"

    def record(self):
        return {"kind": "sample", **asdict(self)}


def decode_sample(record, session_id):
    if not isinstance(record, dict) or record.get("kind") != "sample":
        raise ValueError("Expected a sample record.")
    fields = set(Sample.__dataclass_fields__)
    if set(record) != fields | {"kind"}:
        raise ValueError("Unsupported or missing sample fields.")
    values = {k: record[k] for k in fields}
    for name in ("code", "timestamp_ns", "sequence"):
        if type(values[name]) is not int:
            raise ValueError(f"{name} must be an integer.")
    if not 0 <= values["code"] <= 255 or values["timestamp_ns"] < 0 or values["sequence"] < 1:
        raise ValueError("Sample value, timestamp or sequence is out of range.")
    if values["session_id"] != session_id or values["source"] != "simulator":
        raise ValueError("Only this simulator's session records are supported.")
    if values["validity"] not in ("valid", "invalid"):
        raise ValueError("Unknown validity state.")
    if values["timing_quality"] not in ("simulated", "unqualified", "unavailable"):
        raise ValueError("Unknown timing quality.")
    return Sample(**values)


class RecordingReader:
    """Streaming, bounded-line reader; invalid/truncated files fail visibly."""
    def __init__(self, path):
        self.path = Path(path)
        self.file = self.path.open("rb")
        self.line = 0
        self.last_sequence = 0
        try:
            header = self._read()
            if not isinstance(header, dict) or header.get("kind") != "session":
                raise ValueError("First line must be a session header.")
            if header.get("schema") != SCHEMA or header.get("source") != "simulator":
                raise ValueError("Unsupported schema/source; use a recording from this simulator.")
            if header.get("timestamp_basis") != "python_monotonic_ns_simulated_event":
                raise ValueError("Unsupported timestamp basis.")
            if not isinstance(header.get("session_id"), str) or not header["session_id"]:
                raise ValueError("Missing session identity.")
            self.header = header
        except Exception:
            self.close()
            raise

    def _read(self):
        raw = self.file.readline(MAX_LINE_BYTES + 1)
        if not raw:
            return None
        self.line += 1
        if len(raw) > MAX_LINE_BYTES:
            raise ValueError(f"Line {self.line} is too long.")
        if not raw.endswith(b"\n"):
            raise ValueError(f"Line {self.line} is incomplete (missing newline).")
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                               parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
            if not isinstance(value, dict):
                raise ValueError("Each line must contain a record object.")
            return value
        except (UnicodeError, ValueError) as exc:
            raise ValueError(f"Invalid JSON at line {self.line}: {exc}") from exc

    def next_record(self):
        record = self._read()
        if record is None:
            return None
        if not isinstance(record, dict):
            raise ValueError(f"Expected an object at line {self.line}.")
        if record.get("kind") == "sample":
            sample = decode_sample(record, self.header["session_id"])
            if sample.sequence <= self.last_sequence:
                raise ValueError("Recorded sequence is duplicate or out of order.")
            self.last_sequence = sample.sequence
            return sample
        if record.get("kind") == "gap":
            if type(record.get("lost")) is not int or record["lost"] < 1 or record.get("reason") != "demo_buffer_drop_oldest":
                raise ValueError("Invalid gap record.")
            return record
        raise ValueError(f"Unsupported record kind at line {self.line}.")

    def close(self):
        if not self.file.closed:
            self.file.close()


class Simulator:
    def __init__(self, clock=time.monotonic_ns, capacity=DEMO_BUFFER_SIZE):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Capacity must be positive.")
        self.clock = clock
        self.capacity = capacity
        self.queue = deque()
        self.mode = "Simulator"
        self.running = False
        self.input_paused = False
        self.session_id = ""
        self.sequence = 0
        self.current = None
        self.last_live_publication = None
        self.loss = 0
        self.replay_gaps = 0
        self.pending_gap = 0
        self.writer = None
        self.reader = None
        self.replay_path = None
        self.replay_paused = False
        self.error = ""

    def set_mode(self, mode):
        if mode == "Live Hardware":
            raise ValueError("Live Hardware is unavailable. Hardware details are TBD.")
        if mode not in ("Simulator", "Replay"):
            raise ValueError("Unknown mode.")
        if self.running:
            raise ValueError("Stop before changing modes.")
        self.mode = mode
        self.current = None
        self.error = ""

    def start(self):
        if self.mode != "Simulator":
            raise ValueError("Use Play for a loaded recording.")
        if self.running:
            return
        self.session_id = str(uuid.uuid4())
        self.sequence = 0
        self.queue.clear()
        self.current = None
        self.last_live_publication = None
        self.loss = self.pending_gap = 0
        self.input_paused = False
        self.error = ""
        self.running = True

    def generate(self, code):
        if not self.running or self.mode != "Simulator" or self.input_paused:
            return
        if type(code) is not int or not 0 <= code <= 255:
            raise ValueError("Simulated code must be 0 through 255.")
        self.sequence += 1
        sample = Sample(code, "valid", self.clock(), self.sequence, self.session_id)
        if len(self.queue) == self.capacity:
            self.queue.popleft()
            self.loss += 1
            self.pending_gap += 1
        self.queue.append(sample)

    def publish(self):
        if not self.queue:
            return None
        sample = self.queue.popleft()
        self.current = sample
        self.last_live_publication = self.clock()
        if self.pending_gap:
            self._write({"kind": "gap", "lost": self.pending_gap, "reason": "demo_buffer_drop_oldest"})
            self.pending_gap = 0
        self._write(sample.record())
        return sample

    @property
    def status(self):
        if self.mode == "Replay":
            return "REPLAY PAUSED" if self.replay_paused else ("REPLAY" if self.running else "REPLAY STOPPED")
        if not self.running:
            return "STOPPED (SIMULATOR)"
        if self.last_live_publication is None:
            return "WAITING (SIMULATOR)"
        if self.clock() - self.last_live_publication >= STALE_NS:
            return "STALE (SIMULATOR)"
        return "VALID (SIMULATOR ONLY)"

    def begin_recording(self, path):
        if self.mode != "Simulator" or not self.running:
            raise ValueError("Start the Simulator before recording.")
        if self.writer:
            raise ValueError("Recording is already active.")
        # Exclusive create: never silently replace an existing recording.
        self.writer = Path(path).open("x", encoding="utf-8", newline="\n")
        self.error = ""
        self._write({"kind": "session", "schema": SCHEMA, "session_id": self.session_id,
                     "source": "simulator", "timestamp_basis": "python_monotonic_ns_simulated_event",
                     "demo_interval_ms": DEMO_INTERVAL_MS, "hardware_details": "TBD"})
        if not self.writer:
            raise OSError(self.error)

    def _write(self, record):
        if not self.writer:
            return
        try:
            self.writer.write(json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n")
            self.writer.flush()
        except (OSError, ValueError) as exc:
            self.error = f"Recording failed; file may be incomplete: {exc}"
            self.end_recording()

    def end_recording(self):
        writer, self.writer = self.writer, None
        if writer:
            try:
                writer.close()
            except OSError as exc:
                self.error = f"Recording close failed: {exc}"

    def open_recording(self, path):
        if self.running:
            raise ValueError("Stop before opening another recording.")
        candidate = RecordingReader(path)
        candidate.close()
        self.set_mode("Replay")
        self.replay_path = Path(path)
        self.replay_paused = False

    def play(self):
        if self.mode != "Replay" or not self.replay_path:
            raise ValueError("Open a simulator recording first.")
        if not self.reader:
            self.reader = RecordingReader(self.replay_path)
            self.replay_gaps = 0
            self.current = None
        self.replay_paused = False
        self.running = True
        self.error = ""

    def replay_next(self):
        if not self.reader or not self.running or self.replay_paused:
            return None
        try:
            record = self.reader.next_record()
            if record is None:
                self.stop()
                return None
            if isinstance(record, Sample):
                self.current = record
            else:
                self.replay_gaps += record["lost"]
            return record
        except (OSError, ValueError) as exc:
            self.error = f"Replay stopped: {exc}"
            self.stop()
            return None

    def pause_replay(self):
        if self.mode == "Replay" and self.running:
            self.replay_paused = True

    def request_acquisition_setting(self, name, value, identity=None):
        raise PermissionError("Protected changes unavailable: identity/access policy and hardware settings are TBD.")

    def stop(self):
        self.running = False
        self.input_paused = self.replay_paused = False
        self.queue.clear()
        self.end_recording()
        if self.reader:
            self.reader.close()
            self.reader = None
