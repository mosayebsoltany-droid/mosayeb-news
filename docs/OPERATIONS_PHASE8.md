# فاز ۸: عملیات، پایش و آمادگی PostgreSQL — نسخه ۰٫۵٫۰

این نسخه شبیه‌سازی است. سلامت برنامه، موفقیت تست و وجود Docker به‌معنای تأیید سازمانی، آزمون ظرفیت یا آمادگی کامل تولید نیست. CI/CD و Docker از نسخهٔ قبلی وجود دارند.

## تنظیمات محیط

در اجرای مستقیم Python، `app/config.py` فایل `.env` را از ریشهٔ پروژه، مستقل از پوشهٔ فعلی، می‌خواند. متغیرهای فرایند بر فایل اولویت دارند. تنظیمات cache می‌شوند؛ پس از تغییر، سرویس را مجدداً اجرا کنید. نام‌های موجود `BROKER_*` حفظ شده‌اند؛ نام‌های کوتاه `SECRET_KEY` و `DATABASE_URL` استفاده نمی‌شوند.

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# مقدار تولیدشده را فقط در BROKER_JWT_SECRET فایل محلی قرار دهید.
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

فایل واقعی `.env` در Git نادیده گرفته می‌شود و وارد تصویر Docker نمی‌شود. فایل نمونه کلید ندارد. کلید حداقل ۳۲ بایت است؛ نبود کلید ورود را با ۵۰۳ غیرفعال می‌کند. الگوریتم فقط HS256 و زمان توکن بین ۱ تا ۱۲۰ دقیقه است. نشانی دیتابیس و کلید در نمایش تنظیمات مخفی می‌شوند. برای تولید، فایل/Secret Manager را با دسترسی محدود نگه دارید.

| متغیر | پیش‌فرض / کاربرد |
| --- | --- |
| BROKER_JWT_SECRET | خالی؛ ورود غیرفعال تا تنظیم کلید |
| BROKER_ACCESS_TOKEN_EXPIRE_MINUTES | ۳۰ دقیقه |
| BROKER_DATABASE_URL | SQLite کنار پروژه؛ در Docker، `/data/broker.db` |
| BROKER_MOCK_REGISTRY_URL | `http://mock-registry/submit`؛ شبیه‌ساز داخل فرایند |
| BROKER_REGISTRY_TIMEOUT_SECONDS | ۵ ثانیه برای هر تلاش |
| BROKER_MOCK_FAILURE_RATE | ۰٫۲؛ بین صفر و یک |
| BROKER_AUTO_CREATE_TABLES | true؛ تنها برای SQLite |
| BROKER_ALLOWED_HOSTS | فهرست صریح دامنه‌ها؛ در Codespaces دامنهٔ دقیق پورت لازم است |
| BROKER_CORS_ORIGINS | خالی؛ در صورت نیاز مبدأهای HTTPS مشخص |

برای شبیه‌ساز مستقل، نشانی HTTPS آزمایشی را در `BROKER_MOCK_REGISTRY_URL` تنظیم کنید. HTTP فقط برای localhost و شبیه‌ساز داخلی مجاز است. redirect دنبال نمی‌شود؛ اطلاعات احراز هویت در URL پذیرفته نیست. Retry فقط برای خطاهای ارتباطی و 5xx است؛ 4xx تکرار نمی‌شود. با وجود سه تلاش و backoff، زمان کل از timeout یک تلاش بیشتر است. این تنظیم به‌تنهایی اتصال واقعی سازمان ثبت را ایجاد نمی‌کند.

## پایش

| مسیر | پاسخ | کاربرد |
| --- | --- | --- |
| GET /live | ۲۰۰ | فرایند پاسخ می‌دهد؛ دیتابیس را صدا نمی‌زند |
| GET /ready | ۲۰۰ یا ۵۰۳ | SELECT 1 روی دیتابیس |
| GET /health | همان readiness | سازگاری با پنل و Docker |

پاسخ موفق شامل `status: ok`، `database: connected`، `mode: simulation` و نسخه است. هنگام خرابی دیتابیس، `status: unhealthy` و `database: disconnected` با HTTP 503 برمی‌گردد. نام میزبان، رمز و متن استثنا در پاسخ یا لاگ readiness نیست. پاسخ liveness، صحت همهٔ سرویس‌ها را تضمین نمی‌کند.

```bash
curl -i http://127.0.0.1:8000/live
curl -i http://127.0.0.1:8000/ready
```

در Kubernetes، liveness را به `/live` و readiness را به `/ready` بدهید. healthcheck فعلی Docker از `/health` استفاده می‌کند. اتصال و statement timeout دیتابیس محدود شده‌اند؛ SELECT 1 سلامت schema یا سامانهٔ ثبت را بررسی نمی‌کند.

