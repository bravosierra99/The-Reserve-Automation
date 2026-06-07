"""Interactive agent for The Reserve - talks to local LM Studio model and manages your collection.

Usage:
    uv run reserve-agent --target local
    uv run reserve-agent --target prod
    uv run reserve-agent --target 192.168.1.100:8000
    uv run reserve-agent --target prod --model qwen/qwen2.5-7b-instruct
    uv run reserve-agent --target prod --model lmstudio-community/meta-llama-3.1-8b-instruct-gguf
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from ..core.config import Config

PROD_URL = "https://reserve.teamsmith.xyz"
LOCAL_URL = "http://localhost:8000"

SYSTEM_PROMPT = """\
You are a personal assistant for "The Reserve" — a spirits collection and cocktail recipe manager.

## Your Capabilities
You can manage the user's spirits collection and cocktail recipes by calling tools against the Reserve API.
You also have web search to look up information about spirits, cocktails, and recipes.

## The Reserve Application
The Reserve tracks:
- **Bottles**: A personal spirits collection (whiskeys, wines, gins, rums, tequilas, vodkas, etc.)
- **Ingredients**: A hierarchical taxonomy of cocktail ingredients (categories + specific products)
- **Cocktails**: Saved cocktail recipes with ingredients, instructions, glassware, method, etc.

## Key Workflows

### Adding a Cocktail
1. Search the web for the cocktail recipe (classic ratios, variations, history)
2. Call list_ingredients (flat=true) to get ALL existing ingredients with their exact names
3. For each ingredient in the recipe: find it in the existing list (case-insensitive match), use the exact name as it appears in the list
4. For any ingredient that doesn't exist yet: create its full parent chain first, then the ingredient itself
5. Create the cocktail using the exact ingredient names from the taxonomy

### Adding a Bottle
1. Search the web for the bottle (producer, ABV, year, region, tasting notes, price)
2. Save the bottle with all fields you can find

### Adding Ingredients
- ALWAYS call list_ingredients first and match names case-insensitively against the existing list
- Use the EXACT casing of names already in the list — never create a variant with different capitalisation
- Create parent categories before their children
- Use standard bartending terminology

## Navigating the Ingredient Taxonomy
Use the tree navigation tools to understand where ingredients belong — do not guess at parents.

Recommended approach:
1. Use search_ingredients to find a relevant category (e.g. "Liqueurs", "Rum", "Bitters")
2. If found, use get_ingredient_descendants with its ID to see everything already under it
3. Place the new ingredient under the most specific correct parent that exists
4. If a needed intermediate category is missing, create it first before creating the child
5. Use list_ingredients(flat=true) when you need to check for duplicates across the whole tree

## Ingredient Fields
- name (required), parent (name of parent ingredient or null for top-level)
- abv (float), notes (str), is_product (bool — true only for specific purchasable products like "Angostura Aromatic Bitters")

## Cocktail Fields
- name (required), description, ingredients (list with ingredient name, amount, unit, notes, optional)
- instructions (ordered list of steps), garnish, glassware, method (shaken/stirred/built/blended)
- style (classic/tiki/modern/sour/highball), serving_size

## Bottle Fields
- producer (required), name (required), type (required: wine/whiskey/vodka/gin/rum/tequila/brandy/other)
- year, beverage_type (e.g. "Bourbon", "Single Malt Scotch", "Cabernet Sauvignon")
- country, region, variety, abv, proof, age_statement, price, inventory, purchase_source

