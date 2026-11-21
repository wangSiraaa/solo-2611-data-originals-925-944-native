"""Charter roll-call and amendment-ordering engine.

Two business entry points share one CLI (see ``charter_tool.cli``):

* ``roster``  -- reconstruct the attested roster (attendance + per-motion
  eligibility) for every independently recorded roll-call cutoff.
* ``charter`` -- replay every legal processing order of the motions and
  determine whether the archive supports a unique final charter text.

The package is pure Python 3.11+ standard library and runs offline.
"""

__all__ = ["roll", "roster", "charter", "pipeline", "materials", "cli"]

__version__ = "1.0.0"
