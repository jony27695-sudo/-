"""
sync_prices.py
מושך את קובצי שקיפות המחירים מכמה רשתות, מפענח אותם ומעדכן טבלאות ב-Supabase.

לא נבדק בהרצה אמיתית (הסביבה שכתבה את זה בלי גישה לאינטרנט) — יש לצפות
לכוונון קטן בהרצה הראשונה, בעיקר בשמות הפרמטרים המדויקים של הספריות.
תיעוד עדכני: https://github.com/erlichsefi/israeli-supermarket-scarpers
             https://github.com/erlichsefi/israeli-supermarket-parsers (או OpenIsraeliSupermarkets)

התקנה: pip install -r requirements.txt
הרצה:  python sync_prices.py
נדרשים משתני סביבה: SUPABASE_URL, SUPABASE_SERVICE_KEY, ENABLED_CHAINS (מופרד בפסיקים)
"""
import os
import sys
import glob
import shutil
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync_prices")

DUMP_DIR = "dumps"
# רשתות התחלתיות לבדיקה - שמות המפתח (ENUM) חייבים להתאים למה שמופיע ב-README
# של il_supermarket_scarper תחת ScraperFactory / FileTypesFilters. יש לוודא שם.
DEFAULT_CHAINS = ["SUPER_YUDA", "YAYNO_BITAN", "TIV_TAAM"]


def get_supabase():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def download_dumps(enabled_chains):
    """מוריד את קובצי המקור הגולמיים (XML/GZ) מהרשתות שנבחרו."""
    from il_supermarket_scarper import ScarpingTask

    if os.path.isdir(DUMP_DIR):
        shutil.rmtree(DUMP_DIR)
    os.makedirs(DUMP_DIR, exist_ok=True)

    log.info("מוריד קבצים עבור: %s", enabled_chains)
    # אומת מול הקוד האמיתי של הספרייה (example.py / main.py בריפו
    # OpenIsraeliSupermarkets/israeli-supermarket-scarpers): הפרמטר לתיקיית
    # היעד הוא base_storage_path בתוך output_configuration, לא dump_folder_name.
    task = ScarpingTask(
        enabled_scrapers=enabled_chains,
        output_configuration={
            "output_mode": "disk",
            "base_storage_path": DUMP_DIR,
        },
        status_configuration={
            "database_type": "json",
            "base_path": os.path.join(DUMP_DIR, "status"),
        },
    )
    task.start()
    log.info("סיום הורדה. קבצים בתיקייה: %d", len(glob.glob(f"{DUMP_DIR}/**/*", recursive=True)))


def parse_dumps():
    """הופך את הקבצים הגולמיים למבנה אחיד: רשימת (chain, store, items[])."""
    from il_supermarket_parsers import ConvertingTask

    task = ConvertingTask(data_folder=DUMP_DIR)
    # ה-API המדויק להחזרת התוצאה המפוענחת (return value / output folder)
    # משתנה בין גרסאות - לפי ה-README זה כותב JSON לתיקיית פלט; יש להתאים
    # את הקריאה הבאה לפי מה שבפועל קורה אצלך.
    result = task.run()
    return result


def upsert_to_supabase(sb, parsed):
    """
    מקבל את הפלט המפוענח וכותב אותו לטבלאות chains / branches / products / prices / promotions.
    parsed צפוי להיות איטרבל של רשומות בערך בצורה:
    {"chain": "...", "store_id": "...", "store_name": "...", "items": [
        {"barcode": "...", "name": "...", "price": 12.9, "unit_price": ..., "promo": {...}}
    ]}
    יש להתאים את הגישה לשדות בפועל לפי מה ש-ConvertingTask מחזיר אצלך.
    """
    now = datetime.now(timezone.utc).isoformat()
    chains_cache = {}
    branches_cache = {}

    for store in parsed:
        chain_name = store.get("chain") or store.get("ChainName") or "לא ידוע"
        if chain_name not in chains_cache:
            res = sb.table("chains").upsert(
                {"name": chain_name, "chain_code": chain_name, "source": "gov_files"},
                on_conflict="chain_code",
            ).execute()
            chains_cache[chain_name] = res.data[0]["id"] if res.data else None
        chain_id = chains_cache[chain_name]

        store_key = (chain_id, store.get("store_id") or store.get("StoreId"))
        if store_key not in branches_cache:
            res = sb.table("branches").upsert(
                {
                    "chain_id": chain_id,
                    "external_code": str(store.get("store_id") or store.get("StoreId")),
                    "name": store.get("store_name") or store.get("StoreName") or chain_name,
                    "address": store.get("address"),
                    "city": store.get("city"),
                },
                on_conflict="chain_id,external_code",
            ).execute()
            branches_cache[store_key] = res.data[0]["id"] if res.data else None
        branch_id = branches_cache[store_key]

        price_rows = []
        for item in store.get("items", []):
            barcode = item.get("barcode") or item.get("ItemCode")
            if not barcode:
                continue
            prod = sb.table("products").upsert(
                {
                    "barcode": barcode,
                    "name": item.get("name") or item.get("ItemName") or "",
                    "brand": item.get("brand") or item.get("ManufacturerName"),
                    "size_label": item.get("size") or item.get("Quantity"),
                },
                on_conflict="barcode",
            ).execute()
            product_id = prod.data[0]["id"] if prod.data else None
            if not product_id:
                continue
            price_rows.append({
                "branch_id": branch_id,
                "product_id": product_id,
                "price": item.get("price") or item.get("ItemPrice"),
                "unit_price": item.get("unit_price"),
                "unit_measure": item.get("unit_measure"),
                "source_updated_at": item.get("updated_at") or now,
                "ingested_at": now,
            })
        if price_rows:
            sb.table("prices").upsert(price_rows, on_conflict="branch_id,product_id").execute()
            log.info("עודכנו %d מחירים לסניף %s", len(price_rows), store_key)


def main():
    enabled = os.environ.get("ENABLED_CHAINS", ",".join(DEFAULT_CHAINS)).split(",")
    sb = get_supabase()
    run = sb.table("ingestion_runs").insert({
        "source": "gov_files", "started_at": datetime.now(timezone.utc).isoformat()
    }).execute()
    run_id = run.data[0]["id"] if run.data else None
    try:
        download_dumps(enabled)
        parsed = parse_dumps()
        upsert_to_supabase(sb, parsed)
        if run_id:
            sb.table("ingestion_runs").update({
                "finished_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", run_id).execute()
        log.info("הריצה הסתיימה בהצלחה")
    except Exception as e:
        log.exception("הריצה נכשלה")
        if run_id:
            sb.table("ingestion_runs").update({
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }).eq("id", run_id).execute()
        sys.exit(1)


if __name__ == "__main__":
    main()
