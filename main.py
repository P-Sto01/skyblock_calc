import requests
import json
import os
import time
import subprocess
import sys

script_dir=os.path.dirname(os.path.realpath(__file__))
targetfile = os.path.join(script_dir,"prices.json")
recipehashfile = os.path.join(script_dir,"recipeshash.txt")
getrecipes = os.path.join(script_dir,"getrecipesasync.py")

def get_commit(repo):
    url = f"https://api.github.com/repos/{repo}/commits"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()[0]["sha"]

def get_hash(file):
    with open(file) as fl:
        return fl.read()

def filterdata(x):
    products = json.loads(x)["products"]
    return [product["quick_status"] for product in products.values()]

if not os.path.isfile(targetfile) or time.time()-os.path.getmtime(targetfile) > 60:
    print("Updating prices.json...")
    data = requests.get("https://api.hypixel.net/v2/skyblock/bazaar")
    with open(targetfile,"w") as k:
        k.write(json.dumps(filterdata(data.text), indent=2))
    print("Updating prices.json done!")

if not os.path.isfile(recipehashfile) or get_hash(recipehashfile) != get_commit("NotEnoughUpdates/NotEnoughUpdates-REPO"):
    print("Updating recipes...")
    subprocess.run([sys.executable, getrecipes], check=True)
    print("Updating recipes done!")