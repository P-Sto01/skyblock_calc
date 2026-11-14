import json
import os
import re
import base64
import gzip
import io
import struct
from decimal import Decimal, InvalidOperation
import asyncio
import aiohttp
from urllib.parse import quote

# Import helper functions from getrecipesasync (needed for recipe processing)
try:
    from getrecipesasync import checks, addname
except ImportError:
    # Fallback definitions if the module can't be imported
    def checks(out):
        """Process recipe data and extract valid recipes."""
        result = {"recipes": []}
        
        # Skip recipes with level requirements, results, or drops (not standard crafting)
        if "level" in out or "result" in out or "drops" in out:
            return result
        
        # Handle different recipe types
        recipe_type = out.get("type")
        inputs = out.get("inputs", [])
        
        if recipe_type and inputs:
            result["recipes"] = [{
                "type": recipe_type,
                "items": inputs,
                "count": out.get("count", 1),
                "duration": out.get("duration", 0)
            }]
        
        return result

    def addname(data):
        """Extract item name from NEU data."""
        return data.get("internalname", "Unknown")

# In-memory storage for recipes and prices (on-demand fetching)
_recipes_cache = {}  # item_id -> recipe dict
_prices_cache = None  # Will be a dict: item_id -> price

# Track loaded items to avoid redundant downloads
_loaded_recipe_items = set()
_prices_fetched = False

# Configuration
USE_ON_DEMAND_FETCHING = True  # Set to False to use traditional file-based loading

# ============================================================================
# ON-DEMAND FETCHING SYSTEM
# ============================================================================

async def fetch_single_recipe(item_id):
    """Fetch recipe data for a single item from the NEU API."""
    # URL-encode the item_id to handle special characters like ; (encoded as %3B)
    encoded_item_id = quote(item_id, safe='')
    url = f"https://raw.githubusercontent.com/NotEnoughUpdates/NotEnoughUpdates-REPO/master/items/{encoded_item_id}.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                # Use text() then parse JSON to handle non-JSON content-type headers
                data = json.loads(await response.text())
                if "recipe" in data:
                    out = checks(data["recipe"])
                elif "recipes" in data:
                    if data["recipes"]:
                        out = checks(data["recipes"][0])
                    else:
                        out = {"recipes": []}
                else:
                    out = {"recipes": []}
                if "level" in out or "result" in out or "drops" in out:
                    out = {"recipes": []}
                out["name"] = addname(data)
                return {item_id: out}
    except Exception:
        return None

def fetch_recipe_on_demand(item_id):
    """Synchronous wrapper for fetching a single recipe."""
    if item_id in _loaded_recipe_items:
        return _recipes_cache.get(item_id)
    
    result = asyncio.run(fetch_single_recipe(item_id))
    if result:
        _loaded_recipe_items.add(item_id)
        _recipes_cache.update(result)
        return result.get(item_id)
    return None

async def fetch_prices_async():
    """Fetch all prices from Bazaar and Auction House."""
    global _prices_cache, _prices_fetched
    
    if _prices_fetched:
        return _prices_cache
    
    bazaar_url = "https://api.hypixel.net/v2/skyblock/bazaar"
    auction_url = "https://api.hypixel.net/v2/skyblock/auctions"
    
    prices_dict = {}
    
    async with aiohttp.ClientSession() as session:
        # Fetch bazaar data
        try:
            async with session.get(bazaar_url) as response:
                if response.status == 200:
                    bazaar_data = await response.json()
                    for product_id, product in bazaar_data["products"].items():
                        quick_status = product.get("quick_status")
                        if quick_status:
                            prices_dict[product_id] = quick_status["sellPrice"]
        except Exception as e:
            print(f"Error fetching bazaar data: {e}")
        
        # Fetch auction house data
        try:
            async with session.get(auction_url) as response:
                if response.status == 200:
                    auction_data = await response.json()
                    auctions = auction_data.get("auctions", [])
                    for auction in auctions:
                        if auction.get("bin"):
                            item_bytes = auction.get("item_bytes")
                            starting_bid = auction.get("starting_bid")
                            if item_bytes and starting_bid is not None:
                                try:
                                    item_id = get_item_id(item_bytes)
                                    if item_id not in prices_dict or starting_bid < prices_dict[item_id]:
                                        prices_dict[item_id] = starting_bid
                                except Exception:
                                    continue
        except Exception as e:
            print(f"Error fetching auction data: {e}")
    
    _prices_cache = prices_dict
    _prices_fetched = True
    return prices_dict

