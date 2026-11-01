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
   ERP_ADMIN_PASSWORD = choose a new password (at least 8 characters)
   ERP_VISITOR_PASSWORD = choose a different viewer password (at least 8 characters)
6. Save changes. Render will redeploy. Wait until status is Live.
7. Open the URL ending in .onrender.com.

D. FIRST LOGIN AND DATA
1. Sign in with ID: Admin and the ERP_ADMIN_PASSWORD you set.
2. The first Admin login creates the ERP's initial data if the database is empty.
3. In the ERP, use Restore backup and choose your existing ERP backup JSON file.
4. Check sales, menu, expenses, inventory, vendors, salary and review screenshots.
5. Download a fresh backup after checking everything.

VIEWER LOGIN
ID: Smashed
Password: the ERP_VISITOR_PASSWORD you set.

IMPORTANT LIMITATIONS
- Render Free sleeps after 15 minutes without requests; the first request may take around 1 minute.
- Supabase Free has a 500 MB database limit and may pause inactive projects.
- Keep regular copies using the ERP's Download backup button.
- Do not delete your old ERP or original backup until the new cloud ERP is fully verified.

TROUBLESHOOTING
- If Render says Supabase is not configured, check the four Environment variables above.
- If login fails, check that both ERP passwords were saved in Render Environment and wait for redeploy.
- If SQL fails, make sure you ran the entire supabase-setup.sql in the correct Supabase project.
