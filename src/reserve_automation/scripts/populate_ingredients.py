"""Populate the ingredient tree using LLM-guided taxonomy building.

Connects to the Reserve API and uses the LLM gateway to intelligently build out
a cocktail ingredient taxonomy over multiple rounds.

Usage:
    uv run populate-ingredients --target prod
    uv run populate-ingredients --target 192.168.1.100:8000
    uv run populate-ingredients --target prod --prompt "focus on rum subcategories"
    uv run populate-ingredients --target prod --max-rounds 10
    uv run populate-ingredients --target prod --dry-run
    uv run populate-ingredients --target prod --cleanup
    uv run populate-ingredients --target prod --cleanup --dry-run
"""

import argparse
import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from ..core.config import Config
from ..llm import LLMGateway
from ..llm.response_parser import LLMResponseParser

SYSTEM_PROMPT = """\
You are a bartender and spirits expert building a cocktail ingredient taxonomy.

You will be given the current ingredient tree and asked to expand it. Return a JSON array
of ingredients to add.

## Ingredient Types

You can add two types of entries:

**Categories** — organizational nodes in the tree (e.g. "Bourbon", "Aromatic Bitters")
- Only require "name" and "parent"

**Products** — specific, purchasable items (e.g. "Angostura Aromatic Bitters", "Luxardo Maraschino")
- Include additional fields: "abv", "notes"
- Set "is_product" to true

By default, focus on building out the category structure. Only add specific products when
the user's guidance asks for them (e.g. "add common bitters products", "fill in popular
bourbon brands").

## Depth Rules
- Go deep enough for meaningful distinctions (e.g. Whiskey > American Whiskey > Bourbon)
- Stop before overly granular categories (no "Small Batch Bourbon" as a category)
- Depth varies by category — vodka is relatively flat, whiskey and rum are deep
- Focus on types a bartender would recognize as distinct categories

## Taxonomy Guidelines
- Top-level: Spirits, Liqueurs, Wines & Fortified, Beer & Cider, Mixers, Bitters,
  Sweeteners, Dairy & Eggs, Fruits & Juices, Garnishes, Ice, Syrups, Other
- Use standard bartending terminology
- Aim for 10-20 new ingredients per round
- Don't repeat ingredients already in the tree
- Parent must either be null (top-level) or an ingredient that already exists in the tree
  OR one you're adding in this same batch (added earlier in the array)

## Output Format
Return ONLY a JSON array, no other text:
[
  {"name": "Spirits", "parent": null},
  {"name": "Whiskey", "parent": "Spirits"},
  {"name": "Bourbon", "parent": "American Whiskey"},
  {"name": "Angostura Aromatic Bitters", "parent": "Aromatic Bitters", "is_product": true, "abv": 44.7, "notes": "The classic cocktail bitters"}
]
"""

CLEANUP_SYSTEM_PROMPT = """\
You are a bartender and spirits expert reviewing a cocktail ingredient taxonomy for quality.

You will be given a flat list of all ingredients with their IDs and parent names.
Identify ingredients that should be deleted: duplicates, junk entries, misspellings,
nonsensical names, or anything that doesn't belong in a bartender's ingredient taxonomy.

Rules:
- When two ingredients are duplicates, keep the one with the better/cleaner name and delete the other
- If a parent and child are essentially the same thing, delete the child
- Be conservative — only flag things that are clearly wrong or duplicated
- Do NOT delete things just because they're obscure — if it's a real ingredient category, keep it

You MUST return ONLY a JSON array, with no other text before or after it.
If nothing needs deleting: []
If things need deleting: ["id1", "id2", "id3"]
"""

FILTER_SPEC_SYSTEM_PROMPT = """\
You are a filter interpreter. Given a cleanup instruction, extract the filter criteria as JSON.

Return ONLY a JSON object with these optional fields:
- "name_contains": string that must appear in the ingredient name (case-insensitive)
- "name_not_contains": string that must NOT appear in the ingredient name

Examples:
- "delete everything with chilled in the name" → {"name_contains": "chilled"}
- "remove items that say old or stale but keep everything else" → {"name_contains": "old"}
- "get rid of all the chilled items but nothing that doesn't have chilled in the name" → {"name_contains": "chilled"}

If the instruction is too complex to express as a simple name filter, return: {}
"""


