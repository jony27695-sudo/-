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
import csv
import glob
import shutil
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync_prices")

DUMP_DIR = "dumps"
PARSED_DIR = "parsed"
# שמות המפתח (ENUM) אומתו מול il_supermarket_scarper/utils/folders_name.py
# בריפו המקורי - אלה השמות המדויקים והנכונים לרשתות רמי לוי, אושר עד,
# יוחננוף וכרפור (ששילוב עם יינות ביתן תחת שם אחד בספרייה הזו).
DEFAULT_CHAINS = ["RAMI_LEVY", "OSHER_AD", "YOHANANOF", "YAYNO_BITAN_AND_CARREFOUR"]


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
    # task.start() מריץ את ההורדה ב-thread נפרד ברקע וחוזר מיד - הוא לא מחכה
    # לסיום בפועל. חובה לקרוא ל-join() כדי לחכות שההורדה באמת תסתיים
    # (אומת מול קוד המקור: scrapper_runner.py - start() מחזיר Thread, ו-join()
    # הוא זה ש"מחכה לסיום ה-thread").
    #
    # בלי limit/when_date, הספרייה מנסה להוריד את כל ההיסטוריה של קבצי
    # המחירים של כל רשת (יכול להיות אלפי קבצים) - זו הסיבה שהריצה הקודמת
    # חרגה מ-30 דקות ונעצרה. limit=1 + when_date=היום מגביל להורדת הקובץ
    # העדכני ביותר בלבד לכל סניף (אומת מול example.py הרשמי של הספרייה:
    # scraper.start(limit=1, when_date=_now())).
    task.start(limit=1, when_date=datetime.now())
    task.join()
    n_files = len(glob.glob(f"{DUMP_DIR}/**/*", recursive=True))
    log.info("סיום הורדה. קבצים בתיקייה: %d", n_files)
    if n_files == 0:
        log.warning("לא ירדו קבצים בכלל - כדאי לבדוק את שמות הרשתות ב-ENABLED_CHAINS")


def parse_dumps(enabled_chains):
    """
    הופך את הקבצים הגולמיים ל-CSV אחיד, וקורא את שורות ה-CSV בחזרה.
    אומת מול README הרשמי של il_supermarket_parsers: ConvertingTask כותב
    קבצי CSV לתיקיית פלט (לא מחזיר אובייקט פייתון ישירות), וגם כאן צריך
    start() + join() כי הריצה היא ברקע.

    בלי enabled_parsers, בריצה האמיתית ראינו בלוג שהספרייה דילגה על חלק
    מהתיקיות ("Skipping folder dumps/RamiLevy... not in requested chains")
    - כנראה יש לה רשימת ברירת מחדל משלה. מעבירים לה את אותה רשימת רשתות
    שהורדנו, כדי לוודא שהיא בפועל מפענחת את כולן.
    """
    from il_supermarket_parsers import ConvertingTask

    if os.path.isdir(PARSED_DIR):
        shutil.rmtree(PARSED_DIR)
    os.makedirs(PARSED_DIR, exist_ok=True)

    task = ConvertingTask(
        source_configuration={"folder": DUMP_DIR},
        output_configuration=[{"output_mode": "csv", "output_folder": PARSED_DIR}],
        status_configuration={"database_type": "json", "base_path": PARSED_DIR},
        enabled_parsers=enabled_chains,
    )
    task.start()
    task.join()

    csv_files = glob.glob(f"{PARSED_DIR}/**/*.csv", recursive=True)
    log.info("סיום פענוח. קבצי CSV שנוצרו: %d", len(csv_files))

    rows = []
    for path in csv_files:
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    log.info("סה״כ שורות פריטים שנקראו: %d", len(rows))
    if rows:
        log.info("שמות העמודות שנמצאו בפועל (לצורך אבחון): %s", list(rows[0].keys()))
    return rows


