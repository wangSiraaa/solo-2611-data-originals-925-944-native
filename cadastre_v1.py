"""Read the counter's version-1 parcel run sheets."""

import argparse
import json
import sys
from pathlib import Path


def load_grid(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("expected a version 1 run sheet")
    width, height = data.get("width"), data.get("height")
    if any(type(dim) is not int or not 1 <= dim <= 24 for dim in (width, height)):
        raise ValueError("width and height must be integers from 1 to 24")
    rows = data.get("rows")
    if not isinstance(rows, list) or len(rows) != height:
        raise ValueError("row count must match height")
    grid = []
    for y, row in enumerate(rows):
        if not isinstance(row, list):
            raise ValueError(f"row {y} must be a list")
        cells = []
        for run in row:
            if not isinstance(run, list) or len(run) != 2:
                raise ValueError(f"row {y}: expected [parcel, length]")
            parcel, length = run
            if not isinstance(parcel, str) or not parcel or type(length) is not int or length <= 0:
                raise ValueError(f"row {y}: invalid parcel or length")
            if len(cells) + length > width:
                raise ValueError(f"row {y} exceeds width")
            cells.extend([parcel] * length)
        if len(cells) != width:
            raise ValueError(f"row {y} does not fill width")
        grid.append(cells)
    return grid


def parcel_areas(grid, parcel):
    remaining = {(x, y) for y, row in enumerate(grid) for x, name in enumerate(row) if name == parcel}
    pieces = []
    while remaining:
        first = min(remaining, key=lambda point: (point[1], point[0]))
        remaining.remove(first)
        pending = [first]
        area = 0
        while pending:
            x, y = pending.pop()
            area += 1
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        pieces.append({"start": list(first), "area": area})
    return {"parcel": parcel, "pieces": pieces}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sheet", type=Path)
    actions = parser.add_subparsers(dest="operation", required=True)
    cell = actions.add_parser("cell", help="return the parcel at (x, y)")
    cell.add_argument("x", type=int)
    cell.add_argument("y", type=int)
    areas = actions.add_parser("areas", help="return the areas of this parcel's connected pieces")
    areas.add_argument("parcel")
    args = parser.parse_args()
    try:
        grid = load_grid(args.sheet)
        if args.operation == "cell":
            if not (0 <= args.y < len(grid) and 0 <= args.x < len(grid[0])):
                raise ValueError("cell outside the sheet")
            result = {"x": args.x, "y": args.y, "parcel": grid[args.y][args.x]}
        else:
            result = parcel_areas(grid, args.parcel)
    except (OSError, ValueError) as error:
        print(f"counter: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
