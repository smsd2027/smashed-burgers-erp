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
   Keep the existing ERP_ADMIN_PASSWORD and ERP_VISITOR_PASSWORD variables if they are already configured. This update does not require new variables; the one-time PIN migration below initializes the three requested accounts.
6. Save changes only if you changed anything. Wait until status is Live.
7. Open the URL ending in .onrender.com.

D. FIRST LOGIN AND DATA
1. After deploying the 4 November update, sign in by selecting Admin and entering the initial PIN 1715.
2. The first Admin login creates the ERP's initial data if the database is empty.
3. In the ERP, use Restore backup and choose your existing ERP backup JSON file.
4. Check sales, menu, expenses, inventory, vendors, salary and review screenshots.
5. Download a fresh backup after checking everything.

VIEWER LOGIN
Select Smashed and enter the initial PIN 5050.

IMPORTANT LIMITATIONS
- Render Free sleeps after 15 minutes without requests; the first request may take around 1 minute.
- Supabase Free has a 500 MB database limit and may pause inactive projects.
- Keep regular copies using the ERP's Download backup button.
- Do not delete your old ERP or original backup until the new cloud ERP is fully verified.

TROUBLESHOOTING
- If Render says Supabase is not configured, check the four Environment variables above.
- If login fails, check that both ERP passwords were saved in Render Environment and wait for redeploy.
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
4. CASHIER ACCOUNT
   - Select Cashier and enter the initial PIN 1010.
   - Cashier can access Transportation, Expense from cash, Inventory and Dispatch.
   - Cashier cannot access Sales, Bills and rent, salaries, vendor balances, menu costs, reviews or Admin settings. Server-side write restrictions are enforced.
5. Legacy Staff login, if previously configured, remains restricted to Dispatch and Expenses.
6. Unchanged: Supabase storage, Render settings, environment variable names, database
   table, PWA manifest, service worker and icons.


LATEST ACCESS-CONTROL UPDATE (2026-11-01)
- Cashier is view-only for Inventory and Dispatch. Only Admin can create or change records.
- Only the Admin session can change account passwords; the backend enforces this even if someone calls the API directly.
- Cashier cannot open password-management controls.
- Service worker cache version was increased so installed phones fetch the updated app shell.

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


LATEST FEATURE UPDATE — 4 NOVEMBER 2026
--------------------------------------
This update adds the requested navigation, dispatch and wastage workflows.

LOGIN
- Choose an account first, then enter its 4-digit PIN.
- Admin: 1715
- Smashed (read-only visitor): 5050
- Cashier: 1010
- These are initial rollout PINs. Admin can change them in the ERP using Change account PIN.
- The first server start after this update performs a one-time credential migration and stores salted PIN hashes in the existing users field. No database schema change is required.
- Keep the existing Render environment variable names and values; this update does not require new environment variables. The initial PIN migration takes precedence for the three listed accounts.

NAVIGATION AND WORKFLOWS
- Cashier logo returns to Expenses > Overview. Clicking Expenses always opens Overview.
- Dispatch has Overview and Daily Dispatches. The monthly Overview groups dispatched items by branch and shows quantities, estimated purchase-cost amounts and totals.
- Wastage is Admin-only and records date, item, quantity, amount, From, To and a required photo proof. Photo thumbnails open a larger preview. Wastage photos are included in downloadable backups.
- Cashier can add new cash expenses, cash inflows, cash sales and transportation entries, but existing preview rows are read-only. The backend also enforces append-only access for existing expense/cash records.

DEPLOYMENT
- Replace the complete project files in the existing GitHub repository and let Render deploy.
- Do not rerun SQL or change the existing Supabase project, table, service-role key, Render environment variable names, manifest, app icons or installation settings.
- After deployment, sign in as Admin with 1715, verify the existing data, and immediately change the initial Admin PIN. Then test Cashier (1010) and Smashed (5050).
- Download a backup before and after rollout. Keep the previous deployment/backup until all three accounts and the new tabs have been checked.
