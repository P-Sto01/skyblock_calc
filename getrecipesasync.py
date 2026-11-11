import aiohttp
import asyncio
import requests
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation

start = time.time()
r = requests.get("https://raw.githubusercontent.com/NotEnoughUpdates/NotEnoughUpdates-REPO/refs/heads/master/README.md")
elapsed = time.time() - start
print(f"Single request took {elapsed:.2f}s")

script_dir = os.path.dirname(os.path.abspath(__file__))

if not os.path.isfile(os.path.join(script_dir,"recipes.json")):
    open(os.path.join(script_dir,"recipes.json"),"x")
    print("Created file recipes.json")

starttime=round(time.time(),0)

mcpattern = r'§[0-9A-FK-ORa-fk-or]'
raritypattern = r';[0-9]$'
rarities=["Common","Uncommon","Rare","Epic","Legendary","Mythic","Divine","Special","Very Special"]

columns, rows = os.get_terminal_size()
barlenght=columns/3

items={}
grid=["A1","A2","A3","B1","B2","B3","C1","C2","C3"]
names=[]

def get_commit(repo):
    url = f"https://api.github.com/repos/{repo}/commits"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()[0]["sha"]


def checks(out):
    if not "count" in out:
        out["count"]=1
    if not "duration" in out:
        out["duration"]=0
    if not "coins" in out:
        out["coins"]=0
    if "overrideOutputId" in out:
        del out["overrideOutputId"]
    if "type" in out:
        del out["type"]
    if "supercraftable" in out:
        del out["supercraftable"]
    if "time" in out:
        out["duration"]=out["time"]
        del out["time"]
    ingredients=[]
    if "inputs" in out:
        ingredients.extend(out.pop("inputs"))
    if "items" in out:
        ingredients.extend([out.pop("input"), *out.pop("items")])
        del out["output"]
    for slot in grid:
        if slot in out:
            ingredient=out.pop(slot)
            if ingredient:
                ingredients.append(ingredient)
    item_counts={}
    for ingredient in ingredients:
        if ingredient:
            item, separator, count=ingredient.rpartition(":")
            if not separator:
                item, count=ingredient, "1"
            try:
                amount=Decimal(count)
            except InvalidOperation as e:
                raise ValueError(f"Invalid recipe ingredient count: {ingredient}") from e
            if not amount.is_finite():
                raise ValueError(f"Invalid recipe ingredient count: {ingredient}")
            item_counts[item]=item_counts.get(item, Decimal(0))+amount
    out["recipes"]=[{
        "items":[f"{item}:{format(count.normalize(), 'f')}" for item, count in item_counts.items()],
        "coins":out.pop("coins"),
        "duration":out.pop("duration")
    }]
    return out

def addname(data):
    name = re.sub(mcpattern,"",data["displayname"])
    if re.search(raritypattern,data["internalname"]):
        ending=data["internalname"].split(";")
        if "LVL" in name:
            if ending[1].isdigit():
                name=rarities[int(ending[1])]+" "+name+" Pet"
    if name=="Enchanted Book":
        name=re.sub(r'\b[a-z]', lambda m: m.group().upper(), data["internalname"].removeprefix("ULTIMATE_").replace(";"," ").replace("_"," ").lower())
    return name.replace("[Lvl {LVL}] ","")

async def recipeget(session, item):
    url=f"https://raw.githubusercontent.com/NotEnoughUpdates/NotEnoughUpdates-REPO/refs/heads/master/items/{item}.json"
    async with session.get(url) as r:
        r.raise_for_status()
        data = await r.json(content_type=None)
    out={}
    if "recipe" in data:
        out=data["recipe"]
        out=checks(out)
    elif "recipes" in data:
        if data["recipes"]:
            out=data["recipes"][0]
            out=checks(out)
        else:
            out["recipes"]=[]
    else:
        out["recipes"]=[]
    if "level" in out or "result" in out or "drops" in out:
        out={"recipes":[]}
    out["name"]=addname(data)
    return out

def renderbar(num,total,lenght):
    bar=""
    procent=round(num/total*100,2)
    for i in range(int((procent*lenght)/100)):
        bar+="="
    for i in range(int(lenght-len(bar))):
        bar+="."
    print(f"{bar} {procent}%",end="\r")

listing=[]
names=[]

num = requests.get("https://api.github.com/repos/NotEnoughUpdates/NotEnoughUpdates-REPO/git/trees/master?recursive=1")

namelist=num.json()
for i in namelist["tree"]:
    listing.append(i["path"])

for i in listing:
    if i.startswith("items/"):
        x=i.removeprefix("items/").removesuffix(".json")
        names.append(x)

async def fetch_all_recipes(names):
    results = {}
    total = len(names)
    completed = 0
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(50)
    max_attempts = 3

    async with aiohttp.ClientSession() as session:
        async def fetch(name):
            nonlocal completed
            try:
                for attempt in range(1, max_attempts + 1):
                    try:
                        async with semaphore:
                            result = await recipeget(session, name)
                        return name, result
                    except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
                        if attempt == max_attempts:
                            print(f"\nDownload failed for {name} after {max_attempts} attempts: {e}")
                            return name, None
                        print(f"\nDownload failed for {name} (attempt {attempt}/{max_attempts}): {e}; retrying...")
                        await asyncio.sleep(2 ** (attempt - 1))
            finally:
                async with lock:
                    completed += 1
                    renderbar(completed, total, barlenght)

        tasks = [asyncio.create_task(fetch(name)) for name in names]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        failed = []
        for name, outcome in zip(names, outcomes):
            if isinstance(outcome, BaseException):
                print(f"\nFailed to process {name}: {outcome}")
                failed.append(name)
            elif outcome[1] is None:
                failed.append(name)
            else:
                _, result = outcome
                results[name] = result

    if failed:
        raise RuntimeError(f"Failed to download recipes for {len(failed)} items: {', '.join(failed)}")

    return results

async def main():
    totalnames = len(names)
    print(f"Total names: {totalnames}")
    return await fetch_all_recipes(names)

items = asyncio.run(main())

totalnames = len(names)
renderbar(totalnames,totalnames,barlenght)
print()

with open(os.path.join(script_dir,"recipes.json"),"w") as k:
    k.write(json.dumps(items))

with open(os.path.join(script_dir,"recipeshash.txt"),"w") as k:
    k.write(get_commit("NotEnoughUpdates/NotEnoughUpdates-REPO"))

print(f"Done in {time.strftime("%M:%S", time.gmtime((round(time.time(),0)-starttime)))}")