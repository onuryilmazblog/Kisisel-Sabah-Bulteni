"""Komut satırı: `bulten <komut>`."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import load_config
from .db import connect, kv_get, migrate
from .sources.registry import seed_sources, sync_product_sources
from .settings_store import get_settings


def _conn():
    conn = connect()
    migrate(conn)
    seed_sources(conn)
    sync_product_sources(conn, get_settings(conn))
    return conn


def cmd_init(args) -> None:
    conn = _conn()
    cfg = load_config()
    print(f"Veri tabanı hazır: {cfg.database_path}")
    n = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    print(f"Kaynak sayısı: {n}")
    if cfg.secret_key_is_ephemeral:
        print("UYARI: APP_SECRET_KEY tanımlı değil; e-posta aksiyon bağlantıları ve oturumlar yeniden başlatmada geçersizleşir.")


def cmd_web(args) -> None:
    import uvicorn

    _conn()
    uvicorn.run("bulten.web.app:app", host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


def cmd_worker(args) -> None:
    from .worker.main import main

    main()


def cmd_check(args) -> None:
    from .pipeline.run import collect_and_process

    conn = _conn()
    res = collect_and_process(conn, only_critical=args.critical)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))


def cmd_bulletin(args) -> None:
    from .daily.service import refresh_daily
    from .delivery.dispatcher import enqueue_bulletin, process_deliveries
    from .pipeline.bulletin import compose_bulletin

    conn = _conn()
    refresh_daily(conn)
    bid = compose_bulletin(conn, kind="manual" if args.manual else "daily")
    print(f"Bülten #{bid} oluşturuldu.")
    if args.send:
        ids = enqueue_bulletin(conn, bid)
        print(f"{len(ids)} gönderim kuyruğa alındı.")
        print(process_deliveries(conn))


def cmd_validate(args) -> None:
    from .pipeline.validate import validate_daily, validate_sources

    conn = _conn()
    results = validate_sources(conn, slugs=args.slug or None, include_disabled=args.all)
    if not args.slug:
        results += validate_daily(conn, include_disabled=args.all)
    ok = 0
    for r in results:
        mark = "OK " if r["ok"] and not r["error"] else "HATA"
        ok += 1 if mark == "OK " else 0
        print(f"[{mark}] {r['slug']:<34} {r['items']:>4} kayıt  {r.get('duration_ms', 0):>6} ms  {r['url']}")
        if r["error"]:
            print(f"        hata: {r['error']}")
        for w in r["warnings"][:3]:
            print(f"        uyarı: {w}")
        for t in r["sample"]:
            print(f"        örnek: {t[:140]}")
    print(f"\n{ok}/{len(results)} kaynak doğrulandı.")
    sys.exit(0 if ok == len(results) else 1)


def cmd_demo_load(args) -> None:
    from .demo import load_demo

    bid = load_demo(_conn())
    print(f"Demo verisi yüklendi (demo bülten #{bid}). Arayüzde 'Demo' etiketiyle görünür.")


def cmd_demo_remove(args) -> None:
    from .demo import remove_demo

    remove_demo(_conn())
    print("Demo verisi silindi.")


def cmd_telegram_test(args) -> None:
    from .delivery.dispatcher import enqueue_test, process_deliveries
    from .delivery.telegram import TelegramClient

    cfg = load_config()
    if not cfg.telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN tanımlı değil.")
        sys.exit(1)
    me = TelegramClient(cfg).get_me()
    print(f"Bot: {me.get('username') if me else 'getMe başarısız (token veya ağ erişimi?)'}")
    conn = _conn()
    did = enqueue_test(conn, "telegram")
    if not did:
        print("Telegram kanalı ayarlarda kapalı veya chat id girilmemiş.")
        sys.exit(1)
    print(process_deliveries(conn))


def cmd_telegram_webhook(args) -> None:
    """Webhook modunu etkinleştirir (APP_BASE_URL https olmalı)."""
    from .delivery.telegram import TelegramClient

    cfg = load_config()
    if not (cfg.telegram_bot_token and cfg.telegram_webhook_secret and cfg.app_base_url.startswith("https://")):
        print("Gerekli: TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET ve https ile başlayan APP_BASE_URL.")
        sys.exit(1)
    client = TelegramClient(cfg)
    if args.remove:
        print(client._post("deleteWebhook", {}))
        return
    url = f"{cfg.app_base_url}/telegram/webhook/{cfg.telegram_webhook_secret}"
    res = client._post("setWebhook", {"url": url, "secret_token": cfg.telegram_webhook_secret,
                                      "allowed_updates": ["message", "callback_query"]})
    print(res)
    print("TELEGRAM_MODE=webhook olarak ayarlamayı unutmayın.")


def cmd_status(args) -> None:
    from .pipeline.collect import last_success_by_source
    from .usage import usage_summary

    conn = _conn()
    print("Worker nabzı:", kv_get(conn, "worker_heartbeat") or "yok")
    print("Son başarılı kontrol:", kv_get(conn, "last_success_check_at") or "yok")
    print("Başlangıç taraması:", kv_get(conn, "baseline_at") or "henüz yok")
    for s in last_success_by_source(conn).values():
        if s["enabled"]:
            print(f"  {s['slug']:<34} son başarı: {s['last_ok'] or '-':<27} son durum: {s['last_status'] or '-'}")
    print("Kullanım:", json.dumps(usage_summary(conn), ensure_ascii=False))


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="bulten", description="Kişisel Sabah Bülteni")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="Veri tabanını oluştur/güncelle ve kaynakları ekle").set_defaults(fn=cmd_init)
    w = sub.add_parser("web", help="Web arayüzünü başlat")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8000)
    w.set_defaults(fn=cmd_web)
    sub.add_parser("worker", help="Zamanlayıcı/worker'ı başlat").set_defaults(fn=cmd_worker)
    c = sub.add_parser("kontrol", help="Şimdi kontrol et (topla → eşleştir → analiz → özetle)")
    c.add_argument("--kritik", dest="critical", action="store_true", help="Yalnızca kritik alarm kaynakları")
    c.set_defaults(fn=cmd_check)
    b = sub.add_parser("bulten", help="Günlük bülteni şimdi oluştur")
    b.add_argument("--gonder", dest="send", action="store_true", help="Kanallara gönder")
    b.add_argument("--manuel", dest="manual", action="store_true", help="Günlük yerine anlık (manuel) bülten")
    b.set_defaults(fn=cmd_bulletin)
    v = sub.add_parser("kaynak-dogrula", help="Kaynakları canlı olarak test et (kayıt yazmaz)")
    v.add_argument("--slug", action="append", help="Yalnızca bu kaynak(lar)")
    v.add_argument("--hepsi", dest="all", action="store_true", help="Kapalı kaynakları da dene")
    v.set_defaults(fn=cmd_validate)
    sub.add_parser("demo-yukle", help="Kurgusal demo verisi yükle").set_defaults(fn=cmd_demo_load)
    sub.add_parser("demo-sil", help="Demo verisini sil").set_defaults(fn=cmd_demo_remove)
    sub.add_parser("telegram-test", help="Telegram test mesajı gönder").set_defaults(fn=cmd_telegram_test)
    tw = sub.add_parser("telegram-webhook", help="Telegram webhook'unu ayarla (varsayılan: long polling)")
    tw.add_argument("--kaldir", dest="remove", action="store_true", help="Webhook'u kaldır (polling'e dön)")
    tw.set_defaults(fn=cmd_telegram_webhook)
    sub.add_parser("durum", help="Durum özeti").set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    load_config()
    args.fn(args)


if __name__ == "__main__":
    main()