## Important Notes
- Ingredient "ingredient" field in cocktail recipes is the ingredient NAME (string), not an ID
- When creating a cocktail, use ingredient names that exist in the ingredient tree
- Units: oz, ml, dash, splash, piece, wedge, barspoon, tsp, tbsp
- Always be thorough — fill in as many fields as you can find
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information about spirits, cocktails, recipes, distilleries, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a webpage for more detailed information",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_ingredients",
            "description": "Get the full ingredient taxonomy. Use flat=true for a complete flat list (good for duplicate checking). Use flat=false for the nested tree (good for understanding top-level structure). Prefer search_ingredients or get_ingredient_descendants to explore specific branches rather than dumping the whole tree.",
            "parameters": {
                "type": "object",
                "properties": {
                    "flat": {"type": "boolean", "description": "Return flat list (true) or nested tree (false, default)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_ingredients",
            "description": "Search ingredients by name. Returns matching nodes with their children. Use this to find a specific category and see what's already under it before adding children.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Name search query"}
                },
                "required": ["q"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_ingredient_descendants",
            "description": "Get all descendants (children, grandchildren, etc.) of an ingredient by its ID. Use this to fully explore a subtree — e.g. find everything under 'Spirits' or 'Liqueurs' before deciding where a new ingredient belongs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ingredient_id": {"type": "string", "description": "Ingredient ID (from list_ingredients or search_ingredients)"}
                },
                "required": ["ingredient_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_ingredient",
            "description": "Create a new ingredient (category or product) in the taxonomy",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Ingredient name"},
                    "parent": {"type": "string", "description": "Parent ingredient name (null for top-level)"},
                    "abv": {"type": "number", "description": "ABV percentage (for products)"},
                    "notes": {"type": "string", "description": "Notes about the ingredient"},
                    "is_product": {"type": "boolean", "description": "True if this is a specific purchasable product"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_ingredient",
            "description": "Delete an ingredient by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "ingredient_id": {"type": "string", "description": "Ingredient ID"}
                },
                "required": ["ingredient_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_cocktails",
            "description": "List all cocktails in the collection",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_cocktails",
            "description": "Search cocktails by name or ingredient",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Search query"}
                },
                "required": ["q"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_cocktail",
            "description": "Get full details of a specific cocktail by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "cocktail_id": {"type": "string", "description": "Cocktail ID"}
                },
                "required": ["cocktail_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_cocktail",
            "description": "Create a new cocktail recipe",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ingredient": {"type": "string", "description": "Ingredient name from the taxonomy"},
                                "amount": {"type": "number"},
                                "unit": {"type": "string", "description": "oz, ml, dash, splash, piece, wedge, barspoon, tsp, tbsp"},
                                "notes": {"type": "string"},
                                "optional": {"type": "boolean"}
                            },
                            "required": ["ingredient"]
                        }
                    },
                    "instructions": {"type": "array", "items": {"type": "string"}},
                    "garnish": {"type": "string"},
                    "glassware": {"type": "string"},
                    "method": {"type": "string", "description": "shaken, stirred, built, blended"},
                    "style": {"type": "string", "description": "classic, tiki, modern, sour, highball"},
                    "serving_size": {"type": "integer"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_cocktail",
            "description": "Update an existing cocktail recipe",
            "parameters": {
                "type": "object",
                "properties": {
                    "cocktail_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "ingredients": {"type": "array", "items": {"type": "object"}},
                    "instructions": {"type": "array", "items": {"type": "string"}},
                    "garnish": {"type": "string"},
                    "glassware": {"type": "string"},
                    "method": {"type": "string"},
                    "style": {"type": "string"},
                    "serving_size": {"type": "integer"}
                },
                "required": ["cocktail_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_cocktail",
            "description": "Delete a cocktail by ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "cocktail_id": {"type": "string"}
                },
                "required": ["cocktail_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_bottles",
            "description": "List all bottles in the collection",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_bottle",
            "description": "Add a new bottle to the collection",
            "parameters": {
                "type": "object",
                "properties": {
                    "producer": {"type": "string", "description": "Distillery or winery name"},
                    "name": {"type": "string", "description": "Product name"},
                    "type": {"type": "string", "description": "wine, whiskey, vodka, gin, rum, tequila, brandy, or other"},
                    "year": {"type": "integer"},
                    "beverage_type": {"type": "string", "description": "e.g. Bourbon, Single Malt Scotch, Cabernet Sauvignon"},
                    "country": {"type": "string"},
                    "region": {"type": "string"},
                    "variety": {"type": "string", "description": "Grape variety (wines)"},
                    "abv": {"type": "number"},
                    "proof": {"type": "number"},
                    "age_statement": {"type": "integer"},
                    "price": {"type": "number"},
                    "inventory": {"type": "integer", "description": "Bottles owned (default 1)"},
                    "purchase_source": {"type": "string"},
                    "purchase_link": {"type": "string"},
                    "mash_bill": {"type": "string"},
                    "barrel_type": {"type": "string"}
                },
                "required": ["producer", "name", "type"]
            }
        }
    },
]


