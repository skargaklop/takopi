# Oh My Pi runner

## Scope

Takopi exposes Oh My Pi as the **`omp`** engine backend.

The runner launches the terminal command directly:

```text
omp --print --mode json <prompt>
```

For resumed sessions, Takopi adds the OMP resume flag:

```text
omp --print --mode json --resume <token> <prompt>
```

## Telegram selection

Use `/omp` at the start of the first non-empty Telegram line:

```text
/omp inspect the failing tests
```

Canonical resume line (Takopi preserves and round-trips the full OMP session ID):

```text
`omp --resume 019fd7f2-d1dd-7000-97dd-dc3d5627ab43`
```

Takopi also accepts the Telegram-safe directive form:

```text
/omp resume 019fd7f2-d1dd-7000-97dd-dc3d5627ab43 continue
```

> **Note:** Unlike Pi (which abbreviates to an 8-character prefix for display),
> OMP session IDs are shown and resumed in full. This ensures reliable
> `--resume` matching even when short prefixes collide.

## Install

Install or update the CLI globally with Bun:

```text
bun install -g @oh-my-pi/pi-coding-agent
```

Takopi expects `omp` to be on `PATH`.

## Flags

Takopi uses these launch flags:

- `--print` for non-interactive operation
- `--mode json` for newline-delimited agent events
- `--resume <token>` for continuing an existing OMP session
- `--provider <value>` when configured
- `--model <value>` when configured or overridden
- `--thinking <value>` when a reasoning override is active

The event translator currently reuses the Pi JSON event schema because the
installed OMP package emits the same agent session event types.