## PostgreSQL جدید و خالی

درایور Psycopg 3 و Alembic در requirements هستند. فقط برای یک دیتابیس تست خالی و مجاز:

```bash
export BROKER_DATABASE_URL='postgresql+psycopg://broker:URL_ENCODED_PASSWORD@127.0.0.1:5432/broker'
export BROKER_AUTO_CREATE_TABLES=false
python -m alembic upgrade head
python -m alembic check
python -m app.create_user uat_broker
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

رمز داخل URL باید URL-encode شود. برای سرور راه دور از TLS با اعتبارسنجی گواهی طبق تنظیمات سرور استفاده کنید. startup برنامه و CLI در PostgreSQL جدول نمی‌سازند؛ مهاجرت را پیش از راه‌اندازی و یک بار توسط مسئول استقرار اجرا کنید. تصویر Docker فایل‌های migration را دارد؛ با `docker compose run --rm broker python -m alembic upgrade head` نیز می‌توان دیتابیس جدید تنظیم‌شده را آماده کرد. `localhost` در کانتینر به خود کانتینر اشاره می‌کند، نه میزبان PostgreSQL.

مهاجرت `0001` هر پنج جدول، کلیدهای خارجی و ایندکس‌ها را ایجاد می‌کند. آزمون CI یک PostgreSQL واقعی موقت دارد و پس از migration، نبود اختلاف schema و گردش ورود → ادعا → پیگیری → PDF → audit را بررسی می‌کند.

## SQLite موجود و انتقال داده

دیتابیس فعلی خودکار جابه‌جا یا پاک نمی‌شود. رفتار `create_all` برای SQLite قبلی حفظ شده است. `alembic upgrade head` را روی دیتابیس دارای جدول‌های قدیمی و بدون تاریخچهٔ Alembic اجرا نکنید؛ برای دیتابیس موجود، ابتدا نسخهٔ پشتیبان، مقایسهٔ کامل schema با migration پایه و سپس baseline توسط مسئول فنی لازم است. `stamp` بدون تطبیق ساختار فقط شماره نسخه را ثبت می‌کند و اصلاح schema نیست.

عوض کردن URL، داده‌های SQLite را به PostgreSQL منتقل نمی‌کند. انتقال واقعی نیاز به توقف نوشتن، backup و آزمون restore، export/import کنترل‌شده با حفظ شناسه‌ها و روابط، تنظیم sequenceها، تطبیق تعداد/محتوا و آزمون دسترسی و rollback دارد. این مرحله روی دادهٔ موجود اجرا نشده است. از downgrade روی دیتابیس دارای اطلاعات استفاده نکنید؛ migration پایه جدول‌ها را حذف می‌کند.

## شواهد ارائه

```bash
python -m pip install -r requirements-dev.txt
python -m pytest test_main.py test_scenarios.py test_operations.py -v
```

بدون TEST_POSTGRES_URL فقط آزمون PostgreSQL skip می‌شود؛ بقیه باید پاس شوند. در CI همه، همراه PostgreSQL اجرا می‌شوند. آزمایش‌ها از دیتابیس موقت استفاده می‌کنند. تصاویر Swagger، پنل و نتیجهٔ آزمون باید با نسخه و وضعیت همان اجرای زنده همراه باشند؛ تصویر موفق محیط توسعه تأیید باز شدن لینک روی گوشی دیگران نیست.

برای نمونهٔ گواهی، فقط دادهٔ ساختگی در دمو بسازید: ثبت ادعا → ارسال آزمایشی → خدمت گواهی با کد ادعای تکمیل‌شده → ارسال → دانلود PDF. فایل صریحاً آزمایشی است. برای سرویس احرازشده، مسیر GET `/services/certificate/{tracking_code}` تنها ادعای موفق متعلق به همان کاربر را می‌پذیرد.

Retry و Circuit Breaker با سناریوهای قطعی کنترل‌شده تست می‌شوند؛ مدار پس از پنج شکست تماس باز می‌شود و پس از ۶۰ ثانیه تنها یک probe اجازهٔ بازیابی دارد. این مدار داخل هر فرایند است. پایش و اعلان دائمی، محدودسازی نرخ ورود، آزمون بار/نفوذ و انتقال دادهٔ عملیاتی هنوز تکمیل نشده‌اند.

منابع فنی: [Pydantic Settings](https://pydantic.dev/docs/validation/dev/concepts/pydantic_settings/)، [SQLAlchemy PostgreSQL/Psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)، [Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html).
