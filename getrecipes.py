import requests
import json
from concurrent.futures import ThreadPoolExecutor
import os
import time
import threading
import re

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

done=False

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

def recipeget(item):
    r = requests.get(f"https://raw.githubusercontent.com/NotEnoughUpdates/NotEnoughUpdates-REPO/refs/heads/master/items/{item}.json")
    data = r.json()
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

def update():
    while not done:
        global x
        global totalnames
        global barlenght
        renderbar(x,totalnames,barlenght)
        time.sleep(1)


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

def count(num,max):
        global x
        for (currentitem) in names[int((totalnames/max)*num) : int((totalnames/max)*(num+1))]:
            x+=1
            items[currentitem]=recipeget(currentitem)

while True:
    try:
        x=0
        totalnames=len(names)
        print(f"Total names: {totalnames}")

        t = threading.Thread(target=update)
        t.start()

        workers=100
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(count, i, workers) for i in range(workers)]
        for f in futures:
            f.result()
        break
    except Exception as e:
        print(e)
        print("Failed, retrying script...")

done=True
t.join()
renderbar(totalnames,totalnames,barlenght)
print()

with open(os.path.join(script_dir,"recipes.json"),"w") as k:
    k.write(json.dumps(items))

print(f"Done in {time.strftime("%M:%S", time.gmtime((round(time.time(),0)-starttime)))}")