def build_tree_text(tree: list, indent: int = 0) -> str:
    """Format ingredient tree as indented text for LLM context."""
    lines = []
    for node in tree:
        lines.append("  " * indent + f"- {node['name']}")
        if node.get("children"):
            lines.append(build_tree_text(node["children"], indent + 1))
    return "\n".join(lines)


def build_flat_text(ingredients: list) -> str:
    """Format flat ingredient list as text for LLM context (includes IDs)."""
    lines = []
    for ing in ingredients:
        parent = ing.get("parent") or "(top-level)"
        lines.append(f"  id={ing['id']} name={ing['name']!r} parent={parent!r}")
    return "\n".join(lines)


PROD_URL = "https://reserve.teamsmith.xyz"


def resolve_target(target: str) -> tuple[str, bool]:
    """Resolve target to (base_url, is_prod)."""
    if target == "prod":
        return PROD_URL, True
    if target.startswith("http://") or target.startswith("https://"):
        return target, target == PROD_URL
    return f"http://{target}", False


def get_headers(is_prod: bool) -> dict:
    headers = {"Content-Type": "application/json"}
    if is_prod:
        cf_id = os.environ.get("CF_ACCESS_CLIENT_ID")
        cf_secret = os.environ.get("CF_ACCESS_CLIENT_SECRET")
        if not cf_id or not cf_secret:
            logger.error("Prod target requires CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET env vars")
            sys.exit(1)
        headers["CF-Access-Client-Id"] = cf_id
        headers["CF-Access-Client-Secret"] = cf_secret
    return headers


async def fetch_tree(client: httpx.AsyncClient) -> list:
    """Fetch current ingredient tree from the API."""
    resp = await client.get("/api/v1/ingredients", params={"flat": "false"})
    resp.raise_for_status()
    return resp.json()


async def fetch_flat(client: httpx.AsyncClient) -> list:
    """Fetch flat ingredient list from the API."""
    resp = await client.get("/api/v1/ingredients", params={"flat": "true"})
    resp.raise_for_status()
    return resp.json()


OPTIONAL_FIELDS = ("abv", "cost", "volume_ml", "notes")


async def create_ingredient(client: httpx.AsyncClient, item: dict) -> dict | None:
    """Create an ingredient via the API. Returns the created ingredient or None if skipped."""
    payload = {"name": item["name"]}
    if item.get("parent"):
        payload["parent"] = item["parent"]
    for field in OPTIONAL_FIELDS:
        if item.get(field) is not None:
            payload[field] = item[field]
    try:
        resp = await client.post("/api/v1/ingredients", json=payload)
        if resp.status_code == 409:
            return None
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning(f"Failed to create '{item['name']}': HTTP {e.response.status_code} - {e.response.text}")
        return None


async def delete_ingredient(client: httpx.AsyncClient, ingredient_id: str) -> bool:
    """Delete an ingredient by ID. Returns True if deleted."""
    try:
        resp = await client.delete(f"/api/v1/ingredients/{ingredient_id}")
        if resp.status_code == 409:
            logger.warning(f"Cannot delete {ingredient_id}: has children or is referenced by a recipe")
            return False
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as e:
        logger.warning(f"Failed to delete {ingredient_id}: HTTP {e.response.status_code} - {e.response.text}")
        return False


def collect_names(tree: list) -> set[str]:
    """Collect all ingredient names (lowercased) from a tree into a flat set."""
    names = set()
    for node in tree:
        names.add(node["name"].lower())
        if node.get("children"):
            names.update(collect_names(node["children"]))
    return names


