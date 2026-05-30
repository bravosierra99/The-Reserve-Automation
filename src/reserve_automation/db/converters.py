"""Converters between SQLAlchemy models and Pydantic domain models.

These functions translate between the persistence layer (SQLAlchemy) and
the domain/API layer (Pydantic). This keeps the two layers decoupled.
"""

import json
from datetime import date, datetime

from ..core.models import BottleMetadata
from ..core.tasting_note import TastingNote
from ..core.cocktail import CocktailRecipe, RecipeIngredient
from ..core.cocktail_tasting import (
    CocktailTastingNote,
    CocktailTastingIngredient,
)
from ..core.ingredient import Ingredient

from .models.bottle import BottleModel, TastingNoteModel
from .models.cocktail import CocktailModel, RecipeIngredientModel
from .models.cocktail_tasting import CocktailTastingModel, CocktailTastingIngredientModel
from .models.ingredient import IngredientModel


def _parse_variety(val: str | None) -> list[str] | None:
    """Read variety from DB: handles JSON-encoded lists and legacy plain strings."""
    if not val:
        return None
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            items = [s for s in parsed if isinstance(s, str) and s.strip()]
            return items or None
        if isinstance(parsed, str) and parsed.strip():
            return [parsed.strip()]
    except (json.JSONDecodeError, ValueError):
        pass
    return [val.strip()] if val.strip() else None


def _serialize_variety(val: list[str] | None) -> str | None:
    """Write variety to DB as a JSON array string."""
    if not val:
        return None
    return json.dumps(val)


# --- Bottle converters ---


def bottle_to_pydantic(db: BottleModel) -> BottleMetadata:
    """Convert a BottleModel to a BottleMetadata Pydantic model."""
    return BottleMetadata(
        producer=db.producer,
        name=db.name,
        type=db.type,
        year=db.year,
        beverage_type=db.beverage_type,
        country=db.country,
        region=db.region,
        variety=_parse_variety(db.variety),
        vineyard=db.vineyard,
        style=db.style,
        age_statement=db.age_statement,
        proof=db.proof,
        mash_bill=db.mash_bill,
        barrel_type=db.barrel_type,
        batch_number=db.batch_number,
        bottle_number=db.bottle_number,
        bottle_opened_date=db.bottle_opened_date,
        abv=db.abv,
        price=db.price,
        purchase_source=db.purchase_source,
        purchase_link=db.purchase_link,
        inventory=db.inventory,
        buy=db.buy,
        stars=db.stars,
        value_for_money=db.value_for_money,
        points=db.points,
        confidence=db.confidence,
        source=db.source,
        extracted_at=db.extracted_at or datetime.now(),
        enriched=db.enriched,
        label_image_url=db.label_image_path,
        notes=db.notes,
        id=str(db.id),
        vault_path=None,
    )


def pydantic_to_bottle(p: BottleMetadata, existing: BottleModel | None = None) -> BottleModel:
    """Convert a BottleMetadata Pydantic model to a BottleModel.

    If `existing` is provided, updates that instance instead of creating a new one.
    """
    model = existing or BottleModel()
    model.producer = p.producer
    model.name = p.name
    model.type = p.type if isinstance(p.type, str) else p.type.value
    model.year = p.year
    model.beverage_type = p.beverage_type
    model.country = p.country
    model.region = p.region
    model.variety = _serialize_variety(p.variety)
    model.vineyard = p.vineyard
    model.style = p.style
    model.age_statement = p.age_statement
    model.proof = p.proof
    model.mash_bill = p.mash_bill
    model.barrel_type = p.barrel_type
    model.batch_number = p.batch_number
    model.bottle_number = p.bottle_number
    model.bottle_opened_date = p.bottle_opened_date
    model.abv = p.abv
    model.price = p.price
    model.purchase_source = p.purchase_source
    model.purchase_link = p.purchase_link
    model.inventory = p.inventory
    model.buy = p.buy
    model.stars = p.stars
    model.value_for_money = p.value_for_money
    model.points = p.points
    model.confidence = p.confidence
    model.source = p.source
    model.extracted_at = p.extracted_at
    model.enriched = p.enriched
    model.label_image_path = p.label_image_url
    model.notes = p.notes
    return model


# --- Tasting Note converters ---


def tasting_to_pydantic(db: TastingNoteModel) -> TastingNote:
    """Convert a TastingNoteModel to a TastingNote Pydantic model."""
    return TastingNote(
        id=db.id,
        bottle_name=db.bottle_name,
        taster_name=db.taster_name,
        tasting_date=db.tasting_date,
        beverage_type=db.beverage_type,
        wine_appearance=db.wine_appearance,
        wine_aroma=db.wine_aroma,
        wine_taste=db.wine_taste,
        wine_aftertaste=db.wine_aftertaste,
        wine_overall=db.wine_overall,
        whiskey_nose=db.whiskey_nose,
        whiskey_palate=db.whiskey_palate,
        whiskey_finish=db.whiskey_finish,
        whiskey_overall=db.whiskey_overall,
        appearance_notes=db.appearance_notes,
        nose_notes=db.nose_notes,
        palate_notes=db.palate_notes,
        finish_notes=db.finish_notes,
        overall_notes=db.overall_notes,
        days_from_crack=db.days_from_crack,
        fill_level=db.fill_level,
        place=db.place,
        theme=db.theme,
        price=db.price,
        color=db.color,
        confidence=db.confidence,
    )