def fetch_prices_on_demand():
    """Synchronous wrapper for fetching prices."""
    if _prices_fetched:
        return _prices_cache
    
    return asyncio.run(fetch_prices_async())

def get_recipe(item_id, force_fetch=False):
    """Get recipe for an item, fetching on-demand if needed."""
    if USE_ON_DEMAND_FETCHING:
        if force_fetch or item_id not in _loaded_recipe_items:
            result = fetch_recipe_on_demand(item_id)
            return result if result else {"recipes": []}
        return _recipes_cache.get(item_id, {"recipes": []})
    else:
        # Traditional file-based loading
        with open(recipefile) as fl:
            all_recipes = json.loads(fl.read())
        return all_recipes.get(item_id, {"recipes": []})

def get_price(item_id):
    """Get price for an item, fetching on-demand if needed."""
    if USE_ON_DEMAND_FETCHING:
        fetch_prices_on_demand()
        return _prices_cache.get(item_id)
    else:
        with open(pricefile) as fl:
            all_prices = json.loads(fl.read())
        return all_prices.get(item_id)

def get_all_recipes():
    """Get all cached recipes (for on-demand mode, returns only what's been fetched)."""
    if USE_ON_DEMAND_FETCHING:
        return _recipes_cache.copy()
    else:
        with open(recipefile) as fl:
            return json.loads(fl.read())

def get_all_prices():
    """Get all cached prices."""
    if USE_ON_DEMAND_FETCHING:
        fetch_prices_on_demand()
        return _prices_cache.copy() if _prices_cache else {}
    else:
        with open(pricefile) as fl:
            return json.loads(fl.read())

def reset_caches():
    """Reset all caches for fresh fetching."""
    global _recipes_cache, _prices_cache, _loaded_recipe_items, _prices_fetched
    _recipes_cache = {}
    _prices_cache = None
    _loaded_recipe_items = set()
    _prices_fetched = False


class PricesProxy:
    """Proxy object that fetches prices on-demand and provides dict-like access."""
    
    def __getitem__(self, key):
        if USE_ON_DEMAND_FETCHING:
            fetch_prices_on_demand()
            return _prices_cache.get(key) if _prices_cache else None
        else:
            with open(pricefile) as fl:
                all_prices = json.loads(fl.read())
            return all_prices.get(key)
    
    def get(self, key, default=None):
        result = self[key]
        return result if result is not None else default
    
    def __contains__(self, key):
        if USE_ON_DEMAND_FETCHING:
            fetch_prices_on_demand()
            return key in (_prices_cache or {})
        else:
            with open(pricefile) as fl:
                all_prices = json.loads(fl.read())
            return key in all_prices
    
    def keys(self):
        if USE_ON_DEMAND_FETCHING:
            fetch_prices_on_demand()
            return (_prices_cache or {}).keys()
        else:
            with open(pricefile) as fl:
                all_prices = json.loads(fl.read())
            return all_prices.keys()
    
    def values(self):
        if USE_ON_DEMAND_FETCHING:
            fetch_prices_on_demand()
            return (_prices_cache or {}).values()
        else:
            with open(pricefile) as fl:
                all_prices = json.loads(fl.read())
            return all_prices.values()
    
    def items(self):
        if USE_ON_DEMAND_FETCHING:
            fetch_prices_on_demand()
            return (_prices_cache or {}).items()
        else:
            with open(pricefile) as fl:
                all_prices = json.loads(fl.read())
            return all_prices.items()


class RecipesProxy:
    """Proxy object that fetches recipes on-demand and provides dict-like access."""
    
    def __getitem__(self, key):
        if USE_ON_DEMAND_FETCHING:
            result = fetch_recipe_on_demand(key)
            return result if result else {"recipes": []}
        else:
            with open(recipefile) as fl:
                all_recipes = json.loads(fl.read())
            return all_recipes.get(key, {"recipes": []})
    
    def get(self, key, default=None):
        result = self[key]
        return result if result is not None else default
    
    def __contains__(self, key):
        if USE_ON_DEMAND_FETCHING:
            fetch_recipe_on_demand(key)
            return key in _loaded_recipe_items
        else:
            with open(recipefile) as fl:
                all_recipes = json.loads(fl.read())
            return key in all_recipes