def resolve_target(target: str) -> tuple[str, bool]:
    if target == "prod":
        return PROD_URL, True
    if target == "local":
        return LOCAL_URL, False
    if target.startswith("http://") or target.startswith("https://"):
        return target, target.startswith(PROD_URL)
    return f"http://{target}", False


def get_headers(is_prod: bool) -> dict:
    headers = {"Content-Type": "application/json"}
    if is_prod:
        cf_id = os.environ.get("CF_ACCESS_CLIENT_ID")
        cf_secret = os.environ.get("CF_ACCESS_CLIENT_SECRET")
        if not cf_id or not cf_secret:
            logger.error("Prod requires CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET")
            sys.exit(1)
        headers["CF-Access-Client-Id"] = cf_id
        headers["CF-Access-Client-Secret"] = cf_secret
    return headers


class ReserveTools:
    """Executes tool calls against the Reserve API and web."""

    def __init__(self, api_client: httpx.AsyncClient):
        self.api = api_client
        from ..llm.tool_executor import ToolExecutor
        self.web = ToolExecutor()

    async def _get_flat_ingredients(self) -> list[dict]:
        """Fetch flat ingredient list for case-insensitive lookups."""
        r = await self.api.get("/api/v1/ingredients", params={"flat": "true"})
        r.raise_for_status()
        return r.json()

    async def execute(self, tool_name: str, args: dict) -> dict:
        try:
            if tool_name == "web_search":
                return self.web.execute("web_search", args)
            elif tool_name == "web_fetch":
                return self.web.execute("web_fetch", args)
            elif tool_name == "list_ingredients":
                flat = args.get("flat", False)
                r = await self.api.get("/api/v1/ingredients", params={"flat": str(flat).lower()})
                r.raise_for_status()
                return {"ingredients": r.json()}
            elif tool_name == "search_ingredients":
                r = await self.api.get("/api/v1/ingredients/search", params={"q": args["q"]})
                r.raise_for_status()
                return {"results": r.json()}
            elif tool_name == "get_ingredient_descendants":
                r = await self.api.get(f"/api/v1/ingredients/{args['ingredient_id']}/descendants")
                r.raise_for_status()
                descendants = r.json()
                return {"descendants": descendants, "count": len(descendants)}
            elif tool_name == "create_ingredient":
                # Fetch existing ingredients for case-insensitive matching
                existing = await self._get_flat_ingredients()
                name_map = {ing["name"].lower(): ing["name"] for ing in existing}

                # Check if ingredient already exists (case-insensitive)
                canonical_name = name_map.get(args["name"].lower())
                if canonical_name:
                    return {"skipped": True, "reason": f"already exists as '{canonical_name}'"}

                payload = {"name": args["name"]}

                # Fix parent casing if needed
                if args.get("parent"):
                    canonical_parent = name_map.get(args["parent"].lower())
                    payload["parent"] = canonical_parent if canonical_parent else args["parent"]

                for f in ("abv", "notes", "is_product"):
                    if args.get(f) is not None:
                        payload[f] = args[f]

                r = await self.api.post("/api/v1/ingredients", json=payload)
                if r.status_code == 409:
                    return {"skipped": True, "reason": f"'{args['name']}' already exists"}
                r.raise_for_status()
                return {"created": r.json()}
            elif tool_name == "delete_ingredient":
                r = await self.api.delete(f"/api/v1/ingredients/{args['ingredient_id']}")
                r.raise_for_status()
                return {"deleted": True}
            elif tool_name == "list_cocktails":
                r = await self.api.get("/api/v1/cocktails")
                r.raise_for_status()
                cocktails = r.json()
                return {"cocktails": cocktails, "count": len(cocktails)}
            elif tool_name == "search_cocktails":
                r = await self.api.get("/api/v1/cocktails/search", params={"q": args["q"]})
                r.raise_for_status()
                cocktails = r.json()
                return {"cocktails": cocktails, "count": len(cocktails)}
            elif tool_name == "get_cocktail":
                r = await self.api.get(f"/api/v1/cocktails/{args['cocktail_id']}")
                r.raise_for_status()
                return r.json()
            elif tool_name == "create_cocktail":
                r = await self.api.post("/api/v1/cocktails", json=args)
                if r.status_code == 409:
                    return {"error": f"Cocktail '{args.get('name')}' already exists"}
                r.raise_for_status()
                return {"created": r.json()}
            elif tool_name == "update_cocktail":
                cocktail_id = args.pop("cocktail_id")
                r = await self.api.put(f"/api/v1/cocktails/{cocktail_id}", json=args)
                r.raise_for_status()
                return {"updated": r.json()}
            elif tool_name == "delete_cocktail":
                r = await self.api.delete(f"/api/v1/cocktails/{args['cocktail_id']}")
                r.raise_for_status()
                return {"deleted": True}
            elif tool_name == "list_bottles":
                r = await self.api.get("/api/v1/bottles/collection")
                r.raise_for_status()
                return r.json()
            elif tool_name == "save_bottle":
                payload = {"bottle": args, "force_save": True}
                r = await self.api.post("/api/v1/bottles/save", json=payload)
                r.raise_for_status()
                return {"saved": r.json()}
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except httpx.HTTPStatusError as e:
            return {"error": f"API error {e.response.status_code}: {e.response.text[:300]}"}
        except Exception as e:
            return {"error": str(e)}


