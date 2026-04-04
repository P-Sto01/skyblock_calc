import requests
import json
from concurrent.futures import ThreadPoolExecutor
import os
import time

starttime=time.time()

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
    

def recipeget(item):
    clearout=False
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

totalnames=len(names)
print(f"Total names: {totalnames}")

x=0
def count(num,max):
    global x
    for (currentitem) in names[int((totalnames/max)*num) : int((totalnames/max)*(num+1))]:
        x+=1
        items[currentitem]=recipeget(currentitem)
        renderbar(x,totalnames,barlenght)

workers=100
with ThreadPoolExecutor(max_workers=workers) as executor:
    futures = [executor.submit(count, i, workers) for i in range(workers)]
for f in futures:
    f.result()
print()

script_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(script_dir,"recipes.json"),"w") as k:
    k.write(json.dumps(items))

print(f"Done in {time.strftime("%M:%S", time.gmtime((time.time()-starttime)))}")