def pydantic_to_tasting(
    p: TastingNote, bottle_id: int, existing: TastingNoteModel | None = None
) -> TastingNoteModel:
    """Convert a TastingNote Pydantic model to a TastingNoteModel."""
    model = existing or TastingNoteModel()
    model.bottle_id = bottle_id
    model.bottle_name = p.bottle_name
    model.taster_name = p.taster_name
    model.tasting_date = p.tasting_date
    model.beverage_type = p.beverage_type
    model.wine_appearance = p.wine_appearance
    model.wine_aroma = p.wine_aroma
    model.wine_taste = p.wine_taste
    model.wine_aftertaste = p.wine_aftertaste
    model.wine_overall = p.wine_overall
    model.whiskey_nose = p.whiskey_nose
    model.whiskey_palate = p.whiskey_palate
    model.whiskey_finish = p.whiskey_finish
    model.whiskey_overall = p.whiskey_overall
    model.appearance_notes = p.appearance_notes
    model.nose_notes = p.nose_notes
    model.palate_notes = p.palate_notes
    model.finish_notes = p.finish_notes
    model.overall_notes = p.overall_notes
    model.days_from_crack = p.days_from_crack
    model.fill_level = p.fill_level
    model.place = p.place
    model.theme = p.theme
    model.price = p.price
    model.color = p.color
    model.confidence = p.confidence
    return model


# --- Cocktail converters ---


def cocktail_to_pydantic(db: CocktailModel) -> CocktailRecipe:
    """Convert a CocktailModel to a CocktailRecipe Pydantic model."""
    ingredients = [
        RecipeIngredient(
            ingredient=ri.ingredient_name,
            amount=ri.amount,
            unit=ri.unit,
            notes=ri.notes,
            optional=ri.optional,
        )
        for ri in db.ingredients
    ]
    instructions = [inst.instruction for inst in db.instructions]

    parent_name = db.parent_cocktail.name if db.parent_cocktail else None

    return CocktailRecipe(
        name=db.name,
        description=db.description,
        parent_cocktail=parent_name,
        ingredients=ingredients,
        instructions=instructions,
        garnish=db.garnish,
        glassware=db.glassware,
        method=db.method,
        style=db.style,
        serving_size=db.serving_size,
        stars=db.stars,
        photo=db.photo_path,
        id=str(db.id),
        vault_path=None,
    )


def pydantic_to_cocktail(
    p: CocktailRecipe,
    parent_id: int | None = None,
    existing: CocktailModel | None = None,
) -> CocktailModel:
    """Convert a CocktailRecipe Pydantic model to a CocktailModel.

    Ingredients and instructions are handled separately since they're child tables.
    """
    model = existing or CocktailModel()
    model.name = p.name
    model.description = p.description
    model.parent_cocktail_id = parent_id
    model.garnish = p.garnish
    model.glassware = p.glassware
    model.method = p.method
    model.style = p.style
    model.serving_size = p.serving_size
    model.stars = p.stars
    model.photo_path = p.photo
    return model


# --- Cocktail Tasting converters ---


def cocktail_tasting_to_pydantic(db: CocktailTastingModel) -> CocktailTastingNote:
    """Convert a CocktailTastingModel to a CocktailTastingNote Pydantic model."""
    bottles_used = [
        CocktailTastingIngredient(
            recipe_ingredient=bu.recipe_ingredient,
            actual_product=bu.actual_product,
        )
        for bu in db.bottles_used
    ]

    return CocktailTastingNote(
        recipe_name=db.recipe_name,
        taster_name=db.taster_name,
        tasting_date=db.tasting_date.isoformat() if isinstance(db.tasting_date, date) else str(db.tasting_date),
        bottles_used=bottles_used,
        score=db.score,
        notes=db.notes,
        bartender=db.bartender,
        id=str(db.id),
        vault_path=None,
    )


def pydantic_to_cocktail_tasting(
    p: CocktailTastingNote,
    cocktail_id: int,
    existing: CocktailTastingModel | None = None,
) -> CocktailTastingModel:
    """Convert a CocktailTastingNote to a CocktailTastingModel."""
    model = existing or CocktailTastingModel()
    model.cocktail_id = cocktail_id
    model.recipe_name = p.recipe_name
    model.taster_name = p.taster_name
    model.tasting_date = (
        date.fromisoformat(p.tasting_date)
        if isinstance(p.tasting_date, str)
        else p.tasting_date
    )
    model.score = p.score
    model.notes = p.notes
    model.bartender = p.bartender
    return model


# --- Ingredient converters ---


def ingredient_to_pydantic(
    db: IngredientModel, parent_name: str | None = None
) -> Ingredient:
    """Convert an IngredientModel to an Ingredient Pydantic model.

    Args:
        db: The SQLAlchemy ingredient model.
        parent_name: The parent ingredient's name (resolved from parent_id relationship).
    """
    resolved_parent = parent_name
    if resolved_parent is None and db.parent is not None:
        resolved_parent = db.parent.name

    ing = Ingredient(
        name=db.name,
        parent=resolved_parent,
        cost=db.cost,
        volume_ml=db.volume_ml,
        abv=db.abv,
        notes=db.notes,
        label_image=db.label_image_path,
        id=str(db.id),
        vault_path=None,
    )
    ing.compute_is_product()
    return ing


def pydantic_to_ingredient(
    p: Ingredient,
    parent_id: int | None = None,
    existing: IngredientModel | None = None,
) -> IngredientModel:
    """Convert an Ingredient Pydantic model to an IngredientModel."""
    model = existing or IngredientModel()
    model.name = p.name
    model.parent_id = parent_id
    model.cost = p.cost
    model.volume_ml = p.volume_ml
    model.abv = p.abv
    model.notes = p.notes
    model.label_image_path = p.label_image
    return model