def _parse_xml_tool_calls(text: str) -> list[dict]:
    """
    Parse XML-style tool calls from reasoning content.

    Handles the format some thinking models emit:
      <tool_call>
      <function=NAME>
      <parameter=KEY>VALUE</parameter>
      </function>
      </tool_call>
    """
    tool_calls = []
    call_id = 0

    for call_block in re.finditer(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL):
        block = call_block.group(1)
        fn_match = re.search(r"<function=(\w+)>(.*?)</function>", block, re.DOTALL)
        if not fn_match:
            continue

        name = fn_match.group(1)
        params_text = fn_match.group(2)

        args = {}
        for param in re.finditer(r"<parameter=(\w+)>(.*?)</parameter>", params_text, re.DOTALL):
            key = param.group(1)
            value = param.group(2).strip()
            # Try to parse as JSON value (number, bool, object), fall back to string
            try:
                args[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                args[key] = value

        call_id += 1
        tool_calls.append({
            "id": f"xml_{call_id}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args),
            }
        })

    return tool_calls


async def run_agent(base_url: str, is_prod: bool, model: str, lm_base_url: str):
    headers = get_headers(is_prod)

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0) as api_client:
        # Verify API is reachable
        try:
            r = await api_client.get("/api/v1/health")
            r.raise_for_status()
        except Exception as e:
            print(f"Cannot reach Reserve API at {base_url}: {e}")
            sys.exit(1)

        tools = ReserveTools(api_client)
        messages = []

        target_label = "PROD" if is_prod else base_url
        print("\nThe Reserve Agent")
        print(f"  API: {target_label}")
        print(f"  Model: {model}")
        print(f"  LM Studio: {lm_base_url}")
        print("\nType your request, /clear to reset context, or 'quit' to exit.\n")

        async with httpx.AsyncClient(base_url=lm_base_url, timeout=120.0) as lm_client:
            while True:
                try:
                    user_input = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nBye.")
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit", "q"):
                    print("Bye.")
                    break
                if user_input.lower() == "/clear":
                    messages.clear()
                    print("[Context cleared]\n")
                    continue

                messages.append({"role": "user", "content": user_input})

                # Agent loop: call LM → handle tool calls → repeat until final response
                iteration = 0
                max_iterations = 20

                while iteration < max_iterations:
                    iteration += 1

                    payload = {
                        "model": model,
                        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                        "tools": TOOLS,
                        "temperature": 0.3,
                        "max_tokens": 4000,
                    }

                    try:
                        resp = await lm_client.post("/chat/completions", json=payload)
                        resp.raise_for_status()
                    except httpx.RequestError as e:
                        print(f"\n[Error] Cannot reach LM Studio at {lm_base_url}: {e}")
                        messages.pop()  # Remove the user message we just added
                        break
                    except httpx.HTTPStatusError as e:
                        print(f"\n[Error] LM Studio returned {e.response.status_code}: {e.response.text[:300]}")
                        messages.pop()
                        break

                    data = resp.json()
                    message = data["choices"][0]["message"]
                    finish_reason = data["choices"][0].get("finish_reason")
                    tool_calls = message.get("tool_calls") or []

                    # Show reasoning content if present (thinking models)
                    reasoning = message.get("reasoning_content", "")
                    if reasoning:
                        print(f"\n[thinking] {reasoning.strip()}\n", flush=True)

                    # Fallback: parse XML tool calls from reasoning if tool_calls is empty
                    if not tool_calls and reasoning:
                        tool_calls = _parse_xml_tool_calls(reasoning)
                        if tool_calls:
                            finish_reason = "tool_calls"

                    if tool_calls and finish_reason == "tool_calls":
                        # Add assistant message with tool calls to history
                        messages.append({
                            "role": "assistant",
                            "content": message.get("content") or "",
                            "tool_calls": tool_calls
                        })

                        # Execute each tool
                        for tc in tool_calls:
                            name = tc["function"]["name"]
                            try:
                                args = json.loads(tc["function"]["arguments"])
                            except json.JSONDecodeError:
                                args = {}

                            print(f"  [{name}] ", end="", flush=True)
                            start = time.time()
                            result = await tools.execute(name, args)
                            elapsed = time.time() - start

                            # Print a brief summary
                            if "error" in result:
                                print(f"ERROR: {result['error']}")
                            elif "created" in result:
                                item = result["created"]
                                print(f"created '{item.get('name', item.get('id', '?'))}' ({elapsed:.1f}s)")
                            elif "skipped" in result:
                                print(f"skipped — {result.get('reason', 'already exists')}")
                            elif "saved" in result:
                                print(f"saved ({elapsed:.1f}s)")
                            elif "deleted" in result:
                                print(f"deleted ({elapsed:.1f}s)")
                            elif "updated" in result:
                                item = result["updated"]
                                print(f"updated '{item.get('name', '?')}' ({elapsed:.1f}s)")
                            elif "ingredients" in result:
                                count = len(result["ingredients"]) if isinstance(result["ingredients"], list) else "?"
                                print(f"{count} ingredients ({elapsed:.1f}s)")
                            elif "bottles" in result:
                                print(f"{result.get('count', '?')} bottles ({elapsed:.1f}s)")
                            elif "cocktails" in result:
                                print(f"{len(result.get('cocktails', []))} cocktails ({elapsed:.1f}s)")
                            elif "results" in result:
                                print(f"{len(result['results'])} results ({elapsed:.1f}s)")
                            else:
                                print(f"done ({elapsed:.1f}s)")

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": json.dumps(result)
                            })

                        continue  # Go back for LLM's next response

                    # Final response (no tool calls)
                    content = message.get("content") or ""
                    messages.append({"role": "assistant", "content": content})
                    if content:
                        print(f"\nAssistant: {content}\n")
                    elif not reasoning:
                        print("\nAssistant: (no response)\n")
                    break

                else:
                    print("[Error] Max tool iterations reached")


async def main():
    parser = argparse.ArgumentParser(description="The Reserve interactive agent")
    parser.add_argument(
        "--target", required=True,
        help="'prod', 'local', or host[:port] (e.g. 192.168.1.50:8000)"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="LM Studio model name to use (overrides config)"
    )
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="WARNING", format="<level>{level: <8}</level> | {message}")

    base_url, is_prod = resolve_target(args.target)

    config = Config.load()
    llm_config = config.llm

    # Get LM Studio base URL and default model from config
    provider_config = llm_config.get("providers", {}).get("lm_studio_agent") \
        or llm_config.get("providers", {}).get("lm_studio_text", {})
    lm_base_url = provider_config.get("base_url", "http://localhost:1234/v1")
    default_model = provider_config.get("model", "qwen/qwen3.5-9b")
    model = args.model or default_model

    await run_agent(base_url, is_prod, model, lm_base_url)


def main_cli():
    asyncio.run(main())


if __name__ == "__main__":
    main_cli()
