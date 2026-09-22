# מיקום בריפו: .github/workflows/sync-prices.yml
name: Sync supermarket prices

on:
  schedule:
    - cron: "0 */4 * * *"   # כל 4 שעות. אפשר לשנות.
  workflow_dispatch: {}       # מאפשר הרצה ידנית מכפתור "Run workflow"

jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run sync
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          ENABLED_CHAINS: "RAMI_LEVY,OSHER_AD,YOHANANOF,YAYNO_BITAN_AND_CARREFOUR"
        run: python sync_prices.py
