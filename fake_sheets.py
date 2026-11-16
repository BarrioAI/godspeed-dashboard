"""
In-memory stand-in for a gspread Spreadsheet (the subset sheets.py uses).

Used by the tests, and by the dashboard itself when GODSPEED_DEV_XLSX points at
an .xlsx export of the workbook — that runs the whole app locally against a
copy of the data, with writes kept in memory.
"""

from __future__ import annotations

import re
from datetime import date, datetime


class _Tab:
    def __init__(self, book, title, rows, cols):
        self._book, self.title, self.row_count, self.col_count = book, title, rows, cols

    def resize(self, rows=None, cols=None):
        self._book.calls.append(f"resize:{self.title}")
        self.row_count, self.col_count = rows or self.row_count, cols or self.col_count


class GridLimitError(Exception):
    pass


def _parse(rng: str):
    m = re.match(r"^'((?:[^']|'')*)'(?:!(.+))?$", rng)
    if m:
        return m.group(1).replace("''", "'"), m.group(2) or ""
    tab, _, cells = rng.partition("!")
    return tab, cells


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


class FakeSpreadsheet:
    def __init__(self, tabs: dict[str, list[list]] | None = None):
        self.tabs = {k: [list(r) for r in v] for k, v in (tabs or {}).items()}
        self.calls: list[str] = []
        self._grid = {k: _Tab(self, k, max(len(v), 1) + 5, max([len(r) for r in v] + [1]) + 1)
                      for k, v in self.tabs.items()}

    @classmethod
    def from_xlsx(cls, path: str):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)

        def cell(v):
            if v is None:
                return ""
            if isinstance(v, (datetime, date)):
                return v.strftime("%Y-%m-%d")
            if isinstance(v, float) and v.is_integer():
                return str(int(v))
            return str(v)

        tabs = {}
        for ws in wb.worksheets:
            rows = [[cell(c) for c in r] for r in ws.iter_rows(values_only=True)]
            while rows and not any(rows[-1]):
                rows.pop()
            tabs[ws.title] = rows
        return cls(tabs)

    # --- gspread surface -------------------------------------------------
    def worksheets(self):
        return [self._grid[t] for t in self.tabs]

    def add_worksheet(self, title, rows=100, cols=20):
        self.calls.append(f"add:{title}")
        self.tabs[title] = []
        self._grid[title] = _Tab(self, title, rows, cols)
        return self._grid[title]

    def values_batch_get(self, ranges, params=None):
        self.calls.append("batch_get")
        return {"valueRanges": [{"values": self._read(r)} for r in ranges]}

    def values_get(self, rng, params=None):
        self.calls.append(f"get:{rng}")
        return {"values": self._read(rng)}

    def values_clear(self, rng):
        self.calls.append(f"clear:{rng}")
        tab, cells = _parse(rng)
        if not cells:
            self.tabs[tab] = []
            return
        m = re.match(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$", cells)
        c1, r1, c2, r2 = _col(m.group(1)), int(m.group(2)), _col(m.group(3)), int(m.group(4))
        grid = self._grid[tab]
        if r2 > grid.row_count or c2 > grid.col_count:
            raise GridLimitError(f"{rng} exceeds grid limits")
        rows = self.tabs[tab]
        for r in range(r1 - 1, min(r2, len(rows))):
            for c in range(c1 - 1, min(c2, len(rows[r]))):
                rows[r][c] = ""
        while rows and not any(rows[-1]):
            rows.pop()

    def values_update(self, rng, params=None, body=None):
        self.calls.append(f"update:{rng}")
        tab, cells = _parse(rng)
        m = re.match(r"^([A-Z]+)(\d+)", cells or "A1")
        self._write(tab, int(m.group(2)), _col(m.group(1)), body["values"])

    def values_batch_update(self, body=None):
        self.calls.append("batch_update")
        for item in body["data"]:
            self.values_update(item["range"], body={"values": item["values"]})

    def values_append(self, rng, params=None, body=None):
        self.calls.append(f"append:{rng}")
        tab = _parse(rng)[0]
        self.tabs.setdefault(tab, []).extend(list(r) for r in body["values"])
        grid = self._grid[tab]                     # append grows the grid, like the API
        grid.row_count = max(grid.row_count, len(self.tabs[tab]))

    # --- helpers ---------------------------------------------------------
    def _read(self, rng):
        tab, cells = _parse(rng)
        rows = self.tabs[tab]
        if cells == "1:1":
            return [list(rows[0])] if rows else []
        return [list(r) for r in rows]

    def _write(self, tab, row, col, values):
        grid = self._grid[tab]
        if row + len(values) - 1 > grid.row_count or col + max(len(v) for v in values) - 1 > grid.col_count:
            raise GridLimitError(f"write to {tab} exceeds grid limits "
                                 f"({grid.row_count} rows x {grid.col_count} cols)")
        rows = self.tabs.setdefault(tab, [])
        for dr, line in enumerate(values):
            while len(rows) < row + dr:
                rows.append([])
            target = rows[row + dr - 1]
            while len(target) < col - 1 + len(line):
                target.append("")
            for dc, value in enumerate(line):
                target[col - 1 + dc] = value
