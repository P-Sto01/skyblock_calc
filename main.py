import requests
import json
import os
import time
import subprocess
import sys
import re
import base64
import gzip
import nbtlib
import io

script_dir=os.path.dirname(os.path.realpath(__file__))
pricefile = os.path.join(script_dir,"prices.json")
recipehashfile = os.path.join(script_dir,"recipeshash.txt")
getrecipes = os.path.join(script_dir,"getrecipesasync.py")
recipefile = os.path.join(script_dir,"recipes.json")

def get_commit(repo):
    url = f"https://api.github.com/repos/{repo}/commits"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()[0]["sha"]

def get_hash(file):
    with open(file) as fl:
        return fl.read()

def filterbz(x):
    products = json.loads(x)["products"]
    return {p["productId"]: p["sellPrice"] for p in [product["quick_status"] for product in products.values()]}

def filterah(x):
    prod=[]
    products = json.loads(x)["auctions"]
    for i in products:
        if i["bin"] == True:
            prod.append({get_item_id(i["item_bytes"]): i["starting_bid"]})
    return prod

def get_item_id(item_bytes):
    compressed = base64.b64decode(item_bytes)
    nbt_data = gzip.decompress(compressed)
    nbt = nbtlib.File.parse(io.BytesIO(nbt_data))

    items = nbt.get("i")
    if items is not None:
        if not items:
            raise ValueError("Item NBT contains no items")
        nbt = items[0]

    extra = nbt["tag"]["ExtraAttributes"]
    item_id = str(extra["id"])

    if item_id == "PET":
        pet_info = json.loads(str(extra["petInfo"]))

        pet_type = pet_info["type"]

        rarity_map = {
            "COMMON": 0,
            "UNCOMMON": 1,
            "RARE": 2,
            "EPIC": 3,
            "LEGENDARY": 4,
            "MYTHIC": 5
        }

        rarity = rarity_map[pet_info["tier"]]

        item_id = f"{pet_type};{rarity}"
    elif item_id == "RUNE":
        rune, level = next(iter(extra["runes"].items()))
        item_id = f"{rune}_RUNE;{int(level)}"
    elif item_id == "PARTY_HAT_CRAB_ANIMATED":
        color = str(extra["party_hat_color"]).upper()
        item_id = f"PARTY_HAT_CRAB_{color}_ANIMATED"

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
        
        # Option 1: Buy directly from bazaar (if available)
        # Note: Use max(1, price) to ensure free items cost at least 1 coin
        if item_id in prices and prices[item_id] >= 0:
            buy_price = max(1, prices[item_id])
            results.append((buy_price, 0, [f"Buy {item_id}"]))
        
        # Option 2: Craft from recipes (if available)
        if item_id in recipes:
            item_data = recipes[item_id]
            # Get count (items produced per craft), default to 1 if missing
            output_count = item_data.get("count", 1)
            item_recipes = item_data.get("recipes", [])
            
            for recipe in item_recipes:
                recipe_coins = recipe.get("coins", 0)
                recipe_duration = recipe.get("duration", 0)
                ingredients = recipe.get("items", [])
                
                if not ingredients:
                    # Recipe with only coins cost
                    if recipe_coins > 0:
                        # Divide by count since we get multiple items per craft
                        results.append((recipe_coins / output_count, recipe_duration, [f"Craft {item_id} (coins only)"]))
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
                            # Also multiply quantities in nested items by parent multiplier
                            sub_items = []
                            for line in breakdown:
                                if not line.startswith("Total "):  # Skip summary lines, they'll be recalculated
                                    # Multiply quantities in nested lines by parent amount
                                    scaled_line = re.sub(
                                        r'(\w+)x(\d+)', 
                                        lambda m: f"{m.group(1)}x{int(m.group(2)) * ing_amount}", 
                                        line
                                    )
                                    sub_items.append(f"    └─ {scaled_line}")
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
                
                # Generate combinations from ALL options (no pruning)
                from itertools import product
                
                recipe_results = []
                for combo in product(*ingredient_option_lists):
                    total_price = sum(opt[0] for opt in combo) + recipe_coins
                    max_duration = max(opt[1] for opt in combo) + recipe_duration
                    
                    # Divide by output_count since we get multiple items per craft
                    # This gives us the cost PER item
                    total_price_per_item = total_price / output_count
                    
                    if total_price_per_item == 0:
                        continue
                    
                    # Build detailed breakdown with costs
                    breakdown = [f"Craft {item_id} (x{output_count}, Recipe coins: ${recipe_coins:.2f})"]
                    total_ingredients_cost = sum(opt[0] for opt in combo)
                    
                    for ing_str, (price, dur, ing_breakdown) in zip(ingredients, combo):
                        breakdown.extend(ing_breakdown)
                    
                    breakdown.append(f"Total ingredients: ${total_ingredients_cost:.2f}")
                    breakdown.append(f"Total cost (for {output_count} items): ${total_price:.2f}")
                    breakdown.append(f"Cost per item: ${total_price_per_item:.2f}")
                    
                    recipe_results.append((total_price_per_item, max_duration, breakdown))
                
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
        # Quantities are already multiplied through the tree structure, but we need to
        # account for craft output counts (e.g., Craft BLAZE_POWDER x2 means divide children by 2)
        shopping_list = {}
        
        def extract_shopping_list(lines):
            # Build a map of which items use which ingredients
            item_ingredients = {}  # item -> set of ingredient_ids it uses
            item_quantities = {}   # item -> total quantity needed
            
            # Track current craft hierarchy using stack
            # Each entry: (item_id, base_indent_level)
            craft_stack = []
            
            for line in lines:
                # Skip empty lines and cost-only lines
                if not line.strip() or 'Cost per item' in line or 'Total' in line:
                    continue
                
                # Calculate indent level by counting "└─" prefixes
                indent_level = line.count('└─')
                
                # Match pattern: ITEMxQUANTITY ...: Craft ITEM
                # Example: NULL_OVOIDx32 (59269 each): Craft NULL_OVOID (x1, Recipe coins: $0.00)
                # Use [^:\s]+ to match item IDs that may contain semicolons (e.g., SHEEP;4)
                craft_match = re.search(r'([^:\s]+)x(\d+).*?:\s*Craft\s+([^\s]+)', line)
                if craft_match:
                    item_id = craft_match.group(1)
                    quantity = int(craft_match.group(2))
                    
                    # Pop stack until we find a parent (lower indent)
                    while craft_stack and craft_stack[-1][1] >= indent_level:
                        craft_stack.pop()
                    
                    # If there's a parent on the stack, add this item as its ingredient
                    if craft_stack:
                        parent_craft = craft_stack[-1][0]
                        if parent_craft not in item_ingredients:
                            item_ingredients[parent_craft] = set()
                        item_ingredients[parent_craft].add(item_id)
                    
                    # Add this craft to stack with its indent level
                    craft_stack.append((item_id, indent_level))
                    
                    if item_id not in item_ingredients:
                        item_ingredients[item_id] = set()
                    item_quantities[item_id] = quantity
                
                # Match pattern: ITEMxQUANTITY ...: Buy ITEM (base ingredient)
                # Use [^:\s]+ to match item IDs that may contain semicolons (e.g., SHEEP;4)
                buy_match = re.search(r'([^:\s]+)x(\d+).*?:\s*Buy\s+([^\s]+)', line)
                if buy_match:
                    item_id = buy_match.group(1)
                    quantity = int(buy_match.group(2))
                    
                    # Add to current craft's ingredients (if any)
                    if craft_stack:
                        parent_craft = craft_stack[-1][0]
                        if parent_craft not in item_ingredients:
                            item_ingredients[parent_craft] = set()
                        item_ingredients[parent_craft].add(item_id)
                    
                    item_quantities[item_id] = quantity
                
                # Handle simple "Buy ITEM" case (direct purchase, no quantity pattern)
                # Use [^\s]+ to match item IDs that may contain semicolons (e.g., SHEEP;4)
                simple_buy_match = re.search(r'^Buy\s+([^\s]+)$', line.strip())
                if simple_buy_match:
                    item_id = simple_buy_match.group(1)
                    item_quantities[item_id] = 1

            # Find leaf items (items that don't have ingredients listed)
            leaves = {}
            
            def collect_leaves(item_id, visited=None):
                if visited is None:
                    visited = set()
                
                if item_id in visited:
                    return
                visited.add(item_id)
                
                # Get ingredients for this item
                ingredients = item_ingredients.get(item_id, set())
                
                if ingredients:
                    # Recursively collect leaves from ingredients
                    for ingredient in ingredients:
                        collect_leaves(ingredient, visited)
                else:
                    # This is a leaf - add it with its quantity
                    leaves[item_id] = item_quantities.get(item_id, 0)
            
            # Find root items (items not used as ingredients by any other item)
            all_ingredients = set()
            for ingredients in item_ingredients.values():
                all_ingredients.update(ingredients)
            
            root_items = set(item_quantities.keys()) - all_ingredients
            
            for root_item in root_items:
                collect_leaves(root_item)
            
            return leaves
        
        shopping_list = extract_shopping_list(breakdown)
        
        # Use the shopping list tuple as key to ensure unique results
        key = tuple(sorted(shopping_list.items()))
        if key not in unique_results:
            unique_results[key] = {
                "method": method,
                "total_price": total_price,
                "duration": duration,
                "shopping_list": shopping_list
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

if not os.path.isfile(pricefile) or time.time()-os.path.getmtime(pricefile) > 60:
    print("Updating prices.json...")
    bazaar_data = requests.get("https://api.hypixel.net/v2/skyblock/bazaar").json()
    auction_data = requests.get("https://api.hypixel.net/v2/skyblock/auctions").json()
    
    # Filter and merge both sources into one unified dictionary
    prices_dict = {}
    
    # Add bazaar prices
    for product_id, product in bazaar_data["products"].items():
        quick_status = product.get("quick_status")
        if quick_status:
            prices_dict[product_id] = quick_status["sellPrice"]
    
    # Add auction house prices (bin items only)
    auctions = auction_data.get("auctions", [])
    for auction in auctions:
        if auction.get("bin"):
            item_bytes = auction.get("item_bytes")
            starting_bid = auction.get("starting_bid")
            if item_bytes and starting_bid is not None:
                # Decode to get item_id
                compressed = base64.b64decode(item_bytes)
                nbt_data = gzip.decompress(compressed)
                nbt_item = nbtlib.File.parse(io.BytesIO(nbt_data))
                
                items = nbt_item.get("i")
                if items is not None:
                    if not items:
                        continue
                    nbt_item = items[0]
                
                extra = nbt_item["tag"]["ExtraAttributes"]
                item_id = str(extra["id"])
                
                # Handle special cases
                if item_id == "PET":
                    pet_info = json.loads(str(extra["petInfo"]))
                    pet_type = pet_info["type"]
                    rarity_map = {
                        "COMMON": 0,
                        "UNCOMMON": 1,
                        "RARE": 2,
                        "EPIC": 3,
                        "LEGENDARY": 4,
                        "MYTHIC": 5
                    }
                    rarity = rarity_map.get(pet_info["tier"], 0)
                    item_id = f"{pet_type};{rarity}"
                elif item_id == "RUNE":
                    rune, level = next(iter(extra["runes"].items()))
                    item_id = f"{rune}_RUNE;{int(level)}"
                elif item_id == "PARTY_HAT_CRAB_ANIMATED":
                    color = str(extra["party_hat_color"]).upper()
                    item_id = f"PARTY_HAT_CRAB_{color}_ANIMATED"
                
                # Only add if not already in bazaar or if auction price is lower
                if item_id not in prices_dict or starting_bid < prices_dict[item_id]:
                    prices_dict[item_id] = starting_bid
    
    with open(pricefile, "w") as k:
        json.dump(prices_dict, k)
    
    print("Updating prices.json done!")

if not os.path.isfile(recipehashfile) or get_hash(recipehashfile) != get_commit("NotEnoughUpdates/NotEnoughUpdates-REPO"):
    print("Updating recipes...")
    subprocess.run([sys.executable, getrecipes], check=True)
    print("Updating recipes done!")

with open(recipefile) as fl:
    recipes = json.loads(fl.read())
with open(pricefile) as fl:
    prices = json.loads(fl.read())

item="SHEEP;4"

for i in calculate(item):
    print(i)