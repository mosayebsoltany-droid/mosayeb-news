# سامانه شبیه‌سازی کارگزاری ثبت

نسخهٔ ۰٫۶٫۰ میز کار فارسی، ورود کارگزار، ثبت ادعا، درخواست نقشه، پیگیری، گواهی آزمایشی PDF و مدیریت قطعی شبیه‌ساز ثبت را ارائه می‌کند. داده‌ها در SQLite نگه‌داری می‌شوند. برای مشاهدهٔ میز کار پس از راه‌اندازی، مسیر `/portal` را باز کنید. از دادهٔ ساختگی استفاده کنید.

## پیش‌نیاز

برای اجرای کامل، از Docker Compose استفاده کنید. اجرای مستقیم با Python 3.10 یا جدیدتر ممکن است. مسیر پیش‌فرض فونت PDF برای Debian و Ubuntu تنظیم شده است.

### ویندوز (CMD)

```bat
cd RealEstateBrokerSystem
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

اگر فعال‌سازی محیط در PowerShell محدود بود، بدون تغییر سیاست سیستم اجرا کنید:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### لینوکس و مک

```bash
cd RealEstateBrokerSystem
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

پس از اجرا:

- مستندات و آزمون API: http://127.0.0.1:8000/docs
- بررسی سلامت: http://127.0.0.1:8000/health
- پاسخ مورد انتظار: `{"status":"ok","mode":"simulation"}`

فایل `broker.db` هنگام راه‌اندازی، کنار همین README ساخته می‌شود؛ مسیر آن مستقل از پوشه فعلی ترمینال است.
جداول `users` و `audit_logs` ایجاد می‌شوند. کاربر پیش‌فرضی وجود ندارد.
فیلد `hashed_password` برای هش است؛ نباید رمز خام در آن ذخیره شود.
زمان رویدادها در SQLite با مبنای UTC ذخیره می‌شود.

## ساختار

```text
RealEstateBrokerSystem/
  app/
    __init__.py
    main.py
    database.py
    models.py
    schemas.py
    auth.py
  requirements.txt
  requirements-dev.txt
  .gitignore
  README.md
```

`create_all` فقط جداول غایب را ایجاد می‌کند و مهاجرت ساختار جداول موجود را انجام نمی‌دهد.
حذف `broker.db` همه کاربران و رویدادها را پاک می‌کند؛ برای تغییر ساختار در مراحل بعد، مهاجرت دیتابیس لازم است.

## اجرای Docker و مشاهده از گوشی

```bash
docker compose up --build --detach --wait
curl -fsS http://127.0.0.1:8000/health
```

[Swagger محلی](http://127.0.0.1:8000/docs) روی دستگاهی باز می‌شود که Docker روی آن اجرا شده است. برای گوشی، از مرورگر وارد [Codespaces همین شاخه](https://github.com/codespaces/new?repo=1422906786&ref=real-estate-broker) شوید و محیط را بسازید. راه‌اندازی محیط کانتینر را با Compose اجرا می‌کند. در تب **Ports** آدرس خصوصی پورت **8000** را باز کنید و `/docs` را به انتهای آن اضافه کنید. اگر محیط از قبل ساخته شده است، پیکربندی جدید را با **Rebuild Container** اعمال کنید.

- [راهنمای Docker و انتشار](docs/OPERATIONS.md)
- [تنظیمات، توکن‌ها و API](docs/CONFIGURATION.md)
- [فهرست تسک‌ها و معیار تحویل](docs/TASKS.md)
- [تغییرات نسخه‌ها](CHANGELOG.md)

## آزمون و تحویل نسخهٔ آزمایشی

وابستگی‌ها را با `python -m pip install -r requirements-dev.txt` نصب کنید و `python -m pytest -q` را اجرا کنید. برای اجرای مستقیم روی Debian یا Ubuntu، بستهٔ `fonts-dejavu-core` برای PDF فارسی لازم است. اجرای Docker این بسته را نصب می‌کند.

[مستندات ورود، گواهی PDF و مدیریت قطعی](docs/CONFIGURATION.md)

### اجرای آزمون‌های پذیرش

```bash
python -m pip install -r requirements-dev.txt
python -m pytest test_main.py -v
```

آزمون‌ها برای هر سناریو یک SQLite موقت می‌سازند و نرخ خطا و زمان بازیابی شبیه‌ساز را کنترل می‌کنند. در نتیجه می‌توان آزمون‌ها را بدون تغییر پایگاه دادهٔ کارگزاری و بدون انتظار واقعی ۶۰ ثانیه تکرار کرد.

| سناریو | نتیجهٔ مورد انتظار |
| --- | --- |
| سلامت و میز کار | مسیرهای اصلی و پایگاه داده پاسخ می‌دهند. |
| ساخت حساب و ورود | CLI حساب را ایجاد می‌کند و `POST /auth/token` برای رمز درست JWT می‌دهد. |
| دسترسی و اعتبارسنجی | توکن غایب یا نامعتبر ۴۰۱ و قالب نامعتبر کد ملی ۴۲۲ می‌گیرد. |
| ادعا، پیگیری و PDF | تلاش سوم می‌تواند موفق شود و فقط مالک ادعا به نتیجه و PDF دسترسی دارد. |
| قطعی و بازیابی | پس از پنج خطای متوالی، تماس متوقف می‌شود و پس از ۶۰ ثانیه امکان بازیابی دارد. |
| نقشه و دمو | درخواست‌های نقشه کدهای متمایز می‌گیرند و گردش کار گواهی آزمایشی به PDF می‌رسد. |

### معماری و حدود نسخهٔ تحویلی

FastAPI مسیرهای برنامه و OpenAPI را ارائه می‌دهد. SQLAlchemy روی SQLite کار می‌کند. رمز عبور با Argon2 از طریق pwdlib هش می‌شود و PyJWT توکن ورود را صادر می‌کند. کنترل دسترسی مسیرهای کارگزاری بر پایهٔ کاربر فعال و مالکیت پرونده است. HTTPX شبیه‌ساز ثبت را در همان فرایند فراخوانی می‌کند. Tenacity تلاش مجدد را انجام می‌دهد و fpdf2 با شکل‌دهی حروف، PDF فارسی می‌سازد.

فرایند نقشه و گواهی در محیط آزمایشی اجرا می‌شود. اتصال سازمانی به مشخصات API، دسترسی مجاز به محیط آزمون و تطبیق فرایند و داده‌ها نیاز دارد. [نگاشت الزامات و شواهد آزمون](docs/ACCEPTANCE.md)

## فاز ۷ — امنیت و QA

مدیریت خطای امن، هدرهای امنیتی، فهرست میزبان مجاز و CORS محدود اضافه شد. مسیر پاسخ اعتبارسنجی دارای متن در `detail` و فهرست بدون مقدار ورودی در `errors` است.

[راهنمای Staging و سناریوهای UAT](docs/STAGING.md)

## فاز ۸ — عملیات و پایش

[راهنمای تنظیمات، سلامت و مهاجرت PostgreSQL](docs/OPERATIONS_PHASE8.md). مسیرهای `/live` برای زنده‌بودن فرایند و `/ready` یا `/health` برای اتصال دیتابیس هستند. قطعی دیتابیس پاسخ ۵۰۳ بدون جزئیات حساس می‌دهد.

## فاز ۹ — DevOps

[راهنمای Docker چندمرحله‌ای، Compose PostgreSQL، Redis اختیاری و لاگ JSON](docs/DEVOPS_PHASE9.md). اجرای SQLite قبلی حفظ شده و ترکیب PostgreSQL از فایل `compose.postgres.yaml` استفاده می‌کند.
