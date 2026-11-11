""" Used Anthropic Cluade to generate this code and csv files on 11/11/26 in order to create a database of recipes, costs and etc."""
"""Create recipes.db (if needed) and import the four CSV files into it.
 
Usage:
    python import_recipes.py                      # looks for the CSVs in the current folder
    python import_recipes.py --dir path/to/csvs   # CSVs in another folder
    python import_recipes.py --db other.db
 
Safe to re-run: rows that already exist (same name / title / key) are skipped.
The whole import is one transaction, so a bad row leaves the database untouched.
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path
 
SCHEMA = """
CREATE TABLE IF NOT EXISTS ingredients (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    unit  TEXT NOT NULL CHECK (unit IN ('g', 'ml', 'each'))
);
 
CREATE TABLE IF NOT EXISTS packages (
    id             INTEGER PRIMARY KEY,
    ingredient_id  INTEGER NOT NULL REFERENCES ingredients(id),
    size           REAL    NOT NULL CHECK (size > 0),
    price_cents    INTEGER NOT NULL CHECK (price_cents > 0),
    UNIQUE (ingredient_id, size)
);
 
CREATE TABLE IF NOT EXISTS recipes (
    id     INTEGER PRIMARY KEY,
    title  TEXT NOT NULL UNIQUE
);
 
CREATE TABLE IF NOT EXISTS recipe_ingredients (
    recipe_id        INTEGER NOT NULL REFERENCES recipes(id),
    ingredient_id    INTEGER NOT NULL REFERENCES ingredients(id),
    qty_per_serving  REAL    NOT NULL CHECK (qty_per_serving > 0),
    PRIMARY KEY (recipe_id, ingredient_id)
);
"""
 
 
def read_rows(path, required):
    """Read a CSV into a list of dicts with whitespace-stripped values."""
    with open(path, newline="", encoding="utf-8-sig") as f:  # utf-8-sig drops Excel's BOM
        reader = csv.DictReader(f)
        missing = set(required) - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"{path}: missing column(s): {', '.join(sorted(missing))}")
        # start=2 because line 1 is the header
        return [
            (line_no, {k: (v or "").strip() for k, v in row.items()})
            for line_no, row in enumerate(reader, start=2)
        ]
 
 
def id_map(conn, table, key_col):
    return {key: id_ for id_, key in conn.execute(f"SELECT id, {key_col} FROM {table}")}
 
 
def lookup(mapping, key, what, path, line_no):
    try:
        return mapping[key]
    except KeyError:
        sys.exit(f"{path.name} line {line_no}: unknown {what} {key!r}")
 
 
def insert(conn, sql, params):
    before = conn.total_changes
    conn.executemany(sql, params)
    added = conn.total_changes - before
    return added, len(params) - added
 
 
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="recipes.db")
    ap.add_argument("--dir", default=".", help="folder containing the CSV files")
    ap.add_argument("--recipes", default="recipes.csv")
    ap.add_argument("--ingredients", default="ingredients.csv")
    ap.add_argument("--packages", default="packages.csv")
    ap.add_argument("--recipe-ingredients", default="recipe_ingredients.csv")
    args = ap.parse_args()
 
    folder = Path(args.dir)
    p_recipes = folder / args.recipes
    p_ingredients = folder / args.ingredients
    p_packages = folder / args.packages
    p_ri = folder / args.recipe_ingredients
 
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")  # off by default in SQLite, per connection
    try:
        with conn:  # commit on success, roll back on any error
            conn.executescript(SCHEMA)
 
            # 1. parent tables first
            rows = read_rows(p_ingredients, ["name", "unit"])
            added, skipped = insert(
                conn,
                "INSERT OR IGNORE INTO ingredients (name, unit) VALUES (?, ?)",
                [(r["name"], r["unit"]) for _, r in rows],
            )
            print(f"ingredients:        {added} added, {skipped} already present")
 
            rows = read_rows(p_recipes, ["title"])
            added, skipped = insert(
                conn,
                "INSERT OR IGNORE INTO recipes (title) VALUES (?)",
                [(r["title"],) for _, r in rows],
            )
            print(f"recipes:            {added} added, {skipped} already present")
 
            ingredient_ids = id_map(conn, "ingredients", "name")
            recipe_ids = id_map(conn, "recipes", "title")
 
            # 2. child tables: swap names for ids
            rows = read_rows(p_packages, ["ingredient", "size", "price_cents"])
            params = [
                (lookup(ingredient_ids, r["ingredient"], "ingredient", p_packages, n),
                 float(r["size"]), int(r["price_cents"]))
                for n, r in rows
            ]
            added, skipped = insert(
                conn,
                "INSERT OR IGNORE INTO packages (ingredient_id, size, price_cents) VALUES (?, ?, ?)",
                params,
            )
            print(f"packages:           {added} added, {skipped} already present")
 
            rows = read_rows(p_ri, ["recipe", "ingredient", "qty_per_serving"])
            params = [
                (lookup(recipe_ids, r["recipe"], "recipe", p_ri, n),
                 lookup(ingredient_ids, r["ingredient"], "ingredient", p_ri, n),
                 float(r["qty_per_serving"]))
                for n, r in rows
            ]
            added, skipped = insert(
                conn,
                "INSERT OR IGNORE INTO recipe_ingredients (recipe_id, ingredient_id, qty_per_serving) VALUES (?, ?, ?)",
                params,
            )
            print(f"recipe_ingredients: {added} added, {skipped} already present")
    except (sqlite3.Error, ValueError) as e:
        sys.exit(f"Import failed, nothing was saved: {e}")
    finally:
        conn.close()
    print(f"Done -> {args.db}")
 
 
if __name__ == "__main__":
    main()
 