async def run_round(
    client: httpx.AsyncClient,
    gateway: LLMGateway,
    round_num: int,
    guidance: str | None,
    dry_run: bool,
) -> tuple[int, int]:
    """Run one round of taxonomy building. Returns (created, skipped) counts."""
    tree = await fetch_tree(client)
    existing_names_lower = collect_names(tree)

    tree_text = build_tree_text(tree) if tree else "(empty — start with top-level categories)"
    tree_count = len(existing_names_lower)

    prompt_parts = [f"Current ingredient tree ({tree_count} ingredients):\n{tree_text}"]
    if guidance:
        prompt_parts.append(f"\nGuidance: {guidance}")
    prompt_parts.append("\nAnalyze the tree and suggest the next batch of ingredients to add.")
    prompt = "\n".join(prompt_parts)

    logger.info(f"Round {round_num}: {tree_count} existing ingredients, requesting suggestions...")

    response = await gateway.complete(
        task_type="web_research",
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=4000,
        temperature=0.4,
    )

    data = LLMResponseParser.safe_parse_json(response.content, context="ingredient suggestions")
    if not data:
        logger.error(f"Round {round_num}: Failed to parse LLM response")
        return 0, 0

    if not isinstance(data, list):
        logger.error(f"Round {round_num}: Expected JSON array, got {type(data).__name__}")
        return 0, 0

    logger.info(f"Round {round_num}: LLM suggested {len(data)} ingredients")

    created = 0
    skipped = 0

    for item in data:
        if not isinstance(item, dict) or "name" not in item:
            logger.warning(f"Skipping malformed item: {item}")
            skipped += 1
            continue

        name = item["name"].strip()
        parent = item.get("parent")
        if isinstance(parent, str):
            parent = parent.strip() or None

        if name.lower() in existing_names_lower:
            logger.debug(f"  Skip (exists): {name}")
            skipped += 1
            continue

        is_product = item.get("is_product", False)
        label = f"{'[P] ' if is_product else ''}{name}"
        parent_label = f" (under {parent})" if parent else " (top-level)"

        if dry_run:
            print(f"  [DRY RUN] Would create: {label}{parent_label}")
            created += 1
            existing_names_lower.add(name.lower())
            continue

        result = await create_ingredient(client, item)
        if result:
            print(f"  Created: {label}{parent_label}")
            created += 1
            existing_names_lower.add(name.lower())
        else:
            logger.warning(f"  Skipped (API rejected): {name}")
            skipped += 1

    return created, skipped


