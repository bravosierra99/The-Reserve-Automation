"""SQLAlchemy ORM models for The Reserve."""

# Import all models so they register with Base.metadata
from .bottle import BottleModel, TastingNoteModel  # noqa: F401
from .cocktail import (  # noqa: F401
    CocktailInstructionModel,
    CocktailModel,
    RecipeIngredientModel,
)
from .cocktail_tasting import (  # noqa: F401
    CocktailTastingIngredientModel,
    CocktailTastingModel,
)
from .event import (  # noqa: F401
    EventBottleModel,
    EventCocktailModel,
    EventCocktailRatingModel,
    EventModel,
    EventParticipantModel,
    EventTastingModel,
)
from .ingredient import IngredientModel  # noqa: F401
