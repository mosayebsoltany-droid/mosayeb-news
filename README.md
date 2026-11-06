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

## اجرای Docker و تحویل نسخه

```bash
docker build -t real-estate-broker:local .
docker run -d --name broker -p 127.0.0.1:8000:8000 -v broker-data:/data real-estate-broker:local
curl -fsS http://127.0.0.1:8000/health
```

دیتابیس SQLite در ولوم `broker-data` می‌ماند. برای اولین اجرا از یک ولوم خالی استفاده کنید. در سرور، دسترسی مرورگر را از طریق پراکسی HTTPS تنظیم کنید. این نسخه آزمایشی را با داده واقعی استفاده نکنید.

GitHub Actions روی شاخه `real-estate-broker` و درخواست‌های ادغام به آن، تست Python و اجرای آزمایشی کانتینر را انجام می‌دهد. با ثبت تگ `broker-vX.Y.Z` روی کامیت همین شاخه، پس از موفقیت تست‌ها، تصویر همان نسخه در GHCR منتشر می‌شود. قبل از تگ، نسخه FastAPI و CHANGELOG را به‌روزرسانی کنید.

روی سرور Docker، با دسترسی خواندن بسته وارد GHCR شوید، تصویر تگ‌شده را pull کنید و همان دستور docker run بالا را با نام تصویر GHCR اجرا کنید. برای ارتقا، کانتینر قبلی را پس از پشتیبان‌گیری از ولوم متوقف و جایگزین کنید و ولوم را دوباره متصل کنید. انتشار تصویر خودکار است. استقرار روی سرور پس از تعیین مقصد و دسترسی انجام می‌شود.

```bash
docker pull ghcr.io/mosayebsoltany-droid/real-estate-broker-system:broker-v0.1.0
```
