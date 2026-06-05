"""SQLite repository implementation for tasting notes."""

from sqlalchemy.orm import Session

from ...core.tasting_note import TastingNote
from ..converters import pydantic_to_tasting, tasting_to_pydantic
from ..models.bottle import TastingNoteModel


class SQLiteTastingRepository:
    """SQLite-backed tasting note repository."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, tasting_id: int) -> TastingNote | None:
        db_tasting = self.db.get(TastingNoteModel, tasting_id)
        if db_tasting is None:
            return None
        return tasting_to_pydantic(db_tasting)

    def get_by_bottle_id(self, bottle_id: int) -> list[TastingNote]:
        tastings = (
            self.db.query(TastingNoteModel)
            .filter(TastingNoteModel.bottle_id == bottle_id)
            .order_by(TastingNoteModel.tasting_date.desc())
            .all()
        )
        return [tasting_to_pydantic(t) for t in tastings]

    def create(self, tasting: TastingNote, bottle_id: int) -> TastingNote:
        db_tasting = pydantic_to_tasting(tasting, bottle_id)
        self.db.add(db_tasting)
        self.db.commit()
        self.db.refresh(db_tasting)
        return tasting_to_pydantic(db_tasting)

    def delete(self, tasting_id: int) -> bool:
        db_tasting = self.db.get(TastingNoteModel, tasting_id)
        if db_tasting is None:
            return False
        self.db.delete(db_tasting)
        self.db.commit()
        return True

    def get_summary_for_bottle(self, bottle_id: int) -> dict:
        """Get tasting statistics for a bottle.

        Returns dict with: tasting_count, avg_score, latest_date, tasters
        """
        tastings = (
            self.db.query(TastingNoteModel)
            .filter(TastingNoteModel.bottle_id == bottle_id)
            .all()
        )

        if not tastings:
            return {
                "tasting_count": 0,
                "avg_score": None,
                "latest_date": None,
                "tasters": [],
            }

        scores = []
        tasters = set()
        latest_date = None

        for t in tastings:
            tasters.add(t.taster_name)
            if latest_date is None or t.tasting_date > latest_date:
                latest_date = t.tasting_date

            # Calculate score based on beverage type
            if t.beverage_type == "wine":
                components = [
                    t.wine_appearance or 0,
                    t.wine_aroma or 0,
                    t.wine_taste or 0,
                    t.wine_aftertaste or 0,
                    t.wine_overall or 0,
                ]
                scores.append(sum(components))
            else:
                components = [
                    t.whiskey_nose or 0,
                    t.whiskey_palate or 0,
                    t.whiskey_finish or 0,
                    t.whiskey_overall or 0,
                ]
                scores.append(sum(components))

        return {
            "tasting_count": len(tastings),
            "avg_score": sum(scores) / len(scores) if scores else None,
            "latest_date": latest_date.isoformat() if latest_date else None,
            "tasters": sorted(tasters),
        }

    def get_by_taster(self, taster_name: str) -> list[TastingNote]:
        tastings = (
            self.db.query(TastingNoteModel)
            .filter(TastingNoteModel.taster_name == taster_name)
            .order_by(TastingNoteModel.tasting_date.desc())
            .all()
        )
        return [tasting_to_pydantic(t) for t in tastings]

    def check_duplicate(
        self, bottle_id: int, taster_name: str, tasting_date
    ) -> bool:
        """Check if a tasting with the same bottle/taster/date already exists."""
        existing = (
            self.db.query(TastingNoteModel)
            .filter(
                TastingNoteModel.bottle_id == bottle_id,
                TastingNoteModel.taster_name == taster_name,
                TastingNoteModel.tasting_date == tasting_date,
            )
            .first()
        )
        return existing is not None
