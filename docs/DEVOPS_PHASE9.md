# فاز ۹: Docker، PostgreSQL و لاگ JSON — نسخه ۰٫۶٫۰

Docker و CI/CD از قبل وجود داشتند. در این نسخه build چندمرحله‌ای شده و یک ترکیب مستقل PostgreSQL همراه مهاجرت اولیه، لاگ ساختاریافته و آزمون قطعی/بازیابی دیتابیس اضافه شده است. دادهٔ SQLite فعلی جابه‌جا نمی‌شود.

## اجرای SQLite قبلی

```bash
docker compose up --build --detach --wait
```

حجم `broker-data` قبلی حفظ می‌شود و پورت محلی ۸۰۰۰ است. تصویر با Python 3.12 ساخته می‌شود؛ wheelها در مرحلهٔ builder آماده و بدون مراجعه به شبکه در مرحلهٔ runtime نصب می‌شوند. کد فقط خواندنی برای کاربر UID 10001 است. پوشهٔ داده writable، فایل‌های app/root-owned و `.env` خارج از تصویرند. فونت PDF فارسی و مهاجرت‌ها در تصویر باقی‌اند.

## اجرای مستقل PostgreSQL

ابتدا در `.env` محلی یک `BROKER_JWT_SECRET` تصادفی حداقل ۳۲ بایت و یک `BROKER_POSTGRES_PASSWORD` مستقل بگذارید. برای هر کدام جداگانه `python -c "import secrets; print(secrets.token_urlsafe(48))"` اجرا کنید. رمز PostgreSQL باید URL-safe باشد؛ رمز دارای `@`، `:`، `/`، `%` و سایر جداکننده‌های URL را مستقیم در این Compose استفاده نکنید. هیچ رمز ثابتی در YAML نیست. خروجی `docker compose config` می‌تواند مقادیر محیطی را آشکار کند و نباید منتشر شود.

```bash
docker compose -f compose.postgres.yaml up --build --detach --wait --wait-timeout 180
curl -fsS http://127.0.0.1:8002/ready
docker compose -f compose.postgres.yaml exec broker python -m app.create_user uat_broker
```

ترتیب راه‌اندازی: سلامت PostgreSQL → اجرای موفق Alembic → API. شکست migration مانع شروع API می‌شود. migration با همان تصویر و کاربر غیرروت اجرا می‌شود. API در این ترکیب filesystem فقط‌خواندنی، `/tmp` موقت، capabilities حذف‌شده و no-new-privileges دارد. کد میزبان روی `/app` bind mount نشده است.

داده در حجم مستقل `broker-postgres_postgres-data` و پورت API روی loopback ۸۰۰۲ نگه‌داری می‌شود. PostgreSQL روی میزبان پورت منتشر نمی‌کند. دمو بدون ورود بسته است؛ از Swagger و حساب CLI استفاده کنید. برای دسترسی دیگر دستگاه‌ها، استقرار پشت HTTPS و دامنهٔ مجاز لازم است. پورت را بدون بررسی دسترسی عمومی نکنید.

```bash
docker compose -f compose.postgres.yaml stop
docker compose -f compose.postgres.yaml start
```

برای توقف معمولی `down` نیز داده را حفظ می‌کند؛ `down --volumes` داده را حذف می‌کند و فقط برای محیط CI یک‌بارمصرف استفاده می‌شود. تغییر رمز `.env` پس از ایجاد volume، رمز کاربر داخل PostgreSQL موجود را تغییر نمی‌دهد. برای تغییر رمز، رویهٔ مستقل و مجاز لازم است. در نسخهٔ حاضر نقش migration و runtime دیتابیس جدا نشده‌اند؛ تفکیک نقش‌ها و حداقل مجوزها پیش از تولید لازم است.

### Redis اختیاری

```bash
docker compose -f compose.postgres.yaml --profile cache up --build --detach --wait
docker compose -f compose.postgres.yaml exec redis redis-cli ping
```

این profile سرویس Redis را با کاربر `redis`، بدون پورت میزبان و بدون ذخیرهٔ دائمی اجرا می‌کند. Redis در این نسخه به کش، نشست JWT یا Circuit Breaker برنامه متصل نشده است؛ فقط زیرساخت و ping آن آزموده می‌شوند. JWT همچنان stateless و مدار داخل هر فرایند است. شبکهٔ Compose به‌تنهایی جای احراز هویت/TLS Redis را در استقرار چندمیزبانه نمی‌گیرد.

## لاگ‌ها و جمع‌آوری مرکزی

لاگ‌های برنامه و Uvicorn در تصویر با JSON روی stdout نوشته می‌شوند. هر درخواست رکوردی با `request_id`، method، route template، status و duration_ms دارد. `X-Request-ID` پاسخ با لاگ قابل تطبیق است. مسیرهای ناشناخته `<unmatched>` می‌شوند. Query، متن ورودی، رمز، توکن، IP و کد رهگیری در رکورد access نیستند. خطاها نوع exception را بدون traceback/متن حساس ثبت می‌کنند. AuditLog کسب‌وکار همچنان در دیتابیس باقی می‌ماند.

```bash
docker compose -f compose.postgres.yaml logs --no-log-prefix --follow broker
```

برای اجرای مستقیم، از همان قالب استفاده کنید:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --log-config app/uvicorn_logging.json
```

driver محلی Docker، هر سرویس را به سه فایل حداکثر ۱۰ مگابایتی محدود می‌کند. JSON stdout و rotation محلی، ذخیره‌سازی مرکزی نیستند. Collector مثل Fluent Bit/Vector می‌تواند این خروجی را دریافت کند، اما Elastic، Grafana، Prometheus، Sentry و ارسال ایمیل/تلگرام نصب یا متصل نشده‌اند. `/live` زنده‌بودن فرایند و `/ready` سلامت اتصال دیتابیس را نشان می‌دهد.

## CI و تحویل

خط موجود `.github/workflows/broker.yml` روی شاخهٔ واقعی `real-estate-broker` و tagهای `broker-v*` اجرا می‌شود. خط موازی روی شاخهٔ نامرتبط `main` ساخته نشده است.

1. آزمون‌ها با SQLite موقت و PostgreSQL واقعی؛ شامل صحت JSON و حذف دادهٔ حساس.
2. build چندمرحله‌ای و smoke تست SQLite و Staging.
3. اجرای Compose مستقل با PostgreSQL، Alembic و Redis اختیاری.
4. تأیید UID غیرروت، ورود، ادعا، پیگیری، PDF و audit روی شبکهٔ کانتینر.
5. توقف دیتابیس: readiness=503 و liveness=200؛ راه‌اندازی مجدد و readiness=200.
6. بررسی خروجی JSON، آرشیو و انتشار همان تصویر آزمایش‌شده در GHCR با SHA.

انتشار image به معنی استقرار خودکار روی سرور سازمان نیست. کلیدها فقط به runtime تزریق می‌شوند و رمزهای CI فقط برای دیتابیس‌های موقت‌اند. برای تولید، backup/restore عملیاتی، نقش‌های محدود دیتابیس، TLS، آزمون بار/نفوذ، rate limiting و مانیتورینگ مرکزی همچنان باقی‌اند. فقط معماری و محیط CI تست‌شده ادعا می‌شود؛ اجرا روی تمام معماری‌ها/سرورها تضمین نشده است.

منابع: [Docker Python](https://docs.docker.com/guides/python/)، [Docker Secrets](https://docs.docker.com/compose/how-tos/use-secrets/)، [Python JSON Logger](https://nhairs.github.io/python-json-logger/latest/).