def upsert_to_supabase(sb, rows):
    """
    מקבל רשימה שטוחה של שורות (כל שורה = פריט אחד בסניף אחד) וכותב אותן
    לטבלאות chains / branches / products / prices.
    שמות העמודות המדויקים ב-CSV לא היו ידועים מראש - הקוד מנסה כמה שמות
    נפוצים (לפי תקן קובצי שקיפות המחירים) ומדלג על שורה עם ברקוד/מחיר חסרים.
    אם רואים בלוג "0 מחירים עודכנו" למרות שיש שורות - צריך להסתכל בלוג
    "שמות העמודות שנמצאו בפועל" ולעדכן כאן את שמות המפתחות בהתאם.
    """

    def pick(d, *keys):
        for k in keys:
            v = d.get(k)
            if v not in (None, ""):
                return v
        return None

    def chain_name_from_folder(item):
        # עמודת found_folder מכילה נתיב כמו "dumps/Yohananof/..." - השם
        # שבתיקייה קריא בהרבה משם המספר chainid, אז נשתמש בו כשם תצוגה.
        folder = pick(item, "found_folder")
        if not folder:
            return None
        parts = [p for p in str(folder).replace("\\", "/").split("/") if p and p != "dumps"]
        return parts[0] if parts else None

    now = datetime.now(timezone.utc).isoformat()
    chains_cache = {}
    branches_cache = {}
    price_rows = []
    skipped = 0

    for item in rows:
        # שמות העמודות בפועל ב-CSV שהספרייה יוצרת הם באותיות קטנות (אומת
        # מול לוג ריצה אמיתית: chainid, storeid, itemcode, itemprice וכו').
        chain_code = pick(item, "chainid")
        chain_name = chain_name_from_folder(item) or chain_code or "לא ידוע"
        if chain_code not in chains_cache:
            res = sb.table("chains").upsert(
                {"name": chain_name, "chain_code": str(chain_code or chain_name), "source": "gov_files"},
                on_conflict="chain_code",
            ).execute()
            chains_cache[chain_code] = res.data[0]["id"] if res.data else None
        chain_id = chains_cache[chain_code]

        store_code = pick(item, "storeid")
        store_key = (chain_id, store_code)
        if store_key not in branches_cache:
            res = sb.table("branches").upsert(
                {
                    "chain_id": chain_id,
                    "external_code": str(store_code),
                    "name": f"{chain_name} {store_code}",
                },
                on_conflict="chain_id,external_code",
            ).execute()
            branches_cache[store_key] = res.data[0]["id"] if res.data else None
        branch_id = branches_cache[store_key]

        barcode = pick(item, "itemcode")
        price = pick(item, "itemprice")
        if not barcode or not branch_id or price is None:
            skipped += 1
            continue

        prod = sb.table("products").upsert(
            {
                "barcode": barcode,
                "name": pick(item, "itemname") or "",
                "brand": pick(item, "manufacturername"),
                "size_label": pick(item, "quantity", "unitqty"),
            },
            on_conflict="barcode",
        ).execute()
        product_id = prod.data[0]["id"] if prod.data else None
        if not product_id:
            skipped += 1
            continue

        price_rows.append({
            "branch_id": branch_id,
            "product_id": product_id,
            "price": price,
            "unit_price": pick(item, "unitofmeasureprice"),
            "unit_measure": pick(item, "unitofmeasure"),
            "source_updated_at": pick(item, "priceupdatetime") or now,
            "ingested_at": now,
        })

    if price_rows:
        # Supabase/Postgres upsert מוגבל בכמות שורות לבקשה - שולחים ב"נגסות".
        chunk = 500
        for i in range(0, len(price_rows), chunk):
            sb.table("prices").upsert(
                price_rows[i:i + chunk], on_conflict="branch_id,product_id"
            ).execute()
    log.info("עודכנו %d מחירים. שורות שדולגו (חסר ברקוד/מחיר): %d", len(price_rows), skipped)


def main():
    enabled = os.environ.get("ENABLED_CHAINS", ",".join(DEFAULT_CHAINS)).split(",")
    sb = get_supabase()
    run = sb.table("ingestion_runs").insert({
        "source": "gov_files", "started_at": datetime.now(timezone.utc).isoformat()
    }).execute()
    run_id = run.data[0]["id"] if run.data else None
    try:
        download_dumps(enabled)
        parsed = parse_dumps(enabled)
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