# Global proxy objects used by calculate() and other functions
prices = PricesProxy()
recipes = RecipesProxy()

def get_item_id(item_bytes):
    """Parse item_bytes to extract internal item ID using manual NBT parsing."""
    data = gzip.decompress(base64.b64decode(item_bytes))
    stream = io.BytesIO(data)

    def read(fmt):
        return struct.unpack(">" + fmt, stream.read(struct.calcsize(">" + fmt)))[0]

    def read_string():
        length = read("H")
        return stream.read(length).decode("utf-8")

    def parse_compound_value():
        """Parse a compound tag value and return dict"""
        compound = {}
        while True:
            tag_type = read("B")
            if tag_type == 0:
                break
            name = read_string()
            _, value = parse_tag_value(tag_type)
            compound[name] = value
        return compound

    def parse_tag_value(tag_type):
        """Parse a tag value given its type"""
        if tag_type == 1:  # Int
            return tag_type, read("i")
        elif tag_type == 2:  # Short
            return tag_type, read("h")
        elif tag_type == 3:  # Byte
            return tag_type, read("b")
        elif tag_type == 4:  # Float
            return tag_type, read("f")
        elif tag_type == 5:  # Double
            return tag_type, read("d")
        elif tag_type == 6:  # Long
            return tag_type, read("q")
        elif tag_type == 7:  # ByteArray
            length = read("i")
            return tag_type, stream.read(length)
        elif tag_type == 8:  # String
            return tag_type, read_string()
        elif tag_type == 9:  # List
            child_type = read("B")
            length = read("i")
            values = []
            for _ in range(length):
                _, val = parse_tag_value(child_type)
                values.append(val)
            return tag_type, values
        elif tag_type == 10:  # Compound
            return tag_type, parse_compound_value()
        elif tag_type == 11:  # IntArray
            length = read("i")
            return tag_type, [read("i") for _ in range(length)]
        elif tag_type == 12:  # LongArray
            length = read("i")
            return tag_type, [read("q") for _ in range(length)]
        return tag_type, None

    # Parse root NBT structure
    read("B")  # Root type (should be 10 for compound)
    read_string()  # Root name
    
    # Parse the root compound
    root_data = parse_compound_value()
    
    # Get items array - handle both direct tag and wrapped in "i" key
    if "i" in root_data:
        items = root_data["i"]
        if isinstance(items, list) and len(items) > 0:
            nbt_item = items[0]
        elif isinstance(items, dict):
            nbt_item = items.get("tag", items)
        else:
            nbt_item = root_data
    else:
        nbt_item = root_data
    
    # Extract the item ID
    item_id = nbt_item.get("id") if isinstance(nbt_item, dict) else None
    
    # Get ExtraAttributes for special handling
    extra_attrs = nbt_item.get("ExtraAttributes")
    if extra_attrs and isinstance(extra_attrs, dict):
        if item_id == "PET":
            pet_info_raw = extra_attrs.get("petInfo")
            if pet_info_raw:
                pet_info = json.loads(str(pet_info_raw))
                pet_type = pet_info.get("type", "")
                rarity_map = {"COMMON": 0, "UNCOMMON": 1, "RARE": 2, 
                             "EPIC": 3, "LEGENDARY": 4, "MYTHIC": 5}
                rarity = rarity_map.get(pet_info.get("tier", ""), 0)
                item_id = f"{pet_type};{rarity}"
        elif item_id == "RUNE":
            runes = extra_attrs.get("runes", {})
            if isinstance(runes, dict) and runes:
                rune_name = next(iter(runes.keys()))
                level = int(next(iter(runes.values())))
                item_id = f"{rune_name}_RUNE;{level}"
        elif item_id == "PARTY_HAT_CRAB_ANIMATED":
            color = extra_attrs.get("party_hat_color", "")
            if color:
                item_id = f"PARTY_HAT_CRAB_{str(color).upper()}_ANIMATED"
    
    return item_id

def get_price(item,amount):
    return prices[item]*amount

