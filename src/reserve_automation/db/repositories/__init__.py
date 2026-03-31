"""Repository implementations and FastAPI dependency functions."""

from fastapi import Depends
from sqlalchemy.orm import Session

from ..engine import get_db
from .bottle_repo import SQLiteBottleRepository
from .tasting_repo import SQLiteTastingRepository
from .cocktail_repo import SQLiteCocktailRepository
from .ingredient_repo import SQLiteIngredientRepository
from .event_repo import SQLiteEventRepository


def get_bottle_repo(db: Session = Depends(get_db)) -> SQLiteBottleRepository:
    return SQLiteBottleRepository(db)


def get_tasting_repo(db: Session = Depends(get_db)) -> SQLiteTastingRepository:
    return SQLiteTastingRepository(db)


def get_cocktail_repo(db: Session = Depends(get_db)) -> SQLiteCocktailRepository:
    return SQLiteCocktailRepository(db)


def get_ingredient_repo(db: Session = Depends(get_db)) -> SQLiteIngredientRepository:
    return SQLiteIngredientRepository(db)


def get_event_repo(db: Session = Depends(get_db)) -> SQLiteEventRepository:
    return SQLiteEventRepository(db)
