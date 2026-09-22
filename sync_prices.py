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
    task.start()
    log.info("סיום הורדה. קבצים בתיקייה: %d", len(glob.glob(f"{DUMP_DIR}/**/*", recursive=True)))


def parse_dumps():
    """הופך את הקבצים הגולמיים למבנה אחיד: רשימת (chain, store, items[])."""
    from il_supermarket_parsers import ConvertingTask

    task = ConvertingTask(data_folder=DUMP_DIR)
    # ה-API המדויק להחזרת התוצאה המפוענחת (return value / output folder)
    #