def calculate(item):
    """
    Calculate the best ways to obtain an item (either by buying directly or crafting).
    Returns up to 5 best distinct combinations sorted by total price.
    Each combination includes: items used, total_price, duration, and method description.
    Uses recursive exploration with memoization to find all possible paths.
    """
    from functools import lru_cache
    
    def parse_ingredient(ing_str):
        """Parse 'ITEM:amount' string into (item_id, amount) tuple."""
        parts = ing_str.split(":")
        return (parts[0], int(parts[1]))
    
    @lru_cache(maxsize=None)
    def get_best_options(item_id, visited_frozenset):
        """
        Get all possible ways to obtain an item.
        Returns list of (total_price, duration, breakdown_list) tuples.
        Each breakdown_list contains strings describing each step.
        Pruned to top 5 options per level to prevent combinatorial explosion.
        """
        results = []
        
        # Option 1: Buy directly from bazaar (if available and price > 0)
        if item_id in prices and prices[item_id] > 0:
            buy_price = prices[item_id]
            results.append((buy_price, 0, [f"Buy {item_id}"]))
        
        # Option 2: Craft from recipes (if available)
        if item_id in recipes:
            item_data = recipes[item_id]
            item_recipes = item_data.get("recipes", [])
            
            for recipe in item_recipes:
                recipe_coins = recipe.get("coins", 0)
                recipe_duration = recipe.get("duration", 0)
                ingredients = recipe.get("items", [])
                
                if not ingredients:
                    # Recipe with only coins cost
                    if recipe_coins > 0:
                        results.append((recipe_coins, recipe_duration, [f"Craft {item_id} (coins only)"]))
                    continue
                
                # Get options for each ingredient
                ingredient_option_lists = []
                valid_recipe = True
                
                for ing_str in ingredients:
                    ing_item_id, ing_amount = parse_ingredient(ing_str)
                    
                    # Skip if already in visited set (prevent infinite recursion)
                    if ing_item_id in visited_frozenset:
                        valid_recipe = False
                        break
                    
                    new_visited = visited_frozenset | {ing_item_id}
                    options = get_best_options(ing_item_id, new_visited)
                    
                    # Scale prices by amount
                    scaled_options = []
                    for price, dur, breakdown in options:
                        scaled_price = price * ing_amount
                        # Include full breakdown with indentation for nested items
                        if breakdown:
                            action_line = f"{ing_item_id}x{ing_amount} ({scaled_price/ing_amount if ing_amount > 0 else price:.0f} each): {breakdown[0]}"
                            # Add indented sub-items (skip the summary lines at the end)
                            sub_items = []
                            for line in breakdown:
                                if not line.startswith("Total "):  # Skip summary lines, they'll be recalculated
                                    sub_items.append(f"    └─ {line}")
                            scaled_breakdown = [action_line] + sub_items
                        else:
                            scaled_breakdown = [f"{ing_item_id}x{ing_amount}: Get directly"]
                        scaled_options.append((scaled_price, dur, scaled_breakdown))
                    
                    if not scaled_options:
                        valid_recipe = False
                        break
                    
                    ingredient_option_lists.append(scaled_options)
                
                if not valid_recipe or not ingredient_option_lists:
                    continue
                
                # Get the best option for each ingredient (prune to prevent explosion)
                # Keep more options to explore diverse combinations
                best_options_per_ingredient = []
                for ing_idx, ing_options in enumerate(ingredient_option_lists):
                    sorted_opts = sorted(ing_options, key=lambda x: x[0])
                    
                    # Select multiple options to ensure we capture different strategies:
                    # - Cheapest option
                    # - Buy direct option (if available)  
                    # - Second and third cheapest for variety
                    selected = []
                    
                    # Always take the cheapest option
                    if sorted_opts:
                        selected.append(sorted_opts[0])
                    
                    # Find buy_direct options (where FIRST breakdown line starts with "Buy")
                    buy_direct_opts = [o for o in sorted_opts if o[2] and o[2][0].startswith("Buy")]
                    
                    # Include cheapest buy_direct option if available
                    if buy_direct_opts:
                        cheapest_buy = min(buy_direct_opts, key=lambda x: x[0])
                        if cheapest_buy not in selected:
                            selected.append(cheapest_buy)
                    
                    # Add second and third cheapest if different from what we already have
                    for i in [1, 2]:
                        if len(sorted_opts) > i:
                            opt = sorted_opts[i]
                            if opt not in selected:
                                selected.append(opt)
                    
                    best_options_per_ingredient.append(selected)
                
                # Generate combinations only from pruned options
                from itertools import product
                
                recipe_results = []
                for combo in product(*best_options_per_ingredient):
                    total_price = sum(opt[0] for opt in combo) + recipe_coins
                    max_duration = max(opt[1] for opt in combo) + recipe_duration
                    
                    if total_price == 0:
                        continue
                    
                    # Build detailed breakdown with costs
                    breakdown = [f"Craft {item_id} (Recipe coins: ${recipe_coins:.2f})"]
                    total_ingredients_cost = 0
                    for ing_str, (price, dur, ing_breakdown) in zip(ingredients, combo):
                        breakdown.extend(ing_breakdown)
                        total_ingredients_cost += price
                    
                    breakdown.append(f"Total ingredients: ${total_ingredients_cost:.2f}")
                    breakdown.append(f"Total cost: ${total_price:.2f}")
                    
                    recipe_results.append((total_price, max_duration, breakdown))
                
                # Keep all results from this recipe (will be deduplicated later)
                results.extend(recipe_results)
        
        return results
    
    # Start the calculation
    all_options = get_best_options(item, frozenset())
    
    # Convert to result format and remove duplicates based on exact breakdown
    unique_results = {}
    for total_price, duration, breakdown in all_options:
        method = "craft" if len(breakdown) > 1 or breakdown[0].startswith("Craft") else "buy_direct"
        
        # Extract shopping list from breakdown (only base "Buy" items)
        shopping_list = {}
        for line in breakdown:
            # Handle ingredient format: "ITEMx123 (price each): Buy ITEM"
            buy_match = re.search(r'(\w+)x(\d+).*?:\s*Buy\s+(\w+)', line)
            if buy_match:
                item_id = buy_match.group(3)  # Use the captured "Buy ITEM" part
                quantity = int(buy_match.group(2))
                shopping_list[item_id] = shopping_list.get(item_id, 0) + quantity
            # Handle top-level direct purchase format: "Buy ITEM"
            elif line.startswith("Buy "):
                item_id = line[4:].strip()  # Extract item after "Buy "
                shopping_list[item_id] = shopping_list.get(item_id, 0) + 1
        
        # Use shopping list + method as unique key to avoid duplicate results
        # This ensures we keep both craft and buy_direct options even if they have similar shopping lists
        strategy = {}  # Initialize empty - no longer used for uniqueness
        key = (method, tuple(sorted(shopping_list.items())))
        
        if key not in unique_results:
            unique_results[key] = {
                "method": method,
                "total_price": total_price,
                "duration": duration,
                "shopping_list": shopping_list,
                "strategy": strategy  # Empty dict since we removed strategy extraction
            }
    
    # Get all unique results
    all_unique = list(unique_results.values())
    
    if not all_unique:
        return []
    
    # Select 5 specific options based on criteria (may have duplicates)
    results = []
    
    # 1. Cheapest option
    cheapest = min(all_unique, key=lambda x: x["total_price"])
    results.append(cheapest)
    
    # 2. Second-cheapest option (different from cheapest)
    remaining = [r for r in all_unique if r is not cheapest]
    if remaining:
        second_cheapest = min(remaining, key=lambda x: x["total_price"])
        results.append(second_cheapest)
    
    # 3. Shortest duration option (tiebreaker: cheapest among ALL with that duration)
    min_duration = min(r["duration"] for r in all_unique)
    shortest_candidates = [r for r in all_unique if r["duration"] == min_duration]
    shortest = min(shortest_candidates, key=lambda x: x["total_price"])
    results.append(shortest)
    
    # 4. Buy/least crafting option (tiebreaker: cheapest among ALL with same score)
    def craft_score(r):
        base_score = 0 if r["method"] == "buy_direct" else 1
        return (base_score, len(r["shopping_list"]))
    best_craft_score = min(craft_score(r) for r in all_unique)
    least_crafting_candidates = [r for r in all_unique if craft_score(r) == best_craft_score]
    least_crafting = min(least_crafting_candidates, key=lambda x: x["total_price"])
    results.append(least_crafting)
    
    # 5. Most expensive option (tiebreaker: shortest duration among ALL with that price)
    max_price = max(r["total_price"] for r in all_unique)
    most_expensive_candidates = [r for r in all_unique if r["total_price"] == max_price]
    most_expensive = min(most_expensive_candidates, key=lambda x: x["duration"])
    results.append(most_expensive)
    
    return results[:5]

# ============================================================================
# MAIN EXECUTION
# ============================================================================
# Demo: Calculate cost for an item
item = "FINE_AMBER_GEM"
print(f"\nCalculating best options for: {item}")
for result in calculate(item):
    print(result)