SMASHED BURGERS ERP — FREE CLOUD DEPLOYMENT (RENDER + SUPABASE)

IMPORTANT
- Render Free sleeps after inactivity. First visit after sleeping can take around a minute.
- ERP data and review screenshots are stored in Supabase, NOT on Render's temporary disk.
- Supabase free projects can pause after a period of inactivity. Keep a separate backup.
- Never put the Supabase secret/service_role key in the HTML or GitHub source.

A. SUPABASE (about 5 minutes)
1. Open https://supabase.com/dashboard and open your existing project.
2. Open SQL Editor > New query.
3. Open supabase-setup.sql from this folder, copy all its contents, paste into SQL Editor.
4. Click Run. It should finish successfully.
5. Open Project Settings > API Keys (or API).
6. Copy the Project URL.
7. Open the Legacy API Keys section and copy the service_role key (long JWT-looking value).
   Do NOT use the publishable/anon key. Do NOT share this key in chat or put it in HTML.

B. GITHUB (about 5 minutes)
1. Open https://github.com and sign in.
2. Click + > New repository.
3. Name it smashed-burgers-erp. Choose Private. Create repository.
4. Click Add file > Upload files.
5. Upload ALL files from this folder, including hidden files if any. The important files are:
   server.py, smashed-burgers-erp.html, requirements.txt, render.yaml.
   You can also upload README-DEPLOY-FREE.txt and supabase-setup.sql.
6. Click Commit changes.

C. RENDER (about 10 minutes)
1. Open https://render.com and sign in.
2. Click New + > Blueprint.
3. Connect GitHub if asked and select your smashed-burgers-erp repository.
4. Render reads render.yaml. Choose the FREE plan and create/deploy.
5. When the service is created, open its Environment page and add these values:
   SUPABASE_URL = your Supabase Project URL
   SUPABASE_SERVICE_ROLE_KEY = your Supabase legacy service_role key
   ERP_ADMIN_PASSWORD and ERP_VISITOR_PASSWORD may remain set as legacy deployment variables; account sign-in now uses the PINs below.
6. Save changes. Render will redeploy. Wait until status is Live.
7. Open the URL ending in .onrender.com.

D. FIRST LOGIN AND DATA
1. Select Admin and enter PIN: 1715.
2. The first Admin login creates the ERP's initial data if the database is empty.
3. In the ERP, use Restore backup and choose your existing ERP backup JSON file.
4. Check sales, menu, expenses, inventory, vendors, salary and review screenshots.
5. Download a fresh backup after checking everything.

VIEWER LOGIN
Select Smashed and enter PIN: 5050.

IMPORTANT LIMITATIONS
- Render Free sleeps after 15 minutes without requests; the first request may take around 1 minute.
- Supabase Free has a 500 MB database limit and may pause inactive projects.
- Keep regular copies using the ERP's Download backup button.
- Do not delete your old ERP or original backup until the new cloud ERP is fully verified.

CASHIER LOGIN
Select Cashier and enter PIN: 1010.

TROUBLESHOOTING
- If Render says Supabase is not configured, check the four Environment variables above.
- If PIN login fails, verify the selected account and PIN, then check that the Render service is Live. Legacy ERP_ADMIN_PASSWORD and ERP_VISITOR_PASSWORD variables remain in the deployment template for compatibility; the three current account PINs are verified by the application server.
- If SQL fails, make sure you ran the entire supabase-setup.sql in the correct Supabase project.

------------------------------------------------------------
WHAT'S NEW IN THIS VERSION (no new environment variables needed)
------------------------------------------------------------
1. DOWNLOAD PDF - a "Download PDF" button sits beside "Print" on every tab. It builds
   the PDF inside the app (works offline, no extra service). Admin > "Download full
   report (PDF)" creates one PDF with every tab for the selected month.
2. CASH BOOKS - the "Smashed Burger" cash book was removed from Expenses > Expense from
   cash. Older entries in it are kept but hidden; Admin shows a button to delete them.
3. ADMIN PANEL (admin only) - new "Admin" tab: monthly checklist, items needing attention
   (menu items without cost, inventory items without price, negative stock, open reviews,
   vendor dues), business settings (Foodpanda %, add a branch, expense lines),
   accounts and access, record counts, backup/restore and the full PDF report.
