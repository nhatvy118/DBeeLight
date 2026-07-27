"""Semantic Context Ablation — schema-only vs semantic-enhanced SQL generation.

Tests whether the description layer (table/column descriptions stored in
_descriptions) meaningfully improves SQL generation accuracy over structural
schema alone, using a schema with deliberately abbreviated column names.

Usage:
    cd usecase_testing/ablation
    pip install openai pandas openpyxl
    OPENAI_API_KEY=sk-... python run_ablation.py [--out results.json]

The script:
  1. Builds an in-memory SQLite DB from ablation_schema.sql + seed data.
  2. Populates _descriptions from setup_descriptions.sql (semantic condition).
  3. For each prompt, calls the LLM twice with the same question:
       - schema_only : structural text only (no descriptions)
       - semantic    : structural text + descriptions from _descriptions
  4. Executes both generated SQLs and compares results.
  5. Grades each as Success / Fail and prints a summary table.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import openai

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ablation")

HERE = Path(__file__).parent
SCHEMA_SQL    = HERE / "ablation_schema.sql"
DESC_SQL      = HERE / "setup_descriptions.sql"
PROMPTS_FILE  = HERE / "ablation_prompts.json"

MODEL             = os.getenv("ABLATION_MODEL", "gpt-4o-mini")
MAX_REPAIR        = 3
SEED_DATA_FILE    = HERE / "seed_data.json"   # optional hand-crafted seed; see below


# ─────────────────────────────────────────────────────────────────────────────
# Database setup
# ─────────────────────────────────────────────────────────────────────────────

def _sql_statements(path: Path) -> list[str]:
    """Split a SQL file into individual statements, stripping -- comments first."""
    lines = []
    for line in path.read_text().splitlines():
        # strip inline/full-line comments
        stripped = re.sub(r"--.*$", "", line)
        lines.append(stripped)
    text = "\n".join(lines)
    return [s.strip() for s in text.split(";") if s.strip()]


def build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row

    for stmt in _sql_statements(SCHEMA_SQL):
        try:
            conn.execute(stmt)
        except Exception as e:
            log.debug("Schema stmt skipped (%s): %.80s", e, stmt)
    conn.commit()

    for stmt in _sql_statements(DESC_SQL):
        try:
            conn.execute(stmt)
        except Exception as e:
            log.debug("Desc stmt skipped (%s): %.80s", e, stmt)
    conn.commit()

    _insert_seed(conn)
    conn.commit()
    return conn


def _insert_seed(conn: sqlite3.Connection) -> None:
    """Insert minimal seed data so SQL queries actually return rows."""
    stmts = [
        # categories
        "INSERT INTO cats VALUES (1,'Electronics',NULL),(2,'Phones',1),(3,'Laptops',1),(4,'Fashion',NULL),(5,'Shoes',4)",
        # customers
        "INSERT INTO custs(id,cust_nm,email,city) VALUES (1,'Alice Nguyen','alice@x.vn','HCMC'),(2,'Bob Tran','bob@x.vn','Hanoi'),(3,'Carol Le','carol@x.vn','HCMC')",
        # suppliers
        "INSERT INTO sups(id,name,country) VALUES (1,'TechVN','Vietnam'),(2,'GlobalTech','USA')",
        # products
        "INSERT INTO prods(id,name,prc,inv_qty,cat_id) VALUES (1,'iPhone 15',20000000,10,2),(2,'MacBook Pro',35000000,5,3),(3,'Nike Air',2000000,0,5),(4,'Samsung S24',18000000,8,2)",
        # product_suppliers
        "INSERT INTO prod_sup VALUES (1,1,15000000),(1,2,14500000),(2,1,28000000),(3,1,1200000),(4,2,13000000)",
        # orders  (sts_cd: P=pending, P2=paid, S=shipped, C=cancelled)
        "INSERT INTO ords(id,cust_id,sts_cd,ord_amt,crt_ts) VALUES (1,1,'S',20000000,'2026-05-10'),(2,2,'P2',35000000,'2026-06-01'),(3,3,'P',2000000,'2026-06-15'),(4,1,'C',18000000,'2026-04-20'),(5,2,'S',20000000,'2026-06-18')",
        # order_lines
        "INSERT INTO ord_lines(ord_id,prod_id,qty,u_prc) VALUES (1,1,1,20000000),(2,2,1,35000000),(3,3,1,2000000),(4,4,1,18000000),(5,1,1,20000000)",
        # reviews
        "INSERT INTO rvws(cust_id,prod_id,cust_rtg,cmt) VALUES (1,1,5,'Great!'),(2,2,4,'Good laptop'),(3,3,2,'Poor quality'),(1,4,3,'Average')",
    ]
    for s in stmts:
        try:
            conn.execute(s)
        except Exception as e:
            log.debug("Seed skipped (%s): %.80s", e, s)


# ─────────────────────────────────────────────────────────────────────────────
# Schema rendering — mirrors backend/app/agent/graph/schema_context.py
# ─────────────────────────────────────────────────────────────────────────────

def _raw_schema(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    # Use a fresh connection without row_factory for PRAGMA queries
    raw = sqlite3.connect(":memory:")
    conn.backup(raw)
    tables: dict[str, list[dict]] = {}
    cur = raw.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND SUBSTR(name,1,1) != '_' ORDER BY name"
    )
    for row in cur.fetchall():
        tbl = row[0]
        cols = []
        for r in raw.execute(f"PRAGMA table_info('{tbl}')"):
            cols.append({"name": r[1], "type": r[2], "pk": bool(r[5]),
                         "notnull": bool(r[3]), "fk": None})
        for r in raw.execute(f"PRAGMA foreign_key_list('{tbl}')"):
            ref_tbl, from_col, to_col = r[2], r[3], r[4]
            for c in cols:
                if c["name"] == from_col:
                    c["fk"] = f"{ref_tbl}({to_col})"
        tables[tbl] = cols
    raw.close()
    return tables


def _load_descriptions(conn: sqlite3.Connection) -> tuple[dict[str, str], dict[tuple, dict]]:
    """Return (tbl_desc, col_desc) from _descriptions — same shape as metadata_repo.get_for_scope."""
    tbl: dict[str, str] = {}
    col: dict[tuple[str, str], dict] = {}
    for row in conn.execute("SELECT table_name, column_name, description, enum_values FROM _descriptions"):
        tname, cname, desc, enum_raw = row
        enum = json.loads(enum_raw) if enum_raw else None
        if cname == "":          # table-level (we use '' instead of NULL for SQLite PK compat)
            tbl[tname] = desc
        else:
            col[(tname, cname)] = {"desc": desc, "enum": enum}
    return tbl, col


def render_schema_only(schema: dict[str, list[dict]]) -> str:
    lines = []
    for tbl, cols in schema.items():
        segs = []
        for c in cols:
            seg = f"{c['name']} {c['type']}"
            if c["pk"]:
                seg += " PK"
            elif c["notnull"]:
                seg += " NOT NULL"
            if c["fk"]:
                seg += f" → {c['fk']}"
            segs.append(seg)
        lines.append(f"{tbl}(" + ", ".join(segs) + ")")
    return "\n".join(lines)


def render_schema_semantic(
    schema: dict[str, list[dict]],
    tbl_desc: dict[str, str],
    col_desc: dict[tuple[str, str], dict],
) -> str:
    lines = []
    for tbl, cols in schema.items():
        segs = []
        for c in cols:
            seg = f"{c['name']} {c['type']}"
            if c["pk"]:
                seg += " PK"
            elif c["notnull"]:
                seg += " NOT NULL"
            if c["fk"]:
                seg += f" → {c['fk']}"
            meta = col_desc.get((tbl, c["name"]))
            if meta:
                if meta.get("enum"):
                    seg += f" [{', '.join(str(v) for v in meta['enum'])}]"
                if meta.get("desc"):
                    seg += f" — {meta['desc']}"
            segs.append(seg)
        header = tbl + (f" — {tbl_desc[tbl]}" if tbl in tbl_desc else "")
        lines.append(header + "(" + ", ".join(segs) + ")")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SQL generation
# ─────────────────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
    return re.sub(r"\n?```$", "", t).strip()


def generate_sql(prompt: str, schema_text: str, client: openai.OpenAI) -> str:
    system = (
        "Generate a single read-only SQLite SELECT query to answer the question. "
        "Use ONLY tables and columns that appear in the schema below. "
        "Return SQL only, no explanation.\n"
        f"Schema:\n{schema_text}"
    )
    msgs: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": prompt},
    ]
    for _ in range(MAX_REPAIR):
        resp = client.chat.completions.create(
            model=MODEL, messages=msgs, temperature=0  # type: ignore[arg-type]
        )
        sql = _strip_fences(resp.choices[0].message.content or "")
        if sql:
            return sql
        msgs += [
            {"role": "assistant", "content": sql},
            {"role": "user", "content":
             "You returned no SQL. Re-check the schema (column names may differ from the question) "
             "and return only a SELECT query."},
        ]
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Execution
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    sql: str
    rows: list[Any] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.rows is not None


def execute_sql(conn: sqlite3.Connection, sql: str) -> RunResult:
    if not sql:
        return RunResult(sql="", error="No SQL generated")
    upper = sql.strip().upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return RunResult(sql=sql, error="Non-SELECT rejected")
    try:
        cur = conn.execute(sql)
        return RunResult(sql=sql, rows=[tuple(r) for r in cur.fetchall()])
    except Exception as e:
        return RunResult(sql=sql, error=str(e))


def _rows_equal(a: list | None, b: list | None) -> bool:
    if a is None or b is None:
        return False
    return sorted(str(r) for r in a) == sorted(str(r) for r in b)


# ─────────────────────────────────────────────────────────────────────────────
# Per-prompt runner
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PromptResult:
    id: int
    prompt: str
    ambiguous: list[str]
    schema_only_sql: str
    semantic_sql: str
    schema_only_ok: bool
    semantic_ok: bool
    schema_only_err: str
    semantic_err: str
    results_differ: bool
    semantic_wins: bool
    both_fail: bool

    def as_dict(self) -> dict:
        return asdict(self)


def run_prompt(
    item: dict,
    conn: sqlite3.Connection,
    schema_only_text: str,
    semantic_text: str,
    client: openai.OpenAI,
) -> PromptResult:
    prompt = item["prompt"]
    log.info("[%02d] %s", item["id"], prompt[:75])

    sql_only = generate_sql(prompt, schema_only_text, client)
    sql_sem  = generate_sql(prompt, semantic_text,    client)

    res_only = execute_sql(conn, sql_only)
    res_sem  = execute_sql(conn, sql_sem)

    differ       = not _rows_equal(res_only.rows, res_sem.rows)
    sem_wins     = res_sem.ok and not res_only.ok
    both_fail    = not res_only.ok and not res_sem.ok

    log.info("     schema_only=%s  semantic=%s  differ=%s",
             "OK" if res_only.ok else "FAIL",
             "OK" if res_sem.ok  else "FAIL",
             differ)

    return PromptResult(
        id=item["id"],
        prompt=prompt,
        ambiguous=item.get("ambiguous", []),
        schema_only_sql=sql_only,
        semantic_sql=sql_sem,
        schema_only_ok=res_only.ok,
        semantic_ok=res_sem.ok,
        schema_only_err=res_only.error or "",
        semantic_err=res_sem.error or "",
        results_differ=differ,
        semantic_wins=sem_wins,
        both_fail=both_fail,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(results: list[PromptResult]) -> None:
    n          = len(results)
    so_ok      = sum(r.schema_only_ok for r in results)
    sem_ok     = sum(r.semantic_ok    for r in results)
    sem_wins   = sum(r.semantic_wins  for r in results)
    both_fail  = sum(r.both_fail      for r in results)
    differ     = sum(r.results_differ for r in results)

    bar = "=" * 62
    print(f"\n{bar}")
    print(f"{'ABLATION RESULTS':^62}")
    print(bar)
    print(f"  Total prompts            : {n}")
    print(f"  Schema-only  success     : {so_ok}/{n}  ({100*so_ok/n:.1f}%)")
    print(f"  Semantic     success     : {sem_ok}/{n}  ({100*sem_ok/n:.1f}%)")
    print(f"  Semantic fixed a failure : {sem_wins}")
    print(f"  Outputs differ           : {differ}  (same prompt → different result)")
    print(f"  Both failed              : {both_fail}")
    print(bar)

    if sem_wins:
        print(f"\n[Semantic helped — {sem_wins} prompt(s)]")
        for r in results:
            if r.semantic_wins:
                print(f"  [{r.id:02d}] {r.prompt[:65]}")
                for a in r.ambiguous:
                    print(f"         · {a}")
                print(f"         schema_only error → {r.schema_only_err[:80]}")

    differ_not_win = [r for r in results if r.results_differ and not r.semantic_wins]
    if differ_not_win:
        print(f"\n[Different outputs but both ran — {len(differ_not_win)} prompt(s)]")
        for r in differ_not_win:
            print(f"  [{r.id:02d}] {r.prompt[:65]}")

    if both_fail:
        print(f"\n[Both failed — {both_fail} prompt(s)]")
        for r in results:
            if r.both_fail:
                print(f"  [{r.id:02d}] {r.prompt[:65]}")
                print(f"         schema_only → {r.schema_only_err[:60]}")
                print(f"         semantic    → {r.semantic_err[:60]}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic Context Ablation")
    parser.add_argument("--out", default="results.json")
    parser.add_argument("--append", action="store_true",
                        help="Load existing --out file and only run prompts not already present.")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        sys.exit("Set OPENAI_API_KEY before running.")

    if not PROMPTS_FILE.exists():
        sys.exit(f"{PROMPTS_FILE} not found.")

    client  = openai.OpenAI(api_key=api_key)
    prompts: list[dict] = json.loads(PROMPTS_FILE.read_text())

    out = HERE / args.out
    existing: list[dict] = []
    done_ids: set[int] = set()
    if args.append and out.exists():
        existing = json.loads(out.read_text())
        done_ids = {r["id"] for r in existing}
        log.info("Append mode: %d results already in %s, skipping those ids.", len(existing), out.name)

    pending = [p for p in prompts if p["id"] not in done_ids]
    if not pending:
        log.info("Nothing new to run — all prompt ids already in %s.", out.name)
        return

    log.info("Building ablation database…")
    conn = build_db()

    raw_schema = _raw_schema(conn)
    tbl_desc, col_desc = _load_descriptions(conn)

    schema_only_text = render_schema_only(raw_schema)
    semantic_text    = render_schema_semantic(raw_schema, tbl_desc, col_desc)

    log.info("Schema-only context  (%d chars)", len(schema_only_text))
    log.info("Semantic context     (%d chars)", len(semantic_text))
    log.info("Running %d new prompts with model=%s", len(pending), MODEL)

    new_results: list[PromptResult] = []
    for item in pending:
        r = run_prompt(item, conn, schema_only_text, semantic_text, client)
        new_results.append(r)

    all_dicts = existing + [r.as_dict() for r in new_results]
    all_dicts.sort(key=lambda r: r["id"])

    # Reconstruct PromptResult list for summary (new runs only shown, full for file)
    print_summary(new_results)

    out.write_text(json.dumps(all_dicts, indent=2, ensure_ascii=False))
    log.info("Detailed results (%d total) → %s", len(all_dicts), out)


if __name__ == "__main__":
    main()
