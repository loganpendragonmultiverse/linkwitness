# Testing

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src
pytest
python -m build
```

The redirect suite uses urllib's real redirect/error dispatcher with a mocked
HTTP/HTTPS transport and synthetic DNS answers. No remote URLs or private
networks are contacted. Cover public-to-private redirects, IPv4/IPv6 literals,
mixed DNS answers, same-host relative redirects, changed DNS answers, all
supported redirect status codes (including Python 3.10 rejection of unsupported
308 responses), repeated/distinct-target hop limits, explicit
allow_private, response closure, batch continuation and strict failure.

The initial-only validation regression was reproduced against 1.1.0: an
in-memory public-to-private redirect was followed without a second policy check.
That case must now fail before the private transport is reached.

Verify the bundled offline README example and package versions in fresh wheel
and extracted-source installations. Compare packaged README, changelog,
development and testing guidance with source. DNS checks are not proof of
comprehensive SSRF prevention or control over transport resolution/proxies.

## Upper-bound regression

An in-memory chain with `max_redirects: 10000` reproduced an uncaught
`RecursionError` before the fix. Reject that configuration before DNS or
transport, accept exactly 20 successful hops, reject the next hop, and bound
both distinct-target and repeated-target chains at the documented maximum.
