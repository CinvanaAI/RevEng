"""AbilityExtractionAgent — Phase 1 Python-specific ability extraction.

Extracts atomic capabilities from enriched file breakdowns using call-pattern
matching and decorator inference. These heuristics are Python-specific Phase 1
approximations; they are not universal architecture truth.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reveng.platform.capabilities import (
    CapabilityContext,
    CapabilityContract,
    CapabilityDefinition,
    CapabilityRegistry,
)
from reveng.analysis_engine.meaning.confidence import ConfidenceLevel
from reveng.analysis_engine.meaning.derivation import DerivationBasis
from reveng.analysis_engine.meaning.dimensions import DimensionID
from reveng.analysis_engine.meaning.records import AbilityRecord, to_dict
from reveng.analysis_engine.agentic.tasks.functions import (
    _build_evidence_ref,
    _build_file_index,
    _calls_in_file,
    _classes_in_file,
    _decorators_in_file,
    _generate_id,
    _make_derivation,
    _side_effects_text,
)

PACK_ID = "reveng.pack.meaning_layer"
KIND = "meaning.ability_records.v1"


# ---------------------------------------------------------------------------
# Phase 1 Python-specific pattern table
# Each entry: (match_fn, ability_id, label, dimension, default_basis)
# ---------------------------------------------------------------------------

def _ends_with(called_name: str, suffix: str) -> bool:
    return called_name == suffix or called_name.endswith("." + suffix)


def _starts_with_any(called_name: str, prefixes: tuple[str, ...]) -> bool:
    return any(called_name == p or called_name.startswith(p + ".") for p in prefixes)


_CALL_PATTERNS: list[tuple[Any, str, str, DimensionID, DerivationBasis]] = [
    # (match_fn, ability_id, label, dimension, basis)
    (lambda n: n == "print",
     "can_emit_text_output", "can emit text output",
     DimensionID.OUTPUT_GENERATION, DerivationBasis.DIRECT_CALL_PATTERN),

    (lambda n: n == "input",
     "can_accept_user_input", "can accept user input",
     DimensionID.INPUT_HANDLING, DerivationBasis.DIRECT_CALL_PATTERN),

    # File I/O: open(), Path.read_text/write_text/read_bytes/write_bytes
    (lambda n: (
        n == "open" or _ends_with(n, "open")
        or _ends_with(n, "read_text") or _ends_with(n, "write_text")
        or _ends_with(n, "read_bytes") or _ends_with(n, "write_bytes")
    ),
     "can_read_or_write_file", "can read or write files",
     DimensionID.INPUT_HANDLING, DerivationBasis.DIRECT_CALL_PATTERN),

    # Structured data writing: json.dump, json.dumps, yaml.dump, yaml.dumps
    (lambda n: (
        n in ("json.dump", "json.dumps", "yaml.dump", "yaml.dumps")
        or n.startswith("json.dump.") or n.startswith("yaml.dump.")
    ),
     "can_write_structured_data", "can write structured data (JSON/YAML)",
     DimensionID.OUTPUT_GENERATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Structured data reading: json.load, json.loads, yaml variants
    (lambda n: any(n == x or n.startswith(x) for x in ("json.load", "json.loads", "yaml.safe_load", "yaml.load")),
     "can_read_structured_data", "can read structured data (JSON/YAML)",
     DimensionID.INPUT_HANDLING, DerivationBasis.DIRECT_CALL_PATTERN),

    # CSV I/O
    (lambda n: any(n == x or n.startswith(x + ".") for x in ("csv.reader", "csv.writer", "csv.DictReader", "csv.DictWriter")),
     "can_read_write_csv", "can read or write CSV data",
     DimensionID.INPUT_HANDLING, DerivationBasis.DIRECT_CALL_PATTERN),

    # HTTP (sync) — requests, urllib, urllib3
    (lambda n: (
        _starts_with_any(n, ("requests.get", "requests.post", "requests.put", "requests.delete",
                              "requests.patch", "requests.request", "requests.Session"))
        or n.startswith("urllib.request.") or n.startswith("urllib3.")
        or _ends_with(n, "urlopen")
    ),
     "can_make_http_requests", "can make HTTP requests",
     DimensionID.INTEGRATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # HTTP (async) — aiohttp, httpx async client
    (lambda n: n.startswith("aiohttp.") or (n.startswith("httpx.") and "Async" in n),
     "can_make_async_http_requests", "can make async HTTP requests",
     DimensionID.INTEGRATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Subprocess execution
    (lambda n: (
        n.startswith("subprocess.") or _ends_with(n, "Popen")
        or n.startswith("os.system") or n.startswith("os.popen")
    ),
     "can_run_subprocess", "can run subprocesses or shell commands",
     DimensionID.INTEGRATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Messaging
    (lambda n: _ends_with(n, "send") or _ends_with(n, "send_message"),
     "can_send_message", "can send a message",
     DimensionID.COMMUNICATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Database read — ORM sessions, raw cursors, SQLite, MongoDB, Redis reads
    (lambda n: (
        _starts_with_any(n, ("Session.query", "db.execute", "cursor.execute", "session.execute",
                              "conn.execute", "engine.execute", "engine.connect"))
        or n in ("sqlite3.connect",)
        or _ends_with(n, "find_one") or _ends_with(n, "find_many") or _ends_with(n, "aggregate")
        or _ends_with(n, "fetchone") or _ends_with(n, "fetchall") or _ends_with(n, "fetchmany")
        or n.startswith("pymongo.") or n.startswith("motor.")
        or _ends_with(n, "hget") or _ends_with(n, "lrange") or _ends_with(n, "smembers")
        or _ends_with(n, "zrange") or _ends_with(n, "zscore")
    ),
     "can_query_database", "can query a database",
     DimensionID.PERSISTENCE, DerivationBasis.DIRECT_CALL_PATTERN),

    # Database write — ORM commits, bulk writes, MongoDB mutations, Redis writes
    (lambda n: (
        _starts_with_any(n, ("Session.add", "db.commit", "session.commit", "session.add",
                              "session.flush", "session.merge", "session.bulk_save"))
        or _ends_with(n, "insert_one") or _ends_with(n, "insert_many")
        or _ends_with(n, "update_one") or _ends_with(n, "update_many") or _ends_with(n, "replace_one")
        or _ends_with(n, "delete_one") or _ends_with(n, "delete_many")
        or _ends_with(n, "hset") or _ends_with(n, "hmset") or _ends_with(n, "lpush")
        or _ends_with(n, "rpush") or _ends_with(n, "sadd") or _ends_with(n, "zadd")
    ),
     "can_write_database", "can write to a database",
     DimensionID.PERSISTENCE, DerivationBasis.DIRECT_CALL_PATTERN),

    # Object serialization
    (lambda n: n.startswith("pickle.") or n.startswith("shelve."),
     "can_serialize_objects", "can serialize Python objects",
     DimensionID.PERSISTENCE, DerivationBasis.DIRECT_CALL_PATTERN),

    # Configuration reading: env vars, configparser, dotenv, decouple, dynaconf
    (lambda n: (
        n.startswith("os.getenv") or n.startswith("os.environ")
        or n.startswith("configparser") or n.startswith("dotenv.")
        or _ends_with(n, "load_dotenv")
        or n.startswith("decouple.") or n == "config"
        or n.startswith("dynaconf.") or n.startswith("environ.")
    ),
     "can_read_configuration", "can read configuration",
     DimensionID.CONFIGURATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # CLI argument parsing
    (lambda n: (
        n.startswith("argparse.") or n.startswith("click.")
        or n.startswith("typer.") or n.startswith("optparse.")
    ),
     "can_parse_cli_arguments", "can parse CLI arguments",
     DimensionID.INPUT_HANDLING, DerivationBasis.DIRECT_CALL_PATTERN),

    # Regex / pattern matching
    (lambda n: n.startswith("re.") and any(n.startswith(f"re.{m}") for m in ("compile", "match", "search", "findall", "finditer", "sub", "split", "fullmatch")),
     "can_match_patterns", "can match text patterns with regex",
     DimensionID.TRANSFORMATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Hashing / crypto
    (lambda n: n.startswith("hashlib.") or n.startswith("hmac.") or n.startswith("secrets."),
     "can_compute_hash", "can compute hashes or cryptographic values",
     DimensionID.SECURITY, DerivationBasis.DIRECT_CALL_PATTERN),

    # Filesystem management (create/delete dirs and files beyond open())
    (lambda n: (
        _ends_with(n, "mkdir") or n.startswith("os.makedirs") or n.startswith("os.mkdir")
        or n.startswith("os.remove") or n.startswith("os.unlink") or n.startswith("os.rename")
        or n.startswith("shutil.") or _ends_with(n, "rmdir") or _ends_with(n, "unlink")
        or _ends_with(n, "rename") or _ends_with(n, "symlink")
    ),
     "can_manage_filesystem", "can create, move, or delete filesystem entries",
     DimensionID.PERSISTENCE, DerivationBasis.DIRECT_CALL_PATTERN),

    # Concurrency
    (lambda n: (
        n.startswith("threading.") or n.startswith("multiprocessing.")
        or n.startswith("asyncio.create_task") or n.startswith("asyncio.gather")
        or n.startswith("asyncio.run") or n.startswith("concurrent.futures")
    ),
     "can_run_concurrently", "can run work concurrently",
     DimensionID.SCHEDULING, DerivationBasis.DIRECT_CALL_PATTERN),

    # Task scheduling
    (lambda n: n.startswith("asyncio.sleep") or n.startswith("schedule.") or n.startswith("apscheduler."),
     "can_schedule_tasks", "can schedule or defer tasks",
     DimensionID.SCHEDULING, DerivationBasis.DIRECT_CALL_PATTERN),

    # Logging
    (lambda n: (
        n.startswith("logging.") or _ends_with(n, "logger.info")
        or _ends_with(n, "logger.debug") or _ends_with(n, "logger.error")
        or _ends_with(n, "logger.warning") or _ends_with(n, "logger.critical")
        or _ends_with(n, "log.info") or _ends_with(n, "log.debug")
        or _ends_with(n, "log.error") or _ends_with(n, "log.warning")
    ),
     "can_emit_log_output", "can emit log output",
     DimensionID.OUTPUT_GENERATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Raw sockets
    (lambda n: n.startswith("socket."),
     "can_use_raw_sockets", "can use raw network sockets",
     DimensionID.INTEGRATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Authentication / authorization — JWT, bcrypt, passlib, itsdangerous, werkzeug, cryptography
    (lambda n: (
        n.startswith("jwt.") or n.startswith("jose.")
        or n.startswith("bcrypt.") or n.startswith("passlib.")
        or n.startswith("itsdangerous.") or n.startswith("cryptography.")
        or _ends_with(n, "generate_password_hash") or _ends_with(n, "check_password_hash")
        or _ends_with(n, "hashpw") or _ends_with(n, "checkpw") or _ends_with(n, "gensalt")
        or _ends_with(n, "encode_token") or _ends_with(n, "decode_token")
        or _ends_with(n, "verify_password") or _ends_with(n, "get_password_hash")
    ),
     "can_authenticate_or_authorize", "can authenticate or authorize",
     DimensionID.SECURITY, DerivationBasis.DIRECT_CALL_PATTERN),

    # Email sending — smtplib, email constructors, sendgrid
    (lambda n: (
        n.startswith("smtplib.") or n.startswith("email.mime.")
        or _ends_with(n, "sendmail") or _ends_with(n, "send_email")
        or n.startswith("sendgrid.") or n.startswith("mailchimp.")
    ),
     "can_send_email", "can send email",
     DimensionID.COMMUNICATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Template rendering — Jinja2, Flask render_template, Mako
    (lambda n: (
        n.startswith("jinja2.") or _ends_with(n, "render_template")
        or _ends_with(n, "render_to_string") or _ends_with(n, "get_template")
        or n.startswith("mako.") or n.startswith("chameleon.")
    ),
     "can_render_template", "can render templates",
     DimensionID.OUTPUT_GENERATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Queue / message passing — stdlib queue, asyncio.Queue, celery tasks, pika/kombu
    (lambda n: (
        n.startswith("queue.") or n.startswith("asyncio.Queue")
        or n.startswith("pika.") or n.startswith("kombu.")
        or _ends_with(n, "apply_async") or _ends_with(n, "enqueue") or _ends_with(n, "dequeue")
        or _ends_with(n, "publish_message") or _ends_with(n, "consume")
        or n.startswith("celery.")
    ),
     "can_publish_or_consume_queue", "can publish or consume from a queue",
     DimensionID.SCHEDULING, DerivationBasis.DIRECT_CALL_PATTERN),

    # Data validation — jsonschema, cerberus, voluptuous; marshmallow schema ops
    (lambda n: (
        n.startswith("jsonschema.") or n.startswith("cerberus.")
        or n.startswith("voluptuous.") or n.startswith("marshmallow.")
        or _ends_with(n, "validate") or _ends_with(n, "schema.load") or _ends_with(n, "schema.dump")
    ),
     "can_validate_data", "can validate data against a schema",
     DimensionID.TRANSFORMATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Caching / memoization — functools cache, cachetools, dogpile, beaker
    (lambda n: (
        n.startswith("functools.lru_cache") or n.startswith("functools.cache")
        or n.startswith("cachetools.") or n.startswith("dogpile.")
        or n.startswith("beaker.") or _ends_with(n, "cache.set") or _ends_with(n, "cache.get")
        or _ends_with(n, "setex") or _ends_with(n, "expire")
    ),
     "can_cache_data", "can cache or memoize data",
     DimensionID.STATE_MANAGEMENT, DerivationBasis.DIRECT_CALL_PATTERN),

    # Functional pipeline composition — functools.reduce / reduce
    (lambda n: n in ("functools.reduce", "reduce"),
     "can_transform_data", "can transform data via functional pipeline composition",
     DimensionID.TRANSFORMATION, DerivationBasis.DIRECT_CALL_PATTERN),

    # Exception handling / error recovery — contextlib.suppress, explicit retry patterns
    (lambda n: (
        n.startswith("contextlib.suppress") or n.startswith("tenacity.")
        or n.startswith("retry.") or _ends_with(n, "retry") or _ends_with(n, "backoff")
    ),
     "can_recover_from_errors", "can recover from or suppress errors",
     DimensionID.ERROR_HANDLING, DerivationBasis.DIRECT_CALL_PATTERN),
]

_DECORATOR_PATTERNS: list[tuple[Any, str, str, DimensionID]] = [
    (lambda t: "bot.command" in t or "app.command" in t or "tree.command" in t,
     "can_register_command", "can register a command", DimensionID.ROUTING),

    (lambda t: (
        "app.route" in t or "router.get" in t or "router.post" in t
        or "router.put" in t or "router.delete" in t or "router.patch" in t
        or "blueprint.route" in t or "app.get" in t or "app.post" in t
    ),
     "can_register_route", "can register an HTTP route", DimensionID.ROUTING),

    (lambda t: "client.event" in t or "bot.event" in t or "signal.connect" in t,
     "can_handle_events", "can handle events", DimensionID.ROUTING),

    # Celery / background task decorators
    (lambda t: "app.task" in t or "celery.task" in t or "shared_task" in t or "task(" in t,
     "can_schedule_tasks", "can schedule or defer tasks", DimensionID.SCHEDULING),

    # Auth / access control decorators
    (lambda t: (
        "login_required" in t or "require_auth" in t or "requires_auth" in t
        or "permission_required" in t or "auth_required" in t
        or "jwt_required" in t or "token_required" in t
    ),
     "can_authenticate_or_authorize", "can authenticate or authorize", DimensionID.SECURITY),

    # Test fixture / parametrize decorators
    (lambda t: (
        "pytest.fixture" in t or "@fixture" in t
        or t.strip().lstrip("@") in ("fixture",)
    ),
     "can_provide_test_fixtures", "can provide test fixtures", DimensionID.INPUT_HANDLING),

    (lambda t: "pytest.mark.parametrize" in t or "mark.parametrize" in t,
     "can_parametrize_tests", "can parametrize test cases", DimensionID.INPUT_HANDLING),

    # Context manager decorator
    (lambda t: (
        "contextmanager" in t and "@" in t
        or "contextlib.contextmanager" in t
    ),
     "can_manage_context", "can manage a context or resource lifecycle", DimensionID.STATE_MANAGEMENT),

    # Data model decorator (dataclass / attrs)
    (lambda t: (
        t.strip().lstrip("@").startswith("dataclass")
        or "attrs.define" in t or "attr.s(" in t or "attr.attrs(" in t
    ),
     "can_model_data", "can model structured data", DimensionID.TRANSFORMATION),

    # ASGI/WSGI lifecycle events
    (lambda t: "on_event" in t or "lifespan" in t or "startup" in t or "shutdown" in t,
     "can_handle_lifecycle_events", "can handle application lifecycle events", DimensionID.ROUTING),
]


# ---------------------------------------------------------------------------
# Import-based inference patterns (Phase 5)
# Each entry: (top_module_match_fn, ability_id, label, dimension)
# match_fn receives the top-level module name (first dot-component of the import path).
# These fire at file scope with inferred=True / LOW confidence.
# They do not override or downgrade abilities already established by call-site evidence.
#
# Omissions by design:
#   - stdlib modules (logging, argparse, sqlite3, json, os) are omitted — too broad;
#     the call-pattern passes already handle the specific operations that matter.
#   - Modules where a direct call pattern already provides MEDIUM+ evidence on the
#     same ability_id are still included here to add file-scope provenance for
#     files that import but only call indirectly.
# ---------------------------------------------------------------------------

_IMPORT_PATTERNS: list[tuple[Any, str, str, DimensionID]] = [
    # ORM / database drivers (non-stdlib) — call patterns cover specific ops,
    # imports cover files that set up engines/sessions but don't query directly
    (lambda m: m in ("sqlalchemy", "psycopg2", "psycopg", "pymongo", "motor",
                     "peewee", "tortoise", "databases", "asyncpg", "aiopg",
                     "aiomysql", "pymysql", "cx_Oracle", "pyodbc"),
     "can_query_database", "can query a database",
     DimensionID.PERSISTENCE),

    # Web frameworks — import alone signals HTTP-serving intent
    (lambda m: m in ("flask", "fastapi", "django", "starlette", "tornado",
                     "bottle", "falcon", "sanic", "quart", "litestar", "aiohttp"),
     "can_serve_http_requests", "can serve HTTP requests",
     DimensionID.ROUTING),

    # Auth / security libraries
    (lambda m: m in ("jwt", "jose", "bcrypt", "passlib", "itsdangerous",
                     "cryptography", "authlib", "python_jose", "oauthlib"),
     "can_authenticate_or_authorize", "can authenticate or authorize",
     DimensionID.SECURITY),

    # Cloud-service SDKs
    (lambda m: m in ("boto3", "botocore", "azure", "google", "gcloud",
                     "digitalocean", "linode_api4", "vultr"),
     "can_integrate_with_cloud_services", "can integrate with cloud services",
     DimensionID.INTEGRATION),

    # Distributed task queues
    (lambda m: m in ("celery", "dramatiq", "rq", "huey", "arq", "apscheduler"),
     "can_schedule_tasks", "can schedule or defer tasks",
     DimensionID.SCHEDULING),

    # Message-broker clients
    (lambda m: m in ("pika", "kombu", "kafka", "confluent_kafka",
                     "nats", "aio_pika", "aiokafka", "redis"),
     "can_publish_or_consume_queue", "can publish or consume from a queue",
     DimensionID.SCHEDULING),

    # Data-validation frameworks
    (lambda m: m in ("pydantic", "marshmallow", "cerberus", "voluptuous",
                     "wtforms", "schematics", "attrs"),
     "can_validate_data", "can validate data against a schema",
     DimensionID.TRANSFORMATION),

    # Data analysis / transformation
    (lambda m: m in ("pandas", "numpy", "polars", "scipy", "sklearn",
                     "scikit_learn", "pyarrow", "dask", "numba", "xarray"),
     "can_transform_data", "can transform or analyze data",
     DimensionID.TRANSFORMATION),

    # Structured logging (stdlib logging omitted — too broad)
    (lambda m: m in ("structlog", "loguru", "logbook"),
     "can_emit_log_output", "can emit log output",
     DimensionID.OUTPUT_GENERATION),

    # CLI frameworks (non-stdlib; argparse is omitted — call patterns cover it)
    (lambda m: m in ("click", "typer", "fire", "docopt", "plumbum", "rich"),
     "can_parse_cli_arguments", "can parse CLI arguments",
     DimensionID.INPUT_HANDLING),
]


# Class base patterns: (bases_match_fn, ability_id, label, dimension)
# bases_match_fn receives a set of base class name strings
_CLASS_BASE_PATTERNS: list[tuple[Any, str, str, DimensionID]] = [
    # Abstract interface / protocol definitions
    (lambda bases: bool(bases & {"ABC", "ABCMeta"}),
     "can_define_interface", "can define an abstract interface (ABC)", DimensionID.INTEGRATION),

    (lambda bases: "Protocol" in bases,
     "can_define_interface", "can define an abstract interface (Protocol)", DimensionID.INTEGRATION),

    # Custom exception hierarchy
    (lambda bases: bool(bases & {"Exception", "BaseException", "RuntimeError",
                                  "ValueError", "TypeError", "OSError", "IOError"}),
     "can_raise_custom_exceptions", "can raise custom exception types", DimensionID.ERROR_HANDLING),

    # Pydantic / marshmallow data validation model
    (lambda bases: bool(bases & {"BaseModel", "BaseSettings", "Schema", "SQLModel"}),
     "can_validate_data", "can validate and parse structured data", DimensionID.INPUT_HANDLING),

    # CLI command group
    (lambda bases: bool(bases & {"Command", "Group", "BaseCommand", "AppGroup"}),
     "can_register_command", "can register a CLI command", DimensionID.ROUTING),
]


# ---------------------------------------------------------------------------
# Core extraction logic
# ---------------------------------------------------------------------------

def _extract_dynamic_abilities(
    file_path: str,
    file_record: dict[str, Any],
    accumulator: dict[str, dict[str, Any]],
) -> None:
    """Dynamic dispatch ability inference pass (Phase 7).

    Detects registry/callback patterns that are invisible to call-site matching:
    - Subscript-target assignments with callable values (e.g. REGISTRY[name] = fn)
      indicate handler registration → can_dispatch_to_stored_handlers.

    Marked inferred=True + STRUCTURAL_INFERENCE (structural pattern, not a call).
    One evidence_ref per unique assignment site within the file.
    """
    assignments = file_record.get("assignments", [])

    for asn in assignments:
        targets = asn.get("targets", [])
        value_type = asn.get("value_type", "")
        # Subscript target (X[k] = ...) with a callable-like value type
        if value_type not in ("Name", "Lambda", "Call", "Function"):
            continue
        for target in targets:
            if "[" not in target:
                continue

            ability_id = "can_dispatch_to_stored_handlers"
            lineno: int = asn.get("lineno", 0)
            scope: str = asn.get("enclosing_scope", "module")
            evidence_ref = _build_evidence_ref(
                file_path, scope, lineno, f"{target} = <{value_type}>"
            )
            if ability_id not in accumulator:
                accumulator[ability_id] = {
                    "ability_id": ability_id,
                    "label": "can dispatch to stored handlers",
                    "dimension": DimensionID.ROUTING,
                    "evidence_refs": [],
                    "confidence": ConfidenceLevel.LOW,
                    "inferred": True,
                    "source_files": [],
                    "basis": DerivationBasis.STRUCTURAL_INFERENCE,
                    "best_confidence": ConfidenceLevel.LOW,
                }
            entry = accumulator[ability_id]
            entry["evidence_refs"].append(evidence_ref)
            if file_path not in entry["source_files"]:
                entry["source_files"].append(file_path)
            break  # one evidence_ref per assignment statement


def _extract_import_abilities(
    file_path: str,
    file_record: dict[str, Any],
    accumulator: dict[str, dict[str, Any]],
) -> None:
    """Import-based ability inference pass (Phase 5).

    Matches top-level import module names against _IMPORT_PATTERNS and adds
    LOW-confidence / inferred=True ability entries to the accumulator.

    Rules:
    - If the ability_id is already in the accumulator (from call-site or decorator
      evidence), the import only adds an additional evidence_ref and source_file;
      it never downgrades confidence or changes inferred=False to True.
    - One evidence_ref per (file, ability_id) to avoid evidence inflation from
      files that import the same top-level package multiple times.
    """
    imports = file_record.get("imports", [])
    seen: set[str] = set()  # (ability_id,) dedup within this file

    for imp in imports:
        module: str = imp.get("module", "") or ""
        if not module:
            continue
        top_module = module.split(".")[0]

        for match_fn, ability_id, label, dimension in _IMPORT_PATTERNS:
            if not match_fn(top_module):
                continue
            if ability_id in seen:
                break
            seen.add(ability_id)

            lineno: int = imp.get("lineno", 0)
            evidence_ref = _build_evidence_ref(
                file_path, "module", lineno, f"import {module}"
            )

            if ability_id not in accumulator:
                accumulator[ability_id] = {
                    "ability_id": ability_id,
                    "label": label,
                    "dimension": dimension,
                    "evidence_refs": [],
                    "confidence": ConfidenceLevel.LOW,
                    "inferred": True,
                    "source_files": [],
                    "basis": DerivationBasis.IMPORT_INFERENCE,
                    "best_confidence": ConfidenceLevel.LOW,
                }
            entry = accumulator[ability_id]
            entry["evidence_refs"].append(evidence_ref)
            if file_path not in entry["source_files"]:
                entry["source_files"].append(file_path)
            break  # one pattern matched per import statement


def _extract_abilities(
    enriched: dict[str, Any],
    _relation_map: dict[str, Any],
) -> list[AbilityRecord]:
    """Phase 1 Python-specific ability extraction from enriched breakdowns."""

    # ability_id -> {record fields being accumulated}
    accumulator: dict[str, dict[str, Any]] = {}

    file_index = _build_file_index(enriched)

    for file_path, file_record in file_index.items():
        if "parse_error" in file_record:
            continue

        side_effects = _side_effects_text(file_record)

        # ---- Call-pattern matching ----
        for call in _calls_in_file(file_record):
            called_name: str = call.get("called_name", "")
            scope: str = call.get("enclosing_scope", "<module>")
            lineno: int = call.get("lineno", 0)

            for match_fn, ability_id, label, dimension, basis in _CALL_PATTERNS:
                if not match_fn(called_name):
                    continue

                # Confidence: HIGH if this call appears in observed_side_effects
                # (side effects are string descriptions containing called_name)
                is_side_effect = any(called_name in se for se in side_effects)
                confidence = ConfidenceLevel.HIGH if is_side_effect else ConfidenceLevel.MEDIUM

                evidence_ref = _build_evidence_ref(file_path, scope, lineno, called_name)

                if ability_id not in accumulator:
                    accumulator[ability_id] = {
                        "ability_id": ability_id,
                        "label": label,
                        "dimension": dimension,
                        "evidence_refs": [],
                        "confidence": confidence,
                        "inferred": False,
                        "source_files": [],
                        "basis": basis,
                        "best_confidence": confidence,
                    }
                entry = accumulator[ability_id]
                entry["evidence_refs"].append(evidence_ref)
                if file_path not in entry["source_files"]:
                    entry["source_files"].append(file_path)
                # Upgrade confidence if we found a higher one
                if confidence == ConfidenceLevel.HIGH:
                    entry["best_confidence"] = ConfidenceLevel.HIGH
                break  # one pattern per call

        # ---- Decorator-pattern matching ----
        for dec in _decorators_in_file(file_record):
            text: str = dec.get("text", "")
            scope: str = dec.get("enclosing_scope", "<module>")
            lineno: int = dec.get("lineno", 0)

            for match_fn, ability_id, label, dimension in _DECORATOR_PATTERNS:
                if not match_fn(text):
                    continue

                evidence_ref = _build_evidence_ref(file_path, scope, lineno, text)
                if ability_id not in accumulator:
                    accumulator[ability_id] = {
                        "ability_id": ability_id,
                        "label": label,
                        "dimension": dimension,
                        "evidence_refs": [],
                        "confidence": ConfidenceLevel.LOW,
                        "inferred": True,
                        "source_files": [],
                        "basis": DerivationBasis.DECORATOR_INFERENCE,
                        "best_confidence": ConfidenceLevel.LOW,
                    }
                entry = accumulator[ability_id]
                entry["evidence_refs"].append(evidence_ref)
                if file_path not in entry["source_files"]:
                    entry["source_files"].append(file_path)
                break

        # ---- Class hierarchy evidence ----
        for cls in _classes_in_file(file_record):
            bases_set: set[str] = set(cls.get("bases", []))
            if not bases_set:
                continue
            class_name: str = cls.get("name", "")
            class_scope: str = cls.get("enclosing_scope", "module")
            lineno: int = cls.get("lineno", 0)
            # Build a synthetic "evidence" label
            bases_text = f"class {class_name}({', '.join(sorted(bases_set))})"
            evidence_ref = _build_evidence_ref(file_path, class_scope, lineno, bases_text)

            for match_fn, ability_id, label, dimension in _CLASS_BASE_PATTERNS:
                if not match_fn(bases_set):
                    continue

                if ability_id not in accumulator:
                    accumulator[ability_id] = {
                        "ability_id": ability_id,
                        "label": label,
                        "dimension": dimension,
                        "evidence_refs": [],
                        "confidence": ConfidenceLevel.MEDIUM,
                        "inferred": False,
                        "source_files": [],
                        "basis": DerivationBasis.STRUCTURAL_INFERENCE,
                        "best_confidence": ConfidenceLevel.MEDIUM,
                    }
                entry = accumulator[ability_id]
                entry["evidence_refs"].append(evidence_ref)
                if file_path not in entry["source_files"]:
                    entry["source_files"].append(file_path)
                break  # one pattern per class

        # ---- Main-block (entry-point) evidence ----
        if file_record.get("main_block_present"):
            ability_id = "has_script_entrypoint"
            evidence_ref = _build_evidence_ref(file_path, "module", 0, "__main__")
            if ability_id not in accumulator:
                accumulator[ability_id] = {
                    "ability_id": ability_id,
                    "label": "has a script entry point (if __name__ == '__main__')",
                    "dimension": DimensionID.ROUTING,
                    "evidence_refs": [],
                    "confidence": ConfidenceLevel.HIGH,
                    "inferred": False,
                    "source_files": [],
                    "basis": DerivationBasis.STRUCTURAL_INFERENCE,
                    "best_confidence": ConfidenceLevel.HIGH,
                }
            entry = accumulator[ability_id]
            entry["evidence_refs"].append(evidence_ref)
            if file_path not in entry["source_files"]:
                entry["source_files"].append(file_path)

        # ---- Dynamic dispatch inference (Phase 7) ----
        _extract_dynamic_abilities(file_path, file_record, accumulator)

        # ---- Import-based inference (Phase 5) ----
        _extract_import_abilities(file_path, file_record, accumulator)

    # Build final AbilityRecord list
    records: list[AbilityRecord] = []
    for entry in accumulator.values():
        basis: DerivationBasis = entry["basis"]
        records.append(AbilityRecord(
            ability_id=entry["ability_id"],
            label=entry["label"],
            dimension=entry["dimension"],
            evidence_refs=entry["evidence_refs"],
            confidence=entry["best_confidence"],
            inferred=entry["inferred"],
            source_files=entry["source_files"],
            derivation=_make_derivation(
                basis,
                notes=f"Phase 1 Python-specific heuristic: {entry['label']}",
            ),
        ))
    return records


# ---------------------------------------------------------------------------
# Capability handler
# ---------------------------------------------------------------------------

def ability_records_json_path(output_dir: Path) -> Path:
    return output_dir / "meaning" / "ability_records.json"


def _extract_abilities_capability(context: CapabilityContext) -> dict[str, Any]:
    path = ability_records_json_path(context.runtime.output_dir)

    if context.cache_ready(path, output_name="ability_records"):
        ref = context.load_cached_json_artifact(KIND, path, views={}, metadata={"cached": True})
        data = context.read(ref)
        return {
            "ability_records": ref,
            "ability_records_path": str(path),
            "ability_count": len(data) if isinstance(data, list) else 0,
            "cached": True,
        }

    enriched = context.read_input("enriched_file_breakdowns")
    relation_map = context.read_input("relation_map")
    records = _extract_abilities(enriched, relation_map)
    data = [to_dict(r) for r in records]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    ref = context.record_artifact(KIND, data, path=path)
    return {
        "ability_records": ref,
        "ability_records_path": str(path),
        "ability_count": len(data),
        "cached": False,
    }


def register(registry: CapabilityRegistry) -> None:
    registry.register(CapabilityDefinition(
        capability_id="meaning.abilities.extract",
        pack_id=PACK_ID,
        version="1",
        display_name="Extract Ability Records",
        description=(
            "Extract atomic ability records from enriched file breakdowns. "
            "Phase 1: Python-specific heuristics."
        ),
        capability_type="function",
        contract=CapabilityContract(
            inputs=("enriched_file_breakdowns", "relation_map"),
            output=("ability_records", "ability_records_path", "ability_count", "cached"),
        ),
        implementation_logic=_extract_abilities_capability,
        tags=("meaning", "ability"),
    ))
