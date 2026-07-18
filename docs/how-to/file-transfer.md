# File transfer

Upload files into the active repo/worktree or fetch files back into Telegram.

## Enable file transfer

=== "takopi config"

    ```sh
    takopi config set transports.telegram.files.enabled true
    takopi config set transports.telegram.files.auto_put true
    takopi config set transports.telegram.files.auto_put_mode "upload"
    takopi config set transports.telegram.files.uploads_dir "incoming"
    takopi config set transports.telegram.files.allowed_user_ids "[123456789]"
    takopi config set transports.telegram.files.deny_globs '[".git/**", ".env", ".envrc", "**/*.pem", "**/.ssh/**"]'
    ```

=== "toml"

    ```toml
    [transports.telegram.files]
    enabled = true
    auto_put = true
    auto_put_mode = "upload" # upload | prompt
    uploads_dir = "incoming"
    allowed_user_ids = [123456789]
    deny_globs = [".git/**", ".env", ".envrc", "**/*.pem", "**/.ssh/**"]
    ```

Notes:

- File transfer is **disabled by default**.
- If `allowed_user_ids` is empty, private chats are allowed and group usage requires admin privileges.

## Upload a file (`/file put`)

Send a document with a caption:

```
/file put <path>
```

Examples:

```
/file put docs/spec.pdf
/file put /happy-gadgets @feat/camera assets/logo.png
```

If you send a file **without a caption**, Takopi saves it to `incoming/<original_filename>`.

### Send an image to the agent (vision)

Photos and image documents are saved under `incoming/images/` (configurable) and the path is appended to the agent prompt so **every engine** can open them.

With `image_force_prompt = true` (default when files are enabled in recommended config):

1. Send a photo (optionally with a caption or `/claude …` / `/codex …` directive).
2. Takopi downloads it into the active project, e.g. `incoming/images/photo_a1b2c3d4.jpg`.
3. The run prompt includes an `[image]` / `[images]` block listing paths, then your caption (or `image_default_prompt` if empty).
4. **Codex** also receives native `-i` flags; **Pi / OMP** receive `@path` references.

Recommended settings:

```toml
[transports.telegram.files]
enabled = true
auto_put = true
auto_put_mode = "prompt"
uploads_dir = "incoming"
image_subdir = "images"
image_default_prompt = "Describe this image."
image_force_prompt = true
```

Use `--force` to overwrite:

```
/file put --force docs/spec.pdf
```

## Fetch a file (`/file get`)

Send:

```
/file get <path>
```

Directories are zipped automatically.

## Related

- [Commands & directives](../reference/commands-and-directives.md)
- [Config reference](../reference/config.md)