async def run_cleanup(
    client: httpx.AsyncClient,
    gateway: LLMGateway,
    dry_run: bool,
    guidance: str | None = None,
) -> tuple[int, int]:
    """Ask the LLM to identify junk/duplicate ingredients, confirm, then delete."""
    ingredients = await fetch_flat(client)
    id_to_name = {ing["id"]: ing["name"] for ing in ingredients}

    flat_text = build_flat_text(ingredients)
    logger.info(f"Cleanup: reviewing {len(ingredients)} ingredients...")

    to_delete: list[str] = []

    if guidance:
        # Step 1: ask LLM to interpret the guidance into a simple filter spec
        spec_resp = await gateway.complete(
            task_type="web_research",
            prompt=f"Instruction: {guidance}",
            system=FILTER_SPEC_SYSTEM_PROMPT,
            max_tokens=200,
            temperature=0.0,
        )
        spec = LLMResponseParser.safe_parse_json(spec_resp.content, context="filter spec")
        logger.info(f"Cleanup: filter spec = {spec}")

        if spec and (spec.get("name_contains") or spec.get("name_not_contains")):
            # Step 2: apply the filter in Python — guaranteed correct
            must_have = (spec.get("name_contains") or "").lower()
            must_not = (spec.get("name_not_contains") or "").lower()
            for ing in ingredients:
                name_lower = ing["name"].lower()
                if must_have and must_have not in name_lower:
                    continue
                if must_not and must_not in name_lower:
                    continue
                to_delete.append(ing["id"])
            logger.info(f"Cleanup: Python filter matched {len(to_delete)} ingredients")
        else:
            # Spec too complex for simple filter — fall back to LLM with full list
            logger.info("Cleanup: guidance too complex for simple filter, falling back to LLM")
            prompt = f"{guidance}\n\nIngredient list ({len(ingredients)} total):\n{flat_text}"
            response = await gateway.complete(
                task_type="web_research",
                prompt=prompt,
                system=CLEANUP_SYSTEM_PROMPT,
                max_tokens=8000,
                temperature=0.0,
            )
            data = LLMResponseParser.safe_parse_json(response.content, context="cleanup")
            if data is None:
                logger.error(f"Cleanup: Failed to parse LLM response. Raw:\n{response.content[:500]}")
                return 0, 0
            to_delete = data if isinstance(data, list) else []
    else:
        # No guidance — full LLM semantic cleanup
        prompt = f"Ingredient list ({len(ingredients)} total):\n{flat_text}\n\nIdentify any duplicates, junk entries, or errors to delete."
        response = await gateway.complete(
            task_type="web_research",
            prompt=prompt,
            system=CLEANUP_SYSTEM_PROMPT,
            max_tokens=8000,
            temperature=0.0,
        )
        data = LLMResponseParser.safe_parse_json(response.content, context="cleanup")
        if data is None:
            logger.error(f"Cleanup: Failed to parse LLM response. Raw:\n{response.content[:500]}")
            return 0, 0
        to_delete = data if isinstance(data, list) else []

    if not to_delete:
        print("Nothing to clean up.")
        return 0, 0

    # Show proposed deletions
    print(f"\nProposing to delete {len(to_delete)} ingredient(s):")
    for ingredient_id in to_delete:
        name = id_to_name.get(ingredient_id, f"<unknown id: {ingredient_id}>")
        print(f"  - {name} (id={ingredient_id})")

    if dry_run:
        print("\n[DRY RUN] Stopping here — run without --dry-run to confirm and delete.")
        return len(to_delete), 0

    # Confirm before deleting
    print()
    answer = input(f"Delete these {len(to_delete)} ingredient(s)? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return 0, 0

    deleted = 0
    failed = 0

    for ingredient_id in to_delete:
        name = id_to_name.get(ingredient_id, f"<unknown id: {ingredient_id}>")
        if await delete_ingredient(client, ingredient_id):
            print(f"  Deleted: {name}")
            deleted += 1
        else:
            failed += 1

    return deleted, failed


async def main():
    parser = argparse.ArgumentParser(description="Populate ingredient tree using LLM")
    parser.add_argument("--prompt", type=str, default=None, help="Guidance for the LLM")
    parser.add_argument("--max-rounds", type=int, default=5, help="Number of rounds (default: 5)")
    parser.add_argument("--dry-run", action="store_true", help="Show suggestions without making changes")
    parser.add_argument("--cleanup", action="store_true", help="Delete duplicates/junk instead of adding ingredients")
    parser.add_argument(
        "--target", required=True,
        help="'prod', or a host/IP[:port] (e.g. 192.168.1.50:8000)",
    )
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level: <8}</level> | {message}")

    base_url, is_prod = resolve_target(args.target)
    headers = get_headers(is_prod)

    print(f"Target: {base_url}")
    mode = "CLEANUP" if args.cleanup else "ADD"
    if args.dry_run:
        mode += " (DRY RUN)"
    print(f"Mode: {mode}")
    if args.prompt:
        print(f"Guidance: {args.prompt}")
    if not args.cleanup:
        print(f"Rounds: {args.max_rounds}")
    print()

    config = Config.load()
    gateway = LLMGateway(config.llm)

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0) as client:
        try:
            resp = await client.get("/api/v1/health")
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Cannot reach API at {base_url}: {e}")
            sys.exit(1)

        if args.cleanup:
            deleted, failed = await run_cleanup(client, gateway, args.dry_run, args.prompt)
            print(f"\nCleanup: {deleted} deleted, {failed} failed")
            return

        total_created = 0
        total_skipped = 0

        for round_num in range(1, args.max_rounds + 1):
            print(f"\n{'='*60}")
            print(f"Round {round_num}/{args.max_rounds}")
            print(f"{'='*60}")

            try:
                created, skipped = await run_round(
                    client, gateway, round_num, args.prompt, args.dry_run
                )
                total_created += created
                total_skipped += skipped
                print(f"\nRound {round_num} summary: {created} created, {skipped} skipped")

                if created == 0:
                    print("No new ingredients created — stopping early.")
                    break

            except Exception as e:
                logger.error(f"Round {round_num} failed: {e}")
                import traceback
                traceback.print_exc()
                break

        print(f"\n{'='*60}")
        print(f"TOTAL: {total_created} created, {total_skipped} skipped")
        print(f"{'='*60}")


def main_cli():
    """Sync entry point for pyproject.toml [project.scripts]."""
    asyncio.run(main())


if __name__ == "__main__":
    main_cli()
