"""SQLAlchemy ORM models for The Reserve."""

# Import all models so they register with Base.metadata
from .bottle import BottleModel, TastingNoteModel  # noqa: F401
from .cocktail import (  # noqa: F401
    CocktailModel,
    RecipeIngredientModel,
    CocktailInstructionModel,
)
from .cocktail_tasting import (  # noqa: F401
    CocktailTastingModel,
    CocktailTastingIngredientModel,
)
from .ingredient import IngredientModel  # noqa: F401
from .event import (  # noqa: F401
    EventModel,
    EventBottleModel,
    EventCocktailModel,
    EventParticipantModel,
    EventTastingModel,
    EventCocktailRatingModel,
)
