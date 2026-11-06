# اجرا و انتشار

## Docker

در ریشه شاخه `real-estate-broker` اجرا کنید.

```bash
docker compose up --build --detach --wait
docker compose ps
docker compose logs broker
curl -fsS http://127.0.0.1:8000/health
docker compose down
```

آدرس مستندات `http://127.0.0.1:8000/docs` است. پاسخ سلامت مورد انتظار `{"status":"ok","mode":"simulation"}` است. سرویس با کاربر غیرمدیر اجرا می‌شود. فایل SQLite در ولوم Compose و مسیر `/data/broker.db` است. دستور `docker compose down` داده را حفظ می‌کند. گزینه `--volumes` ولوم را حذف می‌کند و در CI برای داده آزمایشی استفاده می‌شود.

## گوشی

از مرورگر گوشی [Codespaces شاخه پروژه](https://github.com/codespaces/new?repo=1422906786&ref=real-estate-broker) را باز کنید. پس از ساخت محیط و آماده‌شدن Compose، در **Ports** آدرس پورت خصوصی **8000** را باز کنید. برای Swagger انتهای آدرس `/docs` را اضافه کنید. آدرس به همان Codespace تعلق دارد و هنگام توقف محیط از دسترس خارج می‌شود. برای بررسی دستی در ترمینال Codespace، دستورهای بخش Docker را اجرا کنید.

## CI و ایمیج

Workflow روی push شاخه پروژه، تگ‌های `broker-v*` و PR به شاخه پروژه اجرا می‌شود. پس از تست Python، Docker Compose ایمیج را می‌سازد و کانتینر را راه‌اندازی می‌کند. CI منتظر سلامت می‌ماند و Swagger و جدول‌های SQLite را بررسی می‌کند. فایل فشرده ایمیج در صفحه اجرای Actions در بخش **Artifacts** به نام `broker-docker-image` تا ۳۰ روز نگه داشته می‌شود. روی push، همان آرشیو به GHCR منتقل می‌شود. نام تگ برای کامیت عادی `sha-<full-commit-sha>` و برای نسخه رسمی `broker-vX.Y.Z` است.

```bash
docker load -i broker-image.tar.gz
docker run --rm -p 127.0.0.1:8000:8000 -v broker-data:/data real-estate-broker:local
```

برای انتشار رسمی، نسخه برنامه و CHANGELOG را به‌روز کنید، CI را بررسی کنید و روی کامیت تأییدشده تگ نسخه بگذارید. برای استقرار آتی روی سرور، پس از احراز دسترسی به GHCR، نسخه مشخص را pull کنید و با ولوم پشتیبان‌گیری‌شده و پراکسی HTTPS اجرا کنید. استقرار سرور خارج از گردش‌کار فعلی است.
