"""SQLite repository implementation for tasting events.

Events have a complex nested structure. This repo works with dicts
to match the existing event_store interface, making the route migration
simpler. The dicts are assembled from the normalized DB tables.
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from ..models.event import (
    EventModel,
    EventBottleModel,
    EventCocktailModel,
    EventParticipantModel,
    EventTastingModel,
    EventCocktailRatingModel,
)


class SQLiteEventRepository:
    """SQLite-backed event repository."""

    def __init__(self, db: Session):
        self.db = db

    def _event_to_dict(self, event: EventModel) -> dict:
        """Convert an EventModel with relationships to the dict format used by routes."""
        bottles = []
        for eb in event.bottles:
            bottles.append({
                "bottle_id": str(eb.bottle_id),
                "bottle_name": eb.bottle_name,
                "bottle_path": str(eb.bottle_id),
                "blind_number": eb.blind_number,
            })

        cocktails = []
        for ec in event.cocktails:
            cocktails.append({
                "cocktail_name": ec.cocktail_name,
                "recipe_id": str(ec.recipe_id) if ec.recipe_id else None,
                "bartender": ec.bartender,
                "blind_number": ec.blind_number,
                "added_at": ec.added_at.isoformat() if ec.added_at else None,
            })

        participants = {}
        for p in event.participants:
            tastings = []
            for t in p.tastings:
                tastings.append({
                    "bottle_id": str(t.bottle_id),
                    "tasting_data": t.tasting_data,
                })

            cocktail_ratings = []
            for cr in p.cocktail_ratings:
                cocktail_ratings.append({
                    "cocktail_name": cr.cocktail_name,
                    "score": cr.score,
                    "notes": cr.notes,
                })

            participants[p.id] = {
                "participant_id": p.id,
                "participant_name": p.name,
                "tastings": tastings,
                "cocktail_ratings": cocktail_ratings,
            }

        return {
            "event_id": event.id,
            "name": event.name,
            "beverage_type": event.beverage_type,
            "is_blind": event.is_blind,
            "status": event.status,
            "host_name": event.host_name,
            "event_type": event.event_type,
            "event_mode": event.event_mode,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "bottles": bottles,
            "cocktails": cocktails,
            "participants": participants,
        }

    def _eager_query(self):
        return self.db.query(EventModel).options(
            joinedload(EventModel.bottles),
            joinedload(EventModel.cocktails),
            joinedload(EventModel.participants)
            .joinedload(EventParticipantModel.tastings),
            joinedload(EventModel.participants)
            .joinedload(EventParticipantModel.cocktail_ratings),
        )

    def get_by_id(self, event_id: str) -> dict | None:
        event = self._eager_query().filter(EventModel.id == event_id).first()
        if event is None:
            return None
        return self._event_to_dict(event)

    def get_all(self) -> list[dict]:
        events = self._eager_query().order_by(EventModel.created_at.desc()).all()
        return [self._event_to_dict(e) for e in events]

    def create(self, event_data: dict) -> dict:
        event_id = event_data.get("event_id", str(uuid.uuid4()))
        event = EventModel(
            id=event_id,
            name=event_data["name"],
            beverage_type=event_data.get("beverage_type", "whiskey"),
            is_blind=event_data.get("is_blind", False),
            status=event_data.get("status", "setup"),
            host_name=event_data.get("host_name", ""),
            event_type=event_data.get("event_type", "bottle"),
            event_mode=event_data.get("event_mode", "standard"),
        )
        self.db.add(event)

        # Add bottles
        for i, bottle in enumerate(event_data.get("bottles", [])):
            eb = EventBottleModel(
                event_id=event_id,
                bottle_id=int(bottle["bottle_id"]),
                bottle_name=bottle.get("bottle_name", ""),
                blind_number=bottle.get("blind_number", i + 1),
            )
            self.db.add(eb)

        # Add cocktails
        for cocktail in event_data.get("cocktails", []):
            ec = EventCocktailModel(
                event_id=event_id,
                cocktail_name=cocktail["cocktail_name"],
                recipe_id=int(cocktail["recipe_id"]) if cocktail.get("recipe_id") else None,
                bartender=cocktail.get("bartender"),
                blind_number=cocktail.get("blind_number"),
            )
            self.db.add(ec)

        self.db.commit()
        return self.get_by_id(event_id)

    def update(self, event_id: str, event_data: dict) -> dict:
        event = self.db.get(EventModel, event_id)
        if event is None:
            raise ValueError(f"Event {event_id} not found")

        for key in ["name", "beverage_type", "is_blind", "status", "host_name",
                     "event_type", "event_mode"]:
            if key in event_data:
                setattr(event, key, event_data[key])

        self.db.commit()
        return self.get_by_id(event_id)

    def delete(self, event_id: str) -> bool:
        event = self.db.get(EventModel, event_id)
        if event is None:
            return False
        self.db.delete(event)
        self.db.commit()
        return True

    def update_status(self, event_id: str, status: str) -> dict:
        event = self.db.get(EventModel, event_id)
        if event is None:
            raise ValueError(f"Event {event_id} not found")
        event.status = status
        self.db.commit()
        return self.get_by_id(event_id)

    def add_participant(self, event_id: str, participant_data: dict) -> dict:
        participant_id = participant_data.get("participant_id", str(uuid.uuid4()))
        participant = EventParticipantModel(
            id=participant_id,
            event_id=event_id,
            name=participant_data["name"],
        )
        self.db.add(participant)
        self.db.commit()
        return {
            "participant_id": participant_id,
            "participant_name": participant.name,
            "tastings": [],
            "cocktail_ratings": [],
        }

    def add_tasting(self, participant_id: str, tasting_data: dict) -> dict:
        tasting = EventTastingModel(
            participant_id=participant_id,
            bottle_id=int(tasting_data["bottle_id"]),
            tasting_data=tasting_data.get("tasting_data", {}),
        )
        self.db.add(tasting)
        self.db.commit()
        return {
            "bottle_id": str(tasting.bottle_id),
            "tasting_data": tasting.tasting_data,
        }

    def add_cocktail_rating(
        self, participant_id: str, cocktail_name: str, score: float, notes: str | None = None
    ) -> dict:
        # Check for existing rating (update if exists)
        existing = (
            self.db.query(EventCocktailRatingModel)
            .filter_by(participant_id=participant_id, cocktail_name=cocktail_name)
            .first()
        )
        if existing:
            existing.score = score
            existing.notes = notes
        else:
            rating = EventCocktailRatingModel(
                participant_id=participant_id,
                cocktail_name=cocktail_name,
                score=score,
                notes=notes,
            )
            self.db.add(rating)
        self.db.commit()
        return {
            "cocktail_name": cocktail_name,
            "score": score,
            "notes": notes,
        }

    def add_bottle_to_event(self, event_id: str, bottle_data: dict) -> dict:
        eb = EventBottleModel(
            event_id=event_id,
            bottle_id=int(bottle_data["bottle_id"]),
            bottle_name=bottle_data.get("bottle_name", ""),
            blind_number=bottle_data.get("blind_number"),
        )
        self.db.add(eb)
        self.db.commit()
        return self.get_by_id(event_id)

    def add_cocktail_to_event(self, event_id: str, cocktail_data: dict) -> dict:
        ec = EventCocktailModel(
            event_id=event_id,
            cocktail_name=cocktail_data["cocktail_name"],
            recipe_id=int(cocktail_data["recipe_id"]) if cocktail_data.get("recipe_id") else None,
            bartender=cocktail_data.get("bartender"),
            blind_number=cocktail_data.get("blind_number"),
        )
        self.db.add(ec)
        self.db.commit()
        return self.get_by_id(event_id)

    def remove_cocktail_from_event(self, event_id: str, cocktail_name: str) -> bool:
        result = (
            self.db.query(EventCocktailModel)
            .filter(
                EventCocktailModel.event_id == event_id,
                EventCocktailModel.cocktail_name == cocktail_name,
            )
            .delete()
        )
        self.db.commit()
        return result > 0