4. CASHIER ACCOUNT (operational access)
   - Sign-in ID: Cashier; use the four-digit PIN listed in the Account Sign-in section.
   - The server sends this account only the inventory, dispatch, wastage and cash-book
     information needed for daily operations. It cannot access sales, salary, vendor
     balances, menu costs, reviews or Admin settings. Server-side write restrictions apply.
5. Legacy Staff login, if previously configured, remains restricted to Dispatch and Expenses.
6. Unchanged: Supabase storage, Render settings, environment variable names, database
   table, PWA manifest, service worker and icons.


LATEST ACCESS-CONTROL UPDATE (2026-11-03)
- Cashier can add operational records in Inventory, Dispatch, Wastage and cash-book sections.
- Historical expense, cash-book, transportation, stock-in and wastage rows are protected from Cashier edits/deletions by the backend.
- Admin retains historical correction/deletion permissions.
- PIN sign-in is server-verified; the browser does not contain the account PINs.
- Service worker cache version is increased so installed phones fetch the updated app shell.

LATEST MAINTENANCE UPDATE
- Backend now validates nested JSON size/depth and rejects malformed or unsupported
  Cashier payload fields before saving.
- Cashier inventory submissions reject blank/duplicate item names and oversized
  item names/category/unit fields. Protected Admin fields remain server-owned.
- Admin data submissions also receive recursive structure/size validation.
- Service worker cache version has been incremented so deployed phones refresh
  the updated app shell. API/business data is never cached offline.

After deployment, test Admin and Cashier accounts and download a fresh data backup.
The Admin Quick Access area currently provides shortcuts to tab-level add forms;
it does not yet relocate every add form into one central screen. Supabase automatic
point-in-time backups are not configured by this application; download backups
regularly and use Supabase's own backup/export options where available.


iPhone / iPad installation (iOS):
1. Open the live HTTPS Render website in Safari (not an in-app browser).
2. Tap the Share button.
3. Choose Add to Home Screen.
4. Enable Open as Web App if iOS shows that option, then tap Add.
The app icon uses apple-touch-icon.png. iOS does not show a Chrome-style automatic install prompt; installation is done through Safari's Share menu. An internet connection is still required for live ERP data.


LATEST UPDATE (Nov 2026)
- Expenses now has Transportation, Expense from cash, and Bills and rent (Admin only).
- Transportation supports Car, CNG, Bike and Rickshaw and is automatically included in the cash expense ledger and daily closing calculation.
- Cash book supports day-wise opening cash, cash sales, other cash-in, expenses and closing cash. Opening cash carries forward from the previous day's closing unless manually entered. Cash sale is a cash-book entry and does not alter Sales tab figures.
- Cashier can access only Transportation, Expense from cash, Inventory and Dispatch. Cashier cannot access Sales or Bills and rent. These restrictions are enforced by the backend.


LATEST UI REFINEMENTS
- Expense from cash now uses one shared selected date: changing the date at the top updates the opening-cash field, and selecting a day in the daily closing table updates the same date selector.
- Transportation now shows a monthly summary for Gulshan and Dhanmondi below the entry list.
- Foodpanda commission control has been removed from Bills and Rent; the central setting remains under Admin > Business settings because Foodpanda profitability calculations still use it.
- Service worker cache version bumped to refresh the updated app shell.

LATEST BUG-FIX PASS (2026-11-03)
- Cashier sign-in now requires the server; the old local-only fallback no longer
  contains or accepts PINs in browser JavaScript.
- Cashier can add cash-book sales/inflows and opening cash, but saved cash-book,
  cash-expense, transport, stock-in and wastage history is append-only for Cashier.
  Admin retains the ability to correct or remove historical entries.
- Cashier cannot delete stock-in history or edit/delete saved cash sales, cash-in
  records, or an existing opening-cash value from the interface.
- Backend validates dates, amounts and required fields for Cashier dispatch,
  stock-in, transport, cash-book and wastage submissions before saving.
- Existing inventory items cannot be removed or have their category/unit changed
  by Cashier; adding new inventory items remains supported.
- Dashboard profit-and-loss now includes cash expenses and transportation in the
  expense calculation, allocated across each branch's channels consistently with
  salary and bills/rent.
- Stock-in display safely handles legacy rows with a zero quantity.
- Service worker cache version bumped to refresh the updated app shell.

ACCOUNT SIGN-IN
- Admin PIN: 1715
- Smashed (view-only) PIN: 5050
- Cashier PIN: 1010
- The PINs are verified by the ERP server. Keep the Render deployment private to
  the intended staff and do not share PINs outside the business.
