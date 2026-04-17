import aiohttp
import asyncio
import requests
import json
import os
import re
import time

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
rarities=["Common","Uncommon","Rare","Epic","Legendary","Mythic"]

columns, rows = os.get_terminal_size()
barlenght=columns/3

items={}
grid=["A1","A2","A3","B1","B2","B3","C1","C2","C3"]
names=[]

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
    if "inputs" in out:
        x=0
        for i in out["inputs"]:
            out[grid[x]]=i
            x+=1
        del out["inputs"]
        for i in range(len(grid)-x):
            out[grid[i+x]]=""
    if "items" in out:
        x=1
        out[grid[0]]=out["input"]
        for i in out["items"]:
            out[grid[x]]=i
            x+=1
        del out["items"]
        del out["input"]
        del out["output"]
        for i in range(len(grid)-x):
            out[grid[i+x]]=""
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
        data = await r.json(content_type=None)
    out={}
    if "recipe" in data:
        out=data["recipe"]
        out=checks(out)
    elif "recipes" in data:
        out=data["recipes"][0]
        out=checks(out)
    if "level" in out or "result" in out or "drops" in out:
        out={}
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

    async with aiohttp.ClientSession() as session:
        async def fetch(name):
            nonlocal completed
            async with semaphore:
                try:
                    result = await recipeget(session, name)
                except Exception as e:
                    result = {}
            async with lock:
                completed += 1
                renderbar(completed, total, barlenght)
            return name, result

        tasks = [asyncio.create_task(fetch(name)) for name in names]
        for task in asyncio.as_completed(tasks):
            name, result = await task
            results[name] = result

    return results

async def main():
    totalnames = len(names)
    print(f"Total names: {totalnames}")
    while True:
        try:
            return await fetch_all_recipes(names)
        except Exception as e:
            print(e)
            print("Failed, retrying script...")

items = asyncio.run(main())

totalnames = len(names)
renderbar(totalnames,totalnames,barlenght)
print()

with open(os.path.join(script_dir,"recipes.json"),"w") as k:
    k.write(json.dumps(items))

print(f"Done in {time.strftime("%M:%S", time.gmtime((round(time.time(),0)-starttime)))}")