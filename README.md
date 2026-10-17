# Mosayeb News — خبرگزاری مسیب

نسخه اولیه وب‌سایت خبری فارسی برای Cloudflare Workers و Supabase.

## استقرار رایگان
1. Cloudflare > Workers & Pages > Create > Connect GitHub و مخزن `mosayebsoltany-droid/mosayeb-news` را انتخاب کنید.
2. Project name: `mosayeb-news`، Build command خالی، Deploy command: `npx wrangler deploy`.
3. پس از اولین استقرار، در Worker > Settings > Variables and Secrets دو متغیر تنظیم کنید:
   - `SUPABASE_URL`: آدرس پروژه Supabase
   - `SUPABASE_PUBLISHABLE_KEY`: کلید عمومی publishable پروژه (نه secret/service_role)
4. دوباره Deploy کنید و مسیرهای `/`، `/health` و `/api/news` را بررسی کنید.

## امنیت
فقط اخبار با وضعیت `published` از REST API خوانده می‌شوند. سیاست RLS در Supabase نیز باید فقط ردیف‌های منتشرشده را برای anon قابل خواندن کند. هیچ کلید محرمانه‌ای نباید وارد GitHub شود.

## محدوده نسخه
صفحه نمایش اخبار و API خواندن اخبار پیاده‌سازی شده‌اند. پنل مدیریت، جمع‌آوری RSS و بازنویسی AI در این نسخه وجود ندارند. انتشار در Cloudflare هنوز نیازمند اتصال حساب و اجرای Deploy است.
