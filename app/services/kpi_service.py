from app.config.database import db
from datetime import datetime

def process_kpi(event):
    today = datetime.now().strftime("%Y-%m-%d")

    kpi = db.kpis.find_one({"date": today})

    if not kpi:
        kpi = {
            "date": today,
            "plastic": 0,
            "glass": 0,
            "metal": 0,
            "rejects": 0,
            "throughput": 0
        }
        db.kpis.insert_one(kpi)

    update = {}

    if event.get("type") == "classification":
        material = event.get("material")
        result = event.get("result")

        if result == "accepted" and material in ["plastic", "glass", "metal"]:
            update[material] = kpi.get(material, 0) + 1
        else:
            update["rejects"] = kpi.get("rejects", 0) + 1

        update["throughput"] = kpi.get("throughput", 0) + 1


    if event.get("type") == "alert":
        update["alerts"] = kpi.get("alerts", 0) + 1

    line = event.get("line")
    if line:
        update[f"line_{line}"] = kpi.get(f"line_{line}", 0) + 1

    if update:
        db.kpis.update_one({"date": today}, {"$set": update})

    