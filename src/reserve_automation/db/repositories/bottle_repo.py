"""SQLite repository implementation for bottles."""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ...core.models import BottleMetadata
from ..converters import bottle_to_pydantic, pydantic_to_bottle
from ..models.bottle import BottleModel


class SQLiteBottleRepository:
    """SQLite-backed bottle repository."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, bottle_id: int) -> BottleMetadata | None:
        db_bottle = self.db.get(BottleModel, bottle_id)
        if db_bottle is None:
            return None
        return bottle_to_pydantic(db_bottle)

    def get_all(self, beverage_type: str | None = None) -> list[BottleMetadata]:
        query = self.db.query(BottleModel)
        if beverage_type:
            query = query.filter(BottleModel.type == beverage_type)
        query = query.order_by(BottleModel.producer, BottleModel.name)
        return [bottle_to_pydantic(b) for b in query.all()]

    def create(self, bottle: BottleMetadata) -> BottleMetadata:
        db_bottle = pydantic_to_bottle(bottle)
        self.db.add(db_bottle)
        self.db.commit()
        self.db.refresh(db_bottle)
        return bottle_to_pydantic(db_bottle)

    def update(self, bottle_id: int, bottle: BottleMetadata) -> BottleMetadata:
        db_bottle = self.db.get(BottleModel, bottle_id)
        if db_bottle is None:
            raise ValueError(f"Bottle {bottle_id} not found")
        pydantic_to_bottle(bottle, existing=db_bottle)
        self.db.commit()
        self.db.refresh(db_bottle)
        return bottle_to_pydantic(db_bottle)

    def delete(self, bottle_id: int) -> bool:
        db_bottle = self.db.get(BottleModel, bottle_id)
        if db_bottle is None:
            return False
        self.db.delete(db_bottle)
        self.db.commit()
        return True

    def search(self, query: str) -> list[BottleMetadata]:
        pattern = f"%{query}%"
        results = (
            self.db.query(BottleModel)
            .filter(
                or_(
                    BottleModel.producer.ilike(pattern),
                    BottleModel.name.ilike(pattern),
                    BottleModel.beverage_type.ilike(pattern),
                    BottleModel.region.ilike(pattern),
                    BottleModel.country.ilike(pattern),
                )
            )
            .order_by(BottleModel.producer, BottleModel.name)
            .all()
        )
        return [bottle_to_pydantic(b) for b in results]

    def find_exact(
        self, producer: str, name: str, year: int | None, bottle_type: str
    ) -> BottleMetadata | None:
        """Find a bottle matching the unique constraint (producer, name, year, type)."""
        query = self.db.query(BottleModel).filter(
            BottleModel.producer == producer,
            BottleModel.name == name,
            BottleModel.type == bottle_type,
        )
        if year is not None:
            query = query.filter(BottleModel.year == year)
        else:
            query = query.filter(BottleModel.year.is_(None))
        result = query.first()
        return bottle_to_pydantic(result) if result else None

    # NOTE: duplicate detection no longer lives in the repository. A SQL substring
    # prefilter was too brittle — it dropped a stored "Chianti Classico" when
    # checking the longer "Chianti Classico Riserva", so the fuzzy scorer never
    # ran. Candidate generation is now a broad get_all(type) pool scored by
    # web.services.duplicate_service.build_duplicate_matches. find_exact() below
    # is unrelated: it enforces the UNIQUE constraint for the force_save upsert.

    def get_db_model(self, bottle_id: int) -> BottleModel | None:
        """Get the raw SQLAlchemy model (for internal use, e.g., FK references)."""
        return self.db.get(BottleModel, bottle_id)

    def update_label_path(self, bottle_id: int, label_path: str | None) -> bool:
        """Update just the label image path for a bottle."""
        db_bottle = self.db.get(BottleModel, bottle_id)
        if db_bottle is None:
            return False
        db_bottle.label_image_path = label_path
        self.db.commit()
        return True
