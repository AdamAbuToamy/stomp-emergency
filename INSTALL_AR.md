# تحديث موثوقية STOMP
أوقف التطبيق قبل التثبيت. الحسابات والبلاغات تبقى كما هي والمثبت يأخذ نسخة احتياطية.
هذا التحديث يغيّر سيرفر Java؛ يجب تنفيذ mvn -f server/pom.xml compile بعد التثبيت.
شغّل بعدها python3 scripts/run_dashboard.py --mode reactor.
لفحص الحماية أوقف التطبيق ثم نفّذ python3 scripts/test_resilience.py.
تفاصيل الخلل والإصلاحات والحدود موجودة في docs/TRANSPORT_RELIABILITY.md.
لا توجد تغييرات تصميم أو نشر في هذا التحديث.
