# سامانه شبیه‌سازی کارگزاری ثبت — پله اول

این نسخه فقط ساختار پایه، مدل کاربران و رویدادها و بررسی سلامت دیتابیس را دارد.
به هیچ سامانه رسمی متصل نیست. احراز هویت، سرویس‌ها و PDF در پله‌های بعد اضافه می‌شوند.

## پیش‌نیاز

Python 3.10 یا جدیدتر. فایل ZIP را استخراج کنید و وارد پوشه پروژه شوید.

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
فهرست نیازمندی‌ها به پله اول محدود است؛ کتابخانه‌های امنیت، تلاش مجدد و PDF همراه همان مرحله اضافه می‌شوند.

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
