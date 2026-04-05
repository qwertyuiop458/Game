# GitHub proxy allowlist (for CI/API automation)

Этот документ нужен для инфраструктурной команды, чтобы разрешить сетевой доступ из среды агента к GitHub.

## Домены, которые нужно разрешить

- `github.com`
- `api.github.com`
- `uploads.github.com`
- `raw.githubusercontent.com`
- `objects.githubusercontent.com`
- `codeload.github.com`

## Порт и тип трафика

- Разрешить `CONNECT` на `:443` к доменам выше.
- Если proxy делает TLS-intercept, сертификат MITM должен быть корректно доверен в среде запуска.

## Проверочные команды

После внесения allowlist в proxy, в среде должны проходить:

```bash
curl -I https://github.com
curl -I https://api.github.com
curl -I https://raw.githubusercontent.com
```

## Пример для Squid (ориентир)

```conf
acl github_domains dstdomain .github.com .api.github.com .uploads.github.com .raw.githubusercontent.com .objects.githubusercontent.com .codeload.github.com
acl SSL_ports port 443
acl CONNECT method CONNECT

http_access allow CONNECT github_domains SSL_ports
```

> Примечание: синтаксис и политика могут отличаться в вашей инфраструктуре. Используйте это как шаблон для сетевого администратора.

## Пример для Envoy (ориентир)

- В egress-политике/route rules добавить разрешение на SNI/host из списка доменов выше.
- Убедиться, что `CONNECT`/TLS upstream разрешён для `443`.

## Почему это нужно

Без allowlist API-вызовы к GitHub (`workflow_dispatch`, comments API, artifact download) завершаются ошибкой:

- `curl: (56) CONNECT tunnel failed, response 403`

Из-за этого невозможен полностью кодовый запуск цепочки:

- post `/run-apk` comment
- wait workflow
- download `emulator-output`
