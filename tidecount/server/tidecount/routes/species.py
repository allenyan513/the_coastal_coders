"""The species list, read-only. It's edited in tidecount/species.csv."""
from fastapi import APIRouter

from .. import db, models

router = APIRouter()


@router.get("/api/species")
def species():
    """Every fish the suggester may name, and how many tracks a person has given that name here."""
    with db.session() as con:
        named = dict(con.execute("SELECT species, COUNT(*) FROM decisions WHERE state != 'Rejected' AND species IS NOT NULL GROUP BY species").fetchall())
    return [{**row, "confirmed": named.get(row["common"], 0)} for row in models.species_table